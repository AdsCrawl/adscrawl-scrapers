# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/73969723c2fa37536297e75e7c883103
import os
import math
import json
import asyncio

from typing import Dict, List
from adscrawl_scrapers import Request, ScraperClient, Response

BASE_CONFIG = {
    'countryCode': "US",
}

CLIENT = ScraperClient()

def parse_product_page(response: Response) -> Dict:
    """parse hidden product data from product pages"""
    selector = response.selector
    script = selector.xpath("//script[contains(text(),'offers')]/text()").get()
    if not script:
        print(f"Could not find product data script on {response.url}")
        return {}
    data = json.loads(script)
    return data


@managed
async def scrape_product(urls: List[str]) -> List[Dict]:
    """scrape trustpilot company pages"""
    products = []
    # add the product page URLs to a scraping list
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    # scrape all the product pages concurrently
    async for response in CLIENT.fetch_many(to_scrape):
        data = parse_product_page(response)
        products.append(data)
    print(f"scraped {len(products)} product listings from product pages")
    return products


@managed
async def main():
    product_data = await scrape_product(
        urls=[
            "https://www.etsy.com/listing/1552627931",
            "https://www.etsy.com/listing/529765307",
            "https://www.etsy.com/listing/949905096",
        ]
    )

    # save the results to a json file
    with open("product_data.json", "w", encoding="utf-8") as file:
        json.dump(product_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
