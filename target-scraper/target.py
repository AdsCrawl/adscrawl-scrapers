# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for Target.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import asyncio
import gzip
import os
import re
import json
from typing import Dict, List, Optional, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4
from parsel import Selector
from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",

}

# 435 is Target's anti-bot response (the store parser already calls it an access
# denial). 403/429 are the same class. A second session sometimes gets a
# different route; a repeated 435 stays an error and is not treated as an empty
# catalog.
_ANTIBOT_STATUSES = {403, 429, 435}
# Document navigations to redsky return 435. The homepage XHR does not, so
# the API is called with fetch() from a target.com document. Two further
# attempts use a new session. The HTML fallback is only after those fail.
_REDSKY_ATTEMPTS = 3
STORE_SITEMAP_URL = "https://www.target.com/sl/sitemap_0001.xml.gz"


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _antibot_status(error: ScrapeError) -> Optional[int]:
    status = error.response.status_code if error.response is not None else 0
    if error.code == "HTTP_ERROR" and status in _ANTIBOT_STATUSES:
        return status
    if error.code == "HTTP_ERROR" and "435" in error.message:
        return 435
    return None


def _antibot_error(error: ScrapeError) -> ScrapeError:
    status = _antibot_status(error) or 435
    return ScrapeError(
        f"Target anti-bot block (HTTP {status})",
        response=error.response,
        code="HTTP_ERROR",
    )


class Price(TypedDict):
    current_retail: Optional[float]
    reg_retail: Optional[float]
    formatted_current_price: Optional[str]
    location_id: Optional[int]


class ProductVariant(TypedDict):
    tcin: str
    price: Optional[Price]
    free_shipping: Optional[bool]
    in_stock: bool


class Product(TypedDict):
    tcin: str
    title: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    variants: List[ProductVariant]


MODULE_FULFILLMENT = "ProductDetailWebDatasourceFulfillmentAndVariations"
MODULE_WITH_STORE = "ProductDetailWebDatasourceWithStore"
MODULE_REVIEWS = "ProductDetailReviewsAndQuestions"


def _extract_deferred_modules(response: Response) -> Dict[str, Dict]:
    """collect deferred_enrichment module payloads from captured XHR calls"""
    modules = {}
    errors = []
    xhr_calls = response.network or []
    for xhr in xhr_calls:
        if "deferred_enrichment/modules" not in xhr.get("url", ""):
            continue
        status = (xhr.get('response') or {}).get('status', 0)
        if status >= 400:
            errors.append(status)
            continue
        body = (xhr.get("response") or {}).get("body")
        if not body:
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        for module in data.get("modules", []):
            if module_type := module.get("module_type"):
                modules[module_type] = module.get("module_data", {})
    if not modules and errors:
        raise ScrapeError(f'Target data API returned HTTP {errors[-1]}', response=response, code='HTTP_ERROR')
    return modules


def _extract_redsky_credentials(response: Response) -> Dict[str, str]:
    """extract the redsky 'key' and 'visitor_id' from the store_location_v1 XHR captured on the homepage"""
    xhr_calls = response.network or []
    for xhr in xhr_calls:
        if "store_location_v1" not in xhr.get("url", ""):
            continue
        params = parse_qs(urlparse(xhr["url"]).query)
        key = params.get("key", [None])[0]
        visitor_id = params.get("visitor_id", [None])[0]
        if key and visitor_id:
            return {"key": key, "visitor_id": visitor_id}
    raise ValueError("missing store_location_v1 XHR with key and visitor_id")


def _is_in_stock(fulfillment: Optional[Dict]) -> bool:
    if not fulfillment or fulfillment.get("sold_out"):
        return False
    if (fulfillment.get("shipping_options") or {}).get("availability_status") == "IN_STOCK":
        return True
    for store in fulfillment.get("store_options") or []:
        statuses = (
            (store.get("order_pickup") or {}).get("availability_status"),
            (store.get("in_store_only") or {}).get("availability_status"),
        )
        if "IN_STOCK" in statuses:
            return True
    return False


