# Goibibo Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [goibibo.py](./goibibo.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd goibibo-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_hotel_search`
- `scrape_flight_search`

## Country and concurrency

Requests set `countryCode` to `IN`. Goibibo is an India marketplace. A US exit leaves the flight search shell idle and the hotel listing call missing.

A failed hotel or flight attempt closes its named browser session before the next attempt. With `ADSCRAWL_CONCURRENCY=1`, leaving that session open makes the retry raise `SESSION_LIMIT`. The first US retest passed hotel and flight only at `ADSCRAWL_CONCURRENCY=2`.

On the tip3 credits rerun at concurrency 1, hotel search passed. Flight did not. The in-page `fetch()` of `search-stream-dt` raised `BROWSER_ERROR` on the results page (the script set `Origin` and `Referer`, which `fetch()` rejects, and it threw away non-200 bodies). The fallback then blocked on `waitForResponse` until the 120s timeout. Those forbidden headers are no longer set, the script returns the status and body, and the rendered fallback records whatever `search-stream-dt` call the page made, then retries that rendered page once. It does not navigate onto the stream host. Hotel capture is unchanged. This flight change has not been re-run live. `countryCode` stays `IN`.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest goibibo-scraper/test.py -v
```

Hotel and flight search passed on the 2026-11-03 US-route retest at
`ADSCRAWL_CONCURRENCY=2` and `countryCode=IN`. On the tip3 credits rerun at
concurrency 1, hotel passed and flight did not. The flight change above is not
a live pass. Historical files in `results/` are upstream examples, not outputs
from those retests.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/goibibo-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
