# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the google.com (Google Jobs) scraper defined in ./google_jobs.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import google_jobs

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Google Jobs scrape and saving results to ./results directory")

    result = await google_jobs.scrape_jobs(
        query="python developer",
        location="San Francisco, CA",

    )
    with open(output / "search.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"saved {len(result['jobs'])} jobs to results/search.json")


if __name__ == "__main__":
    run_scraper(run())
