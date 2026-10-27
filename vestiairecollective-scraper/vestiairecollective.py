# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for vestiairecollective.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import json
from typing import Dict, List
from pathlib import Path
from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError


CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass vestiairecollective.com web scraping blocking
    'countryCode': "US",
}


output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


def find_hidden_data(result: Response) -> dict:
    """extract hidden NEXT_DATA from page html"""
    data = result.selector.css("script#__NEXT_DATA__::text").get()
    data = json.loads(data)
    return data


def parse_xhr_call(result: Response) -> List[Dict]:
    """extract JSON data from xhr_calls"""
    _xhr_calls = result.network
    # extract the search xhr call (the one that already has its answer)
    search_calls = [call for call in _xhr_calls if "search" in call["url"] and (call.get("response") or {}).get("body")]
    if not search_calls:
        # the page was captured before it asked its search API, or the URL is not a search page
        raise ValueError(
            f"vestiairecollective.com search page did not load its product search results: {result.url}"
        )
    search_call = search_calls[0]
    # extract the product listings data from the first search page
    data = json.loads(search_call["response"]["body"])
    result = {
        "headers": search_call["headers"],
        "payload": json.loads(search_call["body"]),
        "total_pages": data["paginationStats"]["totalPages"],
        "data": data["items"],
    }
    return result


@managed
async def send_api_request(headers, payload, offset) -> List[Dict]:
    """send a POST request the search API"""
    # change the offest to control the number of products to retrieve
    payload["pagination"]["offset"] = offset
    # send a POST request to the search API
    response = await CLIENT.fetch(
        Request(
            url="https://search.vestiairecollective.com/v1/product/search",
            headers=headers,
            body=json.dumps(payload),
            countryCode="US",
            method="POST",
            )
    )
    return response


def parse_search_api(result: Response) -> List[Dict]:
    """extract JSON data from the search API response"""
    data = json.loads(result.content)
    return data["items"]


@managed
async def scrape_products(urls: List[str]) -> dict:
    """scrape vestiairecollective.com product pages for product data"""
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    products = []
    async for response in CLIENT.fetch_many(to_scrape):
        if isinstance(response, ScrapeError):  # a failed request comes back as the error object, not raised
            log.error(f"skipping a product page that could not be scraped: {response}")
            continue
        try:
            data = find_hidden_data(response)
            products.append(data["props"]["pageProps"]["product"])
        except Exception as e:
            log.error(f"An error occurred while parsing the product page. Is the listing expired?: {e}")
    log.success(f"scraped {len(products)} product listings from product pages")
    return products

@managed
async def retry_failure(url: str, _retries: int = 0):
    """retry failed requests with a maximum number of retries"""
    max_retries = 3
    try:
        response = await CLIENT.fetch(
            Request(
                url,
                **BASE_CONFIG,
                render=True,
                actions=[
                    {"type": 'waitForSelector', 'selector': "[data-cy='productCard__productLink']", 'timeoutMs': 15000, "optional": True}
                ],
            )
        )
        if response.status_code != 200:
            if _retries < max_retries:
                log.debug("Retrying failed request")
                return await retry_failure(url, _retries=_retries + 1)
            else:
                raise Exception("Unable to scrape first search page, max retries exceeded")
        return response
    except Exception as e:
        if _retries < max_retries:
            log.debug("Retrying failed request")
            return await retry_failure(url, _retries=_retries + 1)
        else:
            raise Exception("Unable to scrape first search page, max retries exceeded")


@managed
async def scrape_search(url: str, max_pages: int = 10) -> List[Dict]:
    log.info(f"scraping search page {url}")
    # first, scrape the first search page while enabling render_js to capture the xhr calls
    result_first_page = await retry_failure(url)
    # then, parse the first page response to get the headers, payload, data and the number of total pages
    first_page_api_result = parse_xhr_call(result_first_page)
    headers = first_page_api_result["headers"]
    payload = first_page_api_result["payload"]
    results = first_page_api_result["data"]
    total_pages = first_page_api_result["total_pages"]

    # find total page count
    if max_pages and max_pages < total_pages:
        total_pages = max_pages
    total_products = total_pages * 48  # each page contains 48 listings

    # next, scrape the remaining search pages directly from the API
    log.info(f"scraping search pagination, remaining ({total_pages - 1}) more pages")
    for offset in range(48, total_products, 48):
        try:
            result = await send_api_request(headers, payload, offset)
            results.extend(parse_search_api(result))
        except Exception as e:
            log.debug(f"Error occured while requesting search API: {e}")
            pass
    log.success(f"scraped {len(results)} product listings from search pages")
    return results
