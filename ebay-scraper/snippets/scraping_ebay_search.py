# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
from adscrawl_scrapers import run as run_scraper
from adscrawl_scrapers import managed
# https://gist.github.com/scrapfly-dev/1342304e900fe8af086e38aba98bc32e
import json
import math
import os
import re
import asyncio

from collections import defaultdict
from typing import Dict, List, Optional
from nested_lookup import nested_lookup
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from adscrawl_scrapers import Response, Request, ScraperClient

BASE_CONFIG = {
    'countryCode': "US",
    'locale': "en-US"
}

CLIENT = ScraperClient()

def _get_url_parameter(url: str, param: str, default=None) -> Optional[str]:
    """get url parameter value"""
    query_params = dict(parse_qsl(urlparse(url).query))
    return query_params.get(param) or default


def _update_url_param(url: str, **params):
    """adds url parameters or replaces them with new values"""
    parsed_url = urlparse(url)
    query_params = dict(parse_qsl(parsed_url.query))
    query_params.update(params)
    updated_url = parsed_url._replace(query=urlencode(query_params))
    return urlunparse(updated_url)


def parse_search(result: Response) -> List[Dict]:
    """Parse ebay.com search result page for product previews"""
    previews = []

    for box in result.selector.css("ul.srp-results li"):
        css = lambda css: box.css(css).get("").strip() or None
        css_all = lambda css: box.css(css).getall()
        css_re = lambda css, pattern: box.css(css).re_first(pattern, default="").strip()
        css_float = lambda css: float(box.css(css).re_first(r"(\d+\.*\d*)", default="0.0")) if box.css(css) else None
        location = box.xpath(".//*[contains(text(),'Located')]/text()").get()
        price = css(".s-card__price::text") or css(".s-item__price::text")
        url = css("a.s-card__link::attr(href)") or css("a.su-link::attr(href)")

        if price is None:
            continue  # skip boxes inside the best selling container

        item = {
            "url": url.split("?")[0] if url else None,
            "title": css(".s-card__title span::text"),
            "price": css(".s-card__price::text") or css(".s-item__price::text"),
            "shipping": box.xpath(".//*[contains(text(),'delivery')]/text()").get(),
            "location": location.split("Located in ")[1] if location else None,
            "subtitles": css(".s-card__subtitle span::text"),
            "photo": css("img::attr(data-src)") or css("img::attr(src)"),
            "rating": css_float(".x-star-rating .clipped::text") or css_float(".s-item__reviews .clipped::text"),
            "rating_count": int(box.css(".s-card__reviews-count span::text").re_first(r"(\d+)", default="0") or box.css(".s-item__reviews-count span::text").re_first(r"(\d+)", default="0")),
        }
        previews.append(item)
    return previews


@managed
async def scrape_search(url: str, max_pages: Optional[int] = None) -> List[Dict]:
    """Scrape Ebay's search for product preview data for given"""
    print(f"Scraping search for {url}")

    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    results = parse_search(first_page)
    # find total amount of results for concurrent pagination
    total_results = first_page.selector.css(".srp-controls__count-heading>span::text").get()
    total_results = int(total_results.replace(",", "").replace(".", ""))
    items_per_page = int(_get_url_parameter(first_page.url, "_ipg", default=60))
    total_pages = math.ceil(total_results / items_per_page)
    if max_pages and total_pages > max_pages:
        total_pages = max_pages
    other_pages = [
        Request(_update_url_param(first_page.url, _pgn=i), **BASE_CONFIG)
        for i in range(2, total_pages + 1)
    ]
    print(f"Scraping search pagination of {len(other_pages)} total pages for {url}")
    async for result in CLIENT.fetch_many(other_pages):
        results.extend(parse_search(result))
    print(f"Scraped {len(results)} results from search {url}")
    return results


@managed
async def main():
    results = await scrape_search(
        url="https://www.ebay.com/sch/i.html?_from=R40&_nkw=iphone&_sacat=0&LH_TitleDesc=0&Storage%2520Capacity=16%2520GB&_dcat=9355&_ipg=240&rt=nc&LH_All=1",
        max_pages=3
    )

    # save the results to a json file
    with open("search_data.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    run_scraper(main())
