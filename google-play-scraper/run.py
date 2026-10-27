# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the play.google.com scraper defined in ./google_play.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import google_play

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Google Play scrape and saving results to ./results directory")

    apps = await google_play.scrape_apps(app_ids=["com.whatsapp", "com.spotify.music"])
    with open(output / "app.json", "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)

    reviews = await google_play.scrape_reviews(app_id="com.whatsapp", max_reviews=100)
    with open(output / "reviews.json", "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)

    search_results = await google_play.scrape_search(query="Music")
    with open(output / "search.json", "w", encoding="utf-8") as f:
        json.dump(search_results, f, indent=2, ensure_ascii=False)



if __name__ == "__main__":
    run_scraper(run())
