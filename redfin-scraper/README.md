# Redfin.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [redfin.py](./redfin.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd redfin-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_search`
- `scrape_property_for_sale`
- `scrape_property_for_rent`

## US route notes (2026-11-03 retest)

Rent and search passed. For-sale HTML navigation timed out on the first retest.
On the tip2 retest the direct stingray call (`render=False`) returned HTTP 403,
then the property document was the 2 KB noscript shell with no property data.

For-sale now opens the property page on a session first and keeps any
`aboveTheFold` response the page captured. The detail APIs are then requested
like the GIS search that passed: a normal US navigation on that session, not
`render=False`. `initialInfo` and a 403 are retried once. If `initialInfo`
fails, `aboveTheFold` uses the property id from the URL. This has not been
re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest redfin-scraper/test.py -v
```

Rent and search passed on the 2026-11-03 US-route retest. For-sale did not; see
the notes above. Historical files in `results/` are upstream examples, not
outputs from that retest.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/redfin-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
