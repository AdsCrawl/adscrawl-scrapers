# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for idealista.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import json
import re
import math
from adscrawl_scrapers import Request, ScraperClient, Response
from typing import Dict, List
from typing_extensions import TypedDict
from collections import defaultdict
from urllib.parse import urljoin
from pathlib import Path
from loguru import logger as log

CLIENT = ScraperClient()

BASE_CONFIG = {
    # bypass web scraping blocking
    'countryCode': "ES",
}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


def parse_province(response: Response) -> List[str]:
    """parse province page for area search urls"""
    selector = response.selector
    urls = selector.css("#location_list li>a::attr(href)").getall()
    return [urljoin(str(response.url), url) for url in urls]


# type hints fo expected results so we can visualize our scraper easier:
class PropertyResult(TypedDict):
    url: str
    title: str
    location: str
    price: int
    currency: str
    description: str
    updated: str
    features: Dict[str, List[str]]
    images: Dict[str, List[str]]
    plans: List[str]


def parse_property(response: Response) -> PropertyResult:
    """parse Idealista.com property page"""
    # load response's HTML tree for parsing:
    selector = response.selector
    css = lambda x: selector.css(x).get("").strip()
    css_all = lambda x: selector.css(x).getall()

    data = {}
    # Meta data
    data["url"] = str(response.url)

    # Basic information
    data["title"] = css("h1 .main-info__title-main::text")
    data["location"] = css(".main-info__title-minor::text")
    data["currency"] = css(".info-data-price::text")
    data["price"] = int(css(".info-data-price span::text").replace(",", ""))
    data["description"] = "\n".join(css_all("div.comment ::text")).strip()
    data["updated"] = (
        selector.xpath("//p[@class='stats-text']" "[contains(text(),'updated on')]/text()").get("").split(" on ")[-1]
    )

    # Features
    data["features"] = {}
    #  first we extract each feature block like "Basic Features" or "Amenities"
    for feature_block in selector.css(".details-property-h2"):
        # then for each block we extract all bullet points underneath them
        label = feature_block.xpath("text()").get()
        features = feature_block.xpath("following-sibling::div[1]//li")
        data["features"][label] = ["".join(feat.xpath(".//text()").getall()).strip() for feat in features]

    # Images
    # the images are tucked away in a javascript variable.
    # We can use regular expressions to find the variable and parse it as a dictionary:
    image_data = re.findall(r"fullScreenGalleryPics\s*:\s*(\[.+?\]),", response.content)[0]
    # we also need to replace unquoted keys to quoted keys (i.e. title -> "title"):
    images = json.loads(re.sub(r"(\w+?):([^/])", r'"\1":\2', image_data))
    data["images"] = defaultdict(list)
    data["plans"] = []
    for image in images:
        url = urljoin(str(response.url), image["imageUrl"])
        if image["isPlan"]:
            data["plans"].append(url)
        else:
            data["images"][image["tag"]].append(url)
    return data


@managed
async def scrape_provinces(urls: List[str]) -> List[str]:
    """
    Scrape province pages like:
    https://www.idealista.com/en/venta-viviendas/balears-illes/con-chalets/municipios
    for search page urls like:
    https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/
    """
    # Add province pages to a scraping list
    to_scrape = [Request(url, **BASE_CONFIG, render=True, ) for url in urls]
    search_urls = []

    for _ in range(3):  # retry falied requests
        async for response in CLIENT.fetch_many(to_scrape):
            parsed_urls = parse_province(response)
            if parsed_urls:
                search_urls.extend(parsed_urls)

        if search_urls:
            break
        else:
            log.debug("No results retrieved, retrying...")

    log.success(f"Scraped {len(search_urls)} search URLs")
    return search_urls


