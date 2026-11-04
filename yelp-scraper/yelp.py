# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for yelp.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import uuid
import json
import math
import base64
import jmespath
from html import unescape
from typing import Dict, List, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse
from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    # A document navigation is HTTP 403 even after a same-session reload.
    # Pages are read with an in-page fetch. The review POST uses the same
    # browser so it sends the page cookies. The SDK fingerprint is the OS below.
    "countryCode": "US",
    "locale": "en-US",
    "userAgentOs": "windows",
    "render": True,
}
_HOME = "https://www.yelp.com/"
_DOCUMENT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}
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
    title = " ".join(response.selector.css("title::text").getall()).strip().lower()
    if any(phrase in title for phrase in (
        "access denied", "just a moment", "attention required",
        "pardon our interruption", "robot check",
    )):
        return True
    url = (response.url or "").lower()
    return "captcha-delivery" in url or "/blocked" in url


async def _get(session: str, url: str, **extra) -> Response:
    """Read a Yelp document without navigating the tab to it.

    The homepage and the reload both still returned HTTP 403. Selectors are
    ignored: an in-page fetch returns the response body, which is what the
    parsers read (apollo state, biz id, the business markup).
    """
    extra.pop("waitForSelector", None)
    extra.pop("autoScroll", None)
    extra.pop("actions", None)
    extra.pop("waitMs", None)
    page = await CLIENT.fetch(Request(
        url,
        session=session,
        headers={**_DOCUMENT_HEADERS, "Referer": _HOME},
        binary=True,
        timeoutMs=45_000,
        raiseOnHttpError=False,
        **BASE_CONFIG,
        **extra,
    ))
    if page.status_code >= 400 or _challenge(page):
        raise ScrapeError(
            f"Target returned HTTP {page.status_code}",
            response=page,
            code="HTTP_ERROR",
        )
    return page


async def _attempt(work):
    """Run `work(session)` in a fresh named session, once more if it is blocked or the tunnel drops.

    The session is closed before the retry so concurrency 1 can open the next browser.
    """
    last = None
    for attempt in range(2):
        session = f"yelp-{uuid.uuid4().hex}"
        try:
            return await work(session)
        except ScrapeError as error:
            last = error
            if error.code not in _RETRYABLE or attempt == 1:
                raise
            log.warning(f"retrying yelp once after {error.code}")
        finally:
            await CLIENT.close_session(session)
    raise last


class Review(TypedDict):
    id: str
    userId: str
    business: dict
    user: dict
    comment: dict
    rating: int
    # and more


def parse_page(response: Response):
    """parse business data from yelp business pages"""
    sel = response.selector
    xpath = lambda xp: sel.xpath(xp).get(default="").strip()
    open_hours = {}
    for day in sel.xpath('//th/p[contains(@class,"day-of-the-week")]'):
        name = day.xpath("text()").get().strip()
        value = day.xpath("../following-sibling::td//p/text()").get().strip()
        open_hours[name.lower()] = value

    return dict(
        name=xpath("//h1/text()"),
        website=xpath('//p[contains(text(),"Business website")]/following-sibling::p/a/text()'),
        phone=xpath('//p[contains(text(),"Phone number")]/following-sibling::p/text()'),
        address=xpath('//a[contains(text(),"Get Directions")]/../following-sibling::p/text()'),
        logo=xpath('//img[contains(@class,"businessLogo")]/@src'),
        claim_status="".join(sel.xpath('//span[span[contains(@class,"claim")]]/text()').getall()).strip().lower(),
        open_hours=open_hours,
    )


def parse_business_id(response: Response):
    """parse the business id from yelp business pages"""
    selector = response.selector
    business_id = selector.css('meta[name="yelp-biz-id"]::attr(content)').get()
    return business_id


def parse_review_data(response: Response):
    """parse review data from the JSON response"""
    data = json.loads(response.content)
    reviews = data[0]["data"]["business"]["reviews"]["edges"]
    parsed_reviews = []
    for review in reviews:
        result = jmespath.search(
            """{
            encid: encid,
            text: text.{full: full, language: language},
            rating: rating,
            feedback: feedback.{coolCount: coolCount, funnyCount: funnyCount, usefulCount: usefulCount},
            author: author.{encid: encid, displayName: displayName, displayLocation: displayLocation, reviewCount: reviewCount, friendCount: friendCount, businessPhotoCount: businessPhotoCount},
            business: business.{encid: encid, alias: alias, name: name},
            createdAt: createdAt.utcDateTime,
            businessPhotos: businessPhotos[].{encid: encid, photoUrl: photoUrl.url, caption: caption, helpfulCount: helpfulCount},
            businessVideos: businessVideos,
            availableReactions: availableReactionsContainer.availableReactions[].{displayText: displayText, reactionType: reactionType, count: count}
            }""",
            review["node"],
        )
        parsed_reviews.append(result)
    total_reviews = data[0]["data"]["business"]["reviewCount"]
    return {"reviews": parsed_reviews, "total_reviews": total_reviews}


