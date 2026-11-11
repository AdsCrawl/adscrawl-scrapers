# Google Play Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [google_play.py](./google_play.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd google-play-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create`; Playwright controls
the returned CDP connection. App and search GET requests can fall back once to
the SDK's `/html` endpoint after a transient CDP failure. Reviews use browser-side
POST requests. You do not need a local Chromium installation. Both API paths consume
AdsCrawl credits.

## Entry points

- `scrape_apps`
- `scrape_reviews`
- `scrape_search`

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest google-play-scraper/test.py -v
```

On November 11, 2026, all three live tests passed on the US route: metadata for
WhatsApp and Spotify, WhatsApp reviews, and app search. The HTML fallback was also
checked with an injected CDP failure followed by a real US HTML API request.
[Dated evidence and limitations](../docs/live-verification/2026-11-11.md).

Missing app data raises `DATA_MISSING` instead of returning an empty app or silently
omitting it from a batch. Sites and routes can change; a dated pass is not a service
guarantee. Historical files in `results/` were not replaced by this retest.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/google-play-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
