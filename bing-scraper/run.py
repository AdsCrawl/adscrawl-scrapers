# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the bing.com scraper defined in ./bing.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import bing

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Bing scrape and saving results to ./results directory")

    serp_data = await bing.scrape_search(query="web scraping emails", max_pages=3)
    with open(output.joinpath("serps.json"), "w", encoding="utf-8") as file:
        json.dump(serp_data, file, indent=2, ensure_ascii=False)

    keyword_data = await bing.scrape_keywords(query="web scraping emails")
    with open(output.joinpath("keywords.json"), "w", encoding="utf-8") as file:
        json.dump(keyword_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
