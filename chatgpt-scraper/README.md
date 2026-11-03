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

The 2026-10-27 audit passed this site once. An earlier 2026-11-03 run timed out,
then returned an empty string. Commit `ddd17ac` was re-checked the same day on
the US route and did **not** pass. `scripts/smoke.py` still passed. Run 1
exited 1 in about 15s with `ScrapeError` `ERR_TUNNEL_CONNECTION_FAILED`. Run 2
exited 1 in about 83s with `ScrapeError` `ACTION_FAILED`. Direct checks of
chatgpt.com hit that tunnel error or a blank page with no chat UI.
`EMPTY_ANSWER` did not occur. The answer-capture change on that commit did not
run, so it is not live-verified.

Commit `2669477` was retested on the US route. The guest page already showed
"The capital of France is Paris." and `live_test` still exited 1 after about
85s with `ACTION_FAILED` before that reply was returned. Capture then started
reading a reply already on the page, including a guest `/uc/` layout without an
assistant role attribute, and does not require a stop button.

Commit `ef4cc2b` was retested on the US route with `ADSCRAWL_CHATGPT_COUNTRY`
unset. It exited 1 after about 35s. `scrape_conversation` logged success, and
`assert "Paris" in result` failed. The returned string was nav and disclaimer
chrome (`ChatGPT is AI and can make mistakes. ChatGPT New chat Images Plugins
See plans and pricing Help Deep research Settings`), not the assistant reply.
There was no `ScrapeError` and no new failure screenshot. Capture after that
commit ignores that chrome and waits until an assistant reply is stable. That
change has not been live re-verified.

`countryCode` stays `US` unless `ADSCRAWL_CHATGPT_COUNTRY` is set.
`ADSCRAWL_DEFAULT_COUNTRY` does not replace it. From the repository root:

```bash
export ADSCRAWL_API_KEY="your_api_key"
export ADSCRAWL_DEFAULT_COUNTRY=US
export ADSCRAWL_CONCURRENCY=1
SELECTED_SCRAPER=chatgpt-scraper python scripts/live_test.py
```

To try another route for this site only, add `export ADSCRAWL_CHATGPT_COUNTRY=GB`
before that command. Leave it unset to stay on US.

On `ERR_*`, `TIMEOUT`, and `ACTION_FAILED`, a redacted page URL, the page
title, and a screenshot are written under `artifacts/scrape-failures/`
(gitignored). Do not commit that directory.

Historical files in `results/` are earlier examples, not output from that
re-run. Review the prompt in `run.py` first.

## Source and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers/tree/f8db50104853ca8db0d1c4685c616e8107751fd4/chatgpt-scraper).
See [NOTICE](../NOTICE), [LICENSE](../LICENSE) and [migration notes](../docs/MIGRATION.md).
This derivative is distributed under OSL-3.0. Original contributor metadata is
preserved in [upstream-metadata.json](../docs/upstream-metadata.json).
