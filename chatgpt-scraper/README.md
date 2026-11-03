# ChatGPT.com Scraper

Python examples powered by the [AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
The parser is in [chatgpt.py](./chatgpt.py); [run.py](./run.py) demonstrates usage.

## Install and run

From the repository root, using Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd chatgpt-scraper
python run.py
```

Remote browsers are created through `AsyncAdsCrawl.cdp.create` (Air France uses
`AdsCrawl.cdp.create`). Playwright controls the returned CDP connection. You do
not need to download or launch a local Chromium browser.

## Entry points

- `scrape_conversation`

## Validation

Run the credential-free repository checks with `python -m pytest tests` from the root.
To run this site's **live** tests (uses AdsCrawl credits):

```bash
python -m pytest chatgpt-scraper/test.py -v
```

The 2026-10-27 audit passed this site once. The 2026-11-03 re-run failed twice:
the browser action timed out, then the captured page was an empty string. The
scraper no longer treats `button[data-composer-submit]` existing as a finished
answer. It fills the composer, clicks an enabled send control, and reads the
assistant message. That change has **not** been live re-verified.

From the repository root, with a US route:

```bash
export ADSCRAWL_API_KEY="your_api_key"
export ADSCRAWL_DEFAULT_COUNTRY=US
export ADSCRAWL_CONCURRENCY=1
SELECTED_SCRAPER=chatgpt-scraper python scripts/live_test.py
```

Historical files in `results/` are earlier examples, not output from that
re-run. Review the prompt in `run.py` first.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/chatgpt-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
