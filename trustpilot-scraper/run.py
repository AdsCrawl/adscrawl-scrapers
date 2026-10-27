# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the trustpilot.com scraper defined in ./trustpilot.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import trustpilot

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Trustpilot scrape and saving results to ./results directory")

    search_data = await trustpilot.scrape_search(
        url="https://www.trustpilot.com/categories/electronics_technology", max_pages=3
    )
    with open(output.joinpath("search.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)

    companies_data = await trustpilot.scrape_company(
        urls=[
            "https://www.trustpilot.com/review/www.flashbay.com",
            "https://www.trustpilot.com/review/iggm.com",
            "https://www.trustpilot.com/review/www.bhphotovideo.com",
        ]
    )
    with open(output.joinpath("companies.json"), "w", encoding="utf-8") as file:
        json.dump(companies_data, file, indent=2, ensure_ascii=False)

    reviews_data = await trustpilot.scrape_reviews(
        url="https://www.trustpilot.com/review/www.bhphotovideo.com",
        max_pages=3,
    )
    with open(output.joinpath("reviews.json"), "w", encoding="utf-8") as file:
        json.dump(reviews_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
