# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the airbnb.com scraper defined in ./airbnb.py
It scrapes search and listing data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
from adscrawl_scrapers import Request

import airbnb

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
WEEK_FROM_NOW = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")


async def run():
    print("running Airbnb scrape and saving results to ./results directory")

    search_results = await airbnb.scrape_listings(
        query="Panama City Beach, Florida",
        check_in=TODAY,
        check_out=WEEK_FROM_NOW,
        adults=1,
        max_pages=3,
    )
    output.joinpath("search.json").write_text(
        json.dumps(search_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    urls = [item["url"] for item in search_results if item.get("url")][:3]
    property_results = await airbnb.scrape_properties(
        urls=urls, check_in=TODAY, check_out=WEEK_FROM_NOW
    )
    output.joinpath("property.json").write_text(
        json.dumps(property_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    run_scraper(run())
