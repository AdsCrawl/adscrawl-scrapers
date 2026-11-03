# Allegro.pl Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [allegro.py](./allegro.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd allegro-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_search`
- `scrape_product`

Requests set `countryCode` to `PL` and `locale` to `pl-PL`, and send
`Accept-Language: pl-PL`. Each target page is fetched after `https://allegro.pl/`
on the same session. Allegro is a Poland-only marketplace (`allegro.pl`); a US
exit answers HTTP 403 before any HTML is parsed.

The 2026-11-03 US-route retest still returned HTTP 403 for product and search
with `countryCode=PL` already set. A 403 whose body contains listing or offer
JSON is parsed. A 403 block page is raised as an anti-bot error, not returned
as an empty catalog. That block is not fixed here. Other sites in this
repository stay on US unless they document a different code.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest allegro-scraper/test.py -v
```

The 2026-11-03 US-route retest failed both live tests with HTTP 403. Treat a
later 403 the same way: it is an anti-bot block, not a passing empty scrape.
Historical files in `results/` are upstream examples, not outputs from that retest.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/allegro-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
