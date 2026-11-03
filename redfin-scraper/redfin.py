# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for redfin.com adapted from the upstream Scrapfly example:
https://scrapfly.io/blog/how-to-scrape-redfin/

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import json
import os
import re
from html import unescape
from typing import List, Dict, Optional
from urllib.parse import quote, urlsplit
from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()


BASE_CONFIG = {

    'countryCode': "US",
}


def parse_search_api(response: Response) -> List[Dict]:
    """parse JSON data from the search API"""
    return json.loads(response.content.replace("{}&&", ""))["payload"]["homes"]


_DETAIL_PATHS = (
    "/stingray/api/home/details/aboveTheFold",
    "/stingray/api/home/details/mainHouseInfoPanelInfo",
    "/stingray/api/v1/home/details/belowTheFold",
)
_STATE_MARKER = "root.__reactServerState.InitialContext = "


def _payload_from_text(text: str) -> Dict:
    if text.startswith("{}&&"):
        text = text[4:]
    data = json.loads(text)
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else {}


def _cache_from_html(html: str) -> Dict[str, Dict]:
    if _STATE_MARKER not in html:
        return {}
    start = html.index(_STATE_MARKER) + len(_STATE_MARKER)
    state, _ = json.JSONDecoder().raw_decode(html, start)
    cache = {}
    for path, entry in state["ReactServerAgent.cache"]["dataCache"].items():
        text = (entry.get("res") or {}).get("text") or ""
        if text.startswith("{}&&"):  # the same JSON prefix as the search API
            cache[path] = json.loads(text[4:]).get("payload") or {}
    return cache


def _cache_from_network(response: Response) -> Dict[str, Dict]:
    cache = {}
    for call in response.network or []:
        url = call.get("url") or ""
        body = ((call.get("response") or {}).get("body")) or ""
        if "stingray/api/" not in url or not body:
            continue
        path = urlsplit(url).path
        if path not in _DETAIL_PATHS and not path.endswith("/belowTheFold"):
            continue
        key = "/stingray/api/v1/home/details/belowTheFold" if path.endswith("/belowTheFold") else path
        try:
            cache[key] = _payload_from_text(body)
        except json.JSONDecodeError:
            continue
    return cache


def parse_data_cache(response: Response) -> Dict[str, Dict]:
    """parse property API answers from the embedded react state, or from captured stingray calls"""
    html = response.content or ""
    cache = _cache_from_html(html)
    for path, payload in _cache_from_network(response).items():
        cache.setdefault(path, payload)
    if "/stingray/api/home/details/aboveTheFold" not in cache:
        title = response.selector.xpath("//title/text()").get("").strip()
        raise ValueError(f"redfin.com page has no property data: {title!r} ({len(html):,} characters)")
    return cache


def _nested_id(payload: Dict, *names: str, depth: int = 0):
    if not isinstance(payload, dict) or depth > 4:
        return None
    for name in names:
        value = payload.get(name)
        if isinstance(value, (int, str)) and str(value).strip():
            return value
    for value in payload.values():
        if isinstance(value, dict):
            found = _nested_id(value, *names, depth=depth + 1)
            if found is not None:
                return found
    return None


def _details_from_api(above: Dict) -> List[str]:
    """key facts the page's .keyDetails block shows, when that block never hydrated"""
    info = above.get("addressSectionInfo") or {}
    home_type = info.get("homeType")
    if isinstance(home_type, dict):
        home_type = home_type.get("displayValue") or home_type.get("name")
    property_type = info.get("propertyTypeName") or home_type
    rows = []
    if property_type:
        rows.append(f"Property Type: {property_type}")
    if info.get("yearBuilt"):
        rows.append(f"Year Built: {info['yearBuilt']}")
    if info.get("beds") is not None:
        rows.append(f"Beds: {info['beds']}")
    if info.get("baths") is not None:
        rows.append(f"Baths: {info['baths']}")
    sqft = info.get("sqFt") if info.get("sqFt") is not None else info.get("sqft")
    if sqft:
        rows.append(f"Sq. Ft.: {sqft}")
    return rows


def feature_text(entry: Dict) -> str:
    """an amenity entry as "Name: value, value" (the values can hold HTML links)"""
    raw_values = entry.get("amenityValues") or []
    values = [unescape(re.sub(r"<[^>]+>", "", value)) for value in raw_values]
    text = ", ".join(values)
    return f"{entry['amenityName']}: {text}" if entry.get("amenityName") else text


