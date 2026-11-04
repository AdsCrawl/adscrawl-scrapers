"""Remote browser requests implemented with the official AdsCrawl Python SDK.

All target traffic runs in the AdsCrawl browser. In particular, POST requests
use navigation interception, never Playwright's locally executed APIRequestContext.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import inspect
import os
import re
import uuid
import weakref
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from dataclasses import dataclass, field
from functools import cached_property
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, AsyncIterator, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from adscrawl import AsyncAdsCrawl, AdsCrawlAPIError, AdsCrawlTimeoutError
from loguru import logger as log
from parsel import Selector
from playwright.async_api import async_playwright, Error as BrowserError, TimeoutError as BrowserTimeout

_CLIENTS: weakref.WeakSet = weakref.WeakSet()
_SCOPE = ContextVar("adscrawl_scraper_scope", default=None)
_NETWORK_DRAIN_SECONDS = 2
_DISCONNECT_TIMEOUT_SECONDS = 10
# US tunnel failures move between pages, and a GET can also die at the outer
# deadline (Facebook event details, Target search). One new browser is safe
# to repeat. POST bodies are not retried.
_NAVIGATION_RETRY_CODES = {
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_CONNECTION_CLOSED",
    "CONNECT_FAILED",
    "TIMEOUT",
}


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
        country = self.countryCode
        if country is None and self.proxy is None:
            country = os.getenv("ADSCRAWL_DEFAULT_COUNTRY", "US")
        if country:
            settings['countryCode'] = country.upper()
        for key in ("proxy", "locale", "userAgentOs"):
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
    diagnostics: dict = field(default_factory=dict)

    @cached_property
    def selector(self) -> Selector:
        return Selector(text=self.content, base_url=self.url)

    def json(self) -> Any:
        return json.loads(self.content)


class ScrapeError(RuntimeError):
    """Safe-to-log request error; response is available even for failed navigations."""
    def __init__(self, message: str, *, response: Response | None = None, code: str = "SCRAPE_FAILED"):
        self.message = message
        self.response = response
        self.code = code
        # Pytest prints str(exception). The useful ERR_*/TIMEOUT/ACTION_FAILED
        # identifier lived only on .code, so failure reports omitted it.
        # Failure diagnostics may also include a redacted page URL, title, and
        # screenshot path. The raw browser error, which can carry a CDP URL, stays off.
        if code and re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", code) and code not in message:
            message = f"{message} [{code}]"
        super().__init__(message)


def redact_page_url(url: str) -> str:
    """Page URL safe to print. Drops userinfo and secret query values."""
    if not isinstance(url, str):
        return ""
    stripped = url.strip()
    if not stripped:
        return ""
    if stripped.startswith(("about:", "chrome:", "chrome-error:")):
        return stripped.split("?", 1)[0][:500]
    parts = urlsplit(stripped)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        folded = key.lower().replace("-", "_")
        sensitive = folded in {
            "token", "key", "api_key", "apikey", "access_token", "auth", "session",
            "password", "secret", "sig", "signature", "credential", "code",
        } or any(part in folded for part in ("token", "secret", "password", "apikey", "api_key"))
        query.append((key, "REDACTED" if sensitive else value))
    return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))[:500]


def _format_page_diagnostic(info: dict) -> str:
    parts = []
    if info.get("url"):
        parts.append(f"url={info['url']}")
    if info.get("title"):
        parts.append("title=" + json.dumps(info["title"], ensure_ascii=False))
    if info.get("screenshot"):
        parts.append(f"screenshot={info['screenshot']}")
    return (" " + " ".join(parts)) if parts else ""


async def capture_failure_page(page, response, code: str) -> str:
    """Record URL, title, and a screenshot for a tunnel, timeout, or action failure.

    Best-effort: a dead tab must not hide the original error. The note and PNG
    go under ``ADSCRAWL_FAILURE_DIR`` (default ``artifacts/scrape-failures``),
    which is gitignored. Cookies, headers, and secret query values are omitted.
    """
    info = {"code": code, "url": "", "title": "", "screenshot": ""}
    try:
        current = getattr(page, "url", "") or getattr(response, "url", "")
        info["url"] = redact_page_url(current)
    except Exception:
        pass
    try:
        title = await asyncio.wait_for(page.title(), 3)
        info["title"] = re.sub(r"\s+", " ", str(title or "")).strip()[:180]
    except Exception:
        pass
    directory = Path(os.environ.get("ADSCRAWL_FAILURE_DIR", "artifacts/scrape-failures"))
    stem = f"{code}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        note_path = directory / f"{stem}.json"
        image_path = directory / f"{stem}.png"
        try:
            await asyncio.wait_for(page.screenshot(path=str(image_path), type="png"), 5)
            info["screenshot"] = str(image_path)
        except Exception:
            pass
        note_path.write_text(json.dumps({
            "code": code,
            "url": info["url"],
            "title": info["title"],
            "screenshot": image_path.name if info["screenshot"] else "",
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    if info["url"]:
        response.url = info["url"]
    response.diagnostics = info
    return _format_page_diagnostic(info)


async def _finish(coro):
    """Do not abandon a remote resource cleanup when the caller is cancelled."""
    task = asyncio.create_task(coro)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class _Session:
    def __init__(self, sdk, settings):
        self.sdk, self.settings = sdk, settings
        self.info = self.playwright = self.browser = self.context = None
        self.lock = asyncio.Lock()
        # At least the SDK default. A slower site can raise this per request.
        self.create_timeout_ms = 90_000

    async def _known_session_ids(self):
        """Session ids currently listed for this API key.

        ``cdp.list()`` also returns ``cdpBaseUrl``, which embeds a data token.
        Only the ids leave this method, and nothing here is logged.
        """
        list_sessions = getattr(getattr(self.sdk, "cdp", None), "list", None)
        if list_sessions is None:
            return None
        try:
            listed = await list_sessions(timeout_ms=10_000)
        except Exception:
            return None
        data = listed.get("data") if isinstance(listed, dict) else None
        if not isinstance(data, list):
            return None
        return {
            item["sessionId"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("sessionId"), str)
        }

    async def _close_new_sessions(self, before):
        """Close sessions that appeared after a create call timed out.

        The HTTP client can give up before the create response arrives. The
        server may still hold that browser. Ids already present are left alone
        so another in-process session is not deleted.
        """
        if before is None:
            return
        after = await self._known_session_ids()
        if after is None:
            return
        for session_id in sorted(after - before):
            try:
                await self.sdk.cdp.close(session_id, timeout_ms=15_000)
            except Exception:
                pass

    async def open(self):
        # Snapshot first, then create. A timed-out create never returns an id,
        # so the difference between the two listings is the leaked browser.
        before = await self._known_session_ids()
        # SDK uses a worker thread. Await an in-flight creation before handling
        # cancellation so that a successfully created remote session can be closed.
        creation = asyncio.create_task(self.sdk.cdp.create({
            "idleTimeoutMs": 120_000, "maxSessionMs": 3_600_000,
            "browserSettings": self.settings,
        }, timeout_ms=self.create_timeout_ms))
        try:
            self.info = await asyncio.shield(creation)
        except asyncio.CancelledError:
            self.info = await creation
            await _finish(self.close())
            raise
        except AdsCrawlTimeoutError:
            await self._close_new_sessions(before)
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
                await asyncio.wait_for(self.browser.close(), _DISCONNECT_TIMEOUT_SECONDS)
            except Exception:
                pass
            self.browser = None
        if self.info:
            # Drop the id before DELETE. A failed DELETE must not leave this
            # object looking open: callers then keep it in the pool, and the
            # next pytest loop refuses to run.
            session_id = self.info["sessionId"]
            self.info = None
            try:
                await self.sdk.cdp.close(session_id, timeout_ms=30_000)
            except Exception:
                failures.append("AdsCrawl session cleanup failed; inspect active sessions before retrying")
        if self.playwright:
            try:
                await asyncio.wait_for(self.playwright.stop(), _DISCONNECT_TIMEOUT_SECONDS)
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
        self._external_sdk = sdk is not None
        self.concurrency = int(concurrency or os.getenv("ADSCRAWL_CONCURRENCY", "2"))
        if self.concurrency < 1:
            raise ValueError("Concurrency must be positive")
        self._loop = None
        self._gate = None
        self._sessions = {}
        self._active_requests = {}
        self._pool_lock = None
        _CLIENTS.add(self)

    def _bind_loop(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            if self._sessions:
                previous = self._loop
                # A still-running loop owns these browsers. A closed loop is a
                # finished pytest test: the sessions are leftovers from a failed
                # cleanup and cannot be awaited there.
                if previous is not None and not previous.is_closed():
                    raise RuntimeError("Close the client before using it on another event loop")
                log.warning("dropping browser sessions left on a closed event loop")
                self._sessions.clear()
                if not self._external_sdk:
                    self._sdk = None
            self._loop = loop
            self._gate = asyncio.Semaphore(self.concurrency)
            self._pool_lock = asyncio.Lock()
        if self._sdk is None:
            self._sdk = AsyncAdsCrawl(api_key=self._api_key)

    async def reset(self):
        """Drop every tracked browser and the SDK binding.

        The next fetch opens a new client on the running loop. A remote DELETE
        that already failed is not retried; that browser expires on its idle
        timeout instead of blocking later tests.
        """
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            try:
                await _finish(session.close())
            except Exception as error:
                log.warning(f"browser session reset skipped a failed close ({error})")
        self._loop = None
        self._gate = None
        self._pool_lock = None
        if not self._external_sdk:
            self._sdk = None

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
            except Exception as error:
                failures.append(error)
            finally:
                self._sessions.pop(key, None)
        if failures:
            raise failures[0]

    async def close_session(self, name):
        name = (_SCOPE.get(), name)
        session = self._sessions.get(name)
        if session is None:
            return
        try:
            async with session.lock:
                await _finish(session.close())
        finally:
            self._sessions.pop(name, None)

    async def fetch(self, request: Request) -> Response:
        task = asyncio.current_task()
        self._active_requests[task] = _SCOPE.get()
        try:
            try:
                return await self._fetch(request)
            except ScrapeError as error:
                if request.method != "GET" or error.code not in _NAVIGATION_RETRY_CODES:
                    raise
                # The browser that failed is discarded. A named session would
                # otherwise be reused and fail the same way.
                log.warning("retrying GET {} once after {}", redact_page_url(request.url), error.code)
                if request.session:
                    await self.close_session(request.session)
                return await self._fetch(request)
        finally:
            self._active_requests.pop(task, None)

    async def _fetch(self, request: Request) -> Response:
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
                    # Do not shorten the historical 90s create budget. A site that
                    # raises Request.timeoutMs (Kayak) also gives session startup
                    # that long, so a slow create still returns an id we can close.
                    session.create_timeout_ms = max(int(request.timeoutMs), 90_000)
                    self._sessions[key] = session
                    try:
                        await session.open()
                    except AdsCrawlTimeoutError:
                        self._sessions.pop(key, None)
                        page = redact_page_url(request.url)
                        detail = f" url={page}" if page else ""
                        raise ScrapeError(
                            f"AdsCrawl session creation timed out{detail}",
                            code="TIMEOUT",
                            response=Response(request.url, request_url=request.url, status_code=0),
                        ) from None
                    except BaseException:
                        if session.info is None:
                            self._sessions.pop(key, None)
                        raise
                elif session.settings != settings:
                    raise ValueError("A named session cannot change countryCode, proxy, locale, or fingerprint")
            release = False
            try:
                async with session.lock:
                    return await asyncio.wait_for(self._fetch_page(session, request), request.timeoutMs / 1000)
            except ScrapeError:
                raise
            except AdsCrawlAPIError as error:
                raise ScrapeError(f"AdsCrawl API HTTP {error.status}", code=str(error.code or "API_ERROR")) from None
            except AdsCrawlTimeoutError:
                release = True
                page = redact_page_url(request.url)
                detail = f" url={page}" if page else ""
                raise ScrapeError(
                    f"AdsCrawl request timed out{detail}",
                    code="TIMEOUT",
                    response=Response(request.url, request_url=request.url, status_code=0),
                ) from None
            except (BrowserError, asyncio.TimeoutError) as error:
                # Browser errors can contain token-bearing CDP URLs. Never expose them.
                # A named session that dies here is released immediately. Waiting
                # for the caller to unwind left Kayak's browser counted against
                # the account limit and the next site received HTTP 429.
                release = True
                code = "TIMEOUT" if isinstance(error, (BrowserTimeout, asyncio.TimeoutError)) else "BROWSER_ERROR"
                page = redact_page_url(request.url)
                detail = f" url={page}" if page else ""
                raise ScrapeError(f"Remote browser request failed or timed out{detail}", code=code,
                                 response=Response(request.url, request_url=request.url, status_code=0)) from None
            finally:
                if request.session is None or release:
                    # Pop even when close is cancelled. ``_finish`` re-raises
                    # CancelledError after the DELETE, and skipping the pop left
                    # a closed browser in the pool (parser cancellation).
                    try:
                        await _finish(session.close())
                    except Exception:
                        if not release:
                            raise
                    finally:
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
        response = Response(request.url, request_url=request.url, status_code=0)
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
            headers = {k.lower(): v for k, v in request.headers.items()
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
            # Chromium can overwrite navigation headers such as Accept after
            # set_extra_http_headers. Interception applies explicit headers to
            # the actual document request as well as replayed POST payloads.
            if headers or request.method != "GET" or request.body is not None or request.data is not None:
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
            if request.raiseOnHttpError and response.status_code >= 400:
                # An error document cannot satisfy the site's data selector or
                # API wait. Preserve the real status instead of masking it with
                # a later timeout. Callers that inspect errors can opt out.
                response.content = await page.content()
                response.raw = response.content.encode()
                raise ScrapeError(f"Target returned HTTP {response.status_code}", response=response, code="HTTP_ERROR")
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
                detail = await capture_failure_page(page, response, "ACTION_FAILED")
                raise ScrapeError(f"Browser action failed or timed out{detail}", response=response, code="ACTION_FAILED") from None
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
                # Background streams/telemetry can stay open indefinitely. A
                # completed page must not wait for every unrelated response.
                # waitForResponse above explicitly awaits any required payload.
                _, pending = await asyncio.wait(collectors, timeout=_NETWORK_DRAIN_SECONDS)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*collectors, return_exceptions=True)
            response.network = network
            if request.raiseOnHttpError and response.status_code >= 400:
                raise ScrapeError(f"Target returned HTTP {response.status_code}", response=response, code="HTTP_ERROR")
            return response
        except BrowserError as error:
            # Chromium's stable error identifier distinguishes a tunnel failure
            # from an extraction bug. The exception text can contain a CDP URL,
            # so it stays off the message; the page URL below is redacted.
            reason = re.search(r"net::(ERR_[A-Z0-9_]+)", str(error))
            code = reason.group(1) if reason else "TIMEOUT" if isinstance(error, BrowserTimeout) else "BROWSER_ERROR"
            detail = await capture_failure_page(page, response, code)
            raise ScrapeError(f"Browser navigation or interaction failed{detail}", response=response, code=code) from None
        finally:
            page.remove_listener("response", on_response)
            for task in collectors:
                if not task.done():
                    task.cancel()
            if collectors:
                await asyncio.gather(*collectors, return_exceptions=True)
            # A disconnected tab can stop answering even Page.close(). Let the
            # enclosing session's SDK DELETE release it after a bounded wait.
            try:
                await asyncio.wait_for(page.close(), _DISCONNECT_TIMEOUT_SECONDS)
            except (BrowserError, asyncio.TimeoutError):
                pass


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
        # Download endpoints may return JSON as an attachment, or a .gz sitemap
        # whose Content-Type still says xml/text. Inflate gzip before the text
        # decode. `raw` stays the original bytes so callers can decompress too.
        result = Response(url=value["url"], request_url=request.url, raw=raw,
                          content=decode_download_body(raw, content_type), status_code=value["status"],
                          headers=value["headers"], cookies=await session.context.cookies())
        if request.raiseOnHttpError and result.status_code >= 400:
            raise ScrapeError(f"Target returned HTTP {result.status_code}", response=result, code="HTTP_ERROR")
        return result


def decode_download_body(raw: bytes, content_type: str) -> str:
    """Decode a binary-mode download.

    Text, JSON, XML and script bodies use UTF-8. A gzip member (magic ``1f 8b``)
    is decompressed first when the type claims text or the inflated bytes look
    like XML/JSON. Images and other binary payloads stay a latin-1 view of the
    original bytes.
    """
    content_type = (content_type or "").lower()
    textual = content_type.startswith("text/") or any(
        kind in content_type for kind in ("json", "xml", "javascript", "ecmascript")
    )
    payload = raw
    if raw.startswith(b"\x1f\x8b"):
        try:
            payload = gzip.decompress(raw)
        except OSError:
            payload = raw
        else:
            head = payload.lstrip()[:1]
            if not textual and (head in (b"<", b"{", b"[") or payload.startswith(b"\xef\xbb\xbf")):
                textual = True
    if textual:
        return payload.decode("utf-8-sig")
    return raw.decode("latin1")


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


async def _close_scope(scope):
    errors = []
    # An async-for consumer may raise in its parser before fetch_many is closed.
    # Drain its in-flight requests now, while the event loop is still running.
    # Otherwise loop teardown can cancel the SDK creation/cleanup tasks too.
    current = asyncio.current_task()
    requests = {
        task for client in list(_CLIENTS)
        for task, owner in list(client._active_requests.items())
        if owner is scope and task is not current and not task.done()
    }
    for task in requests:
        task.cancel()
    if requests:
        async def drain():
            await asyncio.gather(*requests, return_exceptions=True)
        await _finish(drain())
    for client in list(_CLIENTS):
        for key, session in list(client._sessions.items()):
            if isinstance(key, tuple) and key[0] is scope:
                try:
                    await _finish(session.close())
                except Exception as error:
                    errors.append(error)
                finally:
                    client._sessions.pop(key, None)
    if errors:
        raise errors[0]


def managed(function):
    """Close named sessions when an outer site operation returns or raises.

    Nested helpers share the outer scope; concurrent top-level operations get
    distinct scopes, so one operation never closes another operation's browser.
    """
    if inspect.isasyncgenfunction(function):
        @wraps(function)
        async def generated(*args, **kwargs):
            parent = _SCOPE.get()
            scope = parent if parent is not None else object()
            iterator = function(*args, **kwargs)
            try:
                while True:
                    token = _SCOPE.set(scope)
                    try:
                        item = await iterator.__anext__()
                    except StopAsyncIteration:
                        break
                    finally:
                        # Never leak a generator's scope into its consumer while
                        # suspended at yield, including an early aclose().
                        _SCOPE.reset(token)
                    yield item
            finally:
                token = _SCOPE.set(scope)
                try:
                    await iterator.aclose()
                finally:
                    _SCOPE.reset(token)
                    if parent is None:
                        await _close_scope(scope)
        return generated

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
                await _close_scope(scope)
            finally:
                _SCOPE.reset(token)
    return wrapped
