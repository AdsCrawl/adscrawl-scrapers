# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for Target.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import gzip
import os
import re
import json
from typing import Dict, List, Optional, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4
from parsel import Selector
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",

}


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
    response = await CLIENT.fetch(Request(
        url,
        **BASE_CONFIG,
        render=True,
        waitForResponse="deferred_enrichment/modules",
        waitMs=5000,
    ))
    return parse_product(response)


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


@managed
async def scrape_availability(
    tcins: List[str],
    store_id: str,
    zip_code: str,
) -> Dict:
    """scrape product availability and fulfillment data from product_summary_with_fulfillment_v1"""
    session = str(uuid4()).replace("-", "")
    warm_up = await CLIENT.fetch(Request(
        "https://www.target.com/",
        session=session,
        render=True,
        waitForResponse="store_location_v1",
        waitMs=5000,
        **BASE_CONFIG,
    ))
    credentials = _extract_redsky_credentials(warm_up)

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

    response = await CLIENT.fetch(Request(url, session=session, **BASE_CONFIG))
    return parse_availability(response)

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


@managed
async def scrape_store_locations(store_ids: List[str]) -> List[Dict]:
    """scrape store location details from store_location_v1 for a list of store IDs"""
    session = str(uuid4()).replace("-", "")
    warm_up = await CLIENT.fetch(Request(
        "https://www.target.com/",
        session=session,
        render=True,
        waitForResponse="store_location_v1",
        waitMs=5000,
        **BASE_CONFIG,
    ))
    credentials = _extract_redsky_credentials(warm_up)

    to_scrape = [
        Request(
            "https://redsky.target.com/redsky_aggregations/v1/web/store_location_v1?" + urlencode({
                "key": credentials["key"],
                "visitor_id": credentials["visitor_id"],
                "store_id": store_id,
                "channel": "WEB",
                "page": "/c/root",
            }),
            session=session,
            **BASE_CONFIG,
        )
        for store_id in store_ids
    ]

    stores = []
    async for response in CLIENT.fetch_many(to_scrape):
        stores.append(parse_store_locations(response))
    return stores



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
