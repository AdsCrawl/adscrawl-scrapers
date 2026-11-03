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

Rent and search passed. For-sale HTML navigation timed out, then the stingray
fallback failed on the first `ERR_TUNNEL_CONNECTION_FAILED` (a later run reported
a connect failure after the timeouts stacked).

For-sale now requests the stingray detail APIs first, on the same US route as
search. `initialInfo` is retried once. If it still fails, `aboveTheFold` is
called with the property id from the URL (`/home/46456`). `mainHouseInfoPanelInfo`
and `belowTheFold` are optional. The HTML document is opened only when those
API calls do not return an address. This order has not been re-run live.

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
