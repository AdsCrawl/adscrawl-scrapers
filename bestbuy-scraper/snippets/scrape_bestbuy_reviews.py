# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/9c63f8d23a1714d16c071440623bbc9f
import re
import os
import gzip
import json
import asyncio

from parsel import Selector
from typing import Dict, List
from adscrawl_scrapers import Request, ScraperClient, Response

BASE_CONFIG = {
    'countryCode': "US",

}

CLIENT = ScraperClient()

def parse_reviews(response: Response) -> List[Dict]:
    """parse review data from the review API responses"""
    data = json.loads(response.content)
    total_count = data["totalPages"]
    review_data = data["topics"]
    return {"data": review_data, "total_count": total_count}


@managed
async def scrape_reviews(skuid: int, max_pages: int = None) -> List[Dict]:
    """scrape review data from the reviews API"""
    print(f"scraping first review page for skuid: {skuid}")
    first_page = await CLIENT.fetch(
        Request(
            f"https://www.bestbuy.com/ugc/v2/reviews?page=1&pageSize=20&sku={skuid}&sort=MOST_RECENT", **BASE_CONFIG
        )
    )
    data = parse_reviews(first_page)
    review_data = data["data"]
    total_count = data["total_count"]

    # get the number of total review pages to scrape
    if max_pages and max_pages < total_count:
        total_count = max_pages

    print(f"scraping reviews pagination, {total_count - 1} more pages")
    # add the remaining pages to a scraping list to scrape them concurrently
    to_scrape = [
        Request(
            f"https://www.bestbuy.com/ugc/v2/reviews?page={page_number}&pageSize=20&sku={skuid}&sort=MOST_RECENT",
            **BASE_CONFIG,
        )
        for page_number in range(2, total_count + 1)
    ]
    async for response in CLIENT.fetch_many(to_scrape):
        data = parse_reviews(response)["data"]
        review_data.extend(data)

    print(f"scraped {len(review_data)} reviews from the reviews API")
    return review_data


@managed
async def main():
    review_data = await scrape_reviews(skuid=6565065, max_pages=3)
    with open("product_reviews.json", "w", encoding="utf-8") as file:
        json.dump(review_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
