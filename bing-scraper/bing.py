# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for bing.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed
import re
import os
from adscrawl_scrapers import Request, ScraperClient, Response
from typing import Dict, List
from urllib.parse import urlencode, urlparse, parse_qs
from loguru import logger as log

CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass Bing web scraping blocking
    'countryCode': "GB",
    'autoScroll':True,
}


def parse_serps(response: Response) -> List[Dict]:
    """parse SERPs from bing search pages"""
    selector = response.selector
    data = []
    # the "first" URL parameter is the result offset; bing can add more parameters after it
    position = int(parse_qs(urlparse(response.url).query).get("first", ["0"])[0])
    for result in selector.xpath("//li[@class='b_algo']"):
        url = result.xpath(".//h2/a/@href").get()
        description = result.xpath("normalize-space(.//div/p)").extract_first()
        date = result.xpath(".//span[@class='news_dt']/text()").get()
        if data is not None and date is not None and len(date) > 12:
            date_pattern = re.compile(r"\b\d{2}-\d{2}-\d{4}\b")
            date_pattern.findall(description)
            dates = date_pattern.findall(date)
            date = dates[0] if dates else None
        position += 1
        data.append(
            {
                "position": position,
                "title": "".join(result.xpath(".//h2/a//text()").extract()),
                "url": url,
                "origin": result.xpath(".//div[@class='tptt']/text()").get(),
                "domain": url.split("https://")[-1].split("/")[0].replace("www.", "")
                if url
                else None,
                "description": description,
                "date": date,
            }
        )
    return data

def parse_keywords(response: Response) -> Dict:
    """parse FAQs and popular keywords on bing search pages"""
    selector = response.selector
    related_keywords = []
    for keyword in selector.xpath(".//li[@class='b_ans']/div/ul/li"):
        related_keywords.append("".join(keyword.xpath(".//a/div//text()").extract()))

    return related_keywords


@managed
async def scrape_search(query: str, max_pages: int = None):
    """scrape bing search pages"""
    url = f"https://www.bing.com/search?{urlencode({'q': query})}"
    log.info("scraping the first search page")
    response = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    serp_data = parse_serps(response)

    log.info(f"scraping search pagination ({max_pages - 1} more pages)")
    total_results = (max_pages - 1) * 10  # each page contains 10 results
    other_pages = [
        Request(url + f"&first={start}", **BASE_CONFIG)
        for start in range(10, total_results + 10, 10)
    ]

    # scrape the remaining search pages concurrently
    async for response in CLIENT.fetch_many(other_pages):
        data = parse_serps(response)
        serp_data.extend(data)
    log.success(f"scraped {len(serp_data)} search results from Bing search")
    return serp_data


@managed
async def scrape_keywords(query: str):
    """scrape bing search pages for keyword data"""
    url = f"https://www.bing.com/search?{urlencode({'q': query})}"
    log.info("scraping Bing search for keyword data")
    # bing sends a lighter page without the related searches box to Linux browsers,
    # so the browser presents itself as Windows
    response = await CLIENT.fetch(Request(url, **BASE_CONFIG, render=True, userAgentOs="windows"))
    keyword_data = parse_keywords(response)
    if not keyword_data:
        # bing does not show the related searches box for every query
        log.warning(f"bing.com showed no related searches for '{query}' on this page load")
        return keyword_data
    log.success(
        f"scraped {len(keyword_data)} keywords from Bing search"
    )
    return keyword_data
