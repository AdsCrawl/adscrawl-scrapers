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

## US route notes (through tip6, not live-verified)

Product pages are fetched one at a time. The live product set is the PS5 slim
`B0CL61F39H` and the 2024 MacBook `B0CX22ZW1T`. `style` is `Space Gray` on the
MacBook and `null` on the PS5. Description reads `#productDescription` (including
a bare paragraph), the book description block, a `productDescription` string in
the page, Product/Book JSON-LD, and A+ paragraphs. Feature bullets stay on
`features`. `min_presence` for description stays 0.01.

On tip5 (`5632fb6`, concurrency 1, US, no 402) the shared-client poison from
tip4 was gone. Search and reviews ran after the product failure. There was no
`Close the client before using it on another event loop` error. The three
failures were independent:

- PS5 finished in about 24s. MacBook `B0CX22ZW1T` timed out twice at about 128s.
  The request waited for `#productTitle` with the same 120s budget as the outer
  navigation, so a slow document died as `TIMEOUT`. Product fetches now open
  `https://www.amazon.com/dp/{asin}` with `waitUntil=commit`, `timeoutMs=60000`,
  and no request-level `waitForSelector`. `#productTitle` is a 20s optional
  action. A timeout, tunnel error, or `CLEANUP_FAILED` (after `CLIENT.reset()`)
  is retried, up to three navigations. A page that loads without a title is
  retried the same way. This has not been re-run live.
- Search `k=kindle` was HTTP 503 on `/s` (including the same-session retry) and
  again on `/gp/search?k=kindle&ref=nb_sb_noss`. The first page now warms
  `https://www.amazon.com/` on the session, keeps that `/s` plus `/gp/search`
  path, then requests `/s/query` (`render=False`, `X-Requested-With`) and parses
  `s-search-result` cards out of the `&&&` body. A later page that still fails
  keeps the previews already parsed. `len(result) > 30` is unchanged. Not
  re-run live. If `/s/query` is also HTTP 503, search still fails.
- Reviews for Atomic Habits `0735211299` loaded the product page in about 10s
  and found no `[data-hook=review]` cards. `/product-reviews/0735211299/` was
  then HTTP 404. The in-page script now also POSTs the reviews medley endpoint
  and keeps `review-card` HTML plus JSON objects with `reviewText` or
  `reviewBody`. The fallback reviews URL is the product page's "see all reviews"
  link and reuses the product session. `assert len(result) != 0` stays. Not
  re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest amazon-scraper/test.py -v
```

Search passed on the first 2026-11-03 US-route retest and was HTTP 503 on
tip3 and tip5. Tip4 did not reach search or reviews because the product timeout
poisoned the shared client. Tip5 showed that reset worked and that the three
checks fail on their own. The tip6 request changes above are not a live pass.
Historical files in `results/` are upstream examples, not outputs from those
retests.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/amazon-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
