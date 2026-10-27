# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Threads.net scraper defined in ./threads.py
It scrapes product data and product search and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
from pathlib import Path
import asyncio
import json
import threads

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Threads scrape and saving results to ./results directory")

    url = "https://www.threads.net/t/C8CTu0iswgv"  # example without media
    # url = "https://www.threads.net/t/C8H5FiCtESk/"  # example with media
    thread = await threads.scrape_thread(url)
    output.joinpath("thread.json").write_text(json.dumps(thread, indent=2, ensure_ascii=False), encoding="utf-8")

    url = "https://www.threads.net/@natgeo"
    profile = await threads.scrape_profile(url)
    output.joinpath("profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")



if __name__ == "__main__":
    run_scraper(run())
