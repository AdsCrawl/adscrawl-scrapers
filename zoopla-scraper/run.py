# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the zoopla.com scraper defined in ./zoopla.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import zoopla

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

async def run():


    print("running zoopla scrape and saving results to ./results directory")

    properties_data = await zoopla.scrape_properties(
        urls=[
            "https://www.zoopla.co.uk/new-homes/details/73204716/",
            "https://www.zoopla.co.uk/new-homes/details/72496890/",
            "https://www.zoopla.co.uk/new-homes/details/72527128/"
        ]
    )
    with open(output.joinpath("properties.json"), "w", encoding="utf-8") as file:
        json.dump(properties_data, file, indent=2, ensure_ascii=False)

    search_data = await zoopla.scrape_search(
        scrape_all_pages=False,
        max_scrape_pages=2,
        # make sure you location_slug is valid first by using it in the search
        location_slug="london/islington",
        query_type= "to-rent"
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
