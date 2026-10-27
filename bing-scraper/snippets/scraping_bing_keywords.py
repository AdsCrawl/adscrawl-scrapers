# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/556f2423d2733b33e27a302a43cf9ae2
import re
import os
import json
import asyncio

from typing import Dict, List
from urllib.parse import urlencode
from adscrawl_scrapers import Request, ScraperClient, Response

BASE_CONFIG = {
    'countryCode': "GB",
    'autoScroll':True,
}

CLIENT = ScraperClient()

def parse_keywords(response: Response) -> Dict:
    """parse FAQs and popular keywords on bing search pages"""
    selector = response.selector
    related_keywords = []
    for keyword in selector.xpath(".//li[@class='b_ans']/div/ul/li"):
        related_keywords.append("".join(keyword.xpath(".//a/div//text()").extract()))
    return related_keywords


@managed
async def scrape_keywords(query: str):
    """scrape bing search pages for keyword data"""
    url = f"https://www.bing.com/search?{urlencode({'q': query})}"
    print("scraping Bing search for keyword data")
    response = await CLIENT.fetch(Request(url, **BASE_CONFIG, render=True))
    keyword_data = parse_keywords(response)
    print(f"scraped {len(keyword_data)} keywords from Bing search")
    return keyword_data


@managed
async def main():
    keyword_data = await scrape_keywords(query="web scraping emails")
    with open("search_keywords.json", "w", encoding="utf-8") as file:
        json.dump(keyword_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