def _parse_price_display(item: Dict) -> Optional[Price]:
    """Read the current PriceBlock while keeping unknown prices explicit."""
    current = regular = formatted = None
    for row in (item.get('price_display') or {}).get('rows', []):
        for part in (row.get('text') or {}).get('contents', []):
            text = (part.get('insert') or {}).get('text', '')
            match = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
            if not match:
                continue
            amount = float(match.group(1).replace(',', ''))
            if (part.get('attributes') or {}).get('strike'):
                regular = amount
            elif current is None:
                current, formatted = amount, match.group(0)
    if current is None and regular is None:
        return None
    return {'current_retail': current, 'reg_retail': regular,
            'formatted_current_price': formatted, 'location_id': None}


def parse_product(response: Response) -> Product:
    """parse product data from deferred_enrichment XHR modules captured on the PDP"""
    modules = _extract_deferred_modules(response)
    if MODULE_FULFILLMENT not in modules:
        raise ValueError(f"missing deferred_enrichment module: {MODULE_FULFILLMENT}")
    if MODULE_WITH_STORE not in modules and 'ProductDetailPrice' not in modules:
        raise ValueError('missing product pricing module')

    fulfillment = modules[MODULE_FULFILLMENT]["data"]["product"]
    store = modules.get(MODULE_WITH_STORE, {}).get('data', {}).get('product', {})
    fulfillment_by_tcin = {c["tcin"]: c for c in fulfillment.get("children") or [fulfillment]}
    store_by_tcin = {c["tcin"]: c for c in (store.get("children") or [store]) if c.get('tcin')}
    prices_by_tcin = {p['tcin']: p for p in modules.get('ProductDetailPrice', {}).get('data_by_tcin', []) if p.get('tcin')}

    variants: List[ProductVariant] = []
    for tcin in sorted(set(fulfillment_by_tcin) | set(store_by_tcin) | set(prices_by_tcin)):
        store_child = store_by_tcin.get(tcin, {})
        fulfillment_child = fulfillment_by_tcin.get(tcin, {})
        price_data = store_child.get("price") or {}
        variants.append({
            "tcin": tcin,
            "price": {
                "current_retail": price_data.get("current_retail"),
                "reg_retail": price_data.get("reg_retail"),
                "formatted_current_price": price_data.get("formatted_current_price"),
                "location_id": price_data.get("location_id"),
            } if price_data else _parse_price_display(prices_by_tcin.get(tcin, {})),
            # New price modules omit eligibility; absence is not proof that
            # shipping is paid or free.
            "free_shipping": (store_child.get("free_shipping") or {}).get("enabled"),
            "in_stock": _is_in_stock(fulfillment_child.get("fulfillment")),
        })

    ratings = modules.get(MODULE_REVIEWS, {}).get("ratings_and_reviews") or {}
    tcin = fulfillment.get("tcin") or store.get("tcin")
    if not tcin:
        match = re.search(r"/A-(\d+)", response.url)
        tcin = match.group(1) if match else None

    return {
        "tcin": tcin,
        "title": response.selector.css('h1[data-test="product-title"]::text').get(),
        "rating": ratings.get("average"),
        "review_count": ratings.get("count"),
        "variants": variants,
    }


@managed
async def scrape_product(url: str) -> Product:
    """scrape a Target product page and return parsed product data"""
    request = Request(
        url,
        **BASE_CONFIG,
        render=True,
        waitForResponse="deferred_enrichment/modules",
        waitMs=5000,
    )
    last = None
    for attempt in range(2):
        response = await CLIENT.fetch(request)
        try:
            return parse_product(response)
        except ScrapeError as error:
            last = error
            if _antibot_status(error) is None or attempt == 1:
                if _antibot_status(error) is not None:
                    raise _antibot_error(error) from None
                raise
            log.warning(f"retrying Target once after HTTP {_antibot_status(error)}")
    raise last


def parse_availability(response: Response) -> Dict:
    """parse fulfillment and availability data from a product_summary_with_fulfillment_v1 response"""
    data = json.loads(response.content)
    summaries = data.get("data", {}).get("product_summaries")
    if summaries is None:
        raise ValueError("missing data.product_summaries in availability response")

    availability = {}
    for summary in summaries:
        tcin = summary["tcin"]
        fulfillment = summary.get("fulfillment") or {}
        availability[tcin] = {
            "tcin": tcin,
            "title": summary.get("item", {}).get("product_description", {}).get("title"),
            "price": summary.get("price"),
            "free_shipping": (summary.get("free_shipping") or {}).get("enabled", False),
            "fulfillment": fulfillment,
            "in_stock": _is_in_stock(fulfillment),
        }
    return availability


