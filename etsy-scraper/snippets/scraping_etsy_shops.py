# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/b6f92473a40078f626c3208f0f2ea80d
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

def parse_shop_page(response: Response) -> Dict:
    """parse hidden shop data from shop pages"""
    selector = response.selector
    script = selector.xpath("//script[contains(text(),'itemListElement')]/text()").get()
    data = json.loads(script)
    return data


@managed
async def scrape_shop(urls: List[str]) -> List[Dict]:
    shops = []
    # add the shop page URLs to a scraping list
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    # scrape all the shop pages concurrently
    async for response in CLIENT.fetch_many(to_scrape):
        data = parse_shop_page(response)
        data["url"] = response.url
        shops.append(data)
    print(f"scraped {len(shops)} shops from shop pages")
    return shops


@managed
async def main():
    shop_data = await scrape_shop(
        urls=[
            "https://www.etsy.com/shop/FalkelDesign",
            "https://www.etsy.com/shop/JoshuaHouseCrafts",
            "https://www.etsy.com/shop/Oakywood",
        ]
    )

    # save the results to a json file
    with open("shop_data.json", "w", encoding="utf-8") as file:
        json.dump(shop_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
