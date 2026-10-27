# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the emirates.com scraper defined in ./emirates.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import emirates

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
WEEK_FROM_NOW = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")


async def run():

    print("running Emirates scrape and saving results to ./results directory")

    result = await emirates.scrape_flights(
        origin="JFK",
        destination="DXB",
        departure_date=TODAY,
        return_date=WEEK_FROM_NOW,
        locale="us/english",
    )
    with open(output / "roundtrip.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"saved {len(result['flights'])} flight offers to results/roundtrip.json")

    result = await emirates.scrape_flights(
        origin="JFK",
        destination="DXB",
        departure_date=TODAY,
        locale="us/english",
    )
    with open(output / "oneway.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"saved {len(result['flights'])} flight offers to results/oneway.json")


if __name__ == "__main__":
    run_scraper(run())
