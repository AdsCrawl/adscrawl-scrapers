# Verification record

Date: 2026-10-27. Local environments: Python 3.10.16 and 3.12.14, adscrawl 0.1.0,
Playwright 1.64.1. Source snapshot: f8db50104853ca8db0d1c4685c616e8107751fd4.

## Offline checks

- `python -m pytest tests -q`: 20 tests passed on both local Python versions.
- `python scripts/check_catalog.py`: all 81 site modules imported without a key;
  catalog entry points and request options passed source/configuration checks.
- `python -m build --no-isolation`: source distribution and wheel built locally.

CI also tests Python 3.13. Current run results are available in
[GitHub Actions](https://github.com/AdsCrawl/adscrawl-scrapers/actions/workflows/offline.yml).
The initial CI run exposed a pre-3.12 f-string syntax incompatibility in Similarweb;
it was corrected and rechecked with the Python 3.10 interpreter.

Tests cover browser lifecycle, named-session scopes, bounded batches, error and
cancellation cleanup, remote POST routing, completed XHR capture, actions, Unicode
attachments, HTML/JSON parsers, compressed sitemaps and image bytes. They use
fixtures/mocks and do not prove every website currently works.

## Real AdsCrawl requests

The following bounded checks used the official SDK and real remote browsers:

| Check | Result |
| --- | --- |
| example.com rendered HTML | HTTP 200; title `Example Domain` |
| postman-echo.com remote JSON POST | HTTP 200; submitted test JSON echoed correctly |
| App Store `scrape_app_metadata("6448311069", "us")` | Returned app ID `6448311069`, title `ChatGPT` |
| Session cleanup after these operations | SDK close completed without error |

The iTunes attachment response initially failed ordinary browser navigation.
It now uses remote browser-side byte fetching, with UTF-8 decoding for JSON/text,
and the metadata smoke test passed after that change. No API keys, CDP connection
URLs or user cookies are recorded here. Historical result files were not replaced.

## Not established by these checks

The complete live suites for all 81 sites have **not** been run. Current selectors,
anti-bot behavior, access requirements, pagination and output schemas may need
site-specific updates. In particular, Google AI Mode's configurable DOM selectors
and Air France's form flow have not been live-validated in this migration.
Live tests remain opt-in and consume AdsCrawl credits. CI runs only offline checks
unless the manual live workflow is explicitly selected.
