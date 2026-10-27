# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for trustpilot.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import os
import json
from adscrawl_scrapers import Request, ScraperClient, Response
from typing import Dict, List
from loguru import logger as log

CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass trustpilot web scraping blocking
    'countryCode': "US",
}


def parse_hidden_data(response: Response):
    """parse JSON data from script tags"""
    selector = response.selector
    script = selector.xpath("//script[@id='__NEXT_DATA__']/text()").get()
    data = json.loads(script)
    return data


def parse_company_data(data: Dict) -> Dict:
    """parse company data from JSON and execlude the web app details"""
    data = data["props"]["pageProps"]
    return {
        "pageUrl": data["pageUrl"],
        "companyDetails": data["businessUnit"],
        "reviews": data["reviews"],
    }


@managed
async def scrape_company(urls: List[str]) -> List[Dict]:
    """scrape trustpilot company pages"""
    companies = []
    # add the company pages to a scraping list
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    # scrape all the company pages concurrently
    async for response in CLIENT.fetch_many(to_scrape):
        data = parse_hidden_data(response)
        data = parse_company_data(data)
        companies.append(data)
    log.success(f"scraped {len(companies)} company listings from company pages")
    return companies


@managed
async def scrape_search(url: str, max_pages: int = None) -> List[Dict]:
    """scrape trustpilot search pages"""
    # scrape the first search page first
    log.info("scraping the first search page")
    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    data = parse_hidden_data(first_page)["props"]["pageProps"]["businessUnits"]
    search_data = data["businesses"]

    # get the number of pages to scrape
    total_pages = data["totalPages"]
    if max_pages and max_pages < total_pages:
        total_pages = max_pages

    log.info(f"scraping search pagination ({total_pages - 1} more pages)")
    # add the remaining search pages in a scraping list
    other_pages = [
        Request(url + f"?page={page_number}", **BASE_CONFIG)
        for page_number in range(2, total_pages + 1)
    ]
    # scrape the remaining search pages concurrently
    async for response in CLIENT.fetch_many(other_pages):
        data = parse_hidden_data(response)["props"]["pageProps"]["businessUnits"]["businesses"]
        search_data.extend(data)
    log.success(f"scraped {len(search_data)} company listings from search")
    return search_data


@managed
async def get_reviews_api_url(url: str) -> str:
    """scrape the API version from the HTML and create the reviews API"""
    response = await CLIENT.fetch(
        Request(url, **BASE_CONFIG)
    )
    buildId = json.loads(response.selector.xpath("//script[@id='__NEXT_DATA__']/text()").get())["buildId"]
    business_unit = url.split("review/")[-1]

    return f"https://www.trustpilot.com/_next/data/{buildId}/review/{business_unit}.json?sort=recency&businessUnit={business_unit}"


@managed
async def scrape_reviews(url: str, max_pages: int = None) -> List[Dict]:
    """parse review data from the API"""
    # create the reviews API url
    log.info(f"getting the reviews API for the URL {url}")
    api_url = await get_reviews_api_url(url)
    # send a POST request to the first review page and get the result directly in JSON
    first_page = await CLIENT.fetch(
        Request(api_url, method="POST", **BASE_CONFIG)
    )
    data = json.loads(first_page.content)["pageProps"]
    reviews_data = data["reviews"]

    # get the number of review pages to scrape
    total_pages = data["filters"]["pagination"]["totalPages"]
    if max_pages and max_pages < total_pages:
        total_pages = max_pages

    log.info(f"scraping reviews pagination ({total_pages - 1} more pages)")
    # add the remaining search pages in a scraping list
    other_pages = [
        Request(api_url + f"&page={page_number}", method="POST", **BASE_CONFIG)
        for page_number in range(2, total_pages + 1)
    ]
    # scrape the remaining search pages concurrently
    async for response in CLIENT.fetch_many(other_pages):
        data = json.loads(response.content)["pageProps"]["reviews"]
        reviews_data.extend(data)
    log.success(f"scraped {len(reviews_data)} company reviews")
    return reviews_data