def parse_apollo_businesses(response: Response) -> Dict[str, Dict]:
    """parse the businesses of a search page from its apollo cache (<script data-apollo-state>), by business id"""
    script = response.selector.xpath("//script[@data-apollo-state]/text()").get() or ""
    # the cache is HTML-escaped JSON inside an HTML comment
    script = unescape(script).strip().removeprefix("<!--").removesuffix("-->")
    cache = json.loads(script) if script else {}

    def resolve(value):
        """apollo stores nested objects as {"__ref": "Type:id"} references to other cache entries"""
        if isinstance(value, dict):
            if "__ref" in value:
                return resolve(cache.get(value["__ref"], {}))
            return {key: resolve(val) for key, val in value.items()}
        if isinstance(value, list):
            return [resolve(val) for val in value]
        return value

    return {key.split(":", 1)[1]: resolve(value) for key, value in cache.items() if key.startswith("Business:")}


def business_summary(business: Dict, result: Dict, location: str) -> Dict:
    """the searchResultBusiness fields of a search result, from its apollo cache business entry"""
    address = (business.get("location") or {}).get("address") or {}
    service_area = (business.get("serviceArea") or {}).get("primaryLocation") or {}
    return {
        "alias": business.get("alias"),
        "alternateNames": business.get("alternateNames") or [],
        "businessUrl": result.get("businessUrl"),
        "categories": [
            {
                "title": category["title"],
                "url": "/search?" + urlencode({"find_desc": category["title"], "find_loc": location}),
            }
            for category in business.get("categories") or []
        ],
        "formattedAddress": address.get("addressLine1") or "",
        "isAd": result.get("isAd", False),
        "name": business.get("name"),
        "neighborhoods": (business.get("location") or {}).get("neighborhoods") or [],
        "parentBusiness": business.get("containerBusiness"),
        "phone": "",  # not in the cache
        "priceRange": business.get("priceRange") or "",
        "ranking": result.get("ranking"),
        "rating": business.get("rating"),
        "renderAdInfo": result.get("renderAdInfo", False),
        "reviewCount": business.get("reviewCount"),
        "serviceArea": service_area.get("formatted"),
        "serviceOfferingsCount": None,
    }


def parse_search(response: Response):
    """parse listing data from the search page's hidden JSON data"""
    search_data = []
    selector = response.selector
    script = selector.xpath("//script[@data-id='react-root-props']/text()").get()
    data = json.loads(script.split("react_root_props = ")[-1].rsplit(";", 1)[0])
    search_page_props = data.get("legacyProps", {}).get("searchAppProps", {}).get("searchPageProps", {})
    total_results = (
        search_page_props.get("paginationInfo", {}).get("totalResults")
        or search_page_props.get("searchContext", {}).get("totalResults")
        or 0
    )
    # organic results come without their business data (searchResultBusiness is null):
    # it is in the page's apollo cache, keyed by business id
    businesses = parse_apollo_businesses(response)
    location = parse_qs(urlparse(response.url).query).get("find_loc", [""])[0]
    for component in search_page_props.get("mainContentComponentsListProps", []):
        if component.get("type") == "themedAds":  # ad carousels repeating the ads listed above them
            continue
        # the result cards are in the sections' props.searchResults (or were the components themselves)
        results = (component.get("props") or {}).get("searchResults") or ([component] if component.get("bizId") else [])
        for result in results:
            if not result.get("bizId"):
                continue
            if result.get("searchResultBusiness") is None and result["bizId"] in businesses:
                result["searchResultBusiness"] = business_summary(businesses[result["bizId"]], result, location)
            if result.get("searchResultBusiness") is None:
                log.warning(f"search result {result['bizId']} has no business data, skipping it")
                continue
            search_data.append(result)
    return {"search_data": search_data, "total_results": total_results}


@managed
async def scrape_pages(urls: List[str]) -> List[Dict]:
    """scrape yelp business pages"""
    # add the business pages to a scraping list
    result = []
    for url in urls:
        async def read(session, page_url=url):
            return await _get(session, page_url)
        result.append(parse_page(await _attempt(read)))
    log.success(f"scraped {len(result)} business pages")
    return result


