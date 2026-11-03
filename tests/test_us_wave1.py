"""Offline coverage for the 2026-11-03 US-route live failures.

These tests do not call AdsCrawl. They lock the parser and request changes the
live retest is expected to exercise.
"""
import base64
import gzip
import json
from unittest.mock import AsyncMock

import pytest

from adscrawl_scrapers import Response, ScrapeError

import aliexpress
import allegro
import amazon
import bestbuy
import bookingcom
import goibibo
import redfin


def _sse(payload: dict) -> str:
    raw = base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()
    return f"event: response\ndata: {raw}\n\n"


def _flight_payload() -> dict:
    return {
        "meta": {"locale": {"currCode": "INR"}},
        "cardList": [[{
            "flightNumber": "6E-123",
            "airlineCodes": ["6E"],
            "simpleAirlineHeading": {"nm": "IndiGo"},
            "journeyKeys": ["k"],
            "fare": 100,
        }]],
        "journeyMap": {"k": {
            "depCityCd": "DEL",
            "arrCityCd": "BOM",
            "depCity": "Delhi",
            "arrCity": "Mumbai",
            "depTime": "10:00",
            "arrTime": "12:00",
            "duration": {"h": 2, "m": 0},
            "stops": 0,
            "layover": {"layoverCityList": []},
            "flightDetail": {"legListV2": [{
                "airlineInfo": {"airlineName": "IndiGo", "airlineNumber": "6E 123 (A320)"},
                "depart": {"city": "Delhi(DEL)", "time": "10:00"},
                "arrival": {"city": "Mumbai(BOM)", "time": "12:00"},
            }]},
        }},
    }


def test_flight_url_includes_india_market_params():
    url = goibibo.build_flight_search_url("del", "bom", "2026-11-04")
    assert "itinerary=DEL-BOM-04/11/2026" in url
    assert "ccde=IN" in url and "lang=eng" in url
    assert goibibo.BASE_CONFIG["countryCode"] == "IN"


def test_flight_leg_list_v2_and_legacy_leg_list():
    flights = goibibo.parse_flights(_flight_payload())
    assert flights[0]["origin_code"] == "DEL"
    assert flights[0]["legs"][0]["flight_number"] == "6E-123"
    assert flights[0]["legs"][0]["departure_city"] == "Delhi"
    legacy = _flight_payload()
    legacy["journeyMap"]["k"]["flightDetail"] = {"legList": [{
        "legID": "AI-101",
        "airlinename": "Air India",
        "aircraft": {"text": "A320"},
        "depart": {"city": "Delhi", "time": "09:00"},
        "arrival": {"city": "Mumbai", "time": "11:00"},
    }]}
    assert goibibo.parse_flights(legacy)[0]["legs"][0]["flight_number"] == "AI-101"


async def test_flight_search_uses_preauth_instead_of_the_disabled_shell(monkeypatch):
    shell = Response(
        "https://www.goibibo.com/flight/search?itinerary=DEL-BOM",
        '<html><button data-cy="submit" disabled></button><script>__PRE_AUTH__ = "abc123";</script></html>',
    )
    stream = Response("https://flights-cb.goibibo.com/api/search-stream-dt?it=DEL-BOM", _sse(_flight_payload()))
    fetch = AsyncMock(side_effect=[shell, stream])
    monkeypatch.setattr(goibibo.CLIENT, "fetch", fetch)
    flights = await goibibo.scrape_flight_search("DEL", "BOM", "2026-11-04")
    assert flights[0]["airline_name"] == "IndiGo"
    assert fetch.await_count == 2
    page, api = (call.args[0] for call in fetch.await_args_list)
    assert page.render is False and page.countryCode == "IN"
    assert "search-stream-dt" in api.url
    assert api.headers["X-Cb-Preauth"] == "abc123"
    assert api.session == page.session


