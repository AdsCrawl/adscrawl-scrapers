import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from adscrawl import AdsCrawlTimeoutError
from adscrawl_scrapers import Request, Response, ScraperClient, ScrapeError, managed
from adscrawl_scrapers.runtime import _Session, perform_actions, evaluate_script


def test_redact_page_url_drops_userinfo_and_secret_query_values():
    from adscrawl_scrapers.runtime import redact_page_url
    url = redact_page_url("https://user:secret@chatgpt.com/path?prompt=Paris&token=secret&api_key=secret#session")
    assert url == "https://chatgpt.com/path?prompt=Paris&token=REDACTED&api_key=REDACTED"
    assert "secret" not in url
    assert redact_page_url("about:blank") == "about:blank"
    assert redact_page_url("chrome-error://chromewebdata/?token=secret") == "chrome-error://chromewebdata/"


def test_scrape_error_failure_text_includes_safe_code():
    navigation = ScrapeError("Browser navigation or interaction failed", code="ERR_TUNNEL_CONNECTION_FAILED")
    assert str(navigation) == "Browser navigation or interaction failed [ERR_TUNNEL_CONNECTION_FAILED]"
    assert str(ScrapeError("Remote browser request failed or timed out", code="TIMEOUT")).endswith("[TIMEOUT]")
    assert str(ScrapeError("Browser action failed or timed out", code="ACTION_FAILED")).endswith("[ACTION_FAILED]")
    secret = ScrapeError("Browser navigation failed https://private.invalid/?token=secret", code="not a safe code")
    assert str(secret) == secret.message
    assert "not a safe code" not in str(secret)


def test_response_html_json_and_redirect_metadata():
    page = Response('https://example.com/final', '<h1>Hello</h1>', request_url='https://example.com/start')
    assert page.selector.css('h1::text').get() == 'Hello'
    assert page.request_url.endswith('/start')
    assert Response('https://example.com', '{"ok":true}').json() == {'ok': True}


def test_request_validation_and_payloads():
    request = Request('https://example.com', countryCode='de', body={'q': 'café'})
    assert request.browser_settings()['countryCode'] == 'DE'
    assert json.loads(request.payload()) == {'q': 'café'}
    form = Request('https://example.com', headers={'Content-Type':'application/x-www-form-urlencoded'}, data={'q':['a','b']})
    assert form.payload() == 'q=a&q=b'
    for params in ({'countryCode':'US','proxy':{'server':'http://proxy'}}, {'timeoutMs':0}, {'body':'x','data':'y'}):
        with pytest.raises(ValueError): Request('https://example.com', **params)
    with pytest.raises(TypeError): Request('https://example.com', proxy_pool='legacy')


class FakeSession:
    created = []
    def __init__(self, sdk, settings):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.info = {'sessionId':str(len(self.created))}
        self.closed = False
        self.created.append(self)
    async def open(self): return self
    async def close(self): self.closed = True; self.info = None


@pytest.fixture
def fake_sessions(monkeypatch):
    FakeSession.created = []
    monkeypatch.setattr('adscrawl_scrapers.runtime._Session', FakeSession)
    return FakeSession.created


async def test_one_shot_cleanup_on_success_and_failure(fake_sessions):
    client = ScraperClient(sdk=object())
    client._fetch_page = AsyncMock(return_value=Response('https://example.com'))
    await client.fetch(Request('https://example.com'))
    assert fake_sessions[0].closed and not client._sessions
    client._fetch_page.side_effect = RuntimeError('parse failed')
    with pytest.raises(RuntimeError): await client.fetch(Request('https://example.com'))
    assert fake_sessions[-1].closed and not client._sessions


