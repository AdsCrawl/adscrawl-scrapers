# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This example run script shows how to run the Aliexpress.com scraper defined in ./aliexpress.py
It scrapes product data and product search and saves it to ./results/

To run this script set the env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import run as run_scraper
import asyncio
from datetime import datetime
import json
from pathlib import Path
import realtorcom

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


async def run():

    realtorcom.BASE_CONFIG["country"] = "US"

    print("running Realtor.com scrape and saving results to ./results directory")

    url = "https://www.realtor.com/realestateandhomes-detail/12355-Attlee-Dr_Houston_TX_77077_M70330-35605"
    result_property = await realtorcom.scrape_property(url)
    output.joinpath("property.json").write_text(json.dumps(result_property, indent=2))

    result_search = await realtorcom.scrape_search("CA", "San-Francisco", max_pages=2)
    output.joinpath("search.json").write_text(json.dumps(result_search, indent=2))

    url = "https://cdn.realtor.ca/sitemap/realtorsitemap/sitemap.xml"
    result_feed = await realtorcom.scrape_feed(url)
    output.joinpath("feed.json").write_text(json.dumps(result_feed, indent=2, cls=DateTimeEncoder))


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSONEncoder subclass that knows how to encode datetime values."""

    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()  # Convert datetime objects to ISO-8601 string format

        return super(DateTimeEncoder, self).default(o)  # Default behaviour for other types


if __name__ == "__main__":
    run_scraper(run())
