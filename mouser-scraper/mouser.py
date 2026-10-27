# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for Mouser.com using AdsCrawl
https://scrapfly.io/blog/posts/how-to-scrape-mouser

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/
"""
from adscrawl_scrapers import managed

import os
import json
import urllib.parse
from pathlib import Path
from loguru import logger as log
from typing import List, Dict, TypedDict, Optional, Any
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError


CLIENT = ScraperClient()
BASE_CONFIG = {


    'render': True,

}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


class MouserProduct(TypedDict):
    """Mouser product data structure"""
    product_id: str
    part_number: str
    manufacturer_part_number: str
    manufacturer: str
    description: str
    price: str
    currency: str
    availability: str
    stock_quantity: Optional[int]
    images: List[str]
    specifications: Dict[str, Any]
    datasheet_url: Optional[str]
    url: str


class MouserSearch(TypedDict):
    """Mouser search results"""
    products: List[Dict]
    scraped_pages: int
    total_pages: int
    total_count: int


def parse_product(result: Response) -> MouserProduct:
    """Parse Mouser product page for product data"""
    sel = result.selector

    # Extract JSON-LD Product data
    product_json_ld = None

    json_ld_scripts = sel.xpath('//script[@type="application/ld+json"]/text()').getall()
    for json_ld_text in json_ld_scripts:
        try:
            data = json.loads(json_ld_text)
            if data.get("@type") == "Product":
                product_json_ld = data
                break
        except json.JSONDecodeError:
            continue

    sku = mpn = brand = description = ""

    if product_json_ld:
        sku = product_json_ld.get("sku", "")
        mpn = product_json_ld.get("mpn", "")
        brand = product_json_ld.get("brand", "")
        description = product_json_ld.get("description", "")

    offers = product_json_ld.get("offers", {}) if product_json_ld else {}
    price = str(offers.get("price", ""))
    currency = offers.get("priceCurrency", "USD")
    availability = offers.get("availability", "")

    if availability.startswith("http://schema.org/"):
        availability = availability.replace("http://schema.org/", "").replace("InStock", "In Stock")
    stock_quantity = int(offers.get("inventoryLevel", 0))

    images = []
    if product_json_ld and product_json_ld.get("image"):
        image_data = product_json_ld["image"]
        if isinstance(image_data, str):
            images.append(image_data)
        elif isinstance(image_data, list):
            images.extend([img if isinstance(img, str) else img.get("contentUrl", "") for img in image_data])


    specifications = {}
    spec_rows = sel.xpath('//tr[contains(@id, "pdp_specs_SpecList")]')
    for row in spec_rows:
        label = row.xpath('.//td[@class="attr-col"]//label/text()').get()
        if not label:
            label = row.xpath('.//td[@class="attr-col"]/text()').get()

        value = row.xpath('.//td[@class="attr-value-col"]/text()').get()
        if not value:
            value = row.xpath('normalize-space(.//td[@class="attr-value-col"])').get()

        if label and value:
            label = label.strip().rstrip(':')
            value = value.strip()
            if label and value:
                specifications[label] = value

    datasheet_url = sel.xpath('//a[contains(@href, "datasheet")]/@href').get()

    parsed_data = {
        "product_id": sku,
        "part_number": sku,
        "manufacturer_part_number": mpn,
        "manufacturer": brand,
        "description": description,
        "price": price,
        "currency": currency,
        "availability": availability,
        "stock_quantity": stock_quantity,
        "images": images,
        "specifications": specifications,
        "datasheet_url": datasheet_url,
        "url": result.url,
    }

    return parsed_data


@managed
async def scrape_product(urls: list[str]) -> List[MouserProduct]:
    """Scrape Mouser product pages

    Args:
        urls (list[str]): List of Mouser product URLs

    Returns:
        List[MouserProduct]: List of Mouser product data
    """
    to_scrape = [Request(url, **BASE_CONFIG) for url in urls]
    data = []
    async for response in CLIENT.fetch_many(to_scrape):
        if isinstance(response, ScrapeError):
            log.error(f"Error scraping product: {response.error}")
            continue
        try:
            data.append(parse_product(response))
        except Exception as e:
            log.error(f"Error parsing Mouser product : {e}")
            continue
    return data


def parse_search(result: Response) -> MouserSearch:
    """Parse Mouser search page for product listings"""
    sel = result.selector

    total_count_text = sel.xpath('//span[@class="searchResultsCount total-results-value"]/text()').get()
    total_count = 0
    if total_count_text:
        total_count_clean = total_count_text.strip("()").replace(".", "").replace(",", "")
        try:
            total_count = int(total_count_clean)
        except ValueError:
            log.warning(f"Could not parse total count: {total_count_text}")

    # Calculate total pages (25 products per page)
    results_per_page = 25
    total_pages = (total_count + results_per_page - 1) // results_per_page if total_count > 0 else 1

    products = []
    product_rows = sel.xpath('//table[@id="SearchResultsGrid_grid"]//tbody/tr[@data-index]')
    for row in product_rows:
        mouser_part_number = row.xpath('@data-partnumber').get() or ""
        manufacturer = row.xpath('@data-actualmfrname').get() or ""
        mfr_part_number = row.xpath('@data-mfrpartnumber').get() or ""
        description = row.xpath('.//td[contains(@class, "desc-column")]//span/text()').get() or ""
        price = row.xpath('.//span[starts-with(@id, "lblPrice_")]/text()').get() or ""
        stock_amount = row.xpath('.//span[@class="available-amount"]/text()').get() or ""
        stock_status = row.xpath('.//span[@class="avail-status"]/text()').get() or ""
        availability = f"{stock_amount} {stock_status}".strip()
        product_url = row.xpath('.//a[starts-with(@id, "lnkMfrPartNumber_")]/@href').get() or ""

        if product_url and not product_url.startswith("http"):
            base_url = result.url
            if "mouser.com" in base_url:
                if base_url.startswith("http"):
                    domain = "/".join(base_url.split("/")[:3])
                else:
                    domain = "https://eu.mouser.com"
            else:
                domain = "https://eu.mouser.com"
            product_url = domain + product_url if product_url.startswith("/") else product_url

        datasheet_url = row.xpath('.//a[starts-with(@id, "lnkDataSheet_")]/@href').get() or ""

        if mouser_part_number or mfr_part_number:
            products.append({
                "product_id": mouser_part_number,
                "part_number": mouser_part_number,
                "manufacturer_part_number": mfr_part_number,
                "manufacturer": manufacturer,
                "description": description,
                "price": price,
                "availability": availability,
                "url": product_url,
                "datasheet_url": datasheet_url,
            })

    log.info(f"Parsed {len(products)} products from search page")
    data = {
        "products": products,
        "scraped_pages": 1,
        "total_pages": total_pages,
        "total_count": total_count,
    }
    return data


@managed
async def scrape_search(query: str, max_pages: int = 3, scrape_all_pages: bool = False) -> MouserSearch:
    """
    Scrape Mouser search pages for product listings
    Args:
        query: Search query string
        max_pages: Maximum number of pages to scrape (default: 3)
        scrape_all_pages: If True, scrape all available pages (overrides max_pages)
    """
    encoded_query = urllib.parse.quote(query)
    base_url = f"https://www.mouser.com/c/?q={encoded_query}"
    log.info(f"Scraping base url {base_url}")

    first_page = await CLIENT.fetch(Request(base_url, **BASE_CONFIG))

    first_page_data = parse_search(first_page)
    search_results = first_page_data["products"]
    total_pages = first_page_data["total_pages"]
    log.info(f"Found {total_pages} total pages with {first_page_data['total_count']} total products")

    if scrape_all_pages:
        pages_to_scrape = total_pages
    else:
        pages_to_scrape = min(max_pages, total_pages)

    log.info(f"Scraping {pages_to_scrape - 1} additional pages (total: {pages_to_scrape})")
    scraped_pages = 1
    if pages_to_scrape > 1:
        other_pages = [
            Request(f"{base_url}&p={page}", **BASE_CONFIG)
            for page in range(2, pages_to_scrape + 1)
        ]

        log.info(f"Scraping {len(other_pages)} additional pages")
        async for result in CLIENT.fetch_many(other_pages):
            if isinstance(result, ScrapeError):
                log.error("ASP protection failed - skipping page")
                continue
            try:
                page_data = parse_search(result)
                search_results.extend(page_data["products"])
                scraped_pages += 1
            except Exception as e:
                log.error(f"Error parsing search page: {e}")
                continue
        log.success(f"Scraped {len(search_results)} total products from {scraped_pages} pages")

    data = {
        "products": search_results,
        "scraped_pages": scraped_pages,
        "total_pages": total_pages,
        "total_count": first_page_data["total_count"],
    }
    return data

