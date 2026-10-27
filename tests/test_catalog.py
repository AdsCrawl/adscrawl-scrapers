import importlib.util
import json
from pathlib import Path

from adscrawl_scrapers import Response

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_catalog', ROOT/'scripts/check_catalog.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_all_81_sites_import_without_credentials(monkeypatch):
    monkeypatch.delenv('ADSCRAWL_API_KEY', raising=False)
    assert audit.check() == 81


def test_existing_google_and_amazon_parsers_accept_normalized_response():
    amazon = audit.load_module(ROOT/'amazon-scraper/amazon.py')
    html='''<div class="s-result-item" data-component-type="s-search-result">
    <div><a href="/dp/ASIN"><h2 aria-label="Product"></h2></a></div>
    <span class="a-price" data-a-size="xl"><span class="a-offscreen">$10</span></span>
    </div>'''
    results=amazon.parse_search(Response('https://www.amazon.com/s?q=x',html))
    assert results[0]['url']=='https://www.amazon.com/dp/ASIN'
    assert results[0]['title']=='Product' and results[0]['price']=='$10'
    google = audit.load_module(ROOT/'google-scraper/google.py')
    assert callable(google.scrape_ai_mode)


def test_app_store_json_parser():
    module=audit.load_module(ROOT/'app-store-scraper/app_store.py')
    fixture = {"resultCount": 1, "results": [{"trackId": 123, "trackName": "Example App", "bundleId": "com.example.app", "price": 0, "currency": "USD", "artistName": "Example"}]}
    data = module.parse_app_metadata(Response("https://itunes.apple.com/lookup", json.dumps(fixture)), "123", "US")
    assert data["appId"] == "123" and data["free"] is True
    assert data["title"] == "Example App" and data["country"] == "us"


def test_sitemap_parser_accepts_compressed_and_browser_decoded_bytes():
    import gzip
    module=audit.load_module(ROOT/'bestbuy-scraper/bestbuy.py')
    xml=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/product</loc></url></urlset>'
    for payload in (xml, gzip.compress(xml)):
        result = module.parse_sitemaps(Response("https://example.com/sitemap.gz", raw=payload))
        assert result == ["https://example.com/product"]


def test_pinterest_image_base64_preserves_binary_bytes():
    import base64
    module=audit.load_module(ROOT/'pinterest-scraper/pinterest.py')
    raw=b'\x89PNG\r\n\x1a\n\xff\x00'
    assert base64.b64decode(module._content_to_base64(raw)) == raw


async def test_crunchbase_preserves_original_failure_without_blind_retries(monkeypatch):
    from unittest.mock import AsyncMock
    import pytest
    from adscrawl_scrapers import ScrapeError
    module = audit.load_module(ROOT/'crunchbase-scraper/crunchbase.py')
    for fn in (module.scrape_company, module.scrape_person):
        failure = ScrapeError('Target returned HTTP 403', code='HTTP_ERROR')
        fetch = AsyncMock(side_effect=failure)
        monkeypatch.setattr(module.CLIENT, 'fetch', fetch)
        with pytest.raises(ScrapeError) as caught:
            await fn('https://www.crunchbase.com/organization/example')
        assert caught.value is failure and fetch.await_count == 1


def test_crunchbase_sitemap_accepts_raw_gzip_and_plain_xml():
    import gzip
    module = audit.load_module(ROOT/'crunchbase-scraper/crunchbase.py')
    xml = b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/company</loc><lastmod>2026-10-27T00:00:00Z</lastmod></url></urlset>'
    for payload in (xml, gzip.compress(xml)):
        rows = list(module.parse_sitemap(Response('https://example.com/sitemap.xml.gz', raw=payload)))
        assert rows[0][0] == 'https://example.com/company' and rows[0][1].year == 2026


def test_dhl_empty_feed_is_explicit_and_never_claims_success():
    module = audit.load_module(ROOT/'dhl-scraper/dhl.py')
    result = module._parse_tracking_api_response({'shipments': []}, 'EXAMPLE')
    assert result['classification'] == 'empty'
    assert result['tracking_number'] == 'EXAMPLE' and result['events'] == []


async def test_fashionphile_pagination_uses_canonical_url_and_sort_order(monkeypatch):
    from unittest.mock import AsyncMock
    module = audit.load_module(ROOT/'fashionphile-scraper/fashionphile.py')
    canonical = 'https://www.fashionphile.com/collections/discounted-all'
    html = '<li class="ais-Pagination-item--lastPage"><a href="'+canonical+'?sortBy=price_desc&amp;page=42">42</a></li>'
    monkeypatch.setattr(module.CLIENT, 'fetch', AsyncMock(return_value=Response(canonical, html)))
    requests = []
    async def pages(items):
        requests.extend(items)
        for item in items:
            yield Response(item.url, '')
    monkeypatch.setattr(module.CLIENT, 'fetch_many', pages)
    await module.scrape_search('https://www.fashionphile.com/shop/discounted/all', max_pages=3)
    assert [r.url for r in requests] == [canonical+'?sortBy=price_desc&page=2', canonical+'?sortBy=price_desc&page=3']
    assert all(r.waitForSelector == '.fp-algolia-product-card' for r in requests)
