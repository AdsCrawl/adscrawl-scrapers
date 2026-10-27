# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/e5b7587213da9d9d03eca0ee13e6548c
import re
import os
import gzip
import json
import asyncio

from parsel import Selector
from typing import Dict, List
from adscrawl_scrapers import Request, ScraperClient, Response

BASE_CONFIG = {
    'countryCode': "US",

}

CLIENT = ScraperClient()

def parse_sitemaps(response: Response) -> List[str]:
    """parse links for bestbuy sitemap"""
    # decode the .gz file
    bytes_data = response.raw or response.content.encode("latin1")
    xml = (gzip.decompress(bytes_data) if bytes_data.startswith(b"\x1f\x8b") else bytes_data).decode("utf-8")
    selector = Selector(xml)
    selector.remove_namespaces()
    data = []
    for url in selector.xpath("//url/loc/text()"):
        data.append(url.get())
    return data


@managed
async def scrape_sitemaps(url: str) -> List[str]:
    """scrape link data from bestbuy sitemap"""
    response = await CLIENT.fetch(Request(url, binary=True, **BASE_CONFIG))
    promo_urls = parse_sitemaps(response)
    print(f"scraped {len(promo_urls)} urls from sitemaps")
    return promo_urls


@managed
async def main():
    sitemap_data = await scrape_sitemaps(
        # sample scraper for one sitemap, other sitemaps can be found at:
        # https://www.bestbuy.com/robots.txt
        url="https://sitemaps.bestbuy.com/sitemaps_promos.0000.xml.gz"
    )
    with open("sitemap_promos_data.json", "w", encoding="utf-8") as file:
        json.dump(sitemap_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
