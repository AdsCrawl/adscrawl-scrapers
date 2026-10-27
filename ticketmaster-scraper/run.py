# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Ticketmaster.com scraper defined in ./ticketmaster.py
It scrapes artist and event data and saves it to ./results/
To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import ticketmaster
from loguru import logger as log
from datetime import datetime, timedelta

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    log.info("running Ticketmaster scrape and saving results to ./results directory")

    log.info("scraping artist page")
    artist_data = await ticketmaster.scrape_artist(
        urls=[
            "https://www.ticketmaster.com/imagine-dragons-tickets/artist/1435919",
            "https://www.ticketmaster.com/george-lopez-tickets/artist/770234"
        ]
    )
    with open(output.joinpath("artist.json"), "w", encoding="utf-8") as file:
        json.dump(artist_data, file, indent=2, ensure_ascii=False)

    log.info("scraping discovery page")
    start = datetime.now()
    end = start + timedelta(days=7)
    filters = {
        "classificationId": "KnvZfZ7vAvv",
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d")
    }
    discovery_data = await ticketmaster.scrape_discovery("https://www.ticketmaster.com/discover/concerts", **filters)
    with open(output.joinpath("discovery.json"), "w", encoding="utf-8") as file:
        json.dump(discovery_data, file, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_scraper(run())
