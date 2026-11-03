# Amazon.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [amazon.py](./amazon.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd amazon-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_search`
- `scrape_reviews`
- `scrape_product`

## US route notes (2026-11-03 retest)

Search passed. Product pages are fetched one at a time with a 120s timeout and
one retry, and at most two variants. The live product test uses the PS5 slim
`B0CL61F39H` and the 2024 MacBook `B0CX22ZW1T`. Atomic Habits (`0735211299`) and
the fabric multipack (`B01GCLS32M`) each timed out on that run and are not in
the live product set.

`B0BCNKKZ91` (PlayStation 5 CFI-1215A01X) returns HTTP 404 on
`/product-reviews/`. Reviews now use `B0CL61F39H`. If a reviews URL 404s, the
scraper tries the `/dp/{ASIN}` page once. An empty review list still fails
`assert len(result) != 0`. This ASIN change has not been re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest amazon-scraper/test.py -v
```

Search passed on the 2026-11-03 US-route retest. Product and reviews did not;
see the notes above. Historical files in `results/` are upstream examples, not
outputs from that retest.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/amazon-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
