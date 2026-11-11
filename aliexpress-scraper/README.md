# Aliexpress.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [aliexpress.py](./aliexpress.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd aliexpress-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_search`
- `scrape_product`
- `scrape_product_reviews`
- `find_aliexpress_products`

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest aliexpress-scraper/test.py -v
```

On November 11, 2026, the US product test passed in a targeted run. In the later
full suite, reviews and categories passed, while the product request timed out
and search failed with a proxy tunnel error. This site remains **partially
verified and unstable**. [Dated evidence](../docs/live-verification/2026-11-11.md)
preserves both attempts. Missing product data now raises `DATA_MISSING` instead
of returning an empty product. Historical files in `results/` were not replaced.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/aliexpress-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
