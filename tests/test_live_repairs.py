"""Regressions reproduced during the 2026-11-11 live audit (no API calls)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json

import pytest

import google_play
import nordstorm
import ebay
import target
import bookingcom
import goibibo
import aliexpress
from urllib.parse import parse_qs, urlsplit
from adscrawl_scrapers import Request, Response, ScrapeError


async def test_google_play_navigation_failure_uses_html_once_with_us_routing(monkeypatch):
    fetch = AsyncMock(side_effect=ScrapeError("tunnel failed", code="ERR_TUNNEL_CONNECTION_FAILED"))
    html = AsyncMock(return_value="<html>app document</html>")
    monkeypatch.setattr(google_play.CLIENT, "fetch", fetch)
    monkeypatch.setattr(google_play, "AsyncAdsCrawl", lambda **_: SimpleNamespace(html=html))
    response = await google_play._fetch(Request("https://play.google.com/store/apps/details?id=example", countryCode="US"))
    assert fetch.await_count == html.await_count == 1
    params = html.call_args.args[0]
    assert params["countryCode"] == "US"
    assert params["contentMode"] == "html" and params["timeoutMs"] == 45_000
    assert response.request_url.endswith("id=example")
    assert response.content == "<html>app document</html>" and response.status_code == 0


async def test_google_play_does_not_retry_an_http_denial(monkeypatch):
    failure = ScrapeError("Target returned HTTP 403", code="HTTP_ERROR")
    monkeypatch.setattr(google_play.CLIENT, "fetch", AsyncMock(side_effect=failure))
    with pytest.raises(ScrapeError) as caught:
        await google_play._fetch(Request("https://play.google.com/store/apps/details?id=example"))
    assert caught.value is failure


async def test_google_play_missing_app_data_cannot_be_returned_as_partial_success(monkeypatch):
    monkeypatch.setattr(google_play, "_fetch", AsyncMock(return_value=Response(
        "https://play.google.com/store/apps/details?id=example", "<html><title>Verify</title></html>"
    )))
    with pytest.raises(ScrapeError, match="DATA_MISSING"):
        await google_play.scrape_apps(["example"])


def test_nordstrom_verification_document_is_not_a_missing_product():
    page = Response("https://www.nordstrom.com/s/example/1", "<script>window['istlWasHere'] = true;</script>")
    with pytest.raises(ScrapeError) as caught:
        nordstorm.find_hidden_data(page)
    assert caught.value.code == "TARGET_BLOCKED" and caught.value.response is page


def test_nordstrom_config_does_not_consume_other_script_statements():
    page = Response("https://www.nordstrom.com/s/example/1", '''<script>
        window.other = true; window.__INITIAL_CONFIG__ = {"productDisplay": {"id": 42}};
        window.ready = true;
    </script>''')
    assert nordstorm.find_hidden_data(page) == {"productDisplay": {"id": 42}}


def test_ebay_large_403_error_document_is_not_a_solved_challenge():
    page = Response("https://www.ebay.com/sch/i.html", "<title>Error Page | eBay</title>" + " " * 2000, status_code=403)
    assert not ebay._usable(page)
    solved = Response(page.url, '<title>eBay</title><ul class="srp-results"><li>Product</li></ul>', status_code=403)
    assert ebay._usable(solved)


async def test_ebay_missing_result_count_reports_data_error(monkeypatch):
    monkeypatch.setattr(ebay, "_fetch_document", AsyncMock(return_value=Response(
        "https://www.ebay.com/sch/i.html", "<html><title>eBay</title></html>"
    )))
    with pytest.raises(ScrapeError, match="DATA_MISSING"):
        await ebay.scrape_search("https://www.ebay.com/sch/i.html", max_pages=1)


def test_target_preserves_block_status_when_only_pricing_loaded():
    page = Response("https://www.target.com/p/example", network=[
        {"url": "https://www.target.com/deferred_enrichment/modules", "response": {
            "status": 200, "body": json.dumps({"modules": [{
                "module_type": target.MODULE_WITH_STORE, "module_data": {"data": {"product": {"tcin": "1"}}}
            }]})}},
        {"url": "https://www.target.com/deferred_enrichment/modules", "response": {
            "status": 435, "body": '{"blockScript":"captcha.js"}'}},
    ])
    with pytest.raises(ScrapeError, match="HTTP 435") as caught:
        target.parse_product(page)
    assert caught.value.response is page


@pytest.mark.parametrize("operation", ["hotel", "search"])
async def test_booking_retry_releases_the_only_browser_slot(monkeypatch, operation):
    active = set()
    calls = []
    async def fetch(request):
        assert not active, "the failed browser still occupies the only slot"
        active.add(request.session)
        calls.append(request.session)
        raise ScrapeError("navigation failed", code="TIMEOUT")
    async def close(name):
        active.discard(name)
    monkeypatch.setattr(bookingcom.CLIENT, "fetch", fetch)
    monkeypatch.setattr(bookingcom.CLIENT, "close_session", close)
    monkeypatch.setattr(bookingcom, "search_location_suggestions", AsyncMock(return_value={
        "results": [{"value": "London", "dest_id": "1", "dest_type": "city"}]
    }))
    with pytest.raises(ScrapeError, match="TIMEOUT"):
        if operation == "hotel":
            await bookingcom.scrape_hotel("https://www.booking.com/hotel/example.html", "2026-12-01")
        else:
            await bookingcom.scrape_search("London", "2026-12-01", "2026-12-02", max_pages=1)
    assert len(calls) == 2 and calls[0] != calls[1]


def test_goibibo_hotel_url_supplies_the_destination_id_and_compact_dates():
    url = goibibo.build_search_url("Delhi", "CTDEL", "2026-11-12", "20261118")
    query = parse_qs(urlsplit(url).query)
    assert query["cityCode"] == query["locusId"] == ["CTDEL"]
    assert query["checkin"] == ["20261112"] and query["checkout"] == ["20261118"]
    other = goibibo.build_search_url("Area", "AREA1", "2026-11-12", "2026-11-18", locus_type="area")
    assert "cityCode" not in parse_qs(urlsplit(other).query)


def test_aliexpress_empty_shell_does_not_become_a_successful_product():
    with pytest.raises(ScrapeError, match="DATA_MISSING"):
        aliexpress.parse_product(Response("https://www.aliexpress.us/item/123.html", "<html>Aliexpress</html>"))


def test_aliexpress_prices_and_abbreviated_counts_remain_numeric():
    product = aliexpress.parse_product(Response("https://www.aliexpress.us/item/123.html", '''
        <h1 data-pl>Example product</h1><span class="price-default--current">US $1,299.50</span>
        <a class="reviewer--sliderItem"><span>100K+ sold</span></a>
    '''))
    assert product["info"]["soldCount"] == 100_000
    assert product["pricing"]["price"] == 1299.50 and product["pricing"]["originalPrice"] is None
    assert aliexpress._parse_count("1.2M sold") == 1_200_000
