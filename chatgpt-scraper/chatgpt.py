# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for chatgpt.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
from pathlib import Path
from urllib.parse import quote_plus

from loguru import logger as log
from adscrawl_scrapers import Request, ScraperClient


CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",

}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


js_scenario = [
    {"type": 'click', 'selector': "#credentials-picker-container #close", 'multiple': False, "optional": True},
    {"type": 'click', 'selector': "div[aria-live='polite'] button:first-of-type", 'multiple': False, "optional": True},
    {"type": 'waitForSelector', 'selector': "button[data-composer-submit]", 'timeoutMs': 15000},
    {"type": 'condition', 'selector': "button[data-composer-submit]", 'state': "not_existing", 'outcome': "exit_failed"},
    {"type": 'click', 'selector': "button[data-composer-submit]", 'multiple': False},
    {"type": "wait", "milliseconds": 10000},
    {"type": 'condition', 'selector': "button[data-composer-submit]", 'state': "existing", 'outcome': "exit_success"},
    {"type": "wait", "milliseconds": 10000},
]


@managed
async def scrape_conversation(prompt: str) -> str:
    url = f"https://chatgpt.com/?prompt={quote_plus(prompt)}"
    log.info("scraping conversation for prompt: {}", prompt)
    response = await CLIENT.fetch(
        Request(
            url=url,
            contentMode="markdown",
            render=True,
            actions=js_scenario,
            waitMs=5000,
            **BASE_CONFIG,
        )
    )
    log.success("finished scraping ChatGPT for the prompt: {}", prompt)
    return response.content
