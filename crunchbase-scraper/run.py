# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Crunchbase.com scraper defined in ./crunchbase.py
It scrapes product data and product search and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
from pathlib import Path
import asyncio
import json
import crunchbase

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():


    print("running Crunchbase scrape and saving results to ./results directory")

    url = "https://www.crunchbase.com/organization/tesla-motors/people"
    company = await crunchbase.scrape_company(url)
    output.joinpath("company.json").write_text(json.dumps(company, indent=2, ensure_ascii=False))

    url = "https://www.crunchbase.com/person/elon-musk"
    person = await crunchbase.scrape_person(url)
    output.joinpath("person.json").write_text(json.dumps(person, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run_scraper(run())
