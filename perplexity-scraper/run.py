# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the perplexity.ai scraper defined in ./perplexity.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import perplexity

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Perplexity scrape and saving results to ./results directory")

    result = await perplexity.scrape_answer("How does photosynthesis work")
    with open(output / "answer.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
