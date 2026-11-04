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
    stream = Response("https://www.goibibo.com/flight/search?itinerary=DEL-BOM", "<html></html>")
    stream.javascript = json.dumps({"status": 200, "text": _sse(_flight_payload())})
    fetch = AsyncMock(side_effect=[shell, stream])
    monkeypatch.setattr(goibibo.CLIENT, "fetch", fetch)
    flights = await goibibo.scrape_flight_search("DEL", "BOM", "2026-11-04")
    assert flights[0]["airline_name"] == "IndiGo"
    assert fetch.await_count == 2
    page, follow = (call.args[0] for call in fetch.await_args_list)
    assert page.render is False and page.countryCode == "IN"
    assert follow.url == page.url and follow.session == page.session
    assert "search-stream-dt" in (follow.javascript or "")
    assert "abc123" in (follow.javascript or "")
    assert '"origin"' not in (follow.javascript or "")
    assert '"referer"' not in (follow.javascript or "").lower()


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
    assert not browser.waitForResponse
    assert browser.waitMs == 5000
    assert browser.session
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
    closed = []

    async def close_session(name):
        closed.append(name)

    monkeypatch.setattr(goibibo.CLIENT, "close_session", close_session)
    hotels = await goibibo.scrape_hotel_search("Delhi", "CTDEL", "2026-11-04", "2026-11-10", max_pages=1)
    assert hotels[0]["id"] == "h1"
    assert fetch.await_count == 2
    failed = fetch.await_args_list[0].args[0].session
    assert failed != fetch.await_args_list[1].args[0].session
    assert closed == [failed]


async def test_flight_stream_retries_http2_on_the_same_session(monkeypatch):
    shell = Response(
        "https://www.goibibo.com/flight/search?itinerary=DEL-BOM",
        '<html><script>__PRE_AUTH__ = "abc123";</script></html>',
    )
    stream = Response("https://www.goibibo.com/flight/search?itinerary=DEL-BOM", "<html></html>")
    stream.javascript = _sse(_flight_payload())
    fetch = AsyncMock(side_effect=[
        shell,
        ScrapeError("http2", code="ERR_HTTP2_PROTOCOL_ERROR"),
        stream,
    ])
    monkeypatch.setattr(goibibo.CLIENT, "fetch", fetch)
    flights = await goibibo.scrape_flight_search("DEL", "BOM", "2026-11-04")
    assert flights[0]["airline_name"] == "IndiGo"
    assert fetch.await_count == 3
    assert fetch.await_args_list[1].args[0].session == fetch.await_args_list[2].args[0].session
    assert "search-stream-dt" in (fetch.await_args_list[2].args[0].javascript or "")
    assert "flights-cb.goibibo.com" not in fetch.await_args_list[2].args[0].url


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


async def test_sale_uses_the_url_property_id_when_initial_info_tunnels(monkeypatch):
    url = "https://www.redfin.com/WA/Seattle/506-E-Howell-St-98122/unit-W303/home/46456"
    calls = []

    async def fetch(request):
        calls.append(request.url)
        if "initialInfo" in request.url:
            raise ScrapeError("tunnel", code="ERR_TUNNEL_CONNECTION_FAILED")
        if "aboveTheFold" in request.url:
            assert "propertyId=46456" in request.url
            return Response(request.url, "{}&&" + json.dumps({"payload": _above_payload()}))
        return Response(request.url, "{}&&" + json.dumps({"payload": {}}))

    monkeypatch.setattr(redfin.CLIENT, "fetch", fetch)
    parsed = await redfin.scrape_property_for_sale([url])
    assert parsed[0]["price"] == "$500,000"
    assert sum("initialInfo" in item for item in calls) == 2
    assert any("aboveTheFold" in item and "propertyId=46456" in item for item in calls)
    assert any(item.split("?")[0] == url for item in calls)


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


def _ajax_reviews(html: str) -> str:
    return "&&&" + json.dumps(["append", "#cm_cr-review_list", html])