@managed
async def request_reviews_api(url: str, start_index: int, business_id, session: str = None):
    """request the graphql API for review data"""
    pagionation_data = {"version": 1, "type": "offset", "offset": start_index}
    pagionation_data = json.dumps(pagionation_data)
    after = base64.b64encode(pagionation_data.encode("utf-8")).decode(
        "utf-8"
    )  # decode the pagination values for the payload

    payload = json.dumps(
        [
            {
                "operationName": "GetBusinessReviewFeed",
                "variables": {
                    "encBizId": f"{business_id}",
                    "reviewsPerPage": 10,
                    "selectedReviewEncId": "",
                    "hasSelectedReview": False,
                    "sortBy": "DATE_DESC",
                    "languageCode": "en",
                    "ratings": [5, 4, 3, 2, 1],
                    "isSearching": False,
                    "after": after,  # pagination parameter
                    "isTranslating": False,
                    "translateLanguageCode": "en",
                    "reactionsSourceFlow": "businessPageReviewSection",
                    "minConfidenceLevel": "HIGH_CONFIDENCE",
                    "highlightType": "",
                    "highlightIdentifier": "",
                    "isHighlighting": False,
                },
                "extensions": {
                    "operationType": "query",
                    # static value
                    "documentId": "ef51f33d1b0eccc958dddbf6cde15739c48b34637a00ebe316441031d4bf7681",
                },
            }
        ]
    )

    headers = {
        "authority": "www.yelp.com",
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": "https://www.yelp.com",
        "referer": url,  # main business page URL
        "x-apollo-operation-name": "GetBusinessReviewFeed",
    }
    response = await CLIENT.fetch(
        Request(
            url="https://www.yelp.com/gql/batch",
            headers=headers,
            body=payload,
            method="POST",
            session=session,
            binary=True,
            timeoutMs=45_000,
            countryCode="US",
            locale="en-US",
            userAgentOs="windows",
        )
    )
    return response


@managed
async def scrape_reviews(url: str, max_reviews: int = None) -> List[Review]:
    # first find business ID from business URL
    async def read(session):
        log.info("scraping the business id from the business page")
        response_business = await _get(session, url)
        business_id = parse_business_id(response_business)
        if not business_id:
            raise ScrapeError(
                "Yelp business page did not include a business id",
                response=response_business,
                code="SELECTOR_NOT_FOUND",
            )

        log.info("scraping the first review page")
        # the review POST stays in the business-page session so it sends those cookies
        first_page = await request_reviews_api(
            url=url, business_id=business_id, start_index=1, session=session
        )
        review_data = parse_review_data(first_page)
        reviews = review_data["reviews"]
        total_reviews = review_data["total_reviews"]

        if max_reviews and max_reviews < total_reviews:
            total_reviews = max_reviews

        log.info(f"scraping review pagination, remaining ({total_reviews // 10}) more pages")
        for offset in range(11, total_reviews, 10):
            try:
                response = await request_reviews_api(
                    url=url, business_id=business_id, start_index=offset, session=session
                )
                reviews.extend(parse_review_data(response)["reviews"])
            except Exception as e:
                log.error(f"An error occurred while scraping review pages", e)
                pass
        log.success(f"scraped {len(reviews)} reviews from review pages")
        return reviews

    return await _attempt(read)


@managed
async def scrape_search(keyword: str, location: str, max_pages: int = None):
    """scrape single page of yelp search"""

    def make_search_url(offset):
        base_url = "https://www.yelp.com/search?"
        params = {"find_desc": keyword, "find_loc": location, "start": offset}
        return base_url + urlencode(params)
        # final url example:
        # https://www.yelp.com/search?find_desc=plumbers&find_loc=Seattle%2C+WA&start=1

    async def read(session):
        log.info("scraping the first search page")
        first_page = await _get(session, make_search_url(1))
        data = parse_search(first_page)
        search_data = data["search_data"]
        total_results = data["total_results"]

        total_pages = math.ceil(total_results / 10)  # each page contains 10 results
        if max_pages and max_pages < total_pages:
            total_pages = max_pages

        log.info(f"scraping search pagination, remaining ({total_pages - 1}) more pages")
        for offset in range(11, total_pages * 10, 10):
            try:
                response = await _get(session, make_search_url(offset))
                search_data.extend(parse_search(response)["search_data"])
            except Exception as e:
                log.error(f"An error occurred while scraping search pages", e)
                pass
        log.success(f"scraped {len(search_data)} listings from search pages")
        return search_data

    return await _attempt(read)