async def test_flight_shell_without_token_waits_for_search_instead_of_exiting(monkeypatch):
    shell = Response(
        "https://www.goibibo.com/flight/search?itinerary=DEL-BOM",
        '<html><button data-cy="submit" disabled></button></html>',
    )
    rendered = Response(
        "https://www.goibibo.com/flight/search?itinerary=DEL-BOM",
        "<html><title>Flights</title></html>",
        network=[{"url": "https://flights-cb.goibibo.com/api/search-stream-dt", "response": {"body": _sse(_flight_payload())}}],
    )
    fetch = AsyncMock(side_effect=[shell, rendered])
    monkeypatch.setattr(goibibo.CLIENT, "fetch", fetch)
    flights = await goibibo.scrape_flight_search("DEL", "BOM", "2026-11-04")
    assert len(flights) == 1
    browser = fetch.await_args_list[1].args[0]
    assert browser.waitForResponse == goibibo.SEARCH_STREAM_DT
    assert all(action.get("outcome") != "exit_success" for action in browser.actions)
    assert any(action.get("selector") == "[data-cy='submit']:not([disabled])" for action in browser.actions)


async def test_hotel_listing_retries_a_timeout_once(monkeypatch):
    listing = {
        "response": {
            "currency": "INR",
            "personalizedSections": [{"hotels": [{"id": "h1", "name": "Inn", "soldOut": False}]}],
        }
    }
    ok = Response(
        "https://www.goibibo.com/hotels/hotel-listing/",
        network=[{
            "url": "https://www.goibibo.com/clientbackend-gi/cg/listing/DESKTOP/v1",
            "headers": {"content-type": "application/json"},
            "response": {"body": json.dumps(listing)},
        }],
    )
    fetch = AsyncMock(side_effect=[ScrapeError("timed out", code="TIMEOUT"), ok])
    monkeypatch.setattr(goibibo.CLIENT, "fetch", fetch)
    hotels = await goibibo.scrape_hotel_search("Delhi", "CTDEL", "2026-11-04", "2026-11-10", max_pages=1)
    assert hotels[0]["id"] == "h1"
    assert fetch.await_count == 2
    assert fetch.await_args_list[0].args[0].session != fetch.await_args_list[1].args[0].session


def _above_payload():
    return {
        "addressSectionInfo": {
            "streetAddress": {"assembledAddress": "506 E Howell St"},
            "city": "Seattle",
            "state": "WA",
            "zip": "98122",
            "priceInfo": {"amount": 500000},
            "beds": 2,
            "baths": 1,
            "yearBuilt": 1992,
            "propertyTypeName": "Condo",
        },
        "mediaBrowserInfo": {"photos": [{"photoUrls": {"fullScreenPhotoUrl": "https://ssl.cdn-redfin.com/photo/1.jpg"}}]},
    }


def test_sale_parser_reads_stingray_calls_when_the_html_shell_has_no_state():
    shell = "<!DOCTYPE html><html><head><title></title></head><body><noscript>Enable JavaScript</noscript></body></html>"
    body = "{}&&" + json.dumps({"payload": _above_payload()})
    house = "{}&&" + json.dumps({"payload": {"mainHouseInfo": {"marketingRemarks": [{"marketingRemark": "Bright"}]}}})
    below = "{}&&" + json.dumps({"payload": {"amenitiesInfo": {"superGroups": [{
        "amenityGroups": [{"groupTitle": "Parking Information", "amenityEntries": [
            {"amenityName": "Parking", "amenityValues": ["Garage"]},
        ]}],
    }]}}})
    response = Response(
        "https://www.redfin.com/WA/Seattle/506-E-Howell-St-98122/unit-W303/home/46456",
        shell,
        network=[
            {"url": "https://www.redfin.com/stingray/api/home/details/aboveTheFold?propertyId=46456", "response": {"body": body}},
            {"url": "https://www.redfin.com/stingray/api/home/details/mainHouseInfoPanelInfo?propertyId=46456", "response": {"body": house}},
            {"url": "https://www.redfin.com/stingray/api/v1/home/details/belowTheFold?propertyId=46456", "response": {"body": below}},
        ],
    )
    parsed = redfin.parse_property_for_sale(response)
    assert parsed["address"].startswith("506 E Howell St")
    assert parsed["price"] == "$500,000"
    assert parsed["details"] == ["Property Type: Condo", "Year Built: 1992", "Beds: 2", "Baths: 1"]
    assert parsed["features"]["Parking Information"] == ["Parking: Garage"]
    assert parsed["attachments"] == ["https://ssl.cdn-redfin.com/photo/1.jpg"]