async def test_named_session_preserves_browser_and_closes_at_operation_boundary(fake_sessions):
    client = ScraperClient(sdk=object())
    seen = []
    async def page(session, request):
        seen.append(session)
        return Response(request.url)
    client._fetch_page = page
    @managed
    async def operation():
        await client.fetch(Request('https://example.com/first', session='reviews'))
        await client.fetch(Request('https://example.com/next', session='reviews'))
        assert not fake_sessions[-1].closed
    await operation()
    assert len(fake_sessions) == 1 and seen[0] is seen[1]
    assert fake_sessions[0].closed and not client._sessions
    await operation()
    assert len(fake_sessions) == 2 and all(s.closed for s in fake_sessions)


async def test_nested_operation_does_not_close_parent_session(fake_sessions):
    client = ScraperClient(sdk=object())
    client._fetch_page = AsyncMock(return_value=Response('https://example.com'))
    @managed
    async def child(): await client.fetch(Request('https://example.com', session='same'))
    @managed
    async def parent():
        await child()
        assert not fake_sessions[-1].closed
        await child()
    await parent()
    assert len(fake_sessions) == 1 and fake_sessions[0].closed


async def test_cancellation_waits_for_cleanup(fake_sessions):
    client = ScraperClient(sdk=object())
    started = asyncio.Event()
    async def pending(*args):
        started.set()
        await asyncio.Event().wait()
    client._fetch_page = pending
    task = asyncio.create_task(client.fetch(Request('https://example.com')))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert fake_sessions[0].closed and not client._sessions


async def test_bounded_batch_and_error_propagation(fake_sessions):
    client = ScraperClient(sdk=object(), concurrency=2)
    active = peak = 0
    async def page(session, request):
        nonlocal active, peak
        active += 1; peak = max(active, peak)
        await asyncio.sleep(0.001)
        active -= 1
        if request.url.endswith('/bad'): raise ScrapeError('failed')
        return Response(request.url)
    client._fetch_page = page
    results = [r async for r in client.fetch_many(Request(f'https://example.com/{i}') for i in range(10))]
    assert len(results) == 10 and peak <= 2 and all(s.closed for s in fake_sessions)
    with pytest.raises(ScrapeError):
        async for _ in client.fetch_many([Request('https://example.com/bad'),Request('https://example.com/good')]): pass
    assert all(s.closed for s in fake_sessions)


async def test_named_session_rejects_route_change_without_spending_more(fake_sessions):
    client = ScraperClient(sdk=object())
    client._fetch_page = AsyncMock(return_value=Response('https://example.com'))
    async with client:
        await client.fetch(Request('https://example.com', session='x', countryCode='US'))
        with pytest.raises(ValueError):
            await client.fetch(Request('https://example.com', session='x', countryCode='DE'))
        assert len(fake_sessions) == 1
    assert fake_sessions[0].closed


async def test_sdk_close_runs_even_when_browser_disconnect_fails():
    sdk = SimpleNamespace(cdp=SimpleNamespace(close=AsyncMock()))
    session = _Session(sdk, {})
    session.info = {'sessionId':'safe-id'}
    session.browser = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError('disconnect')))
    session.playwright = SimpleNamespace(stop=AsyncMock())
    await session.close()
    sdk.cdp.close.assert_awaited_once_with('safe-id', timeout_ms=30_000)


async def test_cancel_during_sdk_creation_still_deletes_created_session():
    created = asyncio.Event()
    async def create(params, timeout_ms=None):
        created.set()
        await asyncio.sleep(0.02)
        return {'sessionId':'new-session','cdpBaseUrl':'https://secret.invalid/?token=hidden'}
    sdk = SimpleNamespace(cdp=SimpleNamespace(create=create, close=AsyncMock()))
    session = _Session(sdk, {})
    task = asyncio.create_task(session.open())
    await created.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    sdk.cdp.close.assert_awaited_once_with('new-session', timeout_ms=30_000)


