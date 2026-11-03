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

Opening a `redsky.target.com` URL as the document is HTTP 435. Availability, store locations, product, and search call that API with `fetch()` from a warmed `target.com` page instead of navigating to it. Availability and store locations passed that way on the US route (2026-11-03, second retest). Product still returned HTTP 435 from `deferred_enrichment/modules` after one retry, and search hit the 90s deadline on `https://www.target.com/s?searchTerm=laptop`.

Product now loads the PDP in the homepage session (up to three sessions). A 435, a timeout, or a failed modules wait uses `product_summary_with_fulfillment_v1` in that page, priced at store `1771` / zip `52404`. Ratings are absent on that summary. Search waits 45s for a product card inside a 120s navigation (`waitUntil=commit`). A timeout, a block, or a page with no cards uses `plp_search_v2` the same way. An empty API body is still an error, and a 435 that leaves no page data is still an error. The product and search fallbacks have not been confirmed live. The availability HTML fallback remains the product page (shipping and stock, not store inventory). Store locations still fall back to `/sl/{slug}/{id}`.

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
