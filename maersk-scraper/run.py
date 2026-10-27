# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the maersk.com scraper defined in ./maersk.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
import json
from pathlib import Path

import maersk

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Maersk scrape and saving results to ./results directory")

    tracking = await maersk.scrape_tracking("269124324")
    with open(output / "tracking.json", "w", encoding="utf-8") as f:
        json.dump(tracking, f, indent=2, ensure_ascii=False)

    schedule = await maersk.scrape_schedule_search(
        from_location="2IW9P6J7XAW72",
        to_location="1JUKNJGWHQBNJ",
        from_rkst_code="CNSGH",
        to_rkst_code="NLROT",
        departure_date="2026-08-15",
    )
    with open(output / "schedule.json", "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