async def test_amazon_reviews_use_ajax_pages(monkeypatch):
    def page(html: str) -> Response:
        response = Response("https://www.amazon.com/dp/0735211299", "<html></html>")
        response.javascript = json.dumps({"status": 200, "text": _ajax_reviews(html)})
        return response

    first = page(
        '''<div data-hook="review"><i data-hook="review-star-rating"><span>5.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>First</span></a>
        <span data-hook="review-date">Reviewed in the United States on January 2, 2026</span>
        <div data-hook="review-body"><span>One</span></div></div>'''
    )
    second = page(
        '''<div data-hook="review"><i data-hook="review-star-rating"><span>4.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>Second</span></a>
        <span data-hook="review-date">Reviewed in the United States on January 3, 2026</span>
        <div data-hook="review-body"><span>Two</span></div></div>'''
    )
    fetch = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    reviews = await amazon.scrape_reviews("https://www.amazon.com/Atomic-Habits-Proven-Build-Break/dp/0735211299")
    assert [item["title"] for item in reviews] == ["First", "Second"]
    opened = fetch.await_args_list[0].args[0]
    assert opened.url == "https://www.amazon.com/dp/0735211299"
    assert opened.method == "GET"
    assert amazon.REVIEWS_AJAX in (opened.javascript or "")
    assert amazon.REVIEWS_MEDLEY in (opened.javascript or "")
    assert '"asin": "0735211299"' in (opened.javascript or "")
    assert '"pageNumber": "1"' in (opened.javascript or "")
    assert '"pageNumber": "2"' in (fetch.await_args_list[1].args[0].javascript or "")
    assert "reviews-render" not in opened.url


def test_amazon_description_reads_paragraph_jsonld_and_aplus_not_feature_bullets():
    paragraph = amazon.parse_product(Response("https://www.amazon.com/dp/B0CL61F39H", '''
    <span id="productTitle">PS5</span>
    <input name="ASIN" value="B0CL61F39H">
    <ul id="feature-bullets"><li>Model Number CFI-2000.</li></ul>
    <div id="productDescription"><p>The PS5 console unleashes new gaming possibilities that you never anticipated.</p></div>
    '''))
    assert "unleashes" in paragraph["description"]
    assert "Model Number" not in paragraph["description"]

    embedded = amazon.parse_product(Response("https://www.amazon.com/dp/B0CX22ZW1T", '''
    <span id="productTitle">MacBook</span>
    <input name="ASIN" value="B0CX22ZW1T">
    <script type="application/ld+json">{"@type":"Product","name":"MacBook","description":"Apple 2024 MacBook Air with the M3 chip and a Liquid Retina display."}</script>
    '''))
    assert "Liquid Retina" in embedded["description"]

    aplus = amazon.parse_product(Response("https://www.amazon.com/dp/B0CL61F39H", '''
    <span id="productTitle">PS5</span>
    <div id="aplus"><p>Experience lightning fast loading with an ultra-high speed SSD and deeper immersion.</p></div>
    '''))
    assert "ultra-high speed SSD" in aplus["description"]
    blank = amazon.parse_product(Response(
        "https://www.amazon.com/dp/B0CL61F39H",
        '<span id="productTitle">PS5</span><ul id="feature-bullets"><li>Only a bullet.</li></ul>',
    ))
    assert blank["description"] == ""


def test_amazon_jsonld_reviews_count_when_the_widget_is_absent():
    html = '''<script type="application/ld+json">{"@type":"Product","review":[
      {"@type":"Review","name":"Changed my year","reviewBody":"Small habits, kept.",
       "datePublished":"2024-05-01","author":{"@type":"Person","name":"Ada"},
       "reviewRating":{"@type":"Rating","ratingValue":"5"}}
    ]}</script>'''
    parsed = amazon.parse_jsonld_reviews(Response("https://www.amazon.com/dp/0735211299", html))
    assert parsed[0]["title"] == "Changed my year"
    assert parsed[0]["rating"] == 5.0
    assert "Small habits" in parsed[0]["text"]