def parse_search_data(response: Response) -> List[Dict]:
    """parse search result data"""
    selector = response.selector
    total_results = selector.css("h1#h1-container").re(": (.+) houses")[0]
    max_pages = math.ceil(int(total_results.replace(",", "")) / 30)
    max_pages = 60  if max_pages > 60 else max_pages
    search_data = []
    for box in selector.xpath("//section[contains(@class, 'items-list')]/article[contains(@class, 'item')]"):
        ad = box.xpath(".//p[@class='adv_txt']") # ignore ad listings
        if ad:
            continue
        price = box.xpath(".//span[contains(@class, 'item-price')]/text()").get()
        parking = box.xpath(".//div[contains(@class, 'item-detail-char')]/span[contains(text(), 'Parking')]").get()
        company_url = box.xpath(".//picture[@class='logo-branding']/a/@href").get()
        search_data.append({
            "title": box.xpath(".//div/a/@title").get(),
            "link": "https://www.idealista.com" + box.xpath(".//div/a/@href").get(),
            "picture": box.xpath(".//img/@src").get(),
            "price": int(price.replace(",", '')) if price else None,
            "currency": box.xpath(".//span[contains(@class, 'item-price')]/span/text()").get(),
            "parking_included": True if parking else False,
            "details": box.xpath(".//div[contains(@class, 'item-detail-char')]/span[not(contains(text(), 'Parking'))]/text()").getall(),
            "description": box.xpath(".//div[contains(@class, 'item-description')]/p/text()").get().replace('\n', ''),
            "tags": box.xpath(".//div[@class='listing-tags-container']/span/text()").getall(),
            "listing_company": box.xpath(".//picture[@class='logo-branding']/a/@title").get(),
            "listing_company_url": "https://www.idealista.com" + company_url if company_url else None
        })

    return {"max_pages": max_pages, "search_data": search_data}


def parse_search(response: Response) -> List[str]:
    """Parse search result page for 30 listing URLs"""
    selector = response.selector
    urls = selector.css("article.item .item-link::attr(href)").getall()
    return [urljoin(str(response.url), url) for url in urls]


@managed
async def scrape_properties(urls: List[str]) -> List[PropertyResult]:
    """Scrape Idealista.com properties"""
    properties = []
    # add all property pages to a scraping list
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    async for response in CLIENT.fetch_many(to_scrape):
        # skip invalid property pages
        if response.upstream_status_code != 200:
            log.warning(f"can't scrape property: {response.url}")
            continue
        properties.append(parse_property(response))
    log.success(f"scraped {len(properties)} property listings")
    return properties


@managed
async def crawl_search(url: str, max_scrape_pages: int = None) -> List[str]:
    """
    Crawl search urls like:
    https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/
    for proprety urls
    :param url: Search URL
    :param scrape_all_pages: Whether to scrape all pages found in search result:
    :param max_scrape_pages: Number of max pages to scrape
    """
    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    property_urls = parse_search(first_page)
    total_results = first_page.selector.css("h1#h1-container").re(": (.+) houses")[0]
    total_pages = math.ceil(int(total_results.replace(",", "")) / 30)
    if total_pages > 60:
        log.info(f"search contains more than max page limit ({total_pages}/60)")
        total_pages = 60
    # scrape all available pages in the search if max_scrape_pages is None or max_scrape_pages > total_pages
    if max_scrape_pages and max_scrape_pages < total_pages:
        total_pages = max_scrape_pages
    else:
        total_pages = total_pages
    log.info(f"scraping {total_pages} of search results concurrently")
    # add the search pages to a scraping list
    to_scrape = [
        Request(first_page.url + f"pagina-{page}.htm", **BASE_CONFIG)
        for page in range(2, total_pages + 1)
    ]
    async for response in CLIENT.fetch_many(to_scrape):
        property_urls.extend(parse_search(response))

    max_properties = max_scrape_pages * 20 if max_scrape_pages else len(property_urls)
    if len(property_urls) > max_properties:
        property_urls = property_urls[:max_properties]
        log.info(f"limited to {max_properties} properties based on max_scrape_pages={max_scrape_pages}")

    # then scrape all property pages found in the search pages
    log.info(f"scraping {len(property_urls)} of proeprty pages concurrently")
    properties = await scrape_properties(urls=property_urls)
    return properties


@managed
async def scrape_search(url: str, max_scrape_pages: int = None) -> List[Dict]:
    """scrape Idealista search results"""
    first_page = await CLIENT.fetch(Request(url, **BASE_CONFIG))
    data = parse_search_data(first_page)
    search_data = data["search_data"]
    max_pages = data["max_pages"]

    # get the number of total pages to scrape
    if max_scrape_pages and max_scrape_pages < max_pages:
        max_pages = max_scrape_pages

    # scrape the remaining pages concurrently
    to_scrape = [
        Request(url + f"pagina-{page}.htm", **BASE_CONFIG)
        for page in range(2, max_pages + 1)
    ]
    log.info(f"scraping search pagination, {max_pages - 1} pages remaining")

    async for response in CLIENT.fetch_many(to_scrape):
        # skip invalid property pages
        search_data.extend(parse_search_data(response)["search_data"])
    log.success(f"scraped {len(search_data)} property listings from search pages")
    return search_data
