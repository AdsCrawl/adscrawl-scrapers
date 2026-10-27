# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the zoro.com scraper defined in ./zoro.py
It scrapes product, search listing and review data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import zoro
from loguru import logger as log

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    log.info("running Zoro scrape and saving results to ./results directory")

    # scrape product
    log.info("scraping product")
    urls = [
        "https://www.zoro.com/proto-general-purpose-double-latch-tool-box-with-tray-steel-red-20-w-x-85-d-x-95-h-j9975r/i/G0067825/",
        "https://www.zoro.com/stanley-rolling-tool-chest-50-gal-capacity-37-in-w-x-23-in-d-x-23-in-h-structural-foam-black-037025h/i/G2464271/",
        "https://www.zoro.com/ansell-hyflex-coated-gloves-polyurethane-dipped-palm-coated-ansi-abrasion-level-3-black-large-1-pair-48-101/i/G0050565/"
    ]
    product = await zoro.scrape_product(urls)
    with open(output.joinpath("product.json"), "w", encoding="utf-8") as file:
        json.dump(product, file, indent=2, ensure_ascii=False)

    log.info("scraping search listing")
    search_listing = await zoro.scrape_search_listing("Gloves", filters={"sort": "desc|averageRating"})
    with open(output.joinpath("search_listing.json"), "w", encoding="utf-8") as file:
        json.dump(search_listing, file, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_scraper(run())