async def test_session_create_timeout_closes_only_the_new_session():
    state = {'phase': 0, 'closed': []}

    async def list_sessions(timeout_ms=None):
        state['phase'] += 1
        ids = ['kept'] if state['phase'] == 1 else ['kept', 'orphan']
        return {'ok': True, 'data': [
            {'sessionId': sid, 'expiresAt': '2099-01-01T00:00:00Z', 'cdpBaseUrl': 'https://cdp.invalid/s?token=secret'}
            for sid in ids
        ]}

    async def create(params, timeout_ms=None):
        assert timeout_ms == 180_000
        raise AdsCrawlTimeoutError(timeout_ms)

    async def close(session_id, timeout_ms=None):
        state['closed'].append(session_id)
        return {'ok': True}

    sdk = SimpleNamespace(cdp=SimpleNamespace(list=list_sessions, create=create, close=close))
    session = _Session(sdk, {})
    session.create_timeout_ms = 180_000
    with pytest.raises(AdsCrawlTimeoutError) as caught:
        await session.open()
    assert state['closed'] == ['orphan']
    assert session.info is None
    assert 'secret' not in str(caught.value)


async def test_get_navigation_retries_a_tunnel_once_on_a_new_browser(fake_sessions):
    client = ScraperClient(sdk=object())
    calls = {"n": 0}

    async def page(session, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")
        return Response(request.url)

    client._fetch_page = page
    response = await client.fetch(Request("https://example.com/item"))
    assert response.url == "https://example.com/item"
    assert calls["n"] == 2
    assert fake_sessions[0].closed and not client._sessions

    calls["n"] = 0

    async def denied(session, request):
        calls["n"] += 1
        raise ScrapeError("denied", response=Response(request.url, status_code=403), code="HTTP_ERROR")

    client._fetch_page = denied
    with pytest.raises(ScrapeError) as http_error:
        await client.fetch(Request("https://example.com/item"))
    assert http_error.value.code == "HTTP_ERROR" and calls["n"] == 1

    calls["n"] = 0

    async def post_tunnel(session, request):
        calls["n"] += 1
        raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")

    client._fetch_page = post_tunnel
    with pytest.raises(ScrapeError) as post_error:
        await client.fetch(Request("https://example.com/item", method="POST", body="{}"))
    assert post_error.value.code == "ERR_TUNNEL_CONNECTION_FAILED" and calls["n"] == 1


async def test_named_session_timeout_releases_the_browser(fake_sessions):
    client = ScraperClient(sdk=object(), concurrency=1)

    async def hang(session, request):
        await asyncio.Event().wait()

    client._fetch_page = hang
    with pytest.raises(ScrapeError) as caught:
        await client.fetch(Request('https://example.com/slow', session='kayak', timeoutMs=50))
    assert caught.value.code == 'TIMEOUT'
    assert 'example.com/slow' in str(caught.value)
    assert fake_sessions[0].closed and not client._sessions


async def test_stalled_browser_disconnect_still_releases_remote_session(monkeypatch):
    monkeypatch.setattr('adscrawl_scrapers.runtime._DISCONNECT_TIMEOUT_SECONDS', 0.01)
    sdk = SimpleNamespace(cdp=SimpleNamespace(close=AsyncMock()))
    session = _Session(sdk, {})
    session.info = {'sessionId':'stalled-session'}
    async def stalled():
        await asyncio.Event().wait()
    session.browser = SimpleNamespace(close=stalled)
    session.playwright = SimpleNamespace(stop=AsyncMock())
    await asyncio.wait_for(session.close(), 1)
    sdk.cdp.close.assert_awaited_once_with('stalled-session', timeout_ms=30_000)
    assert session.info is None and session.playwright is None


async def test_browser_actions_and_script_results():
    locator = SimpleNamespace(is_visible=AsyncMock(return_value=False), count=AsyncMock(return_value=0), fill=AsyncMock(), press_sequentially=AsyncMock())
    locator.first = locator
    page = SimpleNamespace(locator=lambda s:locator, wait_for_timeout=AsyncMock(), evaluate=AsyncMock(return_value=[1,2]), wait_for_selector=AsyncMock())
    await perform_actions(page, [
        {'type':'click','selector':'#optional','optional':True},
        {'type':'fill','selector':'input','value':'abc'},
        {'type':'waitForSelector','selector':'h1'},
        {'type':'condition','selector':'missing','state':'not_existing','outcome':'exit_success'},
        {'type':'wait','milliseconds':2000},
    ], 90000)
    locator.fill.assert_awaited_once()
    page.wait_for_timeout.assert_not_awaited()
    assert await evaluate_script(page, 'return [1, 2];') == [1,2]
    with pytest.raises(ValueError): await perform_actions(page,[{'type':'unsupported'}],100)


class FakePage:
    def __init__(self):
        self.url = 'https://example.com/final'
        self.main_frame = object()
        self.handler = None
        self.route_handler = None
        self.closed = False
        self.routed = None
    def on(self, event, handler): self.handler = handler
    def remove_listener(self, event, handler): self.handler = None
    async def set_extra_http_headers(self, headers): self.headers = headers
    async def route(self, pattern, handler): self.route_handler = handler
    async def goto(self, url, **kwargs):
        if self.route_handler:
            request = SimpleNamespace(is_navigation_request=lambda:True,frame=self.main_frame, headers={})
            async def continue_(**kw): self.routed=kw
            await self.route_handler(SimpleNamespace(request=request,continue_=continue_))
        reply = SimpleNamespace(
            request=SimpleNamespace(resource_type='fetch',method='POST',all_headers=AsyncMock(return_value={'x-test':'1'}),post_data='{"q":1}'),
            url='https://example.com/api',status=200,
            all_headers=AsyncMock(return_value={'content-type':'application/json'}),
            text=AsyncMock(return_value='{"rows":[1]}'),body=AsyncMock(return_value=b'{"rows":[1]}'))
        self.handler(reply)
        return reply
    async def content(self): return '<h1>Rendered</h1>'
    async def close(self): self.closed=True


async def test_post_runs_as_browser_navigation_and_collects_network_cookies():
    page = FakePage()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page),add_cookies=AsyncMock(),cookies=AsyncMock(return_value=[{'name':'sid','value':'123'}]))
    client=ScraperClient(sdk=object())
    response=await client._fetch_page(SimpleNamespace(context=context),Request(
        'https://example.com/api',method='POST',body={'q':1},headers={'Content-Type':'application/json','Cookie':'sid=123'}))
    assert page.routed['method']=='POST' and json.loads(page.routed['post_data'])=={'q':1}
    assert 'Cookie' not in page.headers
    context.add_cookies.assert_awaited_once()
    assert response.json()=={'rows':[1]}
    assert response.network[0]['request']['body']=='{"q":1}'
    assert response.network[0]['body']=='{"q":1}'
    assert response.network[0]['headers']=={'x-test':'1'}
    assert response.network[0]['response']['body']=='{"rows":[1]}'
    assert response.cookies[0]['name']=='sid' and page.closed


