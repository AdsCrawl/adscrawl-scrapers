# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the g2.com scraper defined in ./g2.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import g2

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

async def run():


    print("running G2 scrape and saving results to ./results directory")

    search_data = await g2.scrape_search(
        url="https://www.g2.com/search?query=Infrastructure",
        max_scrape_pages=3
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)

    reviews_data = await g2.scrape_reviews(
        url="https://www.g2.com/products/digitalocean/reviews",
        max_review_pages=3
    )
    with open(output.joinpath("reviews.json"), "w", encoding="utf-8") as file:
        json.dump(reviews_data, file, indent=2, ensure_ascii=False)

    alternatives_data = await g2.scrape_alternatives(
        product="digitalocean"
    )
    with open(output.joinpath("alternatives.json"), "w", encoding="utf-8") as file:
        json.dump(alternatives_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
