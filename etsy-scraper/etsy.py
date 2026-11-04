# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for etsy.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import math
import json
import uuid
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError
from typing import Dict, List
from loguru import logger as log

CLIENT = ScraperClient()

BASE_CONFIG = {
    # Etsy answers a cold document with HTTP 403. The SDK fingerprint is the
    # desktop OS below; there is no separate stealth switch. The homepage in
    # the same browser still runs first so a later navigation can send its cookies.
    "countryCode": "US",
    "locale": "en-US",
    "userAgentOs": "windows",
    "render": True,
}
_HOME = "https://www.etsy.com/"
_DOCUMENT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}
# One new browser. HTTP 403 is included because the first exit can be blocked.
_RETRYABLE = {
    "HTTP_ERROR",
    "SELECTOR_NOT_FOUND",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_CONNECTION_CLOSED",
    "ERR_HTTP2_PROTOCOL_ERROR",
    "CONNECT_FAILED",
    "BROWSER_ERROR",
    "TIMEOUT",
}


def _challenge(response: Response) -> bool:
    """A 200 interstitial is not a storefront. DataDome's script URL is on real pages too, so the title and the final URL are the signal."""
    title = " ".join(response.selector.css("title::text").getall()).strip().lower()
    if any(phrase in title for phrase in (
        "access denied", "just a moment", "attention required",
        "pardon our interruption", "robot check",
    )):
        return True
    url = (response.url or "").lower()
    return "captcha-delivery" in url or "/blocked" in url


# Applied only after the probe. On a 403 page, wait_for_selector would sit until
# timeoutMs and the same-session reload would never run.
_READY = {"waitForSelector", "autoScroll", "actions", "waitForResponse", "javascript"}


def _usable(response: Response) -> bool:
    """A solved interstitial keeps the original 403 on the navigation response.

    runtime records that status and does not update it when the document is
    rewritten. A large page with a normal title is the storefront. A known
    challenge title is not, whatever the status is.
    """
    if _challenge(response):
        return False
    if response.status_code < 400:
        return True
    title = " ".join(response.selector.css("title::text").getall()).strip()
    return bool(title) and len(response.content or "") > 1500


async def _navigate(session: str, url: str, referer: str = None, **extra) -> Response:
    """Open a document and let a 403 interstitial run.

    The fetch raises HTTP_ERROR at the navigation status, before waitMs, when
    raiseOnHttpError stays on. That is why the homepage warm-up still failed
    live: the challenge script never ran. Opt out, wait, and reload once in
    this session so the second request can send the cookie the first one set.
    """
    headers = dict(_DOCUMENT_HEADERS)
    if referer:
        headers["Referer"] = referer
    probe = {key: value for key, value in extra.items() if key not in _READY}
    wait_ms = probe.pop("waitMs", 4_000)
    timeout_ms = probe.pop("timeoutMs", 60_000)

    async def load(**more) -> Response:
        return await CLIENT.fetch(Request(
            url,
            session=session,
            headers=headers,
            raiseOnHttpError=False,
            waitMs=wait_ms,
            timeoutMs=timeout_ms,
            **BASE_CONFIG,
            **probe,
            **more,
        ))

    page = await load()
    if not _usable(page):
        log.info(f"reloading {url} once in the same session after HTTP {page.status_code}")
        page = await load()
    if not _usable(page):
        raise ScrapeError(
            f"Target returned HTTP {page.status_code}",
            response=page,
            code="HTTP_ERROR",
        )
    if not _READY.intersection(extra):
        return page
    ready = await CLIENT.fetch(Request(
        url,
        session=session,
        headers=headers,
        raiseOnHttpError=False,
        timeoutMs=timeout_ms,
        **BASE_CONFIG,
        **extra,
    ))
    if not _usable(ready):
        raise ScrapeError(
            f"Target returned HTTP {ready.status_code}",
            response=ready,
            code="HTTP_ERROR",
        )
    return ready


async def _fetch_document(url: str, **extra) -> Response:
    """Homepage, then the document, in one named session.

    The session is closed before a retry. At concurrency 1 a second named
    session cannot be created while the blocked browser is still held.
    """
    last = None
    for attempt in range(2):
        session = f"etsy-{uuid.uuid4().hex}"
        try:
            await _navigate(session, _HOME)
            return await _navigate(session, url, referer=_HOME, **extra)
        except ScrapeError as error:
            last = error
            if error.code not in _RETRYABLE or attempt == 1:
                raise
            log.warning(f"retrying {url} once after {error.code}")
        finally:
            await CLIENT.close_session(session)
    raise last


def strip_text(text):
    """remove extra spaces while handling None values"""
    if text != None:
        text = text.strip()
    return text