async def test_network_wait_matches_completed_response_before_parsing():
    page = FakePage()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    client = ScraperClient(sdk=object())
    result = await client._fetch_page(SimpleNamespace(context=context), Request("https://example.com", waitForResponse="/api"))
    assert result.network[0]["response"]["body"] == '{"rows":[1]}'
    assert page.closed


async def test_binary_background_fetch_does_not_break_html_or_json_capture():
    page = FakePage()
    goto = page.goto
    async def with_binary(*args, **kwargs):
        main = await goto(*args, **kwargs)
        page.handler(SimpleNamespace(
            request=SimpleNamespace(resource_type='fetch', method='POST',
                all_headers=AsyncMock(return_value={}), post_data=None),
            url='https://example.com/telemetry', status=200,
            all_headers=AsyncMock(return_value={'content-type':'application/octet-stream'}),
            text=AsyncMock(side_effect=UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid')),
        ))
        return main
    page.goto = with_binary
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    response = await ScraperClient(sdk=object())._fetch_page(
        SimpleNamespace(context=context), Request('https://example.com'))
    assert response.json() == {'rows':[1]}
    assert next(r for r in response.network if r['url'].endswith('/telemetry'))['response']['body'] is None
    assert page.closed


async def test_open_background_stream_does_not_hold_completed_page(monkeypatch):
    monkeypatch.setattr('adscrawl_scrapers.runtime._NETWORK_DRAIN_SECONDS', 0.01)
    page = FakePage()
    goto = page.goto
    cancelled = asyncio.Event()
    async def streaming_body():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def with_stream(*args, **kwargs):
        main = await goto(*args, **kwargs)
        page.handler(SimpleNamespace(
            request=SimpleNamespace(resource_type='fetch'), text=streaming_body))
        return main
    page.goto = with_stream
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    result = await asyncio.wait_for(ScraperClient(sdk=object())._fetch_page(
        SimpleNamespace(context=context), Request('https://example.com', waitForResponse='/api')), 1)
    assert result.json() == {'rows':[1]} and cancelled.is_set() and page.closed


async def test_attachment_preserves_bytes_and_decodes_unicode_json():
    raw = '{"title":"日本語 café"}'.encode('utf-8')
    page = SimpleNamespace(route=AsyncMock(), goto=AsyncMock(), evaluate=AsyncMock(return_value={
        'url':'https://itunes.apple.com/lookup', 'status':200,
        'headers':{'content-type':'text/javascript; charset=utf-8', 'content-disposition':'attachment'},
        'bytes':list(raw),
    }))
    context = SimpleNamespace(cookies=AsyncMock(return_value=[]))
    client = ScraperClient(sdk=object())
    result = await client._fetch_binary(SimpleNamespace(context=context), page,
        Request('https://itunes.apple.com/lookup', binary=True), {})
    assert result.raw == raw and result.json()['title'] == '日本語 café'
    assert page.evaluate.await_args.args[1]['url'] == 'https://itunes.apple.com/lookup'


async def test_binary_gzip_xml_is_inflated_before_text_decode():
    import gzip
    xml = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://www.bestbuy.com/site/promo</loc></url></urlset>'
    ).encode()
    raw = gzip.compress(xml)
    page = SimpleNamespace(route=AsyncMock(), goto=AsyncMock(), evaluate=AsyncMock(return_value={
        'url': 'https://sitemaps.bestbuy.com/sitemaps_promos.0000.xml.gz',
        'status': 200,
        'headers': {'content-type': 'application/xml'},
        'bytes': list(raw),
    }))
    context = SimpleNamespace(cookies=AsyncMock(return_value=[]))
    result = await ScraperClient(sdk=object())._fetch_binary(
        SimpleNamespace(context=context), page,
        Request('https://sitemaps.bestbuy.com/sitemaps_promos.0000.xml.gz', binary=True),
        {},
    )
    assert result.raw == raw
    assert result.raw[:2] == b'\x1f\x8b'
    assert 'https://www.bestbuy.com/site/promo' in result.content
    assert not result.content.startswith('\x1f')


