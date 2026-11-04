# DHL Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [dhl.py](./dhl.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd dhl-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_tracking`

## Anti-bot limits

`https://www.dhl.com/utapi` answers HTTP 428 (`sec-cp-challenge`) for a direct request, including the Unified Tracking demo `7777777770`. The scraper does not open that URL. It renders the public tracking page and reads a solved shipment document or `#panel_events`. A challenge, a not-found message, or a page with no events is not a successful shipment.

On the US route (2026-11-03) the 428 response was gone. `EXAMPLE_TRACKING_NUMBER` (`146000018487`, the local id from a 2026-05-20 capture of a shipment delivered 2026-04-29) returned no shipment: the result panel did not render (`ACTION_FAILED`, classification `semantic-mismatch`). DHL drops most delivered ids about 90 days after the last event. Public pages only show format samples (`1234567890`, `7777777770`), which are not live shipments, and no replacement with a visible event list could be confirmed. The number is unchanged. The live test still requires `classification == "success"` and at least one event, so this example fails until a current public shipment exists.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest dhl-scraper/test.py -v
```

This site has been migrated at source level. Live website behavior is **not yet
verified** with AdsCrawl. Websites can change selectors, require sign-in, or
reject a browser session. Historical files in `results/` are upstream examples,
not outputs from a verified AdsCrawl run. Review URLs and dates in `run.py` first.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/dhl-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
