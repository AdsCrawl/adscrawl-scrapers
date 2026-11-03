"""Offline coverage for the 2026-11-03 US wave-2 live failures."""
import json

import pytest

from adscrawl_scrapers import Response, ScrapeError

import facebook
import dhl
import kayak
import nordstorm
import pinterest
import target
import walmart


async def test_facebook_marketplace_retries_a_tunnel_once(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")
        return Response(request.url, "<html></html>")

    monkeypatch.setattr(facebook.CLIENT, "fetch", fetch)
    assert await facebook.scrape_marketplace_listings("electronics") == []
    assert calls["n"] == 2


async def test_facebook_does_not_retry_a_target_http_error(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        raise ScrapeError("denied", response=Response(request.url, status_code=403), code="HTTP_ERROR")

    monkeypatch.setattr(facebook.CLIENT, "fetch", fetch)
    with pytest.raises(ScrapeError):
        await facebook.scrape_marketplace_listings("electronics")
    assert calls["n"] == 1


async def test_walmart_product_retries_a_tunnel_once(monkeypatch):
    calls = {"n": 0}
    html = '''<script id="__NEXT_DATA__">{"props":{"pageProps":{"initialData":{"data":{
        "product":{"availabilityStatus":"IN_STOCK","name":"Milk","id":"1"},
        "reviews":{}}}}}}</script>'''

    async def fetch(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")
        return Response(request.url, html)

    monkeypatch.setattr(walmart.CLIENT, "fetch", fetch)
    result = await walmart.scrape_products(["https://www.walmart.com/ip/1"])
    assert calls["n"] == 2
    assert result[0]["product"]["name"] == "Milk"


async def test_walmart_product_does_not_retry_http_errors(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        raise ScrapeError("denied", response=Response(request.url, status_code=403), code="HTTP_ERROR")

    monkeypatch.setattr(walmart.CLIENT, "fetch", fetch)
    with pytest.raises(ScrapeError):
        await walmart.scrape_products(["https://www.walmart.com/ip/1"])
    assert calls["n"] == 1


async def test_pinterest_image_download_uses_navigation_body_and_retries_connect(monkeypatch):
    calls = []

    async def fetch(request):
        calls.append(request)
        if len(calls) == 1:
            raise ScrapeError("connect", code="CONNECT_FAILED")
        return Response(request.url, raw=b"\xff\xd8\xff\x00", headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(pinterest.CLIENT, "fetch", fetch)
    results = await pinterest.download_pin_images([
        {"pin_id": "1", "image": "https://i.pinimg.com/originals/a.jpg"},
    ])
    assert calls[0].binary is False and calls[0].render is False
    assert results[0]["success"] is True
    assert results[0]["image_base64"]


async def test_pinterest_html_challenge_is_not_a_downloaded_image(monkeypatch):
    async def fetch(request):
        return Response(
            request.url,
            content="<html>blocked</html>",
            raw=b"<html>blocked</html>",
            headers={"content-type": "text/html"},
        )

    monkeypatch.setattr(pinterest.CLIENT, "fetch", fetch)
    results = await pinterest.download_pin_images([
        {"pin_id": "1", "image": "https://i.pinimg.com/originals/a.jpg"},
    ])
    assert results[0]["image_base64"] is None
    assert results[0]["success"] is False


def test_nordstrom_waits_for_the_config_script_without_using_the_whole_budget():
    request = nordstorm.Request("https://www.nordstrom.com/sr?keyword=indigo", **nordstorm.BASE_CONFIG)
    assert request.waitUntil == "commit"
    assert request.timeoutMs == 120_000
    action = request.actions[0]
    assert action["state"] == "attached"
    assert "__INITIAL_CONFIG__" in action["selector"]
    assert action["timeoutMs"] < request.timeoutMs


async def test_nordstrom_retries_a_timeout_once(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScrapeError("timed out url=https://www.nordstrom.com/s/example/1", code="TIMEOUT")
        return Response(request.url, "<html></html>")

    monkeypatch.setattr(nordstorm.CLIENT, "fetch", fetch)
    monkeypatch.setattr(nordstorm, "find_hidden_data", lambda response: {
        "productDisplay": {"productDisplaysById": {"entities": {"1": {
            "id": "1",
            "coreProducts": [{"nptHierarchy": "Men.Shoes", "coreChoices": []}],
        }}}},
    })
    products = await nordstorm.scrape_products(["https://www.nordstrom.com/s/example/1"])
    assert calls["n"] == 2
    assert products[0]["id"] == "1"


async def test_kayak_search_waits_for_the_poll_and_raises_the_client_budget(monkeypatch):
    seen = []

    async def fetch(request):
        seen.append(request)
        body = json.dumps({
            "searchStatus": {"tripType": "roundtrip"},
            "searchId": "abc",
            "filteredCount": 1,
            "pageNumber": 1,
            "results": [{
                "type": "core",
                "totalBookingOptions": 1,
                "bookingOptions": [{
                    "displayPrice": {"price": 120, "currency": "USD"},
                    "legFarings": [{
                        "legId": "L",
                        "approxDepartureTime": "10:00 am",
                        "approxArrivalTime": "1:00 pm",
                    }],
                }],
            }],
            "legs": {"L": {
                "segments": [{"id": "S"}],
                "duration": 180,
                "departure": "2026-11-03T10:00:00",
                "arrival": "2026-11-03T13:00:00",
            }},
            "segments": {"S": {"airline": "AA"}},
            "airlines": {"AA": {"name": "American"}},
        })
        return Response(request.url, "", network=[{
            "url": kayak.POLL_URL,
            "headers": {},
            "response": {"body": body},
        }])

    monkeypatch.setattr(kayak.CLIENT, "fetch", fetch)
    flights = await kayak.scrape_flights("JFK", "LAX", "2026-11-03", "2026-11-10", max_pages=1)
    assert seen[0].timeoutMs == 180_000
    assert seen[0].waitForResponse == kayak.POLL_URL
    assert seen[0].session
    assert len(seen) == 1
    assert flights[0]["origin"] == "JFK"
    assert flights[0]["price"] == "$120"


def test_dhl_fixture_is_the_documented_public_example_and_empty_is_not_success():
    assert dhl.EXAMPLE_TRACKING_NUMBER == "7777777770"
    url = dhl._build_tracking_url(dhl.EXAMPLE_TRACKING_NUMBER, api_endpoint=True)
    assert "trackingNumber=7777777770" in url
    assert "requesterCountryCode=US" in url
    assert "source=tt" in url
    empty = dhl._parse_tracking_api_response({"shipments": []}, dhl.EXAMPLE_TRACKING_NUMBER)
    assert empty["classification"] == "empty" and empty["events"] == []
    blocked = dhl._classify_payload({"sec-cp-challenge": "true"}, dhl.EXAMPLE_TRACKING_NUMBER)
    assert blocked["classification"] == "captcha-or-forbidden"
    parsed = dhl._parse_tracking_api_response({
        "shipments": [{
            "id": "7777777770",
            "status": {"description": "Delivered", "statusCode": "delivered"},
            "events": [{
                "timestamp": "2026-09-18T14:22:00",
                "statusCode": "delivered",
                "description": "Delivered",
                "location": {"address": {"addressLocality": "New York"}},
            }],
        }],
    }, dhl.EXAMPLE_TRACKING_NUMBER)
    assert parsed["classification"] == "success"
    assert parsed["events"][0]["location"] == "New York"


def test_dhl_panel_events_fill_in_when_utapi_is_blocked():
    page = Response(
        "https://www.dhl.com/us-en/home/tracking.html",
        '<table id="panel_events"><tr><td>6:25 PM</td><td>Delivered</td><td>New York</td></tr></table>',
    )
    blocked = dhl._classify_payload({"sec-cp-challenge": "true"}, dhl.EXAMPLE_TRACKING_NUMBER)
    result = dhl._with_panel_events(blocked, page, dhl.EXAMPLE_TRACKING_NUMBER)
    assert result["classification"] == "success"
    assert result["events"][0]["description"] == "Delivered"
    assert dhl._with_panel_events(blocked, Response("https://www.dhl.com/us-en/home/tracking.html", "<html></html>"), "7777777770")["classification"] == "captcha-or-forbidden"


async def test_target_product_retries_435_then_names_the_anti_bot_block(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        return Response(request.url, "<html></html>", network=[{
            "url": "https://redsky.target.com/deferred_enrichment/modules",
            "response": {"status": 435, "body": ""},
        }])

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    with pytest.raises(ScrapeError) as caught:
        await target.scrape_product("https://www.target.com/p/-/A-1")
    assert calls["n"] == 2
    assert caught.value.code == "HTTP_ERROR"
    assert "anti-bot" in str(caught.value) and "435" in str(caught.value)


async def test_target_availability_retries_a_435_on_a_new_session(monkeypatch):
    seen = []
    closed = []

    async def fetch(request):
        seen.append(request)
        if "redsky.target.com" in request.url and "product_summary" in request.url:
            raise ScrapeError("blocked", response=Response(request.url, status_code=435), code="HTTP_ERROR")
        return Response(request.url, network=[{
            "url": "https://redsky.target.com/store_location_v1?key=abc&visitor_id=vis",
            "response": {"status": 200, "body": "{}"},
        }])

    async def close_session(name):
        closed.append(name)

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", close_session)
    with pytest.raises(ScrapeError) as caught:
        await target.scrape_availability(["89231676"], "1771", "52404")
    assert "anti-bot" in str(caught.value) and "435" in str(caught.value)
    redsky = [request.session for request in seen if "product_summary" in request.url]
    assert len(redsky) == 2 and redsky[0] != redsky[1]
    assert set(redsky) <= set(closed)