async def test_browser_action_failure_retains_safe_error_code_and_closes_page(monkeypatch, tmp_path):
    from playwright.async_api import Error
    monkeypatch.setenv('ADSCRAWL_FAILURE_DIR', str(tmp_path))
    page = FakePage()
    page.url = 'https://chatgpt.com/'

    async def title():
        return 'Blank'

    async def screenshot(path, type='png'):
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\n')

    page.title = title
    page.screenshot = screenshot
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    client = ScraperClient(sdk=object())
    with patch('adscrawl_scrapers.runtime.perform_actions', AsyncMock(side_effect=Error('secret endpoint'))):
        with pytest.raises(ScrapeError) as failure:
            await client._fetch_page(SimpleNamespace(context=context), Request('https://chatgpt.com/'))
    assert failure.value.code == 'ACTION_FAILED'
    assert 'secret' not in str(failure.value) and 'title="Blank"' in str(failure.value) and page.closed
    assert failure.value.response.diagnostics['url'] == 'https://chatgpt.com/'
    assert list(tmp_path.glob('*.png'))


async def test_managed_async_generator_reuses_session_without_leaking_scope(fake_sessions):
    from adscrawl_scrapers.runtime import _SCOPE
    client = ScraperClient(sdk=object())
    client._fetch_page = AsyncMock(return_value=Response('https://example.com'))
    @managed
    async def pages():
        for number in range(2):
            await client.fetch(Request('https://example.com', session='pages'))
            yield number
    iterator = pages()
    assert await iterator.__anext__() == 0
    assert _SCOPE.get() is None and not fake_sessions[0].closed
    assert await iterator.__anext__() == 1
    assert len(fake_sessions) == 1
    await iterator.aclose()
    assert fake_sessions[0].closed and _SCOPE.get() is None


