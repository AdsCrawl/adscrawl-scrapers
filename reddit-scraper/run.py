# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Reddit.com scraper defined in ./reddit.py
It scrapes product data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import reddit

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Reddit scraper and saving results to ./results directory")

    subreddit_data = await reddit.scrape_subreddit(
        subreddit_id="wallstreetbets",
        max_pages=3
    )
    with open(output.joinpath("subreddit.json"), "w", encoding="utf-8") as file:
        json.dump(subreddit_data, file, indent=2, ensure_ascii=False)

    post_data = await reddit.scrape_post(
        url="https://www.reddit.com/r/wallstreetbets/comments/1c4vwlp/what_are_your_moves_tomorrow_april_16_2024/",
        sort="top",
    )
    with open(output.joinpath("post.json"), "w", encoding="utf-8") as file:
        json.dump(post_data, file, indent=2, ensure_ascii=False)

    user_post_data = await reddit.scrape_user_posts(
        username="Scrapfly",
        sort="top",
        max_pages=3
    )
    with open(output.joinpath("user_posts.json"), "w", encoding="utf-8") as file:
        json.dump(user_post_data, file, indent=2, ensure_ascii=False)

    user_comment_data = await reddit.scrape_user_comments(
        username="Scrapfly",
        sort="top",
        max_pages=3
    )
    with open(output.joinpath("user_comments.json"), "w", encoding="utf-8") as file:
        json.dump(user_comment_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())