async def test_sale_shell_falls_back_to_stingray_detail_apis(monkeypatch):
    shell = Response(
        "https://www.redfin.com/WA/Seattle/506-E-Howell-St-98122/unit-W303/home/46456",
        "<!DOCTYPE html><html><head><title></title></head><body>Enable JavaScript</body></html>",
    )
    initial = Response("https://www.redfin.com/stingray/api/home/details/initialInfo", "{}&&" + json.dumps({
        "payload": {"propertyId": 46456, "listingId": 999},
    }))
    pages = {
        "/stingray/api/home/details/aboveTheFold": _above_payload(),
        "/stingray/api/home/details/mainHouseInfoPanelInfo": {"mainHouseInfo": {"marketingRemarks": []}},
        "/stingray/api/v1/home/details/belowTheFold": {"amenitiesInfo": {"superGroups": [{
            "amenityGroups": [{"groupTitle": "Interior", "amenityEntries": [
                {"amenityName": "Heating", "amenityValues": ["Forced air"]},
            ]}],
        }]}},
    }

    async def fetch(request):
        if "initialInfo" in request.url:
            return initial
        for path, payload in pages.items():
            if path in request.url:
                return Response(request.url, "{}&&" + json.dumps({"payload": payload}))
        return shell

    monkeypatch.setattr(redfin.CLIENT, "fetch", fetch)
    parsed = await redfin.scrape_property_for_sale([shell.url])
    assert parsed[0]["price"] == "$500,000"
    assert "Year Built: 1992" in parsed[0]["details"]
    assert parsed[0]["features"]["Interior"] == ["Heating: Forced air"]


async def test_rent_page_retries_a_loading_browser_error(monkeypatch):
    loading = ScrapeError(
        "Browser navigation or interaction failed",
        response=Response(
            "https://www.redfin.com/WA/Seattle/Onni-South-Lake-Union/apartment/147020546",
            "<html><title>Loading https://www.redfin.com/apartment</title></html>",
        ),
        code="BROWSER_ERROR",
    )
    ready = Response(
        "https://www.redfin.com/WA/Seattle/Onni-South-Lake-Union/apartment/147020546",
        '<html><meta property="og:image" content="https://ssl.cdn-redfin.com/rent/123e4567-e89b-12d3-a456-426614174000/photo.jpg"></html>',
    )
    plans = Response("https://www.redfin.com/stingray/api/v1/rentals/x/floorPlans", '{"rentalId":"123e4567-e89b-12d3-a456-426614174000"}')
    fetch = AsyncMock(side_effect=[loading, ready, plans])
    monkeypatch.setattr(redfin.CLIENT, "fetch", fetch)
    result = await redfin.scrape_property_for_rent([ready.url])
    assert result[0]["rentalId"].startswith("123e4567")
    assert fetch.await_count == 3
    assert "og:image" in (fetch.await_args_list[1].args[0].waitForSelector or "")


def test_amazon_reviews_accept_current_and_legacy_hooks():
    current = '''
    <div data-hook="review">
      <i data-hook="review-star-rating"><span class="a-icon-alt">5.0 out of 5 stars</span></i>
      <a data-hook="review-title"><span>5.0 out of 5 stars</span><span>Solid console</span></a>
      <span data-hook="review-date">Reviewed in the United States on January 2, 2026</span>
      <span data-hook="avp-badge">Verified Purchase</span>
      <div data-hook="review-body"><span>Works every night.</span></div>
    </div>'''
    legacy = '''
    <div data-hook="review">
      <i data-hook="review-star-rating"><span>4.0 out of 5 stars</span></i>
      <span data-hook="reviewTitle">Older title</span>
      <span data-hook="review-date">Reviewed in the United States on March 3, 2024</span>
      <div data-hook="reviewRichContentContainer">Legacy body</div>
    </div>'''
    parsed = amazon.parse_reviews(Response("https://www.amazon.com/product-reviews/B0BCNKKZ91/", current + legacy))
    assert parsed[0]["title"] == "Solid console" and parsed[0]["text"] == "Works every night."
    assert parsed[0]["verified"] is True and parsed[0]["rating"] == 5.0
    assert parsed[1]["title"] == "Older title" and parsed[1]["text"] == "Legacy body"
    assert parsed[1]["verified"] is False


