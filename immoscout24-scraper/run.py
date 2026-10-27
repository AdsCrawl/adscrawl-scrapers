# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the immoscout24.ch scraper defined in ./immoscout24.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import immoscout24

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Immoscout24 scrape and saving results to ./results directory")

    properties_data = await immoscout24.scrape_properties(
        urls=[
            'https://www.immoscout24.ch/rent/4002086534',
            'https://www.immoscout24.ch/rent/4002937830',
            'https://www.immoscout24.ch/rent/4002784101'
        ]
    )
    with open(output.joinpath("properties.json"), "w", encoding="utf-8") as file:
        json.dump(properties_data, file, indent=2, ensure_ascii=False)

    search_data = await immoscout24.scrape_search(
        # change the "rent" in the URL to "buy" to search for properties for sale
        url="https://www.immoscout24.ch/en/real-estate/rent/city-bern",
        scrape_all_pages=False,
        max_scrape_pages=2,
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2)


if __name__ == "__main__":
    run_scraper(run())
