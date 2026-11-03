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


async def test_nordstrom_retries_an_action_failure_once_and_not_a_timeout(monkeypatch):
    calls = {"n": 0}

    async def fetch(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScrapeError("action failed", code="ACTION_FAILED")
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

    calls["n"] = 0

    async def timeout(request):
        calls["n"] += 1
        raise ScrapeError("timed out url=https://www.nordstrom.com/s/example/1", code="TIMEOUT")

    monkeypatch.setattr(nordstorm.CLIENT, "fetch", timeout)
    with pytest.raises(ScrapeError) as caught:
        await nordstorm.scrape_products(["https://www.nordstrom.com/s/example/1"])
    # GET TIMEOUT is one runtime retry. The scraper must not add another 120s pass.
    assert caught.value.code == "TIMEOUT"
    assert calls["n"] == 1


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


def test_dhl_fixture_is_a_public_page_shipment_and_empty_is_not_success():
    assert dhl.EXAMPLE_TRACKING_NUMBER == "146000018487"
    assert dhl.EXAMPLE_TRACKING_NUMBER != "7777777770"
    url = dhl._build_tracking_url(dhl.EXAMPLE_TRACKING_NUMBER, api_endpoint=False)
    assert "tracking-id=146000018487" in url
    assert "/utapi" not in url
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


def test_dhl_page_ignores_the_challenge_xhr_and_not_found_is_empty():
    challenge = {"url": "https://www.dhl.com/utapi?trackingNumber=1", "response": {"body": '{"sec-cp-challenge":"true"}'}}
    shipment = {
        "url": "https://www.dhl.com/utapi?trackingNumber=1",
        "response": {"body": json.dumps({"shipments": [{
            "id": "146000018487",
            "status": {"description": "Delivered"},
            "events": [{
                "timestamp": "2026-04-29T18:25:00",
                "description": "Delivered",
                "location": {"address": {"addressLocality": "France"}},
            }],
        }]})},
    }
    page = Response("https://www.dhl.com/us-en/home/tracking.html", "<html></html>", network=[challenge, shipment])
    solved = dhl._page_result(page, dhl.EXAMPLE_TRACKING_NUMBER)
    assert solved["classification"] == "success"
    assert solved["events"][0]["location"] == "France"
    missing = Response(
        "https://www.dhl.com/us-en/home/tracking.html",
        "<main><p>Sorry, your tracking attempt was not successful. Please check your tracking number.</p></main>",
        network=[challenge],
    )
    assert dhl._page_result(missing, dhl.EXAMPLE_TRACKING_NUMBER)["classification"] == "empty"
    blocked = Response(
        "https://www.dhl.com/us-en/home/tracking.html",
        '<html><iframe id="sec-cpt-if"></iframe></html>',
        status_code=200,
        network=[challenge],
    )
    assert dhl._page_result(blocked, dhl.EXAMPLE_TRACKING_NUMBER)["classification"] == "captcha-or-forbidden"


async def test_dhl_tracking_reads_the_rendered_page_not_the_utapi_document(monkeypatch):
    seen = []

    async def fetch(request):
        seen.append(request)
        html = (
            '<main><div class="c-tracking-result--container is-visible">'
            'Tracking Code: 146000018487'
            '<table id="panel_events"><tr>'
            '<td class="c-event-log--date">April 29, 2026</td>'
            '<td class="c-event-log--localtime">6:25 PM Local time</td>'
            '<td class="c-event-log--status">Delivered</td>'
            '<td class="c-event-log--location">France</td>'
            '</tr></table></div></main>'
        )
        return Response(request.url, html)

    monkeypatch.setattr(dhl.CLIENT, "fetch", fetch)
    result = await dhl.scrape_tracking(dhl.EXAMPLE_TRACKING_NUMBER)
    assert "/utapi" not in seen[0].url
    assert "tracking-id=146000018487" in seen[0].url
    assert seen[0].waitForResponse is None
    assert result["classification"] == "success"
    assert result["events"][0]["description"] == "Delivered"
    assert result["events"][0]["location"] == "France"


def _target_product_block(request):
    return Response(request.url, "<html></html>", network=[{
        "url": "https://redsky.target.com/deferred_enrichment/modules",
        "response": {"status": 435, "body": ""},
    }])


async def test_target_product_retries_435_then_names_the_anti_bot_block(monkeypatch):
    seen = []
    closed = []

    async def pause(seconds):
        return None

    async def fetch(request):
        seen.append(request)
        if request.javascript and "product_summary_with_fulfillment_v1" in request.javascript:
            return Response(
                request.url,
                javascript={"status": 435, "body": "<html>Access Denied</html>"},
            )
        if "/A-" in request.url:
            return _target_product_block(request)
        return _target_credentials(request)

    async def close_session(name):
        closed.append(name)

    monkeypatch.setattr(target, "_pause", pause)
    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", close_session)
    with pytest.raises(ScrapeError) as caught:
        await target.scrape_product("https://www.target.com/p/-/A-1")
    assert caught.value.code == "HTTP_ERROR"
    assert "anti-bot" in str(caught.value) and "435" in str(caught.value)
    assert all(not request.url.startswith("https://redsky.target.com") for request in seen)
    summaries = [
        request for request in seen
        if request.javascript and "product_summary_with_fulfillment_v1" in request.javascript
    ]
    assert len(summaries) == target._REDSKY_ATTEMPTS
    assert len({request.session for request in summaries}) == target._REDSKY_ATTEMPTS
    assert {request.session for request in summaries} <= set(closed)
    assert all("store_id=1771" in request.javascript and "zip=52404" in request.javascript for request in summaries)


async def test_target_product_uses_the_summary_when_the_page_is_blocked(monkeypatch):
    body = json.dumps({"data": {"product_summaries": [{
        "tcin": "95213693",
        "item": {"product_description": {"title": "Lace tank"}},
        "price": {"current_retail": 15, "formatted_current_price": "$15.00"},
        "free_shipping": {"enabled": True},
        "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
    }]}})
    seen = []

    async def fetch(request):
        seen.append(request)
        if request.javascript and "product_summary_with_fulfillment_v1" in request.javascript:
            return Response(request.url, javascript={"status": 200, "body": body})
        if "/A-" in request.url:
            raise ScrapeError(
                "blocked",
                response=Response(request.url, status_code=435),
                code="HTTP_ERROR",
            )
        return _target_credentials(request)

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", lambda name: _done())
    product = await target.scrape_product(
        "https://www.target.com/p/women-s-lace-godet-tank-top-wild-fable/-/A-95213693"
    )
    assert product["tcin"] == "95213693"
    assert product["title"] == "Lace tank"
    assert product["rating"] is None
    assert product["variants"][0]["in_stock"] is True
    assert product["variants"][0]["free_shipping"] is True
    assert all(not request.url.startswith("https://redsky.target.com") for request in seen)
    assert sum(1 for request in seen if request.javascript) == 1


def test_target_search_api_rows_keep_tcin_and_url():
    rows = target.parse_search_api({"data": {"search": {"products": [{
        "tcin": "123",
        "item": {
            "product_description": {"title": "Laptop"},
            "primary_brand": {"name": "Acer"},
            "enrichment": {"buy_url": "/p/laptop/-/A-123"},
        },
        "price": {"formatted_current_price": "$199.00", "formatted_comparison_price": "$249.00"},
    }]}}})
    assert rows == [{
        "tcin": "123",
        "url": "https://www.target.com/p/laptop/-/A-123",
        "title": "Laptop",
        "brand": "Acer",
        "price": "$199.00",
        "reg_price": "$249.00",
    }]
    assert target.parse_search_api({"data": {"search": {"products": []}}}) == []


async def test_target_search_falls_back_to_plp_search_when_the_page_times_out(monkeypatch):
    body = json.dumps({"data": {"search": {"products": [
        {"tcin": str(1000 + index), "item": {"product_description": {"title": f"Laptop {index}"}}}
        for index in range(12)
    ]}}})
    seen = []

    async def fetch(request):
        seen.append(request)
        if request.javascript and "plp_search_v2" in request.javascript:
            return Response(request.url, javascript={"status": 200, "body": body})
        if "/s?" in request.url:
            raise ScrapeError("timed out", code="TIMEOUT")
        return _target_credentials(request)

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", lambda name: _done())
    rows = await target.scrape_search("laptop", max_pages=1)
    assert len(rows) == 12
    assert rows[0]["tcin"] == "1000"
    assert rows[0]["url"] == "https://www.target.com/p/-/A-1000"
    page = next(request for request in seen if "/s?" in request.url)
    assert page.timeoutMs == 120_000
    assert page.waitUntil == "commit"
    assert page.actions[0]["timeoutMs"] == 45_000
    assert page.actions[0]["state"] == "attached"
    assert all(not request.url.startswith("https://redsky.target.com") for request in seen)
    assert "keyword=laptop" in next(request.javascript for request in seen if request.javascript)


async def test_target_search_empty_api_is_an_error(monkeypatch):
    async def fetch(request):
        if request.javascript and "plp_search_v2" in request.javascript:
            return Response(
                request.url,
                javascript={"status": 200, "body": json.dumps({"data": {"search": {"products": []}}})},
            )
        if "/s?" in request.url:
            raise ScrapeError("action failed", code="ACTION_FAILED")
        return _target_credentials(request)

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", lambda name: _done())
    with pytest.raises(ScrapeError) as caught:
        await target.scrape_search("laptop", max_pages=1)
    assert caught.value.code == "HTTP_ERROR"
    assert "no products" in str(caught.value)


def _target_credentials(request):
    return Response(request.url, network=[{
        "url": "https://redsky.target.com/store_location_v1?key=abc&visitor_id=vis",
        "response": {"status": 200, "body": "{}"},
    }])


async def test_target_availability_fetches_redsky_from_the_page_and_falls_back(monkeypatch):
    seen = []
    closed = []

    async def pause(seconds):
        return None

    async def fetch(request):
        seen.append(request)
        if request.javascript and "product_summary_with_fulfillment_v1" in request.javascript:
            request.javascript_result = {"status": 435, "body": "<html>Access Denied</html>"}
            return Response(request.url, "<html></html>", javascript={"status": 435, "body": "<html>Access Denied</html>"})
        if "/A-89231676" in request.url:
            raise ScrapeError("blocked", response=Response(request.url, status_code=435), code="HTTP_ERROR")
        return _target_credentials(request)

    async def close_session(name):
        closed.append(name)

    monkeypatch.setattr(target, "_pause", pause)
    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", close_session)
    with pytest.raises(ScrapeError) as caught:
        await target.scrape_availability(["89231676"], "1771", "52404")
    assert "anti-bot" in str(caught.value) and "435" in str(caught.value)
    redsky_pages = [request for request in seen if request.javascript and "product_summary" in request.javascript]
    # Availability tries the summary three times, then the product fallback
    # tries the same summary three more times before the block is final.
    assert len(redsky_pages) == target._REDSKY_ATTEMPTS * 2
    assert all(request.url.startswith("https://www.target.com/") for request in redsky_pages)
    assert len({request.session for request in redsky_pages}) == target._REDSKY_ATTEMPTS * 2
    assert {request.session for request in redsky_pages} <= set(closed)


async def test_target_availability_uses_an_in_page_json_payload(monkeypatch):
    body = json.dumps({"data": {"product_summaries": [{
        "tcin": "89231676",
        "item": {"product_description": {"title": "Tee"}},
        "fulfillment": {"shipping_options": {"availability_status": "IN_STOCK"}},
    }]}})

    async def fetch(request):
        if request.javascript and "product_summary" in request.javascript:
            return Response(request.url, javascript={"status": 200, "body": body})
        return _target_credentials(request)

    monkeypatch.setattr(target.CLIENT, "fetch", fetch)
    monkeypatch.setattr(target.CLIENT, "close_session", lambda name: _done())
    availability = await target.scrape_availability(["89231676"], "1771", "52404")
    assert availability["89231676"]["in_stock"] is True


async def _done():
    return None


def test_target_store_page_name_comes_from_the_public_heading():
    page = Response("https://www.target.com/sl/crystal/3", "<h1>Target Crystal</h1>")
    parsed = target.parse_store_page(page, "3", "crystal", page.url)
    assert parsed["store_id"] == "3"
    assert parsed["location_name"] == "Crystal"
    assert parsed["slug"] == "crystal"