def parse_search(response: Response) -> Dict:
    """parse data from Etsy search pages"""
    selector = response.selector
    data = []
    script = json.loads(selector.xpath("//script[@type='application/ld+json']/text()").get())
    # get the total number of pages
    total_listings = script["numberOfItems"]
    total_pages = math.ceil(total_listings / 48)
    for product in selector.xpath("//div[@data-search-results-lg]/ul/li[div[@data-appears-component-name]]"):
        link = product.xpath(".//a[contains(@class, 'v2-listing-card')]/@href").get()
        rate = product.xpath(".//clg-static-review-stars/@rating").get()
        number_of_reviews = strip_text(product.xpath(".//clg-static-review-stars/@review-count-text").get())
        if number_of_reviews:
            number_of_reviews = number_of_reviews.replace("(", "").replace(")", "").replace(",", "")
            number_of_reviews = (
                int(float(number_of_reviews.replace("k", "")) * 1000)
                if "k" in number_of_reviews
                else number_of_reviews
            )
        price = product.xpath(".//span[@class='currency-value']/text()").get()
        original_price = product.xpath(".//span[contains(text(),'Original Price')]/text()").get()
        discount = strip_text(product.xpath(".//span[contains(text(),'off')]/text()").get())
        seller = product.xpath(".//span[contains(text(),'From shop')]/text()").get()
        currency = product.xpath(".//span[@class='currency-symbol']/text()").get()
        data.append(
            {
                "productLink": "/".join(link.split("/")[:5]) if link else None,
                "productTitle": strip_text(
                    product.xpath(".//h3[contains(@class, 'v2-listing-card__titl')]/@title").get()
                ),
                "productImage": product.xpath("//img[@data-listing-card-listing-image]/@src").get(),
                "seller": seller.replace("From shop ", "") if seller else None,
                "listingType": (
                    "Paid listing" if product.xpath(".//span[@data-ad-label='Ad by Etsy seller']") else "Free listing"
                ),
                "productRate": float(rate.strip()) if rate else None,
                "numberOfReviews": int(number_of_reviews) if number_of_reviews else None,
                "freeShipping": (
                    "Yes" if product.xpath(".//span[contains(text(),'Free shipping')]/text()").get() else "No"
                ),
                "productPrice": float(price.replace(",", "")) if price else None,
                "priceCurrency": currency,
                "originalPrice": float(original_price.split(currency)[-1].strip()) if original_price else "No discount",
                "discount": discount if discount else "No discount",
            }
        )
    return {"search_data": data, "total_pages": total_pages}


def parse_product_page(response: Response) -> Dict:
    """parse hidden product data from product pages"""
    selector = response.selector
    script = selector.xpath("//script[contains(text(),'offers')]/text()").get()
    if not script:
        log.warning(f"Could not find product data script on {response.url}")
        return {}
    data = json.loads(script)
    return data


def parse_shop_page(response: Response) -> Dict:
    """parse hidden shop data from shop pages"""
    selector = response.selector
    script = selector.xpath("//script[contains(text(),'itemListElement')]/text()").get()
    if not script:
        log.warning(f"Could not find shop data script on {response.url}")
        return {}
    try:
        data = json.loads(script)
        return data
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON from shop page {response.url}: {e}")
        return {}

@managed
async def scrape_search(url: str, max_pages: int = None) -> List[Dict]:
    """scrape product listing data from Etsy search pages"""
    log.info("scraping the first search page")
    # etsy search pages are dynamic; the browser has to render them
    first_page = await _fetch_document(
        url,
        waitForSelector="//div[@data-search-pagination]",
        autoScroll=True,
    )
    data = parse_search(first_page)
    search_data = data["search_data"]

    # get the number of total pages to scrape
    total_pages = data["total_pages"]
    if max_pages and max_pages < total_pages:
        total_pages = max_pages

    log.info(f"scraping search pagination ({total_pages - 1} more pages)")
    for page_number in range(2, total_pages + 1):
        try:
            response = await _fetch_document(
                url + f"&page={page_number}",
                waitForSelector="//div[@data-search-pagination]",
            )
            data = parse_search(response)
            search_data.extend(data["search_data"])
        except Exception as e:
            log.error(f"failed to scrape search page: {e}")
            pass
    log.success(f"scraped {len(search_data)} product listings from search")
    return search_data


@managed
async def scrape_product(urls: List[str]) -> List[Dict]:
    """scrape trustpilot company pages"""
    products = []
    for url in urls:
        products.append(parse_product_page(await _fetch_document(url)))
    log.success(f"scraped {len(products)} product listings from product pages")
    return products


@managed
async def scrape_shop(urls: List[str]) -> List[Dict]:
    shops = []
    for url in urls:
        response = await _fetch_document(url)
        data = parse_shop_page(response)
        data["url"] = response.url
        shops.append(data)
    log.success(f"scraped {len(shops)} shops from shop pages")
    return shops