async def test_amazon_reviews_use_the_reviews_page_and_its_next_link(monkeypatch):
    first = Response(
        "https://www.amazon.com/product-reviews/B0BCNKKZ91/",
        '''<div data-hook="review"><i data-hook="review-star-rating"><span>5.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>First</span></a>
        <span data-hook="review-date">Reviewed in the United States on January 2, 2026</span>
        <div data-hook="review-body"><span>One</span></div></div>
        <ul class="a-pagination"><li class="a-last"><a href="/product-reviews/B0BCNKKZ91/?pageNumber=2">Next</a></li></ul>''',
    )
    second = Response(
        "https://www.amazon.com/product-reviews/B0BCNKKZ91/?pageNumber=2",
        '''<div data-hook="review"><i data-hook="review-star-rating"><span>4.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>Second</span></a>
        <span data-hook="review-date">Reviewed in the United States on January 3, 2026</span>
        <div data-hook="review-body"><span>Two</span></div></div>''',
    )
    fetch = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    reviews = await amazon.scrape_reviews("https://www.amazon.com/PlayStation-5-Console-CFI-1215A01X/dp/B0BCNKKZ91/")
    assert [item["title"] for item in reviews] == ["First", "Second"]
    assert "/product-reviews/B0BCNKKZ91" in fetch.await_args_list[0].args[0].url
    assert "pageNumber=2" in fetch.await_args_list[1].args[0].url


async def test_amazon_product_and_search_retry_tunnel_and_503_once(monkeypatch):
    product_html = "<html><span id='productTitle'>Example</span><input name='ASIN' value='B000000000'></html>"
    product_calls = {"n": 0}

    async def product_fetch(request):
        product_calls["n"] += 1
        if product_calls["n"] == 1:
            raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")
        return Response(request.url, product_html)

    monkeypatch.setattr(amazon.CLIENT, "fetch", product_fetch)
    products = await amazon.scrape_product("https://www.amazon.com/dp/B000000000")
    assert products[0]["name"] == "Example"
    assert product_calls["n"] == 2

    search_html = '''<div cel_widget_id="UPPER-RESULT_INFO_BAR-0"><span>1-1 of 3 results</span></div>
    <div class="s-result-item" data-component-type="s-search-result"><div><a href="/dp/ASINONE"><h2 aria-label="Kindle"></h2></a></div></div>'''
    search_calls = []

    async def search_fetch(request):
        search_calls.append(request.url)
        if request.url.endswith("page=2") and search_calls.count(request.url) == 1:
            raise ScrapeError("busy", response=Response(request.url, status_code=503), code="HTTP_ERROR")
        return Response(request.url, search_html)

    monkeypatch.setattr(amazon.CLIENT, "fetch", search_fetch)
    found = await amazon.scrape_search("https://www.amazon.com/s?k=kindle", max_pages=2)
    assert len(found) == 2
    assert sum(1 for url in search_calls if "page=2" in url) == 2


def test_booking_challenge_error_names_the_page_and_unmarked_apollo_still_parses():
    challenge = Response(
        "https://www.booking.com/searchresults.en-gb.html?ss=Malta",
        "<html><title>Just a moment</title><div id='challenge-container'></div></html>",
    )
    message = bookingcom.describe_search_failure(challenge)
    assert "anti-bot challenge" in message and "Just a moment" in message
    store = {"ROOT_QUERY": {"searchQueries": {"search(x)": {"pagination": {"nbResultsTotal": 2}}}}}
    page = Response("https://www.booking.com/searchresults.html", f"<script>window.store = {json.dumps(store)};</script>")
    assert "nbResultsTotal" in bookingcom.apollo_script(page)


