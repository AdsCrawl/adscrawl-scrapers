# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for nordstorm.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import json
import jmespath
from typing import Dict, List
from urllib.parse import urlencode, parse_qs, urlparse
from nested_lookup import nested_lookup
from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass nordstorm.com web scraping blocking
    'countryCode': "US",
    'render': True,
    # domcontentloaded on this site held the navigation until the outer 90s
    # deadline, which cancelled the page before the selector error could say
    # what was missing. Commit returns when the document starts, then the
    # attached-state action waits for the same script the parser reads.
    # Script nodes are not visible, so the action state has to be attached.
    'waitUntil': "commit",
    'timeoutMs': 120_000,
    'actions': [
        {
            "type": "waitForSelector",
            "selector": "xpath=//script[contains(., '__INITIAL_CONFIG__')]",
            "state": "attached",
            "timeoutMs": 45_000,
        },
    ],
}

_RETRYABLE = {"TIMEOUT", "ACTION_FAILED", "SELECTOR_NOT_FOUND"}


async def _fetch(request: Request) -> Response:
    try:
        return await CLIENT.fetch(request)
    except ScrapeError as error:
        if error.code not in _RETRYABLE:
            raise
        log.warning(f"retrying {request.url} once after {error.code}")
        return await CLIENT.fetch(request)


def parse_product(data: dict) -> dict:
    core_product = data["coreProducts"][0]
    npt_parts = [part for part in core_product.get("nptHierarchy", "").split(".") if part]
    reviews = data.get("reviews") or {}
    product = jmespath.search(
        """{
        id: id,
        title: copyProductTitle,
        description: copyDescription,
        features: copyFeatures
        }""",
        data,
    )
    product["type"] = npt_parts[-1].replace("_", " ").title() if npt_parts else None
    product["typeParent"] = npt_parts[-2].replace("_", " ").title() if len(npt_parts) > 1 else None
    product["reviewAverageRating"] = reviews.get("averageRating")
    product["numberOfReviews"] = reviews.get("numberOfReviews")
    product["brand"] = {
        "brandName": data.get("labelDisplayName"),
        "brandUrl": data.get("brandLink"),
        "labelId": data.get("labelId"),
    }
    product["gender"] = (core_product.get("gender") or {}).get("label")
    product["media"] = []
    product["variants"] = {}
    for choice in core_product.get("coreChoices", []):
        product["media"].append(
            {
                "colorCode": choice["coreChoiceId"],
                "colorName": choice.get("displayColorDescription"),
                "urls": [shot["imageUrl"] for shot in choice.get("orderedShots", [])],
            }
        )
        for variant_item in choice.get("items", []):
            sku = variant_item.get("sku") or {}
            sku_id = sku.get("skuId")
            if not sku_id:
                continue
            proposition = (sku.get("propositions") or [{}])[0]
            pricings = proposition.get("pricings") or [{}]
            product["variants"][sku_id] = {
                "id": sku_id,
                "sizeId": (variant_item.get("sizeDimension1") or {}).get("code"),
                "colorId": choice["coreChoiceId"],
                "totalQuantityAvailable": (proposition.get("availability") or {}).get("shipQuantity", 0),
                "price": (pricings[0].get("sellingRetail") or {}).get("price"),
            }
    return product


def update_url_parameter(url, **params):
    """update url query parameter of an url with new values"""
    current_params = parse_qs(urlparse(url).query)
    updated_query_params = urlencode({**current_params, **params}, doseq=True)
    return urlparse(url)._replace(query=updated_query_params).geturl()


def find_hidden_data(result: Response) -> dict:
    """extract hidden web cache from page html"""
    # use XPath to find script tag with data
    data = result.selector.xpath("//script[contains(.,'__INITIAL_CONFIG__')]/text()").get()
    if not data:
        raise ValueError('Nordstrom page configuration is missing; the page may still be loading or require verification')
    data = data.split("=", 1)[-1].strip().strip(";")
    data = json.loads(data)
    return data


@managed
async def scrape_products(urls: List[str]):
    """scrape nordstorm product pages for product data"""
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    products = []
    for request in to_scrape:
        response = await _fetch(request)
        data = find_hidden_data(response)
        entities = data["productDisplay"]["productDisplaysById"]["entities"]
        products.append(parse_product(list(entities.values())[0]))
    log.success(f"scraped {len(products)} product listings from product pages")
    return products


@managed
async def scrape_search(url: str, max_pages: int = 10) -> List[Dict]:
    """Scrape nordstom search pages for product listings"""
    log.info(f"scraping search page {url}")
    first_page = await _fetch(Request(url, **BASE_CONFIG))
    # parse first page for product search data and total amount of pages:
    data = find_hidden_data(first_page)
    _first_page_results = nested_lookup("productResults", data)[0]
    products = list(_first_page_results["productsById"].values())
    paging_info = _first_page_results["query"]
    total_pages = paging_info["pageCount"]

    if max_pages and max_pages < total_pages:
        total_pages = max_pages

    # then scrape the remaining pages, one retry each if the first load times out:
    log.info(f"scraping search pagination, remaining ({total_pages - 1}) more pages")
    _other_pages = [
        Request(update_url_parameter(url, page=page), **BASE_CONFIG) for page in range(2, total_pages + 1)
    ]
    for request in _other_pages:
        result = await _fetch(request)
        data = find_hidden_data(result)
        data = nested_lookup("productResults", data)[0]
        products.extend(list(data["productsById"].values()))
    log.success(f"scraped {len(products)} product listings from search pages")
    return products
