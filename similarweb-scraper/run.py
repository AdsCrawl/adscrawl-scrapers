# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the SimilarWeb.com scraper defined in ./similarweb.py
It scrapes product data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import similarweb

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

async def run():


    print("running similarweb scrape and saving results to ./results directory")

    website_data = await similarweb.scrape_website(
        domains=["google.com", "twitter.com", "youtube.com"]
    )
    with open(output.joinpath("websites.json"), "w", encoding="utf-8") as file:
        json.dump(website_data, file, indent=2, ensure_ascii=False)

    comparing_data = await similarweb.scrape_website_compare(
        first_domain="twitter.com",
        second_domain="instagram.com"
    )
    with open(output.joinpath("websites_compare.json"), "w", encoding="utf-8") as file:
        json.dump(comparing_data, file, indent=2, ensure_ascii=False)

    sitemap_data = await similarweb.scrape_sitemaps(
        url="https://www.similarweb.com/blog/post-sitemap2.xml"
    )
    with open(output.joinpath("sitemap_urls.json"), "w", encoding="utf-8") as file:
        json.dump(sitemap_data, file, indent=2, ensure_ascii=False)

    trending_data = await similarweb.scrape_trendings(
        urls=[
            "https://www.similarweb.com/top-websites/computers-electronics-and-technology/programming-and-developer-software/",
            "https://www.similarweb.com/top-websites/computers-electronics-and-technology/social-networks-and-online-communities/",
            "https://www.similarweb.com/top-websites/finance/investing/"
        ]
    )
    with open(output.joinpath("trends.json"), "w", encoding="utf-8") as file:
        json.dump(trending_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(run())

