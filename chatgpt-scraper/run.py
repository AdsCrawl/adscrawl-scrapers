# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the chatgpt.com scraper defined in ./chatgpt.py
It scrapes data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper

import asyncio
from pathlib import Path
import chatgpt

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running ChatGPT scrape and saving results to ./results directory")

    conversation = await chatgpt.scrape_conversation("What's the capital of France? with Brief History of the city.")
    with open(output / "conversation.md", "w", encoding="utf-8") as f:
        f.write(conversation)


if __name__ == "__main__":
    run_scraper(run())
