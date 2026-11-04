# Allegro.pl Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [allegro.py](./allegro.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd allegro-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_search`
- `scrape_product`

Requests set `countryCode` to `PL` and `locale` to `pl-PL`, and send
`Accept-Language: pl-PL`. Allegro is a Poland-only marketplace (`allegro.pl`).

This is blocked on the routes that have been tried. A US exit returns HTTP 403.
The tip2 US retest, already on `countryCode=PL` with locale `pl-PL`, a Polish
`Accept-Language`, and a homepage session, was still HTTP 403. Tip3 did not
retest Allegro. There is no residential-proxy field on `Request`. The listing
now uses one short homepage warmup (20s; a timeout still continues), a Windows
`userAgentOs`, and `Referer: https://allegro.pl/` on the same session. A 403
body that actually contains listing or offer JSON is parsed. A 403 block page
is raised as an anti-bot error and is not an empty catalog or a pass. That
warmup has not been re-run live. Other sites stay on US unless they document a
different code.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest allegro-scraper/test.py -v
```

Both live tests failed with HTTP 403 on the 2026-11-03 US retest and again on
the tip2 retest. Tip3 did not retest Allegro. Treat a later 403 the same way:
it is an anti-bot block, not a passing empty scrape. Historical files in
`results/` are upstream examples, not outputs from those retests.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/allegro-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