async def test_booking_hotel_retries_a_loading_navigation(monkeypatch):
    loading = ScrapeError(
        "Browser navigation or interaction failed",
        response=Response(
            "https://www.booking.com/hotel/gb/gardencourthotel.html",
            "<html><title>Loading https://www.booking.com/hotel/gb/gardencourthotel.html</title></html>",
        ),
        code="BROWSER_ERROR",
    )
    hotel = """<html><title>Garden Court</title>
    <h2>Garden Court Hotel</h2>
    <div data-testid="PropertyHeaderAddressDesktop-wrapper">
      <button><div>1 Main St</div></button>
      <a data-atlas-latlng="51.5,-0.1"></a>
    </div>
    <script>b_hotel_id: '10'; hotelCountry: "gb"; hotelName: "garden"; b_csrf_token: 'tok';</script>
    </html>"""
    ready = Response("https://www.booking.com/hotel/gb/gardencourthotel.en-gb.html", hotel)
    price = Response(
        "https://www.booking.com/dml/graphql?lang=en-gb",
        json.dumps({"data": {"availabilityCalendar": {"days": [{"available": True, "checkin": "2026-11-03"}]}}}),
    )
    fetch = AsyncMock(side_effect=[loading, ready, price])
    monkeypatch.setattr(bookingcom.CLIENT, "fetch", fetch)
    parsed = await bookingcom.scrape_hotel(ready.url, checkin="2026-11-03")
    assert parsed["title"] == "Garden Court Hotel"
    assert parsed["price"][0]["checkin"] == "2026-11-03"
    assert fetch.await_count == 3
    assert fetch.await_args_list[0].args[0].session != fetch.await_args_list[1].args[0].session


def _search_document(items):
    fields = {
        "pageInfo": {"pageSize": 60, "totalResults": 120},
        "mods": {"itemList": {"content": items}},
    }
    payload = json.dumps({"data": {"root": {"fields": fields}}})
    return f"<script>_init_data_={{ data: {payload} }}</script>"


async def test_aliexpress_search_retries_a_timeout_and_reviews_use_us_json(monkeypatch):
    calls = []

    async def fetch(request):
        calls.append(request)
        if "page=2" in request.url and sum("page=2" in item.url for item in calls) == 1:
            raise ScrapeError("timed out", code="TIMEOUT")
        return Response(request.url, _search_document([{"id": request.url}]))

    monkeypatch.setattr(aliexpress.CLIENT, "fetch", fetch)
    rows = await aliexpress.scrape_search("https://www.aliexpress.com/w/wholesale-drills.html", max_pages=2)
    assert len(rows) == 2
    assert sum("page=2" in item.url for item in calls) == 2
    assert calls[0].timeoutMs == 120000

    review_calls = []

    async def review_fetch(request):
        review_calls.append(request)
        if len(review_calls) == 1:
            raise ScrapeError("closed", code="ERR_CONNECTION_CLOSED")
        body = {"data": {"totalPage": 1, "evaViewList": [{"evaluationId": 1}], "productEvaluationStatistic": {}}}
        return Response(request.url, json.dumps(body))

    monkeypatch.setattr(aliexpress.CLIENT, "fetch", review_fetch)
    reviews = await aliexpress.scrape_product_reviews("1005006717259012", max_scrape_pages=2)
    assert reviews["reviews"][0]["evaluationId"] == 1
    request = review_calls[0]
    assert request.countryCode == "US" and request.render is False
    assert "pageSize=50" in request.url and "feedback.aliexpress.com" in request.url
    assert review_calls[0].url == review_calls[1].url


async def test_bestbuy_product_retries_http2_once(monkeypatch):
    fetch = AsyncMock(side_effect=[
        ScrapeError("http2", code="ERR_HTTP2_PROTOCOL_ERROR"),
        Response("https://www.bestbuy.com/site/example/1.p", "<html></html>"),
    ])
    monkeypatch.setattr(bestbuy.CLIENT, "fetch", fetch)
    page = await bestbuy._fetch_product("https://www.bestbuy.com/site/example/1.p")
    assert page.status_code == 200
    assert fetch.await_count == 2


async def test_allegro_requests_use_the_polish_route(monkeypatch):
    seen = []

    async def fetch(request):
        seen.append(request)
        return Response(
            request.url,
            '<html><script data-serialize-box-id="search">{"props":{"searchMeta":{"lastAvailablePage":1,"totalCount":30}}}</script></html>',
        )

    async def many(requests):
        for request in requests:
            seen.append(request)
            yield Response(request.url, "<html></html>")

    monkeypatch.setattr(allegro.CLIENT, "fetch", fetch)
    monkeypatch.setattr(allegro.CLIENT, "fetch_many", many)
    await allegro.scrape_search("Cooler CPU")
    await allegro.scrape_product(["https://allegro.pl/oferta/example-1"])
    assert seen and all(request.countryCode == "PL" for request in seen)
