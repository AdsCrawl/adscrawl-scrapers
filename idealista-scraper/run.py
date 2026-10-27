# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the idealista.com scraper defined in ./idealista.py
It scrapes ads data and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
import json
from pathlib import Path
import idealista

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)

async def run():


    print("running Idealista scrape and saving results to ./results directory")

    search_urls = await idealista.scrape_provinces(
        urls = ["https://www.idealista.com/venta-viviendas/almeria-provincia/municipios"]
    )
    with open(output.joinpath("search_URLs.json"), "w", encoding="utf-8") as file:
        json.dump(search_urls, file, indent=2, ensure_ascii=False)

    properties_data = await idealista.scrape_properties(
        urls=[
            "https://www.idealista.com/en/inmueble/109061254/",
            "https://www.idealista.com/en/inmueble/109300670/",
            "https://www.idealista.com/en/inmueble/102051911/",
            "https://www.idealista.com/en/inmueble/99394819/",
            "https://www.idealista.com/en/inmueble/104741954/",
        ]
    )
    with open(output.joinpath("properties.json"), "w", encoding="utf-8") as file:
        json.dump(properties_data, file, indent=2, ensure_ascii=False)

    crawl_data = await idealista.crawl_search(
        url="https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/",
        # remove the max_scrape_pages paremeter to scrape all pages
        max_scrape_pages=2
    )
    with open(output.joinpath("crawl.json"), "w", encoding="utf-8") as file:
        json.dump(crawl_data, file, indent=2, ensure_ascii=False)


    search_data = await idealista.scrape_search(
        url="https://www.idealista.com/en/venta-viviendas/marbella-malaga/con-chalets/",
        # remove the max_scrape_pages paremeter to scrape all pages
        max_scrape_pages=3
    )
    with open(output.joinpath("search_data.json"), "w", encoding="utf-8") as file:
        json.dump(search_data, file, indent=2, ensure_ascii=False)



if __name__ == "__main__":
    run_scraper(run())
