# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Goodreads.com scraper defined in ./goodreads.py
It scrapes book, review, list and search data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
from pathlib import Path
import asyncio
import json
import goodreads

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    print("running Goodreads.com scrape and saving results to ./results directory")

    url = "https://www.goodreads.com/book/show/4671.The_Great_Gatsby"
    book = await goodreads.scrape_book(url)
    output.joinpath("book.json").write_text(json.dumps(book, indent=2, ensure_ascii=False), encoding="utf-8")

    url = "https://www.goodreads.com/book/show/2767052/reviews"
    reviews = await goodreads.scrape_reviews(url)
    output.joinpath("reviews.json").write_text(json.dumps(reviews, indent=2, ensure_ascii=False), encoding="utf-8")

    url = "https://www.goodreads.com/list/show/264.Books_That_Everyone_Should_Read"
    book_list = await goodreads.scrape_list(url, enrich=False)
    output.joinpath("list.json").write_text(json.dumps(book_list, indent=2, ensure_ascii=False), encoding="utf-8")

    search = await goodreads.scrape_search("dune", max_pages=2)
    output.joinpath("search.json").write_text(json.dumps(search, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run_scraper(run())
