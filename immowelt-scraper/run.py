# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the immowelt.de scraper defined in ./immowelt.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import immowelt

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Immowelt scrape and saving results to ./results directory")

    properties_data = await immowelt.scrape_properties(
        urls=["https://www.immowelt.de/expose/k2ag632", "https://www.immowelt.de/expose/k2bw932"]
    )
    with open(output.joinpath("properties.json"), "w", encoding="utf-8") as file:
        json.dump(properties_data, file, indent=2, ensure_ascii=False)

    search_data = await immowelt.scrape_search(
        url="https://www.immowelt.de/classified-search?distributionTypes=Buy&estateTypes=Apartment&locations=AD08DE6345",
        max_scrape_pages=3,
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
