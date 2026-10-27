# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the realestate.com.au scraper defined in ./realestate.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
import realestate
from pathlib import Path

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Realestate.com.au scrape and saving results to ./results directory")

    properties_data = await realestate.scrape_properties(
        urls=[
            "https://www.realestate.com.au/property-house-vic-tarneit-143160680",
            "https://www.realestate.com.au/property-house-vic-doreen-151765412",
            "https://www.realestate.com.au/property-townhouse-vic-glenroy-143556608",
        ]
    )
    with open(output.joinpath("properties.json"), "w", encoding="utf-8") as file:
        json.dump(properties_data, file, indent=2, ensure_ascii=False)

    search_data = await realestate.scrape_search(
        # you can change "buy" to "rent" in the search URL to search for properties for rent
        url="https://www.realestate.com.au/buy/in-melbourne+-+northern+region,+vic/list-1",
        max_scrape_pages=3,
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