def test_amazon_style_reads_dimension_json_and_overview_and_blank_is_null():
    html = '''
    <span id="productTitle">MacBook</span>
    <input name="ASIN" value="B0CX22ZW1T">
    <div id="productOverview_feature_div"><table><tr><td>Color</td><td>Midnight</td></tr></table></div>
    <script>"dimensionValuesDisplayData":{"B0CX22ZW1T":["Midnight","16GB"]},</script>
    '''
    parsed = amazon.parse_product(Response("https://www.amazon.com/dp/B0CX22ZW1T", html))
    assert parsed["style"] and "Midnight" in parsed["style"]
    blank = amazon.parse_product(Response(
        "https://www.amazon.com/dp/B0CL61F39H",
        '<span id="productTitle">PS5</span><input name="ASIN" value="B0CL61F39H">',
    ))
    assert blank["style"] is None


async def test_amazon_reviews_fall_back_to_the_product_page_on_404(monkeypatch):
    product = Response(
        "https://www.amazon.com/dp/B0CL61F39H",
        '''<div data-hook="review"><i data-hook="review-star-rating"><span>5.0 out of 5 stars</span></i>
        <a data-hook="review-title"><span>Kept</span></a>
        <span data-hook="review-date">Reviewed in the United States on January 2, 2026</span>
        <div data-hook="review-body"><span>Still here.</span></div></div>''',
    )

    async def fetch(request):
        if "reviews-render" in request.url or "/product-reviews/" in request.url:
            raise ScrapeError(
                "Target returned HTTP 404",
                response=Response(request.url, status_code=404),
                code="HTTP_ERROR",
            )
        return product

    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    reviews = await amazon.scrape_reviews("https://www.amazon.com/dp/B0CL61F39H")
    assert reviews[0]["title"] == "Kept"
    assert reviews[0]["text"] == "Still here."


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


def _search_card_html() -> str:
    return '''<div cel_widget_id="UPPER-RESULT_INFO_BAR-0"><span>1-16 of 48 results</span></div>
    <div class="s-result-item" data-component-type="s-search-result"><div><a href="/dp/ASINONE"><h2 aria-label="Kindle"></h2></a></div></div>'''


def _is_amazon_home(url: str) -> bool:
    return url.rstrip("/") == "https://www.amazon.com"


async def test_amazon_search_first_page_503_rotates_session_and_path(monkeypatch):
    calls = []

    async def fetch(request):
        calls.append(request)
        if _is_amazon_home(request.url):
            return Response(request.url, "<html></html>")
        if "/gp/search" in request.url:
            return Response(request.url, _search_card_html())
        raise ScrapeError("busy", response=Response(request.url, status_code=503), code="HTTP_ERROR")

    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    found = await amazon.scrape_search("https://www.amazon.com/s?k=kindle", max_pages=1)
    assert len(found) == 1
    homes = [call for call in calls if _is_amazon_home(call.url)]
    documents = [call for call in calls if "/s?" in call.url]
    alternate = [call for call in calls if "/gp/search" in call.url]
    assert len(homes) == 2
    assert len(documents) == 2
    assert len(alternate) == 1
    assert homes[0].session == documents[0].session == documents[1].session
    assert homes[1].session == alternate[0].session
    assert homes[0].session != homes[1].session
    assert "k=kindle" in alternate[0].url
    assert "ref=nb_sb_noss" in alternate[0].url


async def test_amazon_search_query_fallback_parses_cards_when_html_is_503(monkeypatch):
    card = (
        '<div class="s-result-item" data-component-type="s-search-result">'
        '<div><a href="/dp/ASINONE"><h2 aria-label="Kindle"></h2></a></div></div>'
    )
    payload = "&&&" + json.dumps(["append", "#search", card])
    calls = []

    async def fetch(request):
        calls.append(request)
        if _is_amazon_home(request.url):
            return Response(request.url, "<html></html>")
        if "/s/query" in request.url:
            return Response(request.url, payload)
        raise ScrapeError("busy", response=Response(request.url, status_code=503), code="HTTP_ERROR")

    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    found = await amazon.scrape_search("https://www.amazon.com/s?k=kindle", max_pages=1)
    assert [item["title"] for item in found] == ["Kindle"]
    query = [call for call in calls if "/s/query" in call.url]
    assert len(query) == 1
    assert query[0].render is False
    assert "k=kindle" in query[0].url
    assert query[0].headers.get("x-requested-with") == "XMLHttpRequest"


