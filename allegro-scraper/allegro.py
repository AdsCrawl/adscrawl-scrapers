# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for Allegro.pl adapted from the upstream Scrapfly example:
https://scrapfly.io/blog/posts/how-to-scrape-allegro

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/
"""
from adscrawl_scrapers import managed

import os
import json
import re
import urllib.parse
from pathlib import Path
from uuid import uuid4
from loguru import logger as log
from typing import List, Dict, TypedDict
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()
BASE_CONFIG = {
    # allegro.pl is the Polish marketplace. A US exit gets HTTP 403 on both
    # the offer page and the listing page before any HTML is parsed. PL is
    # the site's own country, not a preference over US for other retailers.
    # The 2026-11-03 US retest still returned HTTP 403 with countryCode=PL.
    'countryCode': "PL",
    'locale': "pl-PL",
    'render': True,
}
_ALLEGRO_HEADERS = {
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}
_LISTING_MARKERS = ("searchMeta", "formattedPrice", "__listing_StoreState")

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


def parse_search(result: Response) -> List[Dict]:
    """Parse Allegro search page for product listings"""
    # Find the main JSON data with search results
    search_meta_json = result.selector.xpath(
        '//script[@data-serialize-box-id and contains(text(), "searchMeta")]/text()'
    ).get()
    if not search_meta_json:
        log.error("Could not find searchMeta JSON")
        return {"products": [], "total_pages": 0}

    search_meta = json.loads(search_meta_json)
    last_page = search_meta.get("props", {}).get("searchMeta", {}).get("lastAvailablePage", 1)
    total_count = search_meta.get("props", {}).get("searchMeta", {}).get("totalCount", 0)
    # Find the product listing JSON
    listing_json = result.selector.xpath(
        '//script[contains(text(), "__listing_StoreState")]/text()'
    ).get()

    products = []
    if listing_json:
        listing_data = json.loads(listing_json)
        elements = listing_data.get("__listing_StoreState", {}).get("items", {}).get("elements", [])

        for item in elements:
            # Skip promoted/sponsored items if needed  (Advertised product)
            if item.get("context") == "PROMOTED":
                continue

            # Extract product data
            price_info = item.get("price", {})
            main_price = price_info.get("mainPrice", {}) if price_info else {}

            products.append({
                "product_id": item.get("id", ""),
                "offer_id": item.get("eventData", {}).get("offer_id", ""),
                "title": item.get("alt", ""),
                "price": main_price.get("amount", ""),
                "currency": main_price.get("currency", "PLN"),
                "url": f"https://allegro.pl/oferta/{item.get('eventData', {}).get('offer_id', '')}",
                "image": item.get("mainThumbnail", ""),
                "seller": item.get("seller", {}).get("login", ""),
                "delivery_info": item.get("deliveryInfo", {}).get("text", "")
            })

    log.info(f"Parsed {len(products)} products from search page")
    data = {
        "products": products,
        "scraped_pages": 1,
        "products_count": len(products),
        "total_pages": last_page,
        "total_count": total_count,
    }
    return data


def _allegro_block_message(response: Response, url: str) -> str:
    return (
        f"allegro.pl returned HTTP {response.status_code} for {url} on the PL route. "
        "US and PL exits, locale pl-PL, a Polish Accept-Language, a Windows user agent, "
        "Referer, document Sec-Fetch headers, and a homepage warmup were tried. "
        "Tip5 (5632fb6) returned HTTP 403 for the homepage, so that session was not reused, "
        "and the listing on a fresh session was still HTTP 403. "
        "Request has no residential-proxy field. Further header changes will not clear this block. "
        "This is an anti-bot block, not an empty catalog, and it is not a live pass."
    )


def _document_has_listing(response: Response) -> bool:
    html = response.content or ""
    return any(marker in html for marker in _LISTING_MARKERS)


async def _drop_allegro_session(session: str) -> None:
    try:
        await CLIENT.close_session(session)
    except ScrapeError as error:
        log.warning(f"allegro.pl session close failed ({error.code}); continuing on a new session")


def _cookie_header(response: Response) -> str:
    parts = []
    for cookie in response.cookies or []:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None and value != "":
            parts.append(f"{name}={value}")
    return "; ".join(parts)


async def _open_allegro(url: str, session: str, *, referer: bool, cookies: str = "", **extra) -> Response:
    """rendered PL navigation. Listings stay on waitUntil=load. Offer pages pass commit."""
    headers = dict(_ALLEGRO_HEADERS)
    headers["Sec-Fetch-Site"] = "same-origin" if referer else "none"
    if referer:
        headers["Referer"] = "https://allegro.pl/"
    if cookies:
        headers["Cookie"] = cookies
    headers.update(extra.pop("headers", {}) or {})
    extra.setdefault("timeoutMs", 90000)
    extra.setdefault("waitUntil", "load")
    return await CLIENT.fetch(Request(
        url,
        session=session,
        headers=headers,
        raiseOnHttpError=False,
        userAgentOs="windows",
        **BASE_CONFIG,
        **extra,
    ))


async def _warm_allegro(session: str) -> tuple[str, str]:
    """homepage on its own browser. Return (session, cookie header) for the listing.

    A 200 homepage keeps that browser and its cookie jar. A 403 or a timeout
    closes it. Reusing the block cookie was the tip4 warmup. There is no
    residential-proxy field on Request; countryCode stays PL.
    """
    try:
        page = await _open_allegro("https://allegro.pl/", session, referer=False, timeoutMs=25000)
    except ScrapeError as error:
        log.warning(f"allegro.pl homepage warmup did not finish ({error.code}); listing will use a new session")
        await _drop_allegro_session(session)
        return uuid4().hex, ""
    if page.status_code >= 400 and not _document_has_listing(page):
        log.warning(
            f"allegro.pl homepage returned HTTP {page.status_code}; not reusing that browser for the listing"
        )
        await _drop_allegro_session(session)
        return uuid4().hex, ""
    return session, _cookie_header(page)


async def _fetch_allegro(url: str, session: str, cookies: str = "", **extra) -> Response:
    """one rendered PL request, retried once on a timeout with a new browser.

    A 403 body that actually contains listing JSON is parsed. A 403 block page
    is raised, not turned into an empty catalog.
    """
    try:
        response = await _open_allegro(url, session, referer=True, cookies=cookies, **extra)
    except ScrapeError as error:
        if error.code not in {"TIMEOUT", "BROWSER_ERROR", "CLEANUP_FAILED"}:
            raise
        if error.code == "CLEANUP_FAILED":
            await CLIENT.reset()
        log.warning(f"allegro.pl {url} failed ({error.code}); one fresh session")
        await _drop_allegro_session(session)
        response = await _open_allegro(url, uuid4().hex, referer=True, **extra)
    if response.status_code >= 400 and not _document_has_listing(response):
        raise ScrapeError(_allegro_block_message(response, url), response=response, code="HTTP_ERROR")
    if response.status_code >= 400:
        log.warning(
            f"allegro.pl returned HTTP {response.status_code} for {url} but the body contains listing data; parsing it"
        )
    return response


@managed
async def scrape_search(query: str, max_pages: int = 3, scrape_all_pages: bool = False) -> List[Dict]:
    """
    Scrape Allegro search pages for product listings

    Args:
        query: Search query string
        max_pages: Maximum number of pages to scrape (default: 3)
        scrape_all_pages: If True, scrape all available pages (overrides max_pages)
    """
    encoded_query = urllib.parse.quote(query)
    base_url = f"https://allegro.pl/listing?string={encoded_query}"
    log.info(f"scraping base url {base_url}")
    session, cookies = await _warm_allegro(uuid4().hex)
    try:
        first_page = await _fetch_allegro(base_url, session, cookies)

        # Parse first page
        first_page_data = parse_search(first_page)
        search_results = first_page_data["products"]
        total_pages = first_page_data["total_pages"]
        log.info(f"Found {total_pages} total pages with {first_page_data['total_count']} total products")

        if scrape_all_pages:
            pages_to_scrape = total_pages
        else:
            pages_to_scrape = min(max_pages, total_pages)

        log.info(f"Scraping {pages_to_scrape - 1} additional pages (total: {pages_to_scrape})")
        scraped_pages = 0
        if pages_to_scrape > 1:
            log.info(f"Scraping {pages_to_scrape - 1} additional pages")
            for page in range(2, pages_to_scrape + 1):
                try:
                    result = await _fetch_allegro(f"{base_url}&p={page}", session, cookies)
                except ScrapeError as error:
                    log.error(f"allegro listing page {page} failed: {error}")
                    break
                try:
                    page_data = parse_search(result)
                    search_results.extend(page_data["products"])
                    scraped_pages += 1
                except Exception as e:
                    log.error(f"Error parsing search page: {e}")
                    continue
            log.success(f"Scraped {len(search_results)} total products from {scraped_pages} pages")
        data = {
            "products": search_results,
            "scraped_pages": scraped_pages,
            "products_count": len(search_results),
            "total_pages": total_pages,
            "total_count": first_page_data["total_count"],
        }
        return data
    finally:
        await _drop_allegro_session(session)

def parse_product(result: Response) -> Dict:
    """Parse Allegro product page for product data"""
    sel = result.selector

    # pricing
    price_json = sel.xpath('//script[@data-serialize-box-id and contains(text(), "formattedPrice")]/text()').get()
    price_data = json.loads(price_json) if price_json else None
    if price_data is not None:
        price_data = {
            "formattedPrice": price_data.get("price", {}).get("formattedPrice", None),
            "formattedPriceParts": price_data.get("price", {}).get("formattedPriceParts", None),
            "currency": price_data.get("price", {}).get("currency", None),
            "coupon": price_data.get("coupon", None)
        }

    # images: the offer gallery lives under "galleryItems" (another box's "gallery" key holds review photos)
    gallery_images = None
    gallery_json = sel.xpath('//script[@data-serialize-box-id and contains(text(), "galleryItems")]/text()').get()
    gallery_data = json.loads(gallery_json) if gallery_json else None
    if gallery_data is not None:
        gallery_images = [item["thumbnail"] for item in gallery_data.get("galleryItems", []) if item.get("thumbnail")]

    # fallback to html parsing: gallery thumbnails
    if not gallery_images:
        gallery_images = sel.xpath('//*[@data-box-name="showoffer.gallery"]//img[contains(@src, "/s128/")]/@src').getall()

    # seller info
    seller_json = sel.xpath('//script[@data-serialize-box-id and contains(text(), "sellerName")]/text()').get()
    seller_data = json.loads(seller_json) if seller_json else {}

    # review data
    review_script = sel.xpath('//script[contains(text(), "aggregateRating")]/text()').get()
    review_data = json.loads(review_script) if review_script else None
    rating = review_data.get("aggregateRating", None) if review_data else None
    reviews = review_data.get("review", None) if review_data else None
    if reviews:
        normalized_reviews = []
        for review in reviews:
            rating_value = review.get("reviewRating", {}).get("ratingValue")
            normalized_reviews.append({
                "author": review.get("author", {}).get("name"),
                "rating": int(rating_value) if rating_value else None,
                "content": review.get("reviewBody"),
                "datePublished": review.get("datePublished"),
            })
        reviews = normalized_reviews

    # specifications
    specifications = []
    for spec_item in sel.xpath("//ul/li[b]"):
        key = spec_item.xpath(".//b/text()").get()
        value = spec_item.xpath("./text()").get()
        if key and value:
            specifications.append(
                {"key": key.strip().rstrip(":"), "value": value.strip()}
            )

    # shipping info
    shipping_price = None
    shipping_elem = sel.xpath('//button[@data-analytics-view-label="ShippingInfo"]//span/text()').get()
    if shipping_elem:
        shipping_text = shipping_elem.strip()
        # Extract just the price value
        price_match = re.search(r"(\d+[.,]\d+)", shipping_text)
        shipping_price = price_match.group(1) if price_match else None

    # return policy
    return_elem = sel.xpath('//button[@data-analytics-view-label="TrustInfo"]//div/text()').get()
    return_policy = return_elem.strip() if return_elem else None

    # final product data
    parsed_data = {
        "title": sel.xpath('//meta[@property="og:title"]/@content').get(""),
        "price": price_data,
        "images": gallery_images,
        "shipping_info": {
            "shipping_price": shipping_price if shipping_price else None,
            "return_policy": return_policy,
        },
        "rating": rating,
        "specifications": specifications,
        "seller":{
            "name": seller_data.get("sellerName", None),
            "rating": seller_data.get("sellerRating", None),
            "isSuperSeller": seller_data.get("isSuperSeller", None),
            "url": seller_data.get("sellerListingUrl", None)
        },
        "reviews": reviews,
        "allegro_smart_badge": bool(sel.xpath('//img[contains(@src, "smart")]').get())
    }

    return parsed_data


@managed
async def scrape_product(urls: list[str]) -> Dict:
    """scrape Allegro product pages. A block-page 403 is raised, not returned as an empty list."""
    data = []
    session, cookies = await _warm_allegro(uuid4().hex)
    try:
        for url in urls:
            # Tip5 timed out twice at the outer 90s budget. waitUntil=load plus a
            # request-level waitForSelector uses that same budget again after goto,
            # so a blocked document dies as TIMEOUT. commit returns the status page.
            # The price script is a short optional wait. No new request headers.
            response = await _fetch_allegro(
                url,
                session,
                cookies,
                waitUntil="commit",
                timeoutMs=60000,
                actions=[
                    {
                        "type": "waitForSelector",
                        "selector": "script[data-serialize-box-id]",
                        "timeoutMs": 15000,
                        "optional": True,
                    },
                ],
            )
            try:
                data.append(parse_product(response))
            except Exception as e:
                log.error(f"Error parsing Allegro product: {e}")
                continue
    finally:
        await _drop_allegro_session(session)
    log.success(f"scraped {len(data)} products from product pages")
    return data
