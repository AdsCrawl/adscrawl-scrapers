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

## US route notes (through tip4, `37d4c7d`)

Product pages are fetched one at a time. The live product set is the PS5 slim
`B0CL61F39H` and the 2024 MacBook `B0CX22ZW1T`. On the tip3 retest both pages
scraped. `style` is fixed (`Space Gray` on the MacBook, `null` on the PS5).
`description` was still `""` on both: the old selector only read
`#productDescription p span`. Description now also reads a bare
`#productDescription` paragraph, the book description block, a
`productDescription` string in the page, Product/Book JSON-LD, and A+
paragraphs. Feature bullets stay on `features`. `min_presence` for description
stays 0.01. This parser has not been re-run live.

Search page 1 of `k=kindle` was HTTP 503 after the one same-session retry.
That first page now gets one more attempt on a new session, against
`/gp/search` with `ref=nb_sb_noss`. Later pages still reuse the session and
rotate once if that session stays blocked. `len(result) > 30` is unchanged.
Not re-run live.

Reviews for Atomic Habits `0735211299` navigated onto
`/hz/reviews-render/ajax/reviews/get/` and failed with
`ERR_HTTP_RESPONSE_CODE_FAILURE`. The reviews HTML pages then rendered zero
cards. The XHR is now `fetch()`'d from the product document, and JSON-LD
`Review` nodes count when the widget is absent. `assert len(result) != 0`
stays.

On the tip4 retest the PS5 product page hit a remote-browser TIMEOUT. Closing
that browser then failed (`CLEANUP_FAILED`) and the shared client stayed bound
to the dead pytest loop, so search and reviews raised `Close the client before
using it on another event loop` without running. A failed one-shot close now
drops the session and keeps the original TIMEOUT, which is retried once.
`CLEANUP_FAILED` resets the client before that retry. Product navigation uses
`waitUntil=commit` and still waits for `#productTitle`. This has not been
re-run live.

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest amazon-scraper/test.py -v
```

Search passed on the first 2026-11-03 US-route retest and failed on tip3
(page 1 HTTP 503). Tip4 did not reach search or reviews: the product timeout
poisoned the shared client. The client reset above is not a live pass.
Historical files in `results/` are upstream examples, not outputs from those
retests.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/amazon-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
