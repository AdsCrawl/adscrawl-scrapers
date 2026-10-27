# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the kayak.com scraper defined in ./kayak.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import kayak
from datetime import datetime, timedelta

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

TODAY = datetime.now().strftime('%Y-%m-%d')
WEEK_FROM_NOW = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')

async def run():

    print("running Kayak scrape and saving results to ./results directory")

    flights = await kayak.scrape_flights(
        origin="JFK",
        destination="LAX",
        departure_date=TODAY,
        max_pages=3,
    )
    with open(output / "oneway.json", "w", encoding="utf-8") as f:
        json.dump(flights, f, indent=2, ensure_ascii=False)
    print(f"saved {len(flights)} flights to results/oneway.json")

    flights = await kayak.scrape_flights(
        origin="JFK",
        destination="LAX",
        departure_date=TODAY,
        return_date=WEEK_FROM_NOW,
        max_pages=5,
    )
    with open(output / "roundtrip.json", "w", encoding="utf-8") as f:
        json.dump(flights, f, indent=2, ensure_ascii=False)
    print(f"saved {len(flights)} flights to results/roundtrip.json")


if __name__ == "__main__":
    run_scraper(run())
