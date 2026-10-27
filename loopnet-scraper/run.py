# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the loopnet.com scraper defined in ./loopnet.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import loopnet

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running LoopNet scrape and saving results to ./results directory")

    listings = await loopnet.scrape_listings(
        urls=[
            "https://www.loopnet.com/Listing/2312-Abercorn-St-Savannah-GA/41217887/",
            "https://www.loopnet.com/Listing/1410-Dean-Forest-Rd-Savannah-GA/41166496/",
        ]
    )
    with open(output / "listings.json", "w", encoding="utf-8") as f:
        json.dump(listings, f, indent=2, ensure_ascii=False)

    search_results = await loopnet.scrape_search(
        search_url="https://www.loopnet.com/search/commercial-real-estate/savannah-ga/for-sale/", max_pages=2
    )
    with open(output / "search.json", "w", encoding="utf-8") as f:
        json.dump(search_results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
