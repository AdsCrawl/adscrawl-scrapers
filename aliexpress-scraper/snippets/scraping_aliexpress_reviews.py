# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/798c31befc89a698483479ee4089741d
import json
import math
import os
import re
import asyncio

from typing import Dict, List
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from adscrawl_scrapers import Response, Request, ScraperClient

BASE_CONFIG = {
    'countryCode': "US",
    # Us locale, apply localization settings from the browser and then copy the aep_usuc_f cookie from devtools
    "headers": {
        "cookie": "aep_usuc_f=site=glo&province=&city=&c_tp=USD&region=US&b_locale=en_US&ae_u_p_s=2"
    }
}

CLIENT = ScraperClient()

def parse_review_page(result: Response):
    data = json.loads(result.content)["data"]
    return {
        "max_pages": data["totalPage"],
        "reviews": data["evaViewList"],
        "evaluation_stats": data["productEvaluationStatistic"]
    }


@managed
async def scrape_product_reviews(product_id: str, max_scrape_pages: int = None):
    """scrape all reviews of aliexpress product"""

    def scrape_config_for_page(page):
        url = f"https://feedback.aliexpress.com/pc/searchEvaluation.do?productId={product_id}&lang=en_US&country=US&page={page}&pageSize=10&filter=all&sort=complex_default"
        return Request(url)

    # scrape first page of reviews and find total count of review pages
    first_page_result = await CLIENT.fetch(scrape_config_for_page(1))
    data = parse_review_page(first_page_result)
    max_pages = data["max_pages"]

    if max_scrape_pages and max_scrape_pages < max_pages:
        max_pages = max_scrape_pages

    # scrape the remaining pagination pages
    print(f"scraping reviews pagination of product {product_id}, {max_pages - 1} pages remaining")
    to_scrape = [scrape_config_for_page(page) for page in range(2, max_pages + 1)]
    async for result in CLIENT.fetch_many(to_scrape):
        data["reviews"].extend(parse_review_page(result)["reviews"])
    print(f"scraped {len(data['reviews'])} from review pages")
    data.pop("max_pages")
    return data


@managed
async def main():
    review_results = await scrape_product_reviews(
        product_id="1005006717259012",
        max_scrape_pages=3
    )

    # save the results to a json file
    with open("product_reviews.json", "w", encoding="utf-8") as f:
        json.dump(review_results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