async def test_nested_generator_does_not_close_parent_scope(fake_sessions):
    client = ScraperClient(sdk=object())
    client._fetch_page = AsyncMock(return_value=Response('https://example.com'))
    @managed
    async def pages():
        await client.fetch(Request('https://example.com', session='pages'))
        yield 1
    @managed
    async def parent():
        assert [item async for item in pages()] == [1]
        assert not fake_sessions[0].closed
    await parent()
    assert fake_sessions[0].closed


async def test_parser_failure_cancels_other_requests_before_leaving_scope(fake_sessions):
    client = ScraperClient(sdk=object(), concurrency=2)
    started = asyncio.Event()
    async def page(session, request):
        if request.url.endswith('/slow'):
            started.set()
            await asyncio.Event().wait()
        await started.wait()
        return Response(request.url)
    client._fetch_page = page
    @managed
    async def operation():
        async for response in client.fetch_many([
            Request('https://example.com/fast'), Request('https://example.com/slow')
        ]):
            raise ValueError('parser rejected the response')
    with pytest.raises(ValueError):
        await asyncio.wait_for(operation(), 1)
    assert len(fake_sessions) == 2 and all(session.closed for session in fake_sessions)
    assert not client._active_requests and not client._sessions


async def test_navigation_error_reports_safe_network_code_without_secret_url(monkeypatch, tmp_path):
    from playwright.async_api import Error
    monkeypatch.setenv('ADSCRAWL_FAILURE_DIR', str(tmp_path))
    page = FakePage()
    page.goto = AsyncMock(side_effect=Error('Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED https://private.invalid/?token=secret'))
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    with pytest.raises(ScrapeError) as caught:
        await ScraperClient(sdk=object())._fetch_page(SimpleNamespace(context=context), Request('https://example.com'))
    assert caught.value.code == 'ERR_TUNNEL_CONNECTION_FAILED'
    assert caught.value.response.status_code == 0
    assert 'secret' not in str(caught.value) and page.closed
    note = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert note['code'] == 'ERR_TUNNEL_CONNECTION_FAILED' and 'secret' not in json.dumps(note)


async def test_tunnel_failure_records_redacted_url_title_and_screenshot(monkeypatch, tmp_path):
    from playwright.async_api import Error
    monkeypatch.setenv('ADSCRAWL_FAILURE_DIR', str(tmp_path))
    page = FakePage()
    page.url = 'https://user:secret@chatgpt.com/?prompt=Paris&token=secret'
    page.goto = AsyncMock(side_effect=Error('Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED https://cdp.invalid/?token=secret'))

    async def title():
        return '  ChatGPT \n'

    async def screenshot(path, type='png'):
        Path(path).write_bytes(b'\x89PNG\r\n\x1a\n')

    page.title = title
    page.screenshot = screenshot
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    with pytest.raises(ScrapeError) as caught:
        await ScraperClient(sdk=object())._fetch_page(SimpleNamespace(context=context), Request('https://chatgpt.com/?prompt=Paris'))
    text = str(caught.value)
    assert caught.value.code == 'ERR_TUNNEL_CONNECTION_FAILED'
    assert 'secret' not in text and 'token=REDACTED' in text and 'prompt=Paris' in text
    assert 'title="ChatGPT"' in text and 'screenshot=' in text and page.closed
    note = json.loads(next(tmp_path.glob('*.json')).read_text())
    image = next(tmp_path.glob('*.png'))
    assert note['title'] == 'ChatGPT' and note['screenshot'] == image.name
    assert 'secret' not in json.dumps(note) and image.stat().st_size > 0


