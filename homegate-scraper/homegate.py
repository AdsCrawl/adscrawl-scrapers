# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for homegate.ch.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import re
import os
import json
from adscrawl_scrapers import Request, ScraperClient, Response
from typing import Dict, List
from pathlib import Path
from loguru import logger as log

CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass web scraping blocking
    'render': True
}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


def parse_next_data(response: Response) -> Dict:
    """parse data from script tags"""
    selector = response.selector
    next_data = selector.xpath("//script[contains(text(),'window.__INITIAL_STATE__')]/text()").get()
    if not next_data:
        return
    next_data_json = json.loads(next_data.split("=", 1)[1].strip())

    return next_data_json


def parse_property_page(response: Response) -> Dict:
    """parse property page data from the pinia state"""
    selector = response.selector
    script_content = selector.xpath("//script[contains(., 'window.__PINIA_INITIAL_STATE__')]/text()").get()
    if not script_content:
        return None
    # parse the listing json from pinia state
    pattern = r'window\.__PINIA_INITIAL_STATE__\s*=\s*(\{.+\})\s*$'
    match = re.search(pattern, script_content, re.DOTALL)
    if match is not None:
        data = json.loads(match.group(1))
        listing = data["listing"]["listing"]
        return listing


@managed
async def scrape_properties(urls: List[str]) -> List[Dict]:
    """scrape listing data from homegate proeprty pages"""
    # add the property pages in a scraping list
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    properties = []
    # scrape all property pages concurrently
    async for response in CLIENT.fetch_many(to_scrape):
        if not isinstance(response, Response):
            continue
        try:
            data = parse_property_page(response)
            if data:
                properties.append(data)
            else:
                log.warning(f"expired or empty property page: {response.url}")
        except Exception as e:
            log.warning(f"failed to parse property page {response.url}: {e}")
    log.info(f"scraped {len(properties)} property listings")
    return properties


@managed
async def scrape_search(url: str, scrape_all_pages: bool, max_scrape_pages: int = 10) -> List[Dict]:
    """scrape listing data from homegate search pages"""
    # scrape the first search page first
    first_page = await CLIENT.fetch(Request(url, ))
    log.info("scraping search page {}", url)
    data = parse_next_data(first_page)["resultList"]["search"]["fullSearch"]["result"]
    search_data = data["listings"]
    # get the number of maximum search pages available
    max_search_pages = data["pageCount"]
    if scrape_all_pages == False and max_scrape_pages < max_search_pages:
        total_pages = max_scrape_pages
    # scrape all available pages in the search if scrape_all_pages = True or max_pages > total_search_pages
    else:
        total_pages = max_search_pages
    log.info("scraping search {} pagination ({} more pages)", url, total_pages - 1)
    # add the remaining search pages in a scraping list
    other_pages = [
        Request(first_page.url + f"?ep={page}", )
        for page in range(2, total_pages + 1)
    ]
    # scrape the remaining search pages concurrently
    async for response in CLIENT.fetch_many(other_pages):
        if not isinstance(response, Response):
            continue
        try:
            data = parse_next_data(response)
            search_data.extend(data["resultList"]["search"]["fullSearch"]["result"]["listings"])
        except Exception as e:
            log.warning(f"failed to parse search page {response.url}: {e}")
    log.info("scraped {} proprties from {}", len(search_data), url)
    return search_data
