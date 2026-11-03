# Target.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [target.py](./target.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd target-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_product`
- `scrape_availability`
- `scrape_store_locations_sitemap`
- `scrape_store_locations`
- `scrape_search`

## Anti-bot limits

On the US route (2026-11-03) product, search, and the store sitemap returned data. Availability and store locations did not: opening a `redsky.target.com` URL as the document is HTTP 435. Those two calls now run `fetch()` from a warmed `target.com` page, with two further sessions after a block. If redsky is still 435, availability falls back to the product page (shipping/stock on that page, not store inventory) and store locations fall back to the public `/sl/{slug}/{id}` page. A 435 that leaves no page data is still an error. The in-page fetch and the HTML fallback have not been confirmed live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest target-scraper/test.py -v
```

This site has been migrated at source level. Live website behavior is **not yet
verified** with AdsCrawl. Websites can change selectors, require sign-in, or
reject a browser session. Historical files in `results/` are upstream examples,
not outputs from a verified AdsCrawl run. Review URLs and dates in `run.py` first.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/target-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
