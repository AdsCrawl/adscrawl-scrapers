# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for leboncoin.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import os
import json
from adscrawl_scrapers import Request, ScraperClient, Response
from typing import Dict, List
from pathlib import Path
from loguru import logger as log

CLIENT = ScraperClient()
BASE_CONFIG = {
    'countryCode': "fr",
}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


def parse_search(result: Response):
    """parse search result data from nextjs cache"""
    # select the __NEXT_DATA__ script from the HTML
    next_data = result.selector.css("script[id='__NEXT_DATA__']::text").get()
    # extract ads listing data from the search page
    ads_data = json.loads(next_data)["props"]["pageProps"]["searchData"]["ads"]
    return ads_data


def _max_search_pages(result: Response):
    """get the number of max pages in the search"""
    next_data = result.selector.css("script[id='__NEXT_DATA__']::text").get()
    # extract the total pages number
    max_search_pages = json.loads(next_data)["props"]["pageProps"]["searchData"]["max_pages"]
    return max_search_pages


def parse_ad(result: Response):
    """parse ad data from nextjs cache"""
    next_data = result.selector.css("script[id='__NEXT_DATA__']::text").get()
    # extract ad data from the ad page
    ad_data = json.loads(next_data)["props"]["pageProps"]["ad"]
    return ad_data


@managed
async def scrape_search(
    url: str, scrape_all_pages: bool, max_pages: int = 10
) -> List[Dict]:
    """scrape leboncoin search"""
    log.info("scraping search {}", url)
    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    search_data = parse_search(first_page)
    total_search_pages = _max_search_pages(first_page)
    # scrape a specfic amount of search pages
    if scrape_all_pages == False and max_pages < total_search_pages:
        total_pages = max_pages
    # scrape all available pages in the search if scrape_all_pages = True or max_pages > total_search_pages
    else:
        total_pages = total_search_pages
    log.info("scraping search {} pagination ({} more pages)", url, total_pages - 1)
    # add the ramaining pages in a scraping list
    _other_pages = [
        Request(f"{first_page.url}&page={page}", **BASE_CONFIG)
        for page in range(2, total_pages + 1)
    ]
    # scrape the remaining pages concurrently
    async for result in CLIENT.fetch_many(_other_pages):
        ads_data = parse_search(result)
        search_data.extend(ads_data)
    log.info("scraped {} ads from {}", len(search_data), url)
    return search_data


@managed
async def scrape_ad(url: str, _retries: int = 0) -> Dict:
    """scrape ad page"""
    log.info("scraping ad {}", url)
    ad_data = None
    try:
        result = await CLIENT.fetch(Request(url, **BASE_CONFIG))
        ad_data = parse_ad(result)
    except:
        if _retries < 2:
            # requests get blocked and redirected to homepage
            log.debug("retrying failed request")
            result = await scrape_ad(url, _retries=_retries + 1)
        else:
            return None
    return ad_data