async def test_navigation_timeout_still_reports_timeout_when_screenshot_fails(monkeypatch, tmp_path):
    from playwright.async_api import TimeoutError as PlaywrightTimeout
    monkeypatch.setenv('ADSCRAWL_FAILURE_DIR', str(tmp_path))
    page = FakePage()
    page.url = 'about:blank'
    page.goto = AsyncMock(side_effect=PlaywrightTimeout('Timeout 90000ms exceeded'))

    async def title():
        return 'timeout'

    page.title = title
    page.screenshot = AsyncMock(side_effect=PlaywrightTimeout('shot'))
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    with pytest.raises(ScrapeError) as caught:
        await ScraperClient(sdk=object())._fetch_page(SimpleNamespace(context=context), Request('https://chatgpt.com/'))
    assert caught.value.code == 'TIMEOUT'
    assert 'title="timeout"' in str(caught.value)
    note = json.loads(next(tmp_path.glob('*.json')).read_text())
    assert note['url'] == 'about:blank' and note['screenshot'] == '' and not list(tmp_path.glob('*.png'))


async def test_stalled_tab_close_does_not_hold_a_completed_request(monkeypatch):
    from adscrawl_scrapers import runtime
    page = FakePage()
    async def stalled_close():
        await asyncio.Event().wait()
    page.close = stalled_close
    monkeypatch.setattr(runtime, '_DISCONNECT_TIMEOUT_SECONDS', 0.01)
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    response = await asyncio.wait_for(ScraperClient(sdk=object())._fetch_page(
        SimpleNamespace(context=context), Request('https://example.com/api')), 1)
    assert response.json() == {'rows': [1]}


async def test_http_error_is_reported_before_waiting_for_missing_site_data():
    page = FakePage()
    page.goto = AsyncMock(return_value=SimpleNamespace(status=403, all_headers=AsyncMock(return_value={})))
    page.wait_for_selector = AsyncMock(side_effect=AssertionError('must not wait on the error document'))
    context = SimpleNamespace(new_page=AsyncMock(return_value=page))
    with pytest.raises(ScrapeError) as caught:
        await ScraperClient(sdk=object())._fetch_page(SimpleNamespace(context=context), Request(
            'https://example.com', waitForSelector='#products', waitForResponse='/api/products'))
    assert caught.value.code == 'HTTP_ERROR' and caught.value.response.status_code == 403
    assert caught.value.response.content == '<h1>Rendered</h1>' and page.closed


def test_default_us_route_respects_explicit_country_and_custom_proxy(monkeypatch):
    monkeypatch.delenv('ADSCRAWL_DEFAULT_COUNTRY', raising=False)
    assert Request('https://example.com').browser_settings()['countryCode'] == 'US'
    monkeypatch.setenv('ADSCRAWL_DEFAULT_COUNTRY', 'gb')
    assert Request('https://example.com').browser_settings()['countryCode'] == 'GB'
    assert Request('https://example.com', countryCode='us').browser_settings()['countryCode'] == 'US'
    settings = Request('https://example.com', proxy={'server':'http://proxy.example:8080'}).browser_settings()
    assert settings['proxy']['server'] == 'http://proxy.example:8080'
    assert 'countryCode' not in settings


async def test_explicit_accept_is_applied_to_get_navigation_interception():
    page = FakePage()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    await ScraperClient(sdk=object())._fetch_page(SimpleNamespace(context=context), Request(
        'https://example.com/api', headers={'Accept':'application/json'}))
    assert page.routed['method'] == 'GET'
    assert page.routed['headers']['accept'] == 'application/json'
    assert 'Accept' not in page.routed['headers']
