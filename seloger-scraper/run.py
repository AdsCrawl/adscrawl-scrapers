# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the seloger.com scraper defined in ./seloger.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
import json
from pathlib import Path
import seloger

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Seloger scrape and saving results to ./results directory")

    search_data = await seloger.scrape_search(
        url="https://www.seloger.com/classified-search?distributionTypes=Buy&estateTypes=Apartment&locations=AD08FR13100",
        max_pages=2,
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)

    property_data = await seloger.scrape_property(
        urls=[
            "https://www.seloger.com/annonces/achat/appartement/bordeaux-33/193612259.htm",
            "https://www.seloger.com/annonce/achat/nouvelle-aquitaine/gironde-33/bordeaux-33000/267XYAI8HI5K",
            "https://www.seloger.com/annonce/achat/nouvelle-aquitaine/gironde-33/bordeaux-33000/2678R57E48KZ"
        ]
    )
    with open(output.joinpath("property.json"), "w", encoding="utf-8") as file:
        json.dump(property_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
