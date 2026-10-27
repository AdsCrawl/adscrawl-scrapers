# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Walmart.com scraper defined in ./walmart.py
It scrapes product data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
import json
from pathlib import Path
import walmart

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Walmart scrape and saving results to ./results directory")

    products_data = await walmart.scrape_products(
        urls=[
            "https://www.walmart.com/ip/1736740710",
            "https://www.walmart.com/ip/715596133",
        ]
    )
    with open(output.joinpath("products.json"), "w", encoding="utf-8") as file:
        json.dump(products_data, file, indent=2, ensure_ascii=False)

    search_data = await walmart.scrape_search(query="laptop", sort="best_seller", max_pages=3)
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
