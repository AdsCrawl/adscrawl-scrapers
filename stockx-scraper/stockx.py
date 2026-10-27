# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for StockX.com adapted from the upstream Scrapfly example:
https://scrapfly.io/blog/how-to-scrape-stockx/

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import json
import math
import os
from nested_lookup import nested_lookup
from typing import Dict, List

from loguru import logger as log
from adscrawl_scrapers import Response, Request, ScraperClient

CLIENT = ScraperClient()
BASE_CONFIG = {


    'render': True,
    'autoScroll': True,
    'countryCode': "US"
}


def parse_nextjs(result: Response) -> Dict:
    """extract nextjs cache from page"""
    data = result.selector.css("script#__NEXT_DATA__::text").get()
    if not data:
        data = result.selector.css("script[data-name=query]::text").get()
        data = data.split("=", 1)[-1].strip().strip(";")
    data = json.loads(data)
    return data


def parse_pricing(result: Response, sku: str = None) -> Dict:
    """extractproduct data from xhr responses"""
    _xhr_calls = result.network
    json_calls = []
    for xhr in _xhr_calls:
        if xhr["response"]["body"] is None:
            continue
        try:
            data = json.loads(xhr["response"]["body"])
        except json.JSONDecodeError:
            continue
        json_calls.append(data)

    for xhr in json_calls:
        if "data" not in xhr or "product" not in xhr["data"] or "uuid" not in xhr["data"]["product"]:
            continue
        if sku == xhr["data"]["product"]["uuid"]:
            data = xhr["data"]["product"]
            return {
                "minimumBid": data["minimumBid"],
                "market": data["market"],
                "variants": data["variants"],
            }
    return None



@managed
async def scrape_product(url: str) -> Dict:
    """scrape a single stockx product page for product data"""
    log.info("scraping product {}", url)
    result = await CLIENT.fetch(Request(
        url, **BASE_CONFIG, waitMs=5000, waitForSelector="//h2[@data-testid='trade-box-buy-amount']"
    ))
    data = parse_nextjs(result)
    # extract all products datasets from page cache
    products = nested_lookup("product", data)
    # find the current product dataset
    try:
        # the page cache also holds partial copies of the product without a urlKey: skip those
        product = next(p for p in products if p.get("urlKey") and p["urlKey"] in result.url)
        product["pricing"] = parse_pricing(result, product["id"])
    except StopIteration:
        raise ValueError("Could not find product dataset in page cache", result.url)
    return product


@managed
async def scrape_search(url: str, max_pages: int = 25) -> List[Dict]:
    """Scrape StockX search"""
    log.info("scraping search {}", url)
    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    # parse first page for product search data and total amount of pages:
    data = parse_nextjs(first_page)
    _first_page_results = nested_lookup("results", data)[0]
    _paging_info = _first_page_results["pageInfo"]
    total_pages = _paging_info["pageCount"] or math.ceil(_paging_info["total"] / _paging_info["limit"])
    if max_pages < total_pages:
        total_pages = max_pages

    product_previews = [edge["node"] for edge in _first_page_results["edges"]]

    # then scrape other pages concurrently:
    log.info("scraping search {} pagination ({} more pages)", url, total_pages - 1)
    _other_pages = [
        Request(f"{first_page.url}&page={page}", **BASE_CONFIG)
        for page in range(2, total_pages + 1)
    ]
    async for result in CLIENT.fetch_many(_other_pages):
        data = parse_nextjs(result)
        _page_results = nested_lookup("results", data)[0]
        product_previews.extend([edge["node"] for edge in _page_results["edges"]])
    log.info("scraped {} products from {}", len(product_previews), url)
    return product_previews
