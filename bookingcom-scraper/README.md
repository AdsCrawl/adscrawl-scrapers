# Booking.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [bookingcom.py](./bookingcom.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd bookingcom-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `search_location_suggestions`
- `scrape_search`
- `scrape_hotel`
- `scrape_hotel_reviews`

## US route notes (2026-11-03 retest)

Hotel and hotel-review tests passed. Search for Malta returned 25 unique hotels
while the test requires at least 50. Three GraphQL pages were requested, but
every page shared one request body, so each page used the last offset. Each
offset is now its own body, pages are requested in order, and a later page that
only repeats hotels already scraped stops the loop. The `>= 50` assertion is
unchanged. This pagination fix has not been re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest bookingcom-scraper/test.py -v
```

Hotel and hotel reviews passed on the 2026-11-03 US-route retest. Search did
not; see the notes above. Historical files in `results/` are upstream examples,
not outputs from that retest.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/bookingcom-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
