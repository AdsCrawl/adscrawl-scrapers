# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the RS-Online (rs-online.com) scraper defined in ./rs_online.py
It scrapes product data, category listings and keyword search, and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import rs_online

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running RS-Online scrape and saving results to ./results directory")

    products = await rs_online.scrape_products(
        urls=[
            "https://us.rs-online.com/product/aim-cambridge-cinch-connectivity-solutions/40-9715m/70081087/",
            "https://us.rs-online.com/product/cinch/dah15s/70152743/",
        ]
    )
    with open(output / "products.json", "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)

    category_results = await rs_online.scrape_category(
        url="https://us.rs-online.com/connectors/d-sub-connectors-contacts-accessories/d-sub-connectors/",
        max_pages=2,
    )
    with open(output / "category.json", "w", encoding="utf-8") as f:
        json.dump(category_results, f, indent=2, ensure_ascii=False)

    search_results = await rs_online.scrape_search(query="transformer", max_pages=2)
    with open(output / "search.json", "w", encoding="utf-8") as f:
        json.dump(search_results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
