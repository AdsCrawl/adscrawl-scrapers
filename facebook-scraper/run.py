# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Facebook.com scraper defined in ./facebook.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
import json
from pathlib import Path
import facebook

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)



async def run():

    page_data = await facebook.scrape_facebook_page(
        page_urls=[
            "https://www.facebook.com/bbcnews",
            "https://www.facebook.com/adidas/",
            "https://www.facebook.com/copperkettleyqr/",
        ]
    )
    with open(output.joinpath("pages.json"), "w", encoding="utf-8") as file:
        json.dump(page_data, file, indent=2, ensure_ascii=False)

    print("running Facebook scrape and saving results to ./results directory")

    marketplace_data = await facebook.scrape_marketplace_listings(
        query="electronics",
    )
    with open(output.joinpath("marketplace.json"), "w", encoding="utf-8") as file:
        json.dump(marketplace_data, file, indent=2, ensure_ascii=False)

    events_data = await facebook.scrape_facebook_events(event_name="New York, NY")
    with open(output.joinpath("events.json"), "w", encoding="utf-8") as file:
        json.dump(events_data, file, indent=2, ensure_ascii=False)

    group_data = await facebook.scrape_group_posts(
        group_urls=[
            "https://www.facebook.com/groups/instantpotcommunity",
            "https://www.facebook.com/groups/dotnetdevelopers",
            "https://www.facebook.com/groups/airfryerrecipesuk",
        ]
    )
    with open(output.joinpath("group_posts.json"), "w", encoding="utf-8") as file:
        json.dump(group_data, file, indent=2, ensure_ascii=False)

    print("Scraping completed! Check ./results directory for output files")


if __name__ == "__main__":
    run_scraper(run())
