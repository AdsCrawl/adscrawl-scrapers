"""Remote browser requests implemented with the official AdsCrawl Python SDK.

All target traffic runs in the AdsCrawl browser. In particular, POST requests
use navigation interception, never Playwright's locally executed APIRequestContext.
"""
from __future__ import annotations

import asyncio
import json
import os
import weakref
from contextvars import ContextVar
from functools import wraps
from dataclasses import dataclass, field
from functools import cached_property
from http.cookies import SimpleCookie
from typing import Any, AsyncIterator, Iterable
from urllib.parse import urlsplit, urlencode

from adscrawl import AsyncAdsCrawl, AdsCrawlAPIError
from parsel import Selector
from playwright.async_api import async_playwright, Error as BrowserError, TimeoutError as BrowserTimeout

_CLIENTS: weakref.WeakSet = weakref.WeakSet()
_SCOPE = ContextVar("adscrawl_scraper_scope", default=None)


@dataclass
class Request:
    url: str
    countryCode: str | None = None
    proxy: dict | None = None
    locale: str | None = None
    userAgentOs: str | None = None
    render: bool = True
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    data: Any = None
    session: str | None = None
    waitUntil: str = "domcontentloaded"
    timeoutMs: int = 90_000
    waitForSelector: str | None = None
    waitForResponse: str | None = None
    binary: bool = False
    waitMs: int = 0
    autoScroll: bool = False
    actions: list[dict] = field(default_factory=list)
    javascript: str | None = None
    contentMode: str = "html"
    raiseOnHttpError: bool = True

    def __post_init__(self):
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Request.url must be an absolute HTTP(S) URL")
        if self.proxy and self.countryCode:
            raise ValueError("proxy and countryCode cannot be combined")
        if self.countryCode:
            self.countryCode = self.countryCode.upper()
        if self.timeoutMs <= 0 or self.waitMs < 0:
            raise ValueError("timeoutMs must be positive and waitMs non-negative")
        if self.waitUntil not in {"load", "domcontentloaded", "networkidle", "commit"}:
            raise ValueError("Unsupported waitUntil")
        if self.contentMode not in {"html", "markdown"}:
            raise ValueError("Unsupported contentMode")
        if self.body is not None and self.data is not None:
            raise ValueError("Set body or data, not both")
        self.method = self.method.upper()

    def browser_settings(self) -> dict:
        settings = {"viewport": {"width": 1440, "height": 900}}
        for key in ("countryCode", "proxy", "locale", "userAgentOs"):
            value = getattr(self, key)
            if value is not None:
                settings[key] = value
        if self.userAgentOs:
            settings["userAgentMode"] = "random"
        return settings

    def payload(self) -> str | bytes | None:
        value = self.body if self.body is not None else self.data
        if value is None or isinstance(value, (str, bytes)):
            return value
        content_type = next((v for k, v in self.headers.items() if k.lower() == "content-type"), "")
        if "application/x-www-form-urlencoded" in content_type:
            return urlencode(value, doseq=True)
        return json.dumps(value, ensure_ascii=False)


@dataclass
class Response:
    url: str
    content: str = ""
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    request_url: str = ""
    network: list[dict] = field(default_factory=list)
    cookies: list[dict] = field(default_factory=list)
    javascript: Any = None
    raw: bytes = b""

    @cached_property
    def selector(self) -> Selector:
        return Selector(text=self.content, base_url=self.url)

    def json(self) -> Any:
        return json.loads(self.content)


class ScrapeError(RuntimeError):
    """Safe-to-log request error; response is available even for failed navigations."""
    def __init__(self, message: str, *, response: Response | None = None, code: str = "SCRAPE_FAILED"):
        super().__init__(message)
        self.message = message
        self.response = response
        self.code = code