def parse_property_for_sale(response: Response) -> Dict:
    """parse a property page from the API answers embedded in it"""
    cache = parse_data_cache(response)
    above_the_fold = cache.get("/stingray/api/home/details/aboveTheFold") or {}
    if "addressSectionInfo" not in above_the_fold:
        raise ValueError("redfin.com page has no property details (aboveTheFold)")
    address = above_the_fold["addressSectionInfo"]
    street = address["streetAddress"]["assembledAddress"]
    price = address.get("priceInfo") or {}  # list price, or last sold price of a sold home
    photos = (above_the_fold.get("mediaBrowserInfo") or {}).get("photos") or []
    house_info = cache.get("/stingray/api/home/details/mainHouseInfoPanelInfo") or {}
    remarks = (house_info.get("mainHouseInfo") or {}).get("marketingRemarks") or []
    below_the_fold = cache.get("/stingray/api/v1/home/details/belowTheFold") or {}
    amenities = below_the_fold.get("amenitiesInfo") or {}
    features_data = {}
    for super_group in amenities.get("superGroups") or []:
        for group in super_group.get("amenityGroups") or []:
            if not group.get("groupTitle"):  # the public facts block has no title
                continue
            entries = group.get("amenityEntries") or []
            features_data[group["groupTitle"]] = [feature_text(entry) for entry in entries]
    selector = response.selector
    details = []  # the key details block of the page, e.g. "Year Built: 1992"
    for row in selector.css(".keyDetails-value"):
        label = row.css(".valueType::text").get("")
        value = row.css(".valueText::text").get("")
        if label or value:
            details.append(f"{label}: {value}")
    if not details:
        details = _details_from_api(above_the_fold)
    monthly = selector.css(".est-monthly-payment .monthly-payment ::text").getall()
    monthly_price = "".join(monthly).strip()
    return {
        "address": f"{street}, {address['city']}, {address['state']} {address['zip']}",
        "description": unescape(remarks[0]["marketingRemark"]) if remarks else None,
        "price": f"${price['amount']:,}" if price.get("amount") else None,
        "estimatedMonthlyPrice": f"Est. {monthly_price}" if monthly_price else "",
        "propertyUrl": str(response.url),
        "attachments": [photo["photoUrls"]["fullScreenPhotoUrl"] for photo in photos],
        "details": details,
        "features": features_data,
    }


def parse_property_for_rent(response: Response):
    """get the rental ID from the HTML to use it in the API"""
    selector = response.selector
    data = selector.xpath("//meta[@property='og:image']/@content").get()
    if not data or "rent/" not in data:
        title = selector.xpath("//title/text()").get("").strip()
        log.warning(f"redfin rental page has no rental id (title: {title!r})")
        return None
    rental_id = data.split("rent/")[1].split("/")[0]
    if len(rental_id) != 36:
        log.warning(f"redfin rental id {rental_id!r} is not a 36-character id")
        return None
    return rental_id


@managed
async def scrape_search(url: str) -> List[Dict]:
    """scrape search data from the searh API"""
    # send a request to the search API
    search_api_response = await CLIENT.fetch(
        Request(url, countryCode="US")
    )
    search_data = parse_search_api(search_api_response)
    log.success(f"scraped ({len(search_data)}) search results from the search API")
    return search_data


_SALE_ACTIONS = [
    # the document is often a 2 KB noscript shell until the react state or stingray calls arrive
    {"type": "waitForSelector", "selector": "xpath=//script[contains(., '__reactServerState')]", "timeoutMs": 15000, "optional": True},
]


def _property_id_from_url(url: str) -> Optional[str]:
    tail = urlsplit(url).path.rstrip("/").split("/")[-1]
    return tail if tail.isdigit() else None


_STINGRAY_RETRY = {
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_FAILED",
    "ERR_CONNECTION_RESET",
    "ERR_TIMED_OUT",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "ERR_EMPTY_RESPONSE",
    "TIMEOUT",
    "BROWSER_ERROR",
}


def _stingray_retryable(error: ScrapeError) -> bool:
    code = error.code or ""
    return code in _STINGRAY_RETRY or "CONNECT" in code or "TUNNEL" in code


async def _stingray_get(url: str) -> Response:
    """one JSON stingray call, retried once. Search already succeeds on this US route;
    a single tunnel must not abort the sale listing."""
    request = Request(
        url,
        countryCode="US",
        render=False,
        headers={"Accept": "application/json,text/plain,*/*", "Referer": "https://www.redfin.com/"},
        timeoutMs=30000,
    )
    try:
        return await CLIENT.fetch(request)
    except ScrapeError as error:
        if not _stingray_retryable(error):
            raise
        log.warning(f"retrying stingray once after {error.code}: {url}")
        return await CLIENT.fetch(request)


def _detail_queries(property_id, listing_id) -> List[str]:
    if listing_id:
        return [f"propertyId={property_id}&listingId={listing_id}&accessLevel=1"]
    # initialInfo is what normally supplies listingId. The URL still has propertyId,
    # and aboveTheFold accepts that alone; listingId=propertyId is the second try.
    return [
        f"propertyId={property_id}&accessLevel=1",
        f"propertyId={property_id}&listingId={property_id}&accessLevel=1",
    ]


def _usable_above(payload: Dict) -> bool:
    info = payload.get("addressSectionInfo") if isinstance(payload, dict) else None
    return isinstance(info, dict) and bool(info.get("streetAddress"))


