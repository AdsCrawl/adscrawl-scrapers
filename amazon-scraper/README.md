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

## US route notes (2026-11-03 retests)

Product pages are fetched one at a time. The live product set is the PS5 slim
`B0CL61F39H` and the 2024 MacBook `B0CX22ZW1T`. On the tip2 retest both pages
scraped, and `style` was `""` because the inline-twister span was empty. Style
is now read from that span, the variation selection, the product-overview row,
and `dimensionValuesDisplayData`. When the page has none of those, `style` is
`null` (not `""`). A nullable style with no `min_presence` counts that null as
present. Name, images, and the other fields keep their presence checks.

Search page 2 of `k=kindle` was HTTP 503 after one retry on a fresh browser.
Later pages reuse the first page's session and, if that session is still
blocked, try once on a new session. The `len(result) > 30` assertion is unchanged.

`/product-reviews/B0CL61F39H` was HTTP 404 and the product page never rendered
the review widget (6 attempts). Reviews are requested from
`/hz/reviews-render/ajax/reviews/get/` first. The live example ASIN is Atomic
Habits `0735211299`. `assert len(result) != 0` stays. This path has not been
re-run live.

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
