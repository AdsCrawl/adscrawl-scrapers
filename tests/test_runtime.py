import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from adscrawl_scrapers import Request, Response, ScraperClient, ScrapeError, managed
from adscrawl_scrapers.runtime import _Session, perform_actions, evaluate_script


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
    sdk.cdp.close.assert_awaited_once_with('safe-id')


async def test_cancel_during_sdk_creation_still_deletes_created_session():
    created = asyncio.Event()
    async def create(params):
        created.set()
        await asyncio.sleep(0.02)
        return {'sessionId':'new-session','cdpBaseUrl':'https://secret.invalid/?token=hidden'}
    sdk = SimpleNamespace(cdp=SimpleNamespace(create=create, close=AsyncMock()))
    session = _Session(sdk, {})
    task = asyncio.create_task(session.open())
    await created.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    sdk.cdp.close.assert_awaited_once_with('new-session')


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


async def test_browser_action_failure_retains_safe_error_code_and_closes_page():
    from playwright.async_api import Error
    page = FakePage()
    context = SimpleNamespace(new_page=AsyncMock(return_value=page), cookies=AsyncMock(return_value=[]))
    client = ScraperClient(sdk=object())
    with patch('adscrawl_scrapers.runtime.perform_actions', AsyncMock(side_effect=Error('secret endpoint'))):
        with pytest.raises(ScrapeError) as failure:
            await client._fetch_page(SimpleNamespace(context=context), Request('https://example.com'))
    assert failure.value.code == 'ACTION_FAILED'
    assert 'secret' not in str(failure.value) and page.closed