def _redsky_script(url: str) -> str:
    """Fetch redsky from the target.com page instead of navigating to it."""
    return (
        "const response = await fetch(%s, {credentials: 'include', headers: {accept: 'application/json'}});\n"
        "const body = await response.text();\n"
        "return {status: response.status, body};\n"
    ) % json.dumps(url)


def _redsky_response(url: str, payload) -> Response:
    if not isinstance(payload, dict):
        raise ScrapeError(
            "Target page did not return a redsky response",
            response=Response(url, request_url=url, status_code=0),
            code="HTTP_ERROR",
        )
    status = int(payload.get("status") or 0)
    body = payload.get("body") if isinstance(payload.get("body"), str) else ""
    response = Response(url, content=body, request_url=url, status_code=status)
    blocked_document = not body.lstrip().startswith(("{", "[")) and "access denied" in body[:400].lower()
    if status in _ANTIBOT_STATUSES or blocked_document:
        raise ScrapeError(
            f"Target data API returned HTTP {status or 435}",
            response=response,
            code="HTTP_ERROR",
        )
    if status >= 400:
        raise ScrapeError(f"Target returned HTTP {status}", response=response, code="HTTP_ERROR")
    if not body.lstrip().startswith(("{", "[")):
        raise ScrapeError("Target page fetch did not return JSON", response=response, code="HTTP_ERROR")
    return response


async def _fetch_redsky(session: str, url: str) -> Response:
    """Call redsky with the cookies of a target.com document in this session."""
    page = await CLIENT.fetch(Request(
        "https://www.target.com/",
        session=session,
        render=True,
        waitUntil="commit",
        javascript=_redsky_script(url),
        timeoutMs=90_000,
        **BASE_CONFIG,
    ))
    return _redsky_response(url, page.javascript)


async def _availability_from_product_pages(tcins: List[str]) -> Dict:
    """Product-page fulfillment when redsky keeps returning 435.

    This is the PDP shipping/stock flag, not the store-inventory payload.
    """
    availability = {}
    for tcin in tcins:
        product = await scrape_product(f"https://www.target.com/p/-/A-{tcin}")
        variants = list(product.get("variants") or [])
        if not variants and product.get("tcin"):
            variants = [{
                "tcin": product["tcin"],
                "in_stock": False,
                "price": None,
                "free_shipping": None,
            }]
        for variant in variants:
            availability[variant["tcin"]] = {
                "tcin": variant["tcin"],
                "title": product.get("title"),
                "price": variant.get("price"),
                "free_shipping": variant.get("free_shipping"),
                "fulfillment": None,
                "in_stock": bool(variant.get("in_stock")),
            }
    if not availability:
        raise ValueError("product page did not include a tcin")
    return availability


async def _redsky_session():
    """Homepage session that yields redsky key and visitor id. Closed by the caller."""
    session = str(uuid4()).replace("-", "")
    try:
        warm_up = await CLIENT.fetch(Request(
            "https://www.target.com/",
            session=session,
            render=True,
            waitForResponse="store_location_v1",
            waitMs=5000,
            **BASE_CONFIG,
        ))
        return session, _extract_redsky_credentials(warm_up)
    except Exception:
        await CLIENT.close_session(session)
        raise


