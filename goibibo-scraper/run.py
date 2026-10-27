# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the goibibo.com scraper defined in ./goibibo.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import goibibo

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


TOMORROW = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
WEEK_FROM_NOW = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")


async def run():
    print("running Goibibo scrape and saving results to ./results directory")

    hotels = await goibibo.scrape_hotel_search(
        search_text="Delhi",
        locus_id="CTDEL",
        checkin=TOMORROW,
        checkout=WEEK_FROM_NOW,
        max_pages=5,
    )
    with open(output / "hotel_search.json", "w", encoding="utf-8") as f:
        json.dump(hotels, f, indent=2, ensure_ascii=False)

    flights = await goibibo.scrape_flight_search(
        origin="DEL",
        destination="BOM",
        departure_date=TOMORROW,
        adults=1,
    )
    with open(output / "flight_search.json", "w", encoding="utf-8") as f:
        json.dump(flights, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