def test_amazon_search_payload_reads_cards_inside_query_chunks():
    card = (
        '<div class="s-result-item" data-component-type="s-search-result">'
        '<div><a href="/dp/ASINONE"><h2 aria-label="Kindle"></h2></a></div></div>'
    )
    parsed = amazon.parse_search_payload(
        "&&&" + json.dumps(["replace", "#s-result", card]),
        "https://www.amazon.com/s/query?k=kindle",
    )
    assert parsed[0]["title"] == "Kindle"
    assert parsed[0]["url"].endswith("/dp/ASINONE")


def test_amazon_structured_reviews_read_review_text_objects():
    body = json.dumps({
        "reviews": [{
            "reviewText": "Kept the habit.",
            "reviewTitle": "Useful",
            "rating": 5,
            "verifiedPurchase": True,
        }]
    })
    parsed = amazon.parse_structured_reviews(body)
    assert parsed[0]["title"] == "Useful"
    assert parsed[0]["text"] == "Kept the habit."
    assert parsed[0]["rating"] == 5.0
    assert parsed[0]["verified"] is True


async def test_amazon_product_timeout_cleanup_retries_on_a_reset_client(monkeypatch):
    seen = []
    resets = []

    async def fetch(request):
        seen.append(request)
        if len(seen) == 1:
            raise ScrapeError("cleanup", code="CLEANUP_FAILED")
        return Response(request.url, "<html><span id='productTitle'>Example</span><input name='ASIN' value='B000000000'></html>")

    async def reset():
        resets.append(True)

    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    monkeypatch.setattr(amazon.CLIENT, "reset", reset)
    products = await amazon.scrape_product("https://www.amazon.com/dp/B000000000")
    assert products[0]["name"] == "Example"
    assert resets == [True]
    assert len(seen) == 2
    assert seen[0].waitUntil == "commit"
    assert seen[0].waitForSelector is None
    assert seen[0].timeoutMs == 60000
    assert seen[1].url == seen[0].url == "https://www.amazon.com/dp/B000000000"


async def test_amazon_product_timeout_retries_up_to_three_fresh_navigations(monkeypatch):
    seen = []

    async def fetch(request):
        seen.append(request)
        if len(seen) < 3:
            raise ScrapeError("slow", code="TIMEOUT")
        return Response(
            request.url,
            "<html><span id='productTitle'>MacBook</span><input name='ASIN' value='B0CX22ZW1T'></html>",
        )

    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    products = await amazon.scrape_product(
        "https://www.amazon.com/Apple-2024-MacBook-13-inch-Laptop/dp/B0CX22ZW1T"
    )
    assert products[0]["name"] == "MacBook"
    assert len(seen) == 3
    assert all(request.url == "https://www.amazon.com/dp/B0CX22ZW1T" for request in seen)
    assert all(request.waitForSelector is None and request.timeoutMs == 60000 for request in seen)


async def test_amazon_product_missing_title_is_retried(monkeypatch):
    pages = [
        Response("https://www.amazon.com/dp/B0CX22ZW1T", "<html><title>Robot Check</title></html>"),
        Response("https://www.amazon.com/dp/B0CX22ZW1T", "<html><span id='productTitle'>MacBook</span></html>"),
    ]
    fetch = AsyncMock(side_effect=pages)
    monkeypatch.setattr(amazon.CLIENT, "fetch", fetch)
    products = await amazon.scrape_product("https://www.amazon.com/dp/B0CX22ZW1T")
    assert products[0]["name"] == "MacBook"
    assert fetch.await_count == 2