@managed
async def scrape_availability(
    tcins: List[str],
    store_id: str,
    zip_code: str,
) -> Dict:
    """scrape product availability from redsky, called inside a target.com page.

    Opening the redsky URL itself is HTTP 435. After three blocked sessions,
    the product page is the fallback. That fallback is not store inventory.
    """
    last = None
    for attempt in range(_REDSKY_ATTEMPTS):
        session = None
        try:
            session, credentials = await _redsky_session()
            url = "https://redsky.target.com/redsky_aggregations/v1/web/product_summary_with_fulfillment_v1?" + urlencode({
                "key": credentials["key"],
                "visitor_id": credentials["visitor_id"],
                "tcins": ",".join(tcins),
                "store_id": store_id,
                "pricing_store_id": store_id,
                "required_store_id": store_id,
                "scheduled_delivery_store_id": store_id,
                "zip": zip_code,
                "channel": "WEB",
                "page": f"/p/A-{tcins[0]}",
            })
            return parse_availability(await _fetch_redsky(session, url))
        except ScrapeError as error:
            last = error
            if _antibot_status(error) is None:
                raise
            if attempt == _REDSKY_ATTEMPTS - 1:
                break
            log.warning(f"retrying Target after HTTP {_antibot_status(error)}")
            await _pause(2 * (attempt + 1))
        finally:
            if session is not None:
                await CLIENT.close_session(session)
    try:
        return await _availability_from_product_pages(tcins)
    except Exception as error:
        log.warning(f"Target product-page fallback failed: {error}")
        raise _antibot_error(last) from None

def parse_store_locations_sitemap(response: Response) -> List[Dict]:
    """parse store location entries from a sitemap response"""
    bytes_data = response.raw or response.content.encode('utf-8')
    if bytes_data.startswith(b"\x1f\x8b"):
        bytes_data = gzip.decompress(bytes_data)
    # sitemaps declare a default xmlns: parse as XML and select url/loc in that namespace
    selector = Selector(text=bytes_data.decode("utf-8"), type="xml")
    namespaces = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    locations = []
    for url in selector.xpath("//sm:url/sm:loc/text()", namespaces=namespaces):
        url = url.get()
        slug, store_id = urlparse(url).path.strip("/").split("/")[-2:]
        locations.append({"url": url, "slug": slug, "store_id": store_id})
    return locations


@managed
async def scrape_store_locations_sitemap(url: str) -> List[Dict]:
    """scrape store location URLs from the Target store sitemap"""
    response = await CLIENT.fetch(Request(url, **BASE_CONFIG, binary=True))
    return parse_store_locations_sitemap(response)

def parse_store_locations(response: Response) -> Dict:
    """parse store location data from a store_location_v1 response"""
    if not response.content.lstrip().startswith("{"):
        # target.com sometimes answers this request with an HTML "Access to this page has been denied" page (HTTP 435)
        title = response.selector.css("title::text").get()
        raise ValueError(
            f"target.com answered the store location request with HTTP {response.upstream_status_code} "
            f"({title}) instead of JSON: {response.url}"
        )
    data = json.loads(response.content)
    store = data.get("data", {}).get("store")
    if store is None:
        raise ValueError("missing data.store in store location response")

    params = parse_qs(urlparse(response.url).query)
    page = params.get("page", [""])[0]
    if page.startswith("/sl/"):
        slug, store_id = page.strip("/").split("/")[-2:]
        store["slug"] = slug
        store["url"] = f"https://www.target.com/sl/{slug}/{store_id}"
    return store


def parse_store_page(response: Response, store_id: str, slug: str, page_url: str) -> Dict:
    """location name from the public /sl/{slug}/{id} page."""
    name = (response.selector.css("h1::text").get() or "").strip()
    name = re.sub(r"^Target\s+", "", name).strip()
    if not name:
        match = re.search(r'"location_name"\s*:\s*"([^"]+)"', response.content or "")
        name = match.group(1).strip() if match else ""
    if not name:
        raise ValueError(f"store page {page_url} did not include a location name")
    return {"store_id": str(store_id), "location_name": name, "slug": slug, "url": page_url}


async def _stores_from_pages(store_ids: List[str]) -> List[Dict]:
    """Resolve ids through the sitemap, then read each public store page."""
    locations = await scrape_store_locations_sitemap(STORE_SITEMAP_URL)
    by_id = {item["store_id"]: item for item in locations}
    stores = []
    for store_id in store_ids:
        item = by_id.get(str(store_id))
        if item is None:
            raise ValueError(f"store id {store_id} was not in the Target sitemap")
        page = await CLIENT.fetch(Request(item["url"], render=True, timeoutMs=90_000, **BASE_CONFIG))
        stores.append(parse_store_page(page, str(store_id), item["slug"], item["url"]))
    return stores


