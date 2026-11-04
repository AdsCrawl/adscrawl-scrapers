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

## US route notes (through tip7)

Tip6 (`74d70d7`, concurrency 1, US, no 402) passed product and search. Those two
paths are unchanged below. Reviews failed and are the only tip7 change.

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
  retried the same way. Tip6 product passed. This path was not edited again.
- Search `k=kindle` was HTTP 503 on `/s` (including the same-session retry) and
  again on `/gp/search?k=kindle&ref=nb_sb_noss`. The first page now warms
  `https://www.amazon.com/` on the session, keeps that `/s` plus `/gp/search`
  path, then requests `/s/query` (`render=False`, `X-Requested-With`) and parses
  `s-search-result` cards out of the `&&&` body. A later page that still fails
  keeps the previews already parsed. `len(result) > 30` is unchanged. Tip6
  search passed. This path was not edited again. If `/s/query` is also HTTP
  503, search still fails.
- Reviews for Atomic Habits `0735211299` did not return a document on tip6.
  The product-page script started at 13:00:37 and the same-session retry was
  not logged until 13:08:53 (`TIMEOUT`). The retry then timed out at 90s.
  `product-reviews/...?reviewerType=all_reviews` timed out twice as well
  (`TIMEOUT HTTP 0`). `assert 0 != 0`. The in-page `fetch` now aborts each
  reviews endpoint after 8s. The document uses `waitUntil=commit` and a 45s
  budget, the same commit navigation that returned the product pages. A timeout
  closes that browser and retries once on a new session. The dedicated reviews
  URL no longer scrolls and no longer waits for `domcontentloaded`.
  `assert len(result) != 0` stays. This reviews change has not been re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest amazon-scraper/test.py -v
```

Search passed on the first 2026-11-03 US-route retest, failed on tip3 and
tip5, and passed on tip6 with product. Reviews are still open. The tip7 reviews
change is not a live pass.
Historical files in `results/` are upstream examples, not outputs from those
retests.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/amazon-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