async def _finish(coro):
    """Do not abandon a remote resource cleanup when the caller is cancelled."""
    task = asyncio.create_task(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class _Session:
    def __init__(self, sdk, settings):
        self.sdk, self.settings = sdk, settings
        self.info = self.playwright = self.browser = self.context = None
        self.lock = asyncio.Lock()

    async def open(self):
        # SDK uses a worker thread. Await an in-flight creation before handling
        # cancellation so that a successfully created remote session can be closed.
        creation = asyncio.create_task(self.sdk.cdp.create({
            "idleTimeoutMs": 120_000, "maxSessionMs": 3_600_000,
            "browserSettings": self.settings,
        }))
        try:
            self.info = await asyncio.shield(creation)
        except asyncio.CancelledError:
            self.info = await creation
            await _finish(self.close())
            raise
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.connect_over_cdp(self.info["cdpBaseUrl"], timeout=30_000)
            self.context = self.browser.contexts[0]
        except BrowserError:
            await _finish(self.close())
            raise ScrapeError("AdsCrawl CDP connection failed", code="CONNECT_FAILED") from None
        except BaseException:
            await _finish(self.close())
            raise
        return self

    async def close(self):
        # The SDK DELETE, not merely disconnecting Playwright, releases the session.
        failures = []
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
        if self.info:
            try:
                await self.sdk.cdp.close(self.info["sessionId"])
                self.info = None
            except Exception:
                failures.append("AdsCrawl session cleanup failed; inspect active sessions before retrying")
        if self.playwright:
            try:
                await self.playwright.stop()
            finally:
                self.playwright = None
        if failures:
            raise ScrapeError(failures[0], code="CLEANUP_FAILED")


class ScraperClient:
    """Lazy SDK client, bounded browser pool, and named session reuse.

    Use ``async with ScraperClient()`` in applications, or ``run(coroutine)``
    in standalone scripts. Both close all owned remote sessions on exit.
    """
    def __init__(self, *, api_key=None, concurrency=None, sdk=None):
        self._api_key = api_key
        self._sdk = sdk
        self.concurrency = int(concurrency or os.getenv("ADSCRAWL_CONCURRENCY", "2"))
        if self.concurrency < 1:
            raise ValueError("Concurrency must be positive")
        self._loop = None
        self._gate = None
        self._sessions = {}
        self._pool_lock = None
        _CLIENTS.add(self)

    def _bind_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            if self._sessions:
                raise RuntimeError("Close the client before using it on another event loop")
            self._loop = loop
            self._gate = asyncio.Semaphore(self.concurrency)
            self._pool_lock = asyncio.Lock()
        if self._sdk is None:
            self._sdk = AsyncAdsCrawl(api_key=self._api_key)

    async def __aenter__(self):
        self._bind_loop()
        return self

    async def __aexit__(self, *exc):
        await _finish(self.close())

    async def close(self):
        sessions = list(self._sessions.items())
        failures = []
        for key, session in sessions:
            try:
                await _finish(session.close())
                self._sessions.pop(key, None)
            except Exception as error:
                failures.append(error)
        if failures:
            raise failures[0]

    async def close_session(self, name):
        name = (_SCOPE.get(), name)
        if name in self._sessions:
            session = self._sessions[name]
            async with session.lock:
                await _finish(session.close())
                self._sessions.pop(name, None)

    async def fetch(self, request: Request) -> Response:
        self._bind_loop()
        async with self._gate:
            settings = request.browser_settings()
            # Serialize creation of named sessions; preserve their browser/IP,
            # storage and cookies until close(). They count against the pool cap.
            async with self._pool_lock:
                key = (_SCOPE.get(), request.session) if request.session else object()
                session = self._sessions.get(key)
                if session is None:
                    if len(self._sessions) >= self.concurrency:
                        raise ScrapeError("Named sessions occupy the browser limit; close_session(name) before opening another", code="SESSION_LIMIT")
                    session = _Session(self._sdk, settings)
                    self._sessions[key] = session
                    try:
                        await session.open()
                    except BaseException:
                        if session.info is None:
                            self._sessions.pop(key, None)
                        raise
                elif session.settings != settings:
                    raise ValueError("A named session cannot change countryCode, proxy, locale, or fingerprint")
            try:
                async with session.lock:
                    return await asyncio.wait_for(self._fetch_page(session, request), request.timeoutMs / 1000)
            except ScrapeError:
                raise
            except AdsCrawlAPIError as error:
                raise ScrapeError(f"AdsCrawl API HTTP {error.status}", code=str(error.code or "API_ERROR")) from None
            except (BrowserError, asyncio.TimeoutError):
                # Browser errors can contain token-bearing CDP URLs. Never expose them.
                raise ScrapeError("Remote browser request failed or timed out", response=Response(request.url, request_url=request.url)) from None
            finally:
                if request.session is None:
                    await _finish(session.close())
                    self._sessions.pop(key, None)

    async def fetch_many(self, requests: Iterable[Request]) -> AsyncIterator[Response]:
        # Keep only `concurrency` tasks alive, even for a generator of millions of URLs.
        iterator = iter(requests)
        pending = set()
        finished = set()
        def schedule():
            for _ in range(self.concurrency - len(pending)):
                request = next(iterator, None)
                if request is None:
                    break
                pending.add(asyncio.create_task(self.fetch(request)))
        schedule()
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                finished = done
                for task in done:
                    # Failed requests fail the batch instead of silently yielding
                    # errors into site parsers and returning incomplete datasets.
                    yield task.result()
                schedule()
        finally:
            for task in pending:
                task.cancel()
            if pending or finished:
                await asyncio.gather(*pending, *finished, return_exceptions=True)

    def fetch_sync(self, request):
        async def once():
            try:
                return await self.fetch(request)
            finally:
                await self.close()
        return asyncio.run(once())

    async def _fetch_page(self, session, request):
        page = await session.context.new_page()
        network, collectors = [], set()
        response_ready = asyncio.Event()
        response = Response(request.url, request_url=request.url)
        async def collect(reply):
            if reply.request.resource_type not in {"xhr", "fetch"}:
                return
            try:
                body = await reply.text()
            except (BrowserError, UnicodeDecodeError):
                # Some sites fetch binary telemetry/fonts alongside their JSON.
                # A non-text background response must not discard a valid page.
                body = None
            network.append({
                "url": reply.url, "method": reply.request.method,
                "headers": await reply.request.all_headers(), "body": reply.request.post_data,
                "request": {"url": reply.url, "method": reply.request.method,
                            "headers": await reply.request.all_headers(), "body": reply.request.post_data},
                "response": {"status": reply.status, "status_code": reply.status,
                             "headers": await reply.all_headers(), "body": body},
            })
            if request.waitForResponse and request.waitForResponse in reply.url:
                response_ready.set()
        def on_response(reply):
            task = asyncio.create_task(collect(reply))
            collectors.add(task)
        page.on("response", on_response)
        try:
            # Replayed XHR metadata must not override browser-managed routing or
            # stale payload lengths; cookies are installed into the context below.
            headers = {k: v for k, v in request.headers.items()
                       if k.lower() not in {"host", "content-length", "connection", "accept-encoding"}
                       and not k.startswith(":")}
            # Browser navigation forbids a Cookie override; install actual cookies.
            cookie_header = next((headers.pop(k) for k in list(headers) if k.lower() == "cookie"), None)
            if cookie_header:
                jar = SimpleCookie()
                jar.load(cookie_header)
                await session.context.add_cookies([
                    {"name": name, "value": morsel.value, "url": request.url}
                    for name, morsel in jar.items()
                ])
            await page.set_extra_http_headers(headers)
            if request.binary:
                return await self._fetch_binary(session, page, request, headers)
            if request.method != "GET" or request.body is not None or request.data is not None:
                intercepted = False
                async def intercept(route):
                    nonlocal intercepted
                    req = route.request
                    if not intercepted and req.is_navigation_request() and req.frame == page.main_frame:
                        intercepted = True
                        await route.continue_(method=request.method, post_data=request.payload(), headers={**req.headers, **headers})
                    else:
                        await route.continue_()
                await page.route("**/*", intercept)
            main = await page.goto(request.url, wait_until=request.waitUntil, timeout=request.timeoutMs)
            response.url = page.url
            if main:
                response.status_code = main.status
                response.headers = await main.all_headers()
            if request.waitForResponse:
                await asyncio.wait_for(response_ready.wait(), request.timeoutMs / 1000)
            if request.waitForSelector:
                try:
                    await page.wait_for_selector(request.waitForSelector, state="attached", timeout=request.timeoutMs)
                except BrowserTimeout:
                    response.url, response.content = page.url, await page.content()
                    raise ScrapeError("Required page selector was not found", response=response, code="SELECTOR_NOT_FOUND") from None
            try:
                await perform_actions(page, request.actions, request.timeoutMs)
            except (BrowserError, asyncio.TimeoutError):
                response.url = page.url
                raise ScrapeError("Browser action failed or timed out", response=response, code="ACTION_FAILED") from None
            if request.autoScroll:
                await scroll_page(page, 5)
            if request.waitMs:
                await page.wait_for_timeout(request.waitMs)
            if request.javascript:
                response.javascript = await evaluate_script(page, request.javascript)
            response.url = page.url
            content_type = response.headers.get("content-type", "").lower()
            if main and (not request.render or (content_type and "html" not in content_type)):
                response.raw = await main.body()
                if content_type.startswith(("image/", "application/octet-stream", "application/gzip")):
                    response.content = response.raw.decode("latin1")
                else:
                    response.content = await main.text()
            else:
                response.content = await page.content()
                response.raw = response.content.encode()
            if request.contentMode == "markdown":
                from markdownify import markdownify
                root = Selector(response.content).css("main").get() or response.content
                response.content = markdownify(root, heading_style="ATX")
            response.cookies = await session.context.cookies()
            page.remove_listener("response", on_response)
            if collectors:
                await asyncio.gather(*collectors)
            response.network = network
            if request.raiseOnHttpError and response.status_code >= 400:
                raise ScrapeError(f"Target returned HTTP {response.status_code}", response=response, code="HTTP_ERROR")
            return response
        except BrowserError:
            response.url = page.url
            raise ScrapeError("Browser navigation or interaction failed", response=response) from None
        finally:
            page.remove_listener("response", on_response)
            for task in collectors:
                if not task.done():
                    task.cancel()
            if collectors:
                await asyncio.gather(*collectors, return_exceptions=True)
            await page.close()


    async def _fetch_binary(self, session, page, request, headers):
        # A download navigation has no readable DOM. Give browser-side fetch a
        # same-origin document, then read bytes in the remote browser (not via
        # context.request, which would send the target request from this machine).
        origin = urlsplit(request.url)
        bootstrap = f"{origin.scheme}://{origin.netloc}/__adscrawl_binary_context__"
        async def document(route):
            await route.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Binary fetch</title>")
        await page.route(bootstrap, document)
        await page.goto(bootstrap, wait_until="domcontentloaded", timeout=request.timeoutMs)
        payload = request.payload()
        if isinstance(payload, bytes):
            payload = list(payload)
        value = await page.evaluate("""async ({url, method, headers, body}) => {
            if (Array.isArray(body)) body = new Uint8Array(body);
            const response = await fetch(url, {method, headers, body, credentials: 'include'});
            return {url: response.url, status: response.status,
                    headers: Object.fromEntries(response.headers.entries()),
                    bytes: Array.from(new Uint8Array(await response.arrayBuffer()))};
        }""", {"url": request.url, "method": request.method, "headers": headers, "body": payload})
        raw = bytes(value["bytes"])
        content_type = value["headers"].get("content-type", "").lower()
        # Download endpoints may return JSON as an attachment. Preserve Unicode
        # for textual payloads while keeping the original bytes for images/gzip.
        textual = content_type.startswith("text/") or any(
            kind in content_type for kind in ("json", "xml", "javascript")
        )
        result = Response(url=value["url"], request_url=request.url, raw=raw,
                          content=raw.decode("utf-8-sig" if textual else "latin1"), status_code=value["status"],
                          headers=value["headers"], cookies=await session.context.cookies())
        if request.raiseOnHttpError and result.status_code >= 400:
            raise ScrapeError(f"Target returned HTTP {result.status_code}", response=result, code="HTTP_ERROR")
        return result


async def evaluate_script(page, script):
    # Site scripts can contain return/await at top level. Wrapping them in an
    # async function preserves that contract without evaluating them locally.
    return await page.evaluate("async () => {\n" + script + "\n}")


async def scroll_page(page, steps=5, selector=None):
    for _ in range(min(int(steps), 20)):
        if selector and selector != "bottom":
            await page.locator(selector).first.evaluate("el => el.scrollTop = el.scrollHeight")
        else:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(500)


async def perform_actions(page, actions, timeout_ms):
    for action in actions:
        kind = action["type"]
        timeout = action.get("timeoutMs", min(timeout_ms, 15_000))
        try:
            if kind == "wait":
                await page.wait_for_timeout(action["milliseconds"])
            elif kind == "waitForSelector":
                await page.wait_for_selector(action["selector"], state=action.get("state", "visible"), timeout=timeout)
            elif kind == "click":
                loc = page.locator(action["selector"])
                if action.get("optional") and not await loc.first.is_visible():
                    continue
                targets = await loc.all() if action.get("multiple") else [loc.first]
                for target in targets:
                    await target.click(timeout=timeout)
            elif kind == "fill":
                loc = page.locator(action["selector"]).first
                if action.get("clear", True):
                    await loc.fill(action["value"], timeout=timeout)
                else:
                    await loc.press_sequentially(action["value"], timeout=timeout)
            elif kind == "scroll":
                await scroll_page(page, action.get("steps", 1), action.get("selector"))
            elif kind == "evaluate":
                await asyncio.wait_for(evaluate_script(page, action["script"]), timeout / 1000)
            elif kind == "condition":
                exists = bool(await page.locator(action["selector"]).count())
                matched = exists if action["state"] == "existing" else not exists
                if matched:
                    if action["outcome"] == "exit_failed":
                        raise ScrapeError("A required page condition failed", code="CONDITION_FAILED")
                    break
            else:
                raise ValueError(f"Unsupported action type: {kind}")
        except (BrowserError, asyncio.TimeoutError):
            if not action.get("optional"):
                raise


async def close_all():
    failures = []
    for client in list(_CLIENTS):
        if client._loop is asyncio.get_running_loop():
            try:
                await client.close()
            except Exception as error:
                failures.append(error)
    if failures:
        raise failures[0]


def run(coroutine):
    async def wrapped():
        try:
            return await coroutine
        finally:
            await close_all()
    return asyncio.run(wrapped())


def managed(function):
    """Close named sessions when an outer site operation returns or raises.

    Nested helpers share the outer scope; concurrent top-level operations get
    distinct scopes, so one operation never closes another operation's browser.
    """
    @wraps(function)
    async def wrapped(*args, **kwargs):
        if _SCOPE.get() is not None:
            return await function(*args, **kwargs)
        scope = object()
        token = _SCOPE.set(scope)
        try:
            return await function(*args, **kwargs)
        finally:
            try:
                errors = []
                for client in list(_CLIENTS):
                    for key, session in list(client._sessions.items()):
                        if isinstance(key, tuple) and key[0] is scope:
                            try:
                                await _finish(session.close())
                                client._sessions.pop(key, None)
                            except Exception as error:
                                errors.append(error)
                if errors:
                    raise errors[0]
            finally:
                _SCOPE.reset(token)
    return wrapped
