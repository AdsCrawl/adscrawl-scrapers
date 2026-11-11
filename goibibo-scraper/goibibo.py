# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for goibibo.com hotel search.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"

For example use instructions see ./run.py
"""
from adscrawl_scrapers import managed
import base64
import gzip
import json
import os
import re
import time
from copy import deepcopy
from datetime import datetime
from typing import Dict, List, Optional, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from uuid import uuid4

from loguru import logger as log
from adscrawl_scrapers import Response, Request, ScraperClient, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    # Goibibo is an India marketplace. US routing leaves the flight shell idle
    # and the hotel listing call missing; IN matches the site.
    'countryCode': "IN",
    'render': True,
    'autoScroll': True,
}

LISTING_API = "clientbackend-gi/cg/listing/DESKTOP/"
SEARCH_STREAM_DT = "search-stream-dt"
FLIGHT_SEARCH_API = "https://flights-cb.goibibo.com/api/search-stream-dt"


class Hotel(TypedDict):
    id: str
    gi_id: Optional[str]
    name: str
    property_type: Optional[str]
    star_rating: Optional[int]
    sold_out: bool
    total_room_count: Optional[int]
    categories: List[str]
    area: Optional[str]
    city: Optional[str]
    country: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    images: List[str]
    price: Optional[float]
    price_with_tax: Optional[float]
    price_suffix: Optional[str]
    currency: Optional[str]
    rating: Optional[float]
    rating_text: Optional[str]
    review_count: Optional[int]
    rating_count: Optional[int]
    amenities: List[str]
    description: Optional[str]
    url: Optional[str]

class FlightLeg(TypedDict):
    flight_number: Optional[str]
    airline: Optional[str]
    aircraft: Optional[str]
    departure_city: Optional[str]
    departure_time: Optional[str]
    arrival_city: Optional[str]
    arrival_time: Optional[str]


class Flight(TypedDict):
    flight_number: Optional[str]
    airline_code: Optional[str]
    airline_name: Optional[str]
    origin_code: Optional[str]
    origin_city: Optional[str]
    destination_code: Optional[str]
    destination_city: Optional[str]
    departure_time: Optional[str]
    arrival_time: Optional[str]
    departure_timestamp: Optional[int]
    arrival_timestamp: Optional[int]
    duration: Optional[str]
    stops: Optional[int]
    layover_cities: List[str]
    legs: List[FlightLeg]
    fare: Optional[float]
    currency: Optional[str]

def build_search_url(
    search_text: str,
    locus_id: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    locus_type: str = "city",
) -> str:
    params = {
        "checkin": datetime.strptime(checkin.replace("-", ""), "%Y%m%d").strftime("%Y%m%d"),
        "checkout": datetime.strptime(checkout.replace("-", ""), "%Y%m%d").strftime("%Y%m%d"),
        "roomString": f"{rooms}-{adults}-{children}",
        "searchText": search_text,
        "locusId": locus_id,
        "locusType": locus_type,
        "cc": "IN",
        "_uCurrency": "INR",
    }
    # The current listing app initializes destination._id from cityCode.
    # locusId alone leaves it empty and no hotel listing API request starts.
    if locus_type == "city":
        params["cityCode"] = locus_id
    return "https://www.goibibo.com/hotels/hotel-listing/?" + urlencode(params)


def _flight_date(date: str) -> str:
    fmt = "%Y-%m-%d" if "-" in date else "%Y%m%d"
    return datetime.strptime(date, fmt).strftime("%d/%m/%Y")


def build_flight_search_url(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    return_date: Optional[str] = None,
) -> str:
    origin, destination = origin.upper(), destination.upper()
    itinerary = f"{origin}-{destination}-{_flight_date(departure_date)}"
    if return_date:
        itinerary += f"_{destination}-{origin}-{_flight_date(return_date)}"

    params = {
        "itinerary": itinerary,
        "tripType": "R" if return_date else "O",
        "paxType": f"A-{adults}_C-{children}_I-{infants}",
        "intl": "false",
        "cabinClass": "E",
        # ccde/lang are part of the results URL the site itself issues. They
        # select the India market; browser countryCode stays IN (see BASE_CONFIG).
        "ccde": "IN",
        "lang": "eng",
    }
    return f"https://www.goibibo.com/flight/search?{urlencode(params, safe='/')}"


def build_flight_search_api_url(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    return_date: Optional[str] = None,
) -> str:
    """search-stream-dt URL the results page requests for these inputs"""

    def api_date(date: str) -> str:
        return datetime.strptime(date, "%Y-%m-%d" if "-" in date else "%Y%m%d").strftime("%Y%m%d")

    origin, destination = origin.upper(), destination.upper()
    itinerary = f"{origin}-{destination}-{api_date(departure_date)}"
    if return_date:
        itinerary += f"${destination}-{origin}-{api_date(return_date)}"
    params = {
        "apiCallTimestamp": int(time.time() * 1000),
        "cc": "E",
        "cmpId": "",
        "crId": str(uuid4()),
        "creditShellInfo": "",
        "cur": "INR",
        "currency": "INR",
        "dfs": "0",
        "forwardFlowRequired": "true",
        "it": itinerary,
        "language": "eng",
        "pax": f"A-{adults}_C-{children}_I-{infants}",
        "pfm": "DESKTOP",
        "region": "in",
        "shd": "true",
        "sortBy": "rhino",
        "src": "",
    }
    return f"{FLIGHT_SEARCH_API}?{urlencode(params)}"


_BROWSER_FORBIDDEN_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "cookie",
    "host",
    "origin",
    "referer",
    "user-agent",
}


def _browser_fetch_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """headers fetch() may set. Origin and Referer throw in the page and became BROWSER_ERROR."""
    return {key: value for key, value in headers.items() if key.lower() not in _BROWSER_FORBIDDEN_HEADERS}


def build_flight_api_headers(token: str, device_id: str) -> Dict[str, str]:
    """headers the results page sends with search-stream-dt; token is __PRE_AUTH__"""
    return {
        "accept": "text/event-stream",
        "app-ver": "1.0.0",
        "currency": "INR",
        "User-Currency": "INR",
        "device-id": device_id,
        "mcid": device_id,
        "domain": "in",
        "language": "eng",
        "os": "Windows",
        "pfm": "DESKTOP",
        "profile-type": "PERSONAL",
        "region": "in",
        "src": "gi",
        "x-user-cc": "IN",
        "Cache-Control": "no-cache",
        "X-Cb-Preauth": token,
        "origin": "https://www.goibibo.com",
        "referer": "https://www.goibibo.com/",
    }


def parse_flight_stream(body: str) -> Dict:
    """parse a search-stream-dt SSE body (gzip + base64 event payloads)"""
    data = {}
    body = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    for block in body.split("\n\n"):
        lines = block.split("\n")
        if "event: response" not in lines:
            if "event: error" in lines:
                raw = "".join(line[5:].strip() for line in lines if line.startswith("data:"))
                error = json.loads(gzip.decompress(base64.b64decode(raw))) if raw else {}
                raise RuntimeError(f"search-stream-dt returned an error event: {error.get('error', {}).get('type')}")
            continue
        raw = "".join(line[5:].strip() for line in lines if line.startswith("data:"))
        if raw:
            data = json.loads(gzip.decompress(base64.b64decode(raw)))
    if not data:
        raise RuntimeError("no response event in search-stream-dt SSE body")
    return data


def parse_flight_stream_call(response: Response):
    """extract the search-stream-dt API call captured by the browser"""
    calls = [
        call
        for call in response.network
        if SEARCH_STREAM_DT in call["url"] and (call.get("response") or {}).get("body")
    ]
    if not calls:
        url = response.url
        # the page sometimes comes as its shell only: search bar filled in, SEARCH button disabled, no results loaded
        if response.selector.css("[data-cy='submit'][disabled]"):
            raise RuntimeError(
                f"goibibo.com answered the flight search with its page shell, the search never started: {url}"
            )
        raise RuntimeError(f"flight search-stream-dt API call not found in captured browser data for {url}")
    return parse_flight_stream(calls[-1]["response"]["body"])


def parse_flight_leg(leg: Dict) -> FlightLeg:
    """one journey leg. Older payloads use legList fields; current ones use legListV2 text."""

    def _strip(html: Optional[str]) -> Optional[str]:
        return re.sub(r"<[^>]+>", "", html).strip() if html else html

    def _city(point: str) -> Optional[str]:
        city = (leg.get(point) or {}).get("city")
        return re.sub(r"\s*\(.*$", "", city).strip() if city else city

    info = leg.get("airlineInfo")
    if info:
        number = info.get("airlineNumber") or ""
        code = re.match(r"\s*([A-Z0-9]{2})\s*-?\s*(\d+)", number)
        aircraft = re.search(r"\(([^)]*)\)", number)
        return FlightLeg(
            flight_number=f"{code[1]}-{code[2]}" if code else number.split("(")[0].strip() or None,
            airline=info.get("airlineName"),
            aircraft=aircraft[1].strip() if aircraft else None,
            departure_city=_city("depart"),
            departure_time=(leg.get("depart") or {}).get("time"),
            arrival_city=_city("arrival"),
            arrival_time=(leg.get("arrival") or {}).get("time"),
        )
    return FlightLeg(
        flight_number=leg.get("legID"),
        airline=leg.get("airlinename"),
        aircraft=_strip((leg.get("aircraft") or {}).get("text")),
        departure_city=_city("depart"),
        departure_time=(leg.get("depart") or {}).get("time"),
        arrival_city=_city("arrival"),
        arrival_time=(leg.get("arrival") or {}).get("time"),
    )


def parse_flights(data: Dict) -> List[Flight]:
    """parse flight cards from a search-stream-dt response"""
    currency = ((data.get("meta") or {}).get("locale") or {}).get("currCode")
    journey_map = data.get("journeyMap") or {}
    flights = []

    for group in data.get("cardList") or []:
        for card in group:
            key = (card.get("journeyKeys") or [None])[0]
            journey = journey_map.get(key) or {}
            detail = journey.get("flightDetail") or {}
            legs = detail.get("legList") or detail.get("legListV2") or []
            layover = journey.get("layover") or {}

            def _strip(html: Optional[str]) -> Optional[str]:
                return re.sub(r"<[^>]+>", "", html).strip() if html else html

            flights.append(
                Flight(
                    flight_number=card.get("flightNumber"),
                    airline_code=", ".join(card.get("airlineCodes") or []),
                    airline_name=(card.get("simpleAirlineHeading") or {}).get("nm"),
                    origin_code=journey.get("depCityCd"),
                    origin_city=_strip(journey.get("depCity")),
                    destination_code=journey.get("arrCityCd"),
                    destination_city=_strip(journey.get("arrCity")),
                    departure_time=journey.get("depTime"),
                    arrival_time=journey.get("arrTime"),
                    departure_timestamp=journey.get("depTimeStamp"),
                    arrival_timestamp=journey.get("arrTimeStamp"),
                    duration=journey.get("duration") and f"{journey['duration']['h']}h {journey['duration']['m']}m",
                    stops=journey.get("stops"),
                    layover_cities=[c.get("cd") for c in layover.get("layoverCityList") or []],
                    legs=[parse_flight_leg(leg) for leg in legs],
                    fare=card.get("fare"),
                    currency=currency,
                )
            )

    return flights

def parse_listing_call(response: Response):
    """extract the listing API call captured by the browser"""
    calls = []
    for call in response.network or []:
        body = ((call.get("response") or {}).get("body")) or ""
        url = call.get("url") or ""
        if not body:
            continue
        # the desktop path is the one the page has used; a renamed listing URL
        # still carries personalizedSections and should not be dropped
        if LISTING_API in url or "personalizedSections" in body:
            calls.append(call)
    if not calls:
        seen = []
        for call in (response.network or [])[:8]:
            seen.append((call.get("url") or "")[:160])
        raise RuntimeError(f"hotel listing API call not found in captured browser data; network: {seen}")

    call = calls[-1]
    data = json.loads(call["response"]["body"])["response"]
    payload = json.loads(call["body"]) if call.get("body") else None
    return call, data, payload


def parse_hotels(data: Dict) -> List[Hotel]:
    """parse hotel cards from a listing API response"""
    currency = data.get("currency")
    hotels = []

    for section in data.get("personalizedSections") or []:
        for item in section.get("hotels") or []:
            price = item.get("priceDetail") or {}
            location = item.get("locationDetail") or {}
            geo = item.get("geoLocation") or {}
            review = item.get("reviewSummaryUgc") or {}
            area = (item.get("locationPersuasion") or [None])[0]
            images = [
                f"https:{url}" if url.startswith("//") else url
                for media in item.get("media") or []
                if (url := media.get("url"))
            ]

            hotels.append(
                Hotel(
                    id=item.get("id"),
                    gi_id=item.get("giId"),
                    name=item.get("name"),
                    property_type=item.get("propertyType"),
                    star_rating=item.get("starRating"),
                    sold_out=item.get("soldOut", False),
                    total_room_count=item.get("totalRoomCount"),
                    categories=item.get("categories") or [],
                    area=area,
                    city=location.get("name"),
                    country=location.get("countryName"),
                    latitude=geo.get("latitude"),
                    longitude=geo.get("longitude"),
                    images=images,
                    price=price.get("discountedPrice", price.get("price")),
                    price_with_tax=price.get("discountedPriceWithTax", price.get("priceWithTax")),
                    price_suffix=price.get("priceSuffix"),
                    currency=currency,
                    rating=review.get("hotelRating"),
                    rating_text=review.get("ratingText"),
                    review_count=review.get("reviewCount"),
                    rating_count=review.get("ratingCount"),
                    amenities=item.get("facilityHighlights") or [],
                    description=item.get("shortDescSeo"),
                    url=item.get("seoUrl") or item.get("detailDeeplinkUrl"),
                )
            )

    return hotels


def _listing_cursor(data: Dict) -> Optional[Dict[str, str]]:
    """read pagination cursor from the listing response"""
    source = data.get("searchCriteria") or data
    window = source.get("lastFetchedWindowInfo")
    if not window:
        return None
    return {
        "lastHotelId": source.get("lastHotelId", ""),
        "lastHotelCategory": source.get("lastHotelCategory", ""),
        "lastFetchedWindowInfo": window,
    }


def _next_listing_request(api_url: str, payload: Dict, cursor: Dict[str, str]):
    """build the next listing page url and POST body"""
    request_id = str(uuid4())
    parsed = urlparse(api_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["ck"] = [str(uuid4())]
    params["requestId"] = [request_id]
    next_url = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))

    next_payload = deepcopy(payload)
    next_payload.setdefault("requestDetails", {})["requestId"] = request_id
    next_payload.setdefault("searchCriteria", {}).update(cursor)
    return next_url, next_payload


@managed
async def scrape_hotel_search(
    search_text: str,
    locus_id: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    children: int = 0,
    rooms: int = 1,
    max_pages: int = 5,
) -> List[Hotel]:
    """Scrape goibibo hotel search; capture the listing API from the search page then paginate until max_pages (copy locus_id from a hotel-listing URL)."""
    url = build_search_url(search_text, locus_id, checkin, checkout, adults, children, rooms)
    log.info(f"scraping goibibo hotels for {search_text}: {url}")

    page = None
    session = None
    last_error: Optional[BaseException] = None
    for attempt in range(1, 3):
        # a fresh session per attempt: a timed-out shell must not keep the next try
        session = uuid4().hex
        try:
            # waitForResponse on the old path timed out the whole navigation at
            # concurrency 1 even when a listing body was already on the wire.
            # Scroll, then read whatever listing JSON the page captured.
            page = await CLIENT.fetch(
                Request(
                    url,
                    waitMs=8000,
                    session=session,
                    timeoutMs=90000,
                    **BASE_CONFIG,
                )
            )
            call, data, payload = parse_listing_call(page)
            break
        except (ScrapeError, RuntimeError) as error:
            last_error = error
            # the named session still occupies a browser slot after a timeout.
            # at concurrency 1 the next attempt would raise SESSION_LIMIT.
            await CLIENT.close_session(session)
            session = None
            if attempt == 2:
                raise
            log.warning(f"hotel listing was not captured ({error}); retrying once")
    else:
        raise last_error or RuntimeError("hotel listing API call not found")
    headers = call["headers"]
    api_url = call["url"]

    hotels = parse_hotels(data)
    seen = {h["id"] for h in hotels}
    log.info(f"page 1: {len(hotels)} hotels")

    cursor = _listing_cursor(data)
    for page_num in range(2, max_pages + 1):
        if not cursor or not payload:
            break

        api_url, body = _next_listing_request(api_url, payload, cursor)
        response = await CLIENT.fetch(
            Request(
                api_url,
                method="POST",
                headers=headers,
                body=json.dumps(body),
                session=session,
                render=False,
                countryCode="IN",
            )
        )
        data = json.loads(response.content)["response"]
        page_hotels = parse_hotels(data)
        new_hotels = [h for h in page_hotels if h["id"] not in seen]
        if not new_hotels:
            break

        seen.update(h["id"] for h in new_hotels)
        hotels.extend(new_hotels)
        log.info(f"page {page_num}: +{len(new_hotels)} (total {len(hotels)})")
        cursor = _listing_cursor(data)

    log.success(f"scraped {len(hotels)} hotels for {search_text}")
    return hotels

@managed
async def scrape_flight_search(
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    return_date: Optional[str] = None,
) -> List[Flight]:
    """Scrape flight search results and return parsed flight data.

    The results URL often paints a shell with SEARCH left disabled and never
    fires search-stream-dt. The static page still carries ``__PRE_AUTH__``;
    the same session then requests the stream the page would have sent. If
    that token is missing, one rendered attempt waits for the stream and only
    clicks SEARCH once the control is enabled.
    """
    page_url = build_flight_search_url(origin, destination, departure_date, adults, children, infants, return_date)
    log.info(f"scraping flight search: {page_url}")
    try:
        data = await _flight_via_preauth(
            page_url, origin, destination, departure_date, adults, children, infants, return_date
        )
    except (RuntimeError, ScrapeError) as error:
        log.warning(f"flight API path failed ({error}); waiting for the page to start search")
        data = await _flight_via_browser(page_url)
    flights = parse_flights(data)
    log.success(f"scraped {len(flights)} flights for {origin}-{destination}")
    return flights


def _preauth_token(html: str) -> Optional[str]:
    match = re.search(r'__PRE_AUTH__\s*=\s*"([0-9a-f]+)"', html or "")
    return match.group(1) if match else None


async def _flight_via_preauth(
    page_url: str,
    origin: str,
    destination: str,
    departure_date: str,
    adults: int,
    children: int,
    infants: int,
    return_date: Optional[str],
) -> Dict:
    session = uuid4().hex
    try:
        page = await CLIENT.fetch(Request(page_url, session=session, render=False, countryCode="IN"))
        token = _preauth_token(page.content)
        if not token:
            if page.selector.css("[data-cy='submit'][disabled]"):
                raise RuntimeError(
                    "goibibo.com answered the flight search with its page shell, the search never started: "
                    f"no __PRE_AUTH__ token at {page.url}"
                )
            raise RuntimeError(f"no __PRE_AUTH__ token in the goibibo.com flight search page: {page.url}")
        api_url = build_flight_search_api_url(
            origin, destination, departure_date, adults, children, infants, return_date
        )
        headers = build_flight_api_headers(token, device_id=str(uuid4()))
        # Navigating the browser onto search-stream-dt fails with
        # ERR_HTTP2_PROTOCOL_ERROR before any event arrives. The results page
        # itself fetches that URL; do the same from the page. A thrown status
        # became BROWSER_ERROR and discarded the body, so the status comes back
        # in the script result. Origin and Referer are not set: fetch() rejects them.
        script = (
            "const response = await fetch("
            + json.dumps(api_url)
            + ", {method: 'GET', credentials: 'include', headers: "
            + json.dumps(_browser_fetch_headers(headers))
            + "});\n"
            "const text = await response.text();\n"
            "return JSON.stringify({status: response.status, text: text});"
        )
        request = Request(
            page_url, session=session, render=False, countryCode="IN", javascript=script, timeoutMs=60000,
        )
        try:
            response = await CLIENT.fetch(request)
        except ScrapeError as error:
            if error.code not in {"ERR_HTTP2_PROTOCOL_ERROR", "ERR_TUNNEL_CONNECTION_FAILED", "ERR_CONNECTION_CLOSED", "TIMEOUT", "BROWSER_ERROR"}:
                raise
            log.warning(f"retrying the in-page flight stream once after {error.code}")
            response = await CLIENT.fetch(request)
        data = _flight_stream_from_response(response)
        if data is None:
            raise RuntimeError(f"flight stream script returned no SSE body for {page_url}")
        return data
    except BaseException:
        await CLIENT.close_session(session)
        raise


def _flight_stream_from_response(response: Response) -> Optional[Dict]:
    """SSE from the in-page script, or from a search-stream-dt call the page recorded."""
    text = ""
    value = response.javascript
    if isinstance(value, str) and value:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            text = value
        else:
            if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                text = payload["text"]
            else:
                text = value
    if "event:" in text:
        return parse_flight_stream(text)
    try:
        return parse_flight_stream_call(response)
    except RuntimeError:
        return None


_FLIGHT_BROWSER_ACTIONS = [
    {"type": "wait", "milliseconds": 3000},
    {"type": "click", "selector": "[data-testid='cta-wrapper'] button", "optional": True},
    {"type": "waitForSelector", "selector": "[data-cy='submit']:not([disabled])", "timeoutMs": 20000, "optional": True},
    {"type": "click", "selector": "[data-cy='submit']:not([disabled])", "optional": True},
    {"type": "wait", "milliseconds": 8000},
]


async def _flight_via_browser(page_url: str) -> Dict:
    """rendered fallback. Record the page's own search call instead of blocking on it.

    waitForResponse burned the whole timeout when Akamai left SEARCH disabled, and
    the empty timeout response discarded any stream that had arrived under another URL.
    """
    last_error: Optional[BaseException] = None
    for attempt in range(1, 3):
        session = uuid4().hex
        try:
            page = await CLIENT.fetch(
                Request(
                    page_url,
                    actions=_FLIGHT_BROWSER_ACTIONS,
                    waitMs=5000,
                    session=session,
                    timeoutMs=90000,
                    **BASE_CONFIG,
                )
            )
            data = _flight_stream_from_response(page)
            if data is None:
                raise RuntimeError(f"flight search-stream-dt API call not found in captured browser data for {page.url}")
            return data
        except (ScrapeError, RuntimeError) as error:
            last_error = error
            log.warning(f"flight page attempt {attempt} did not capture search-stream-dt ({error})")
            if attempt == 2:
                break
        finally:
            await CLIENT.close_session(session)
    raise RuntimeError(
        "goibibo.com flight search did not start: search-stream-dt was not captured "
        f"(SEARCH stays disabled on the page shell): {page_url}"
    ) from last_error
