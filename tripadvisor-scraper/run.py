# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the tripadvisor scraper defined in ./tripadvisor.py
It scrapes hotel data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import tripadvisor

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Tripadvisor scrape and saving results to ./results directory")
    result_location = await tripadvisor.scrape_location_data(query="Malta")
    output.joinpath("location.json").write_text(json.dumps(result_location, indent=2, ensure_ascii=False), encoding="utf-8")

    result_search = await tripadvisor.scrape_search(
        search_url="https://www.tripadvisor.com/Hotels-g60763-oa30-New_York_City_New_York-Hotels.html", max_pages=2
    )
    output.joinpath("search.json").write_text(json.dumps(result_search, indent=2, ensure_ascii=False), encoding="utf-8")

    result_hotel = await tripadvisor.scrape_hotel(
        "https://www.tripadvisor.com/Hotel_Review-g190327-d264936-Reviews-1926_Hotel_Spa-Sliema_Island_of_Malta.html",
        max_review_pages=3,
    )
    output.joinpath("hotels.json").write_text(json.dumps(result_hotel, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run_scraper(run())
