"""Opt-in real AdsCrawl smoke test: one browser, HTML and JSON POST requests.

Runs only when explicitly invoked. Consumes AdsCrawl credits. Does not log keys,
CDP URLs, cookies, response bodies or exception messages containing credentials.
"""
import asyncio
import json
from adscrawl_scrapers import Request, ScraperClient

async def main():
    results = []
    async with ScraperClient(concurrency=1) as client:
        html = await client.fetch(Request('https://example.com', session='smoke', countryCode='US', timeoutMs=60000))
        print(json.dumps({'check':'html_observed','status':html.status_code,'title':html.selector.css('title::text').get(),'content_type':html.headers.get('content-type')}),flush=True)
        assert html.status_code == 200 and html.selector.css('title::text').get() == 'Example Domain'
        results.append({'check':'rendered_html', 'status':'passed'})
        result = await client.fetch(Request('https://postman-echo.com/post', session='smoke', countryCode='US',
            method='POST', body={'adscrawl_smoke':'ok'}, headers={'content-type':'application/json'}, timeoutMs=60000))
        print(json.dumps({'check':'post_observed','status':result.status_code,'content_type':result.headers.get('content-type'),'json':result.json().get('json'),'data':result.json().get('data')}),flush=True)
        assert result.status_code == 200 and result.json()['json'] == {'adscrawl_smoke':'ok'}
        results.append({'check':'remote_json_post', 'status':'passed'})
    results.append({'check':'session_cleanup','status':'passed'})
    print(json.dumps(results))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps({'status':'failed','error_type':type(error).__name__,'code':getattr(error,'code',None)}))
        raise SystemExit(1)
