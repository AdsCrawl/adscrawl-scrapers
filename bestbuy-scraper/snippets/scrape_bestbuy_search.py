# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/d1665ee235c828de8e664408019295ee
import re
import os
import gzip
import json
import asyncio

from parsel import Selector
from typing import Dict, List, Union
from urllib.parse import urlencode, quote_plus
from adscrawl_scrapers import Request, ScraperClient, Response

BASE_CONFIG = {
    # bypass bestbuy.com web scraping blocking
    'countryCode': "US",

}

CLIENT = ScraperClient()

def parse_search(response: Response):
    """parse search data from search pages"""
    selector = response.selector
    data = []

    for item in selector.css(".product-grid-view-container li"):
        if item.css(".a-skeleton-shimmer").get():
            continue
        name = item.css(".product-title::attr(title)").get()

        link = item.css("a.product-list-item-link::attr(href)").get()

        sku = item.xpath("@data-testid").get()

        price = None
        price_element = item.css('[data-testid="price-block-customer-price"] span::text').get()
        if price_element:
            price = re.sub(r'[^\d.]', '', price_element) or None
        original_price = None
        original_price_elements = item.css('[data-testid="price-block-regular-price"] span::text').getall()
        for elem in original_price_elements:
            if '$' in elem:
                original_price = re.sub(r'[^\d.]', '', elem) or None
                break

        rating = item.css('.font-weight-bold::text').get()

        rating_count = 0
        rating_count_element = item.css('.c-reviews::text').get()
        if rating_count_element:
            count_matches = re.findall(r'\(([0-9,]+)\s+reviews?\)', rating_count_element)
            if count_matches:
                rating_count = int(count_matches[0].replace(',', ''))

        images = item.css("img[data-testid='product-image']::attr(srcset)").getall()

        if name and sku:
            data.append({
                "name": name,
                "link": link if (link and link.startswith('http')) else (f"https://www.bestbuy.com{link}" if link else None),
                "images": images,
                "sku": sku,
                "price": price,
                "original_price": original_price,
                "rating": rating,
                "rating_count": rating_count,
            })

    total_pages = 1
    if len(data):
        try:
            pagination_text = selector.css(".pagination-num-found::text").get()
            if pagination_text:
                total_matches = re.findall(r'of (\d+)', pagination_text.replace(',', ''))
                if total_matches:
                    total_count = int(total_matches[0])
                    total_pages = (total_count + len(data) - 1) // len(data)
        except Exception as e:
            print(f"Could not parse total pages: {e}")
            total_pages = 1

    return {"data": data, "total_pages": total_pages}


@managed
async def scrape_search(search_query: str, sort: Union["-bestsellingsort", "-Best-Discount"] = None, max_pages=None):
    """scrape search data from bestbuy search"""

    def form_search_url(page_number: int):
        """form the search url"""
        base_url = "https://www.bestbuy.com/site/searchpage.jsp?"
        # search parameters
        params = {"st": quote_plus(search_query)}
        if page_number > 1:
            params["cp"] = page_number
        if sort:
            params["sp"] = sort
        return base_url + urlencode(params)
    first_page = await CLIENT.fetch(
        Request(
            form_search_url(1),
            render=True,
            waitMs=10000,
            autoScroll=True,
            **BASE_CONFIG,
        )
    )
    data = parse_search(first_page)
    search_data = data["data"]
    total_pages = data["total_pages"]

    # get the number of total search pages to scrape
    if max_pages and max_pages < total_pages:
        total_pages = max_pages

    print(f"scraping search pagination, {total_pages - 1} more pages")
    # add the remaining pages to a scraping list to scrape them concurrently
    to_scrape = [Request(form_search_url(page_number), **BASE_CONFIG, render=True, waitMs=10000, autoScroll=True) for page_number in range(2, total_pages + 1)]
    async for response in CLIENT.fetch_many(to_scrape):
        data = parse_search(response)["data"]
        search_data.extend(data)

    print(f"scraped {len(search_data)} products from search pages")
    return search_data


@managed
async def main():
    search_data = await scrape_search(
        search_query="macbook",
        max_pages=3
    )
    with open("search.json", "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    run_scraper(main())
