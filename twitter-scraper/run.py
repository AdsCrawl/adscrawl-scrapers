# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Twitter.com scraper defined in ./twitter.py
It scrapes product data and product search and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
from pathlib import Path
import asyncio
import json
import twitter

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running X.com tweet scrape and saving results to ./results directory")

    url = "https://x.com/robinhanson/status/1872047986873885082"
    tweet = await twitter.scrape_tweet(url)
    output.joinpath("tweet.json").write_text(json.dumps(tweet, indent=2, ensure_ascii=False))

    url = "https://x.com/robinhanson/"
    profile = await twitter.scrape_profile(url)
    output.joinpath("profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False))



if __name__ == "__main__":
    run_scraper(run())