def test_booking_graphql_pages_keep_distinct_offsets():
    body = {"variables": {"input": {"pagination": {"offset": 0, "rowsPerPage": 25}}}, "query": "q"}
    requests = [bookingcom.generate_graphql_request("ss=Malta", body, offset) for offset in (0, 25, 50)]
    offsets = [json.loads(item.payload())["variables"]["input"]["pagination"]["offset"] for item in requests]
    assert offsets == [0, 25, 50]
    assert body["variables"]["input"]["pagination"]["offset"] == 0


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
        response = Response(
            request.url,
            '<html><script data-serialize-box-id="search">{"props":{"searchMeta":{"lastAvailablePage":1,"totalCount":30}}}</script>'
            '<script data-serialize-box-id="price">{"price":{"formattedPrice":"10 zl"}}</script></html>',
        )
        if request.url.rstrip("/") == "https://allegro.pl":
            response.cookies = [{"name": "wdctx", "value": "kept"}]
        return response

    monkeypatch.setattr(allegro.CLIENT, "fetch", fetch)
    await allegro.scrape_search("Cooler CPU")
    await allegro.scrape_product(["https://allegro.pl/oferta/example-1"])
    assert seen and all(request.countryCode == "PL" and request.locale == "pl-PL" for request in seen)
    assert all(request.headers.get("Accept-Language", "").startswith("pl-PL") for request in seen)
    assert all(request.userAgentOs == "windows" for request in seen)
    listing = next(request for request in seen if "/listing" in request.url)
    home = next(request for request in seen if request.url.rstrip("/") == "https://allegro.pl")
    offer = next(request for request in seen if "/oferta/" in request.url)
    assert home.timeoutMs == 25000
    assert home.waitUntil == "load"
    assert listing.waitUntil == "load"
    assert home.headers.get("Sec-Fetch-Site") == "none"
    assert home.session == listing.session
    assert listing.timeoutMs == 90000
    assert listing.headers.get("Referer") == "https://allegro.pl/"
    assert listing.headers.get("Sec-Fetch-Site") == "same-origin"
    assert listing.headers.get("Cookie") == "wdctx=kept"
    assert offer.waitUntil == "commit"
    assert offer.timeoutMs == 60000
    assert offer.waitForSelector is None
    assert offer.waitMs == 0
    assert offer.actions[0]["selector"] == "script[data-serialize-box-id]"
    assert offer.actions[0]["optional"] is True
    assert offer.actions[0]["timeoutMs"] == 15000


async def test_allegro_403_block_page_is_an_error_and_a_data_body_is_parsed(monkeypatch):
    calls = []

    async def blocked(request):
        calls.append(request)
        return Response(request.url, "<html><title>Access denied</title></html>", status_code=403)

    monkeypatch.setattr(allegro.CLIENT, "fetch", blocked)
    with pytest.raises(ScrapeError, match="anti-bot"):
        await allegro.scrape_search("Cooler CPU")
    assert calls[0].url.rstrip("/") == "https://allegro.pl"
    assert "/listing" in calls[1].url
    assert calls[1].session != calls[0].session
    assert "Cookie" not in calls[1].headers

    html = (
        '<html><script data-serialize-box-id="search">'
        '{"props":{"searchMeta":{"lastAvailablePage":1,"totalCount":30}}}</script></html>'
    )

    async def with_data(request):
        return Response(request.url, html, status_code=403)

    monkeypatch.setattr(allegro.CLIENT, "fetch", with_data)
    data = await allegro.scrape_search("Cooler CPU")
    assert data["total_count"] == 30


async def test_allegro_listing_continues_after_a_homepage_timeout(monkeypatch):
    html = (
        '<html><script data-serialize-box-id="search">'
        '{"props":{"searchMeta":{"lastAvailablePage":1,"totalCount":30}}}</script></html>'
    )
    calls = []

    async def fetch(request):
        calls.append(request)
        if request.url.rstrip("/") == "https://allegro.pl":
            raise ScrapeError("timed out", code="TIMEOUT")
        return Response(request.url, html)

    monkeypatch.setattr(allegro.CLIENT, "fetch", fetch)
    data = await allegro.scrape_search("Cooler CPU")
    assert data["total_count"] == 30
    assert calls[0].url.rstrip("/") == "https://allegro.pl"
    assert "/listing" in calls[1].url
    assert calls[1].session != calls[0].session
