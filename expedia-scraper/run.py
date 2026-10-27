# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the expedia.com scraper defined in ./expedia.py
It scrapes hotel search results and saves them to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import expedia

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

TODAY = datetime.now().strftime("%Y-%m-%d")
WEEK_FROM_NOW = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")


async def run():
    print("running Expedia scrape and saving results to ./results directory")

    hotels = await expedia.scrape_hotel_search(
        destination="New York",
        check_in=TODAY,
        check_out=WEEK_FROM_NOW,
        max_pages=3,
    )
    output.joinpath("hotels.json").write_text(
        json.dumps(hotels, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"saved {len(hotels)} hotels to results/hotels.json")


    flight_results = await expedia.scrape_flight_search(
        origin="JFK",
        destination="LAX",
        departure_date=TODAY,
        return_date=WEEK_FROM_NOW,
    )
    output.joinpath("flights.json").write_text(
        json.dumps(flight_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

if __name__ == "__main__":
    run_scraper(run())