async def _property_from_apis(url: str) -> Response:
    """stingray detail calls. initialInfo is optional: the sale URL ends in the property id."""
    path = urlsplit(url).path
    property_id = _property_id_from_url(url)
    listing_id = None
    try:
        initial = await _stingray_get(
            "https://www.redfin.com/stingray/api/home/details/initialInfo?path=" + quote(path)
        )
        payload = _payload_from_text(initial.content)
        property_id = _nested_id(payload, "propertyId") or property_id
        listing_id = _nested_id(payload, "listingId")
    except (ScrapeError, json.JSONDecodeError, ValueError) as error:
        log.warning(f"initialInfo failed ({error}); using property id {property_id} from {url}")
    if not property_id:
        raise ValueError(f"redfin.com has no property id for {url}")

    chosen = None
    above_body = None
    last_error: Optional[BaseException] = None
    for query in _detail_queries(property_id, listing_id):
        api_url = f"https://www.redfin.com/stingray/api/home/details/aboveTheFold?{query}"
        try:
            above = await _stingray_get(api_url)
            payload = _payload_from_text(above.content)
        except (ScrapeError, json.JSONDecodeError, ValueError) as error:
            last_error = error
            continue
        if _usable_above(payload):
            chosen = query
            above_body = above.content
            break
        last_error = ValueError(f"aboveTheFold had no address for {api_url}")
    if not chosen or above_body is None:
        raise ValueError(f"redfin.com aboveTheFold had no property details for {url}") from last_error

    network = [{
        "url": "https://www.redfin.com/stingray/api/home/details/aboveTheFold",
        "response": {"body": above_body},
    }]
    for key in (
        "/stingray/api/home/details/mainHouseInfoPanelInfo",
        "/stingray/api/v1/home/details/belowTheFold",
    ):
        api_url = f"https://www.redfin.com{key}?{chosen}"
        try:
            api_response = await _stingray_get(api_url)
        except ScrapeError as error:
            log.warning(f"stingray {key} failed ({error.code}); continuing with aboveTheFold")
            continue
        network.append({"url": "https://www.redfin.com" + key, "response": {"body": api_response.content}})
    return Response(url, content="", network=network)


async def _load_sale_page(url: str) -> Response:
    # The HTML document timed out on the 2026-11-03 US retest, and the stingray
    # call that followed died on the first tunnel. Ask for the JSON first (the
    # same US route search already uses) and only open the document if that fails.
    try:
        return await _property_from_apis(url)
    except (ScrapeError, ValueError, json.JSONDecodeError) as error:
        log.warning(f"stingray details were not usable ({error}); opening {url}")
    try:
        return await CLIENT.fetch(
            Request(url, **BASE_CONFIG, actions=_SALE_ACTIONS, timeoutMs=60000)
        )
    except ScrapeError as error:
        raise ScrapeError(
            f"redfin.com for-sale listing failed after stingray details and HTML navigation ({error.code}) for {url}",
            response=error.response,
            code=error.code,
        ) from None


@managed
async def scrape_property_for_sale(urls: List[str]) -> List[Dict]:
    """scrape properties for sale data from HTML, falling back to the stingray detail APIs"""
    properties = []
    for url in urls:
        response = await _load_sale_page(url)
        properties.append(parse_property_for_sale(response))
    log.success(f"scraped {len(properties)} property listings for sale")
    return properties


_RENT_RETRYABLE = {"BROWSER_ERROR", "TIMEOUT", "SELECTOR_NOT_FOUND", "ERR_TUNNEL_CONNECTION_FAILED", "ERR_CONNECTION_CLOSED"}


async def _load_rent_page(url: str) -> Response:
    request = Request(
        url,
        **BASE_CONFIG,
        waitForSelector="meta[property='og:image']",
        timeoutMs=90000,
    )
    last_error: Optional[ScrapeError] = None
    for attempt in range(2):
        try:
            return await CLIENT.fetch(request)
        except ScrapeError as error:
            last_error = error
            title = ""
            if error.response and error.response.content:
                title = error.response.selector.xpath("//title/text()").get("") or ""
            loading = title.lower().startswith("loading")
            if attempt == 0 and (error.code in _RENT_RETRYABLE or loading):
                log.warning(f"retrying rental page {url} after {error.code} (title: {title!r})")
                continue
            if loading:
                raise ScrapeError(
                    f"redfin.com rental page stayed on its loading shell (title: {title!r})",
                    response=error.response,
                    code=error.code,
                ) from None
            raise
    raise last_error or ScrapeError("redfin.com rental page failed", code="BROWSER_ERROR")


@managed
async def scrape_property_for_rent(urls: List[str]) -> list[Dict]:
    """scrape properties for rent from the API"""
    api_urls = []
    properties = []
    for url in urls:
        response_html = await _load_rent_page(url)
        rental_id = parse_property_for_rent(response_html)
        if rental_id:
            api_urls.append(
                f"https://www.redfin.com/stingray/api/v1/rentals/{rental_id}/floorPlans"
            )
    # add the property pages API URLs to a scraping list
    to_scrape = [Request(url, countryCode="US") for url in api_urls]
    async for response in CLIENT.fetch_many(to_scrape):
        properties.append(json.loads(response.content))
    log.success(f"scraped {len(properties)} property listings for rent")
    return properties
