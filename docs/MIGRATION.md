# Migration notes

Source revision: `f8db50104853ca8db0d1c4685c616e8107751fd4`.
All 81 directories and their parser/test/example files are retained.

## Request behavior

| Upstream behavior | AdsCrawl implementation |
| --- | --- |
| Request authentication | Official `adscrawl` SDK, `ADSCRAWL_API_KEY` |
| Country routing | `browserSettings.countryCode`, normalized to uppercase |
| Browser rendering | SDK-created CDP session and Playwright page |
| POST/body/headers | Remote navigation interception; no local HTTP transport |
| JSON, text, binary | Main response body; binary also available as `Response.raw` |
| Browser actions | Explicit `type` actions, executed by Playwright |
| JavaScript evaluation | Async page function; result exposed as `Response.javascript` |
| XHR/fetch collection | Listener installed before navigation; `Response.network` |
| Named sessions | Same remote browser and context during one managed operation |
| Batch requests | Bounded task window; errors fail the batch |
| Resource cleanup | SDK DELETE after completion, errors and cancellation |
| Provider cache/debug/proxy-pool/ASP/retry switches | Removed; not accepted as silent no-ops |
| ChatGPT Markdown | Convert rendered main content locally after browser actions |
| Google AI Mode LLM extraction prompt | SDK SPA DOM extraction with required answer field |

The API's country routing is not a promise of a particular upstream proxy pool
or anti-bot product. No automatic billing retries are added. Existing site-level
retry loops may still issue extra requests; inspect the chosen site's code.
A timeout does not prove remote work stopped; cleanup errors are surfaced.

`render=False` requests preserve the main response body rather than the mutated
DOM. The remote browser still runs JavaScript while navigating. `contentMode`
accepts HTML or Markdown. Responses expose `url`, `request_url`, `content`, `raw`,
`headers`, `status_code`, `cookies`, `network`, `javascript`, `selector` and `json()`.

Download endpoints (including iTunes JSON attachments, compressed sitemaps and
images) use `binary=True`: browser-side fetch from a same-origin document returns
bytes through CDP. JSON/XML/text bodies are decoded as UTF-8; other bytes remain
available unchanged in `raw`. This mode does not execute page actions or scripts.

## Sessions and embedding

Site-level async functions use `@managed`: nested helpers share an operation's
session scope, and named sessions close when the outer operation exits. Standalone
scripts use `run()` to close leftover clients even on failure. For custom code use
`async with ScraperClient()` or explicitly await `close()` in a finally block.
Call `close_session(name)` before creating more named sessions than your capacity.
Concurrent top-level operations have independent scopes. Account-wide capacity
can be shared with other processes, so set concurrency conservatively.

Air France's direct synchronous SDK integration closes sessions explicitly even
when CDP connection or form interaction fails.

## Verification boundaries

Offline tests cover transport lifecycle, POST payloads, actions, response parsing,
configuration compatibility and imports for all 81 modules. They do not establish
that third-party selectors, endpoints, access requirements or flight dates remain
valid. Historical `results/` files are attributed upstream samples.

Live tests are opt-in and billable. Review selected entry points before running.
No scheduled live jobs or notification integrations from upstream are enabled.

Google AI Mode now uses deterministic markup extraction instead of an LLM. Its
answer and source-card selectors are configurable through
`ADSCRAWL_GOOGLE_AI_ANSWER_SELECTOR` and `ADSCRAWL_GOOGLE_AI_SOURCES_SELECTOR`.
The default selectors require live verification for your locale. Missing answers
raise an error. Source snippets are null when absent; they are never fabricated.