@managed
async def scrape_store_locations(store_ids: List[str]) -> List[Dict]:
    """scrape store details from store_location_v1, called inside a target.com page.

    A repeated HTTP 435 falls back to the public store page. That page still
    has to include a location name; a block with no page data stays an error.
    """
    last = None
    for attempt in range(_REDSKY_ATTEMPTS):
        session = None
        try:
            session, credentials = await _redsky_session()
            stores = []
            for store_id in store_ids:
                url = "https://redsky.target.com/redsky_aggregations/v1/web/store_location_v1?" + urlencode({
                    "key": credentials["key"],
                    "visitor_id": credentials["visitor_id"],
                    "store_id": store_id,
                    "channel": "WEB",
                    "page": "/c/root",
                })
                stores.append(parse_store_locations(await _fetch_redsky(session, url)))
            return stores
        except ScrapeError as error:
            last = error
            if _antibot_status(error) is None:
                raise
            if attempt == _REDSKY_ATTEMPTS - 1:
                break
            log.warning(f"retrying Target after HTTP {_antibot_status(error)}")
            await _pause(2 * (attempt + 1))
        finally:
            if session is not None:
                await CLIENT.close_session(session)
    try:
        return await _stores_from_pages(store_ids)
    except Exception as error:
        log.warning(f"Target store-page fallback failed: {error}")
        raise _antibot_error(last) from None



def parse_search(response: Response) -> List[Dict]:
    """parse product listing data from a search results page"""
    products = []
    # older layout: ProductCardWrapper cards; current layout: ListingPageProductListing cards
    cards = response.selector.css(
        '[data-test="@web/site-top-of-funnel/ProductCardWrapper"], [data-test="ListingPageProductListing"]'
    )
    for card in cards:
        link = card.css('a[href*="/A-"]::attr(href)').get()
        if not link:
            continue
        match = re.search(r'/A-(\d+)', link)
        if not match:
            continue
        # current layout: the image link's label is the full title (" Sponsored" added on ads), the heading starts
        # with the brand, the first "$" text block is the price, followed by " reg " and the regular price on sale
        heading = card.css('h3[data-test="text-quill"]')
        label = card.css('a[data-test="product-listing-gallery-desktop-image-link"]::attr(aria-label)').get()
        price_block = next(
            (
                block
                for block in card.css('[data-test="text-quill"]')
                if (block.css('[data-test="text-quill-insert-0"]::text').get() or "").startswith("$")
            ),
            None,
        )
        price_parts = price_block.css("span::text").getall() if price_block else []
        products.append({
            "tcin": match.group(1),
            "url": "https://www.target.com" + link.split("#")[0],
            "title": (
                card.css('[data-test="@web/ProductCard/title"] ::text').get()
                or card.css('[data-test="@web/ProductCard/title"]::attr(aria-label)').get()
                or (label.removesuffix(" Sponsored") if label else None)
            ),
            "brand": (
                card.css('[data-test="@web/ProductCard/ProductCardBrandAndRibbonMessage/brand"] ::text').get()
                or (heading.css('[data-test="text-quill-insert-0"]::text').get() or "").strip()
                or None
            ),
            "price": (
                card.css('[data-test="current-price"] span ::text').get()
                or (price_parts[0] if price_parts else None)
            ),
            "reg_price": (
                card.css('[data-test="comparison-price"] span ::text').get()
                or (price_parts[2] if len(price_parts) > 2 and price_parts[1].strip() == "reg" else None)
            ),
        })
    return products


@managed
async def scrape_search(
    keyword: str,
    max_pages: Optional[int] = None,
) -> List[Dict]:
    """scrape search results and paginate through all result pages"""
    results: List[Dict] = []
    for page in range(max_pages or 1):
        params = {"searchTerm": keyword}
        if page > 0:
            params["Nao"] = page * 24
        url = "https://www.target.com/s?" + urlencode(params)
        response = await CLIENT.fetch(
            Request(
                url,
                render=True,
                # wait for the product cards (current and older layout); XPath because the old name contains "/"
                waitForSelector='//*[@data-test="ListingPageProductListing" '
                'or @data-test="@web/site-top-of-funnel/ProductCardWrapper"]',
                **BASE_CONFIG,
            )
        )
        results.extend(parse_search(response))
    return results
