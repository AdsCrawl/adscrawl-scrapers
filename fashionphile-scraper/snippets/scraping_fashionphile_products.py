# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/7813858d18444bace241ee881e624c57
import os
import json
import asyncio

from typing import Dict, List
from adscrawl_scrapers import Request, ScraperClient

BASE_CONFIG = {
    'countryCode': "US",
    'render': True,
}

CLIENT = ScraperClient()

def convert_to_json_urls(urls):
    converted = []
    for url in urls:
        # Replace '/p/' with '/products/' and add '.json' at the end
        new_url = url.replace("/p/", "/products/") + ".json"
        converted.append(new_url)
    return converted


@managed
async def scrape_products(urls: List[str]) -> List[Dict]:
    """
    Scrape product data from Fashionphile product pages using the product API.
    """
    urls = convert_to_json_urls(urls)
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    products = []
    async for response in CLIENT.fetch_many(to_scrape):
        # Extract just the product data from the JSON content
        content = response.content
        product_data = json.loads(content)['product']
        products.append(product_data)
        print(f"scraped {len(products)} product listings from product pages")
    return products


@managed
async def main():
    products_data = await scrape_products(
        urls=[
            "https://www.fashionphile.com/p/bottega-veneta-nappa-twisted-padded-intrecciato-curve-slide-sandals-36-black-1048096",
            "https://www.fashionphile.com/p/louis-vuitton-ostrich-lizard-majestueux-tote-mm-navy-1247825",
            "https://www.fashionphile.com/p/louis-vuitton-monogram-multicolor-lodge-gm-black-1242632",
        ]
    )
    # save the results to a json file
    with open("products_data.json", "w", encoding="utf-8") as file:
        json.dump(products_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
