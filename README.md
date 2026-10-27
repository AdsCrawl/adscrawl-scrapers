# AdsCrawl Scrapers

81 site-specific Python scraper examples powered by the
[AdsCrawl Python SDK](https://github.com/AdsCrawl/adscrawl-python).
Extract products, search results, reviews, real estate, flights and public web
content using remote browsers, HTML/JSON parsers and bounded concurrency.

[Get an API key](https://app.adscrawl.net/dashboard/keys/) ·
[API documentation](https://www.adscrawl.net/docs/) ·
[中文](README.zh-CN.md) · [Migration details](docs/MIGRATION.md)

> All 81 site modules are ported. **All 81 sites have been live-tested** (2026-10-27):
> 15 fully passed, 11 partially passed, and 55 failed. See the
> [dated per-site evidence report](docs/live-verification/2026-10-27.md) and
> [machine-readable results](docs/live-verification/2026-10-27.json).
> Each status reflects the latest recorded attempt; see the report for scope and remaining failures.
> Files in `results/` remain historical upstream examples.

Verified examples from the current audit: **Bing** returned 30 search results and
8 keyword suggestions; **ChatGPT** returned the correct answer to the test prompt.
These checks cover the specific functions recorded in the report, not a blanket
guarantee for every feature or future request.

![ChatGPT live verification through AdsCrawl](docs/live-verification/evidence/chatgpt-answer.png)

<!-- LIVE_VERIFIED_START -->

Current fully passed live suites (2026-10-27)：

| Scraper | Passed live checks |
| --- | --- |
| [app-store](app-store-scraper/) | 2/2 |
| [bing](bing-scraper/) | 2/2 |
| [chatgpt](chatgpt-scraper/) | 1/1 |
| [fashionphile](fashionphile-scraper/) | 2/2 |
| [idealo](idealo-scraper/) | 4/4 |
| [imdb](imdb-scraper/) | 5/5 |
| [imovelweb](imovelweb-scraper/) | 2/2 |
| [reddit](reddit-scraper/) | 4/4 |
| [rightmove](rightmove-scraper/) | 2/2 |
| [shopify](shopify-scraper/) | 5/5 |
| [similarweb](similarweb-scraper/) | 4/4 |
| [ticketmaster](ticketmaster-scraper/) | 2/2 |
| [twitter](twitter-scraper/) | 2/2 |
| [vestiairecollective](vestiairecollective-scraper/) | 2/2 |
| [zillow](zillow-scraper/) | 2/2 |

[Scope, output counts and limitations](docs/live-verification/2026-10-27.md)

<!-- LIVE_VERIFIED_END -->

## Quick start

Python 3.10 or newer is required.

```bash
git clone https://github.com/AdsCrawl/adscrawl-scrapers.git
cd adscrawl-scrapers
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
export ADSCRAWL_API_KEY="your_api_key"
cd amazon-scraper
python run.py
```

Edit `run.py` to choose URLs, dates and page limits before running. Requests
consume AdsCrawl credits. The default limit is two browser sessions per client;
set `ADSCRAWL_CONCURRENCY` to match your account capacity. No local Chromium
installation is necessary. Never commit your API key.

Requests default to a **US** browser route when no country or custom proxy is
specified. Set `ADSCRAWL_DEFAULT_COUNTRY` to change this default. A site's explicit
`countryCode` takes precedence; custom proxies are not combined with country routing.

## How requests run

The shared [transport](src/adscrawl_scrapers/runtime.py) creates browsers using
`AsyncAdsCrawl.cdp.create`, connects Playwright over CDP, captures HTML and
XHR/fetch responses, and closes the remote session with `cdp.close`. POST requests
are issued from the remote browser using navigation interception. Named sessions
reuse cookies, browser storage and the browser connection within one operation.

Site modules keep their parsing and pagination logic, with explicit AdsCrawl
country routing and Playwright actions. Air France uses the synchronous SDK.
Google AI Mode uses `AsyncAdsCrawl.spa.extract` with configurable DOM selectors.
The transport does not accept obsolete provider switches or retry billable
requests automatically; individual example retry loops are documented in the code.

```python
from adscrawl_scrapers import Request, ScraperClient, run

async def main():
    async with ScraperClient() as client:
        page = await client.fetch(Request("https://example.com", countryCode="US"))
        print(page.selector.css("title::text").get())

run(main())
```

## Validation

```bash
python -m pytest tests -q          # offline, no key and no credits
python scripts/check_catalog.py  # imports and request configuration for every site
# Explicit live testing, with ADSCRAWL_API_KEY set:
python -m pytest amazon-scraper/test.py -v
```

See [verification results](docs/VERIFICATION.md) for the checks actually run.

CI runs offline tests on pushes and pull requests. Live tests are available only
through a manual workflow for a selected scraper and require the
`ADSCRAWL_API_KEY` repository secret. There is no scheduled billable test suite.

## Scrapers

Each directory includes source, a runnable example, live schema tests and
historical sample data. See [catalog.json](docs/catalog.json) for the function list.

| Site | Module | Entry points |
| --- | --- | --- |
| [airbnb](airbnb-scraper/) | [airbnb.py](airbnb-scraper/airbnb.py) | `scrape_listings`, `scrape_properties` |
| [airfrance](airfrance-scraper/) | [airfrance.py](airfrance-scraper/airfrance.py) | `scrape_flights` |
| [aliexpress](aliexpress-scraper/) | [aliexpress.py](aliexpress-scraper/aliexpress.py) | `scrape_search`, `scrape_product`, `scrape_product_reviews`, `find_aliexpress_products` |
| [allegro](allegro-scraper/) | [allegro.py](allegro-scraper/allegro.py) | `scrape_search`, `scrape_product` |
| [amazon](amazon-scraper/) | [amazon.py](amazon-scraper/amazon.py) | `scrape_search`, `scrape_reviews`, `scrape_product` |
| [app-store](app-store-scraper/) | [app_store.py](app-store-scraper/app_store.py) | `scrape_app_metadata`, `scrape_reviews` |
| [autoscout24](autoscout24-scraper/) | [autoscout24.py](autoscout24-scraper/autoscout24.py) | `scrape_listings`, `scrape_car_details` |
| [bestbuy](bestbuy-scraper/) | [bestbuy.py](bestbuy-scraper/bestbuy.py) | `scrape_sitemaps`, `scrape_products`, `search_products_data`, `scrape_search`, `scrape_reviews` |
| [bing](bing-scraper/) | [bing.py](bing-scraper/bing.py) | `scrape_search`, `scrape_keywords` |
| [bookingcom](bookingcom-scraper/) | [bookingcom.py](bookingcom-scraper/bookingcom.py) | `search_location_suggestions`, `scrape_search`, `scrape_hotel`, `scrape_hotel_reviews` |
| [capterra](capterra-scraper/) | [capterra.py](capterra-scraper/capterra.py) | `scrape_category`, `scrape_reviews` |
| [chatgpt](chatgpt-scraper/) | [chatgpt.py](chatgpt-scraper/chatgpt.py) | `scrape_conversation` |
| [crunchbase](crunchbase-scraper/) | [crunchbase.py](crunchbase-scraper/crunchbase.py) | `scrape_company`, `scrape_person`, `discover_target` |
| [dhl](dhl-scraper/) | [dhl.py](dhl-scraper/dhl.py) | `scrape_tracking` |
| [digikey](digikey-scraper/) | [digikey.py](digikey-scraper/digikey.py) | `scrape_products`, `scrape_category`, `scrape_search` |
| [domaincom](domaincom-scraper/) | [domaincom.py](domaincom-scraper/domaincom.py) | `scrape_properties`, `scrape_search` |
| [ebay](ebay-scraper/) | [ebay.py](ebay-scraper/ebay.py) | `scrape_product`, `scrape_product_variants`, `scrape_search` |
| [emirates](emirates-scraper/) | [emirates.py](emirates-scraper/emirates.py) | `scrape_flights` |
| [etsy](etsy-scraper/) | [etsy.py](etsy-scraper/etsy.py) | `scrape_search`, `scrape_product`, `scrape_shop` |
| [expedia](expedia-scraper/) | [expedia.py](expedia-scraper/expedia.py) | `scrape_hotel_search`, `scrape_flight_search` |
| [facebook](facebook-scraper/) | [facebook.py](facebook-scraper/facebook.py) | `scrape_facebook_events`, `scrape_marketplace_listings`, `scrape_facebook_page`, `scrape_group_posts` |
| [fashionphile](fashionphile-scraper/) | [fashionphile.py](fashionphile-scraper/fashionphile.py) | `scrape_products`, `scrape_search` |
| [g2](g2-scraper/) | [g2.py](g2-scraper/g2.py) | `scrape_search`, `scrape_reviews`, `scrape_alternatives` |
| [glassdoor](glassdoor-scraper/) | [glassdoor.py](glassdoor-scraper/glassdoor.py) | `scrape_jobs`, `scrape_reviews`, `scrape_salaries`, `find_companies` |
| [goat](goat-scraper/) | [goat.py](goat-scraper/goat.py) | `find_hidden_data`, `scrape_products`, `scrape_search` |
| [goibibo](goibibo-scraper/) | [goibibo.py](goibibo-scraper/goibibo.py) | `scrape_hotel_search`, `scrape_flight_search` |
| [goodreads](goodreads-scraper/) | [goodreads.py](goodreads-scraper/goodreads.py) | `scrape_book`, `scrape_list`, `scrape_reviews`, `scrape_search` |
| [google-flights](google-flights-scraper/) | [google_flights.py](google-flights-scraper/google_flights.py) | `scrape_flights`, `scrape_price_insights` |
| [google-jobs](google-jobs-scraper/) | [google_jobs.py](google-jobs-scraper/google_jobs.py) | `scrape_jobs` |
| [google-play](google-play-scraper/) | [google_play.py](google-play-scraper/google_play.py) | `scrape_apps`, `scrape_reviews`, `scrape_search` |
| [google](google-scraper/) | [google.py](google-scraper/google.py) | `scrape_google_map_places`, `find_google_map_places`, `scrape_keywords`, `scrape_serp`, `scrape_ai_mode` |
| [homegate](homegate-scraper/) | [homegate.py](homegate-scraper/homegate.py) | `scrape_properties`, `scrape_search` |
| [idealista](idealista-scraper/) | [idealista.py](idealista-scraper/idealista.py) | `scrape_provinces`, `scrape_properties`, `crawl_search`, `scrape_search` |
| [idealo](idealo-scraper/) | [idealo.py](idealo-scraper/idealo.py) | `scrape_with_retry`, `scrape_products`, `scrape_search`, `scrape_manufacturer`, `scrape_price_history` |
| [imdb](imdb-scraper/) | [imdb.py](imdb-scraper/imdb.py) | `scrape_titles`, `scrape_reviews`, `scrape_search`, `scrape_chart`, `scrape_person` |
| [immobilienscout24](immobilienscout24-scraper/) | [immobilienscout24.py](immobilienscout24-scraper/immobilienscout24.py) | `find_json_objects`, `scrape_search`, `scrape_properties` |
| [immoscout24](immoscout24-scraper/) | [immoscout24.py](immoscout24-scraper/immoscout24.py) | `scrape_properties`, `scrape_search` |
| [immowelt](immowelt-scraper/) | [immowelt.py](immowelt-scraper/immowelt.py) | `scrape_properties`, `find_json_objects`, `scrape_search` |
| [imovelweb](imovelweb-scraper/) | [imovelweb.py](imovelweb-scraper/imovelweb.py) | `scrape_properties`, `scrape_search` |
| [indeed](indeed-scraper/) | [indeed.py](indeed-scraper/indeed.py) | `scrape_search`, `scrape_jobs` |
| [instagram](instagram-scraper/) | [instagram.py](instagram-scraper/instagram.py) | `scrape_user`, `scrape_post`, `scrape_user_posts`, `scrape_post_comments` |
| [kayak](kayak-scraper/) | [kayak.py](kayak-scraper/kayak.py) | `scrape_flights` |
| [leboncoin](leboncoin-scraper/) | [leboncoin.py](leboncoin-scraper/leboncoin.py) | `scrape_search`, `scrape_ad` |
| [linkedin](linkedin-scraper/) | [linkedin.py](linkedin-scraper/linkedin.py) | `scrape_profile`, `scrape_company`, `scrape_job_search`, `scrape_jobs`, `scrape_articles` |
| [loopnet](loopnet-scraper/) | [loopnet.py](loopnet-scraper/loopnet.py) | `scrape_listings`, `scrape_search` |
| [lowes](lowes-scraper/) | [lowes.py](lowes-scraper/lowes.py) | `scrape_products`, `scrape_search`, `scrape_store_locations` |
| [maersk](maersk-scraper/) | [maersk.py](maersk-scraper/maersk.py) | `scrape_schedule_search`, `scrape_tracking` |
| [marriott](marriott-scraper/) | [marriott.py](marriott-scraper/marriott.py) | `scrape_search`, `scrape_hotels` |
| [mouser](mouser-scraper/) | [mouser.py](mouser-scraper/mouser.py) | `scrape_product`, `scrape_search` |
| [naver](naver-scraper/) | [naver.py](naver-scraper/naver.py) | `scrape_web_search`, `scrape_image_search`, `scrape_blog_post`, `scrape_news_article` |
| [nordstorm](nordstorm-scraper/) | [nordstorm.py](nordstorm-scraper/nordstorm.py) | `find_hidden_data`, `scrape_products`, `scrape_search` |
| [perplexity](perplexity-scraper/) | [perplexity.py](perplexity-scraper/perplexity.py) | `scrape_answer` |
| [pinterest](pinterest-scraper/) | [pinterest.py](pinterest-scraper/pinterest.py) | `scrape_search`, `scrape_board`, `scrape_profile`, `scrape_pin` |
| [realestatecom](realestatecom-scraper/) | [realestate.py](realestatecom-scraper/realestate.py) | `scrape_properties`, `scrape_search` |
| [realtorcom](realtorcom-scraper/) | [realtorcom.py](realtorcom-scraper/realtorcom.py) | `scrape_property`, `scrape_search`, `scrape_feed` |
| [reddit](reddit-scraper/) | [reddit.py](reddit-scraper/reddit.py) | `scrape_paginated`, `scrape_subreddit`, `scrape_post_comments`, `scrape_post`, `scrape_user_posts`, `scrape_user_comments` |
| [redfin](redfin-scraper/) | [redfin.py](redfin-scraper/redfin.py) | `scrape_search`, `scrape_property_for_sale`, `scrape_property_for_rent` |
| [rightmove](rightmove-scraper/) | [rightmove.py](rightmove-scraper/rightmove.py) | `find_json_objects`, `scrape_properties`, `find_locations`, `scrape_search` |
| [rs-online](rs-online-scraper/) | [rs_online.py](rs-online-scraper/rs_online.py) | `scrape_products`, `scrape_category`, `scrape_search` |
| [seloger](seloger-scraper/) | [seloger.py](seloger-scraper/seloger.py) | `scrape_search`, `scrape_property` |
| [shopify](shopify-scraper/) | [shopify.py](shopify-scraper/shopify.py) | `classify_catalog_response`, `scrape_catalog`, `scrape_collection`, `scrape_product_pages`, `scrape_product_urls` |
| [similarweb](similarweb-scraper/) | [similarweb.py](similarweb-scraper/similarweb.py) | `scrape_website`, `scrape_website_compare`, `scrape_sitemaps`, `scrape_trendings` |
| [skyscanner](skyscanner-scraper/) | [skyscanner.py](skyscanner-scraper/skyscanner.py) | `scrape_flights` |
| [stockx](stockx-scraper/) | [stockx.py](stockx-scraper/stockx.py) | `scrape_product`, `scrape_search` |
| [target](target-scraper/) | [target.py](target-scraper/target.py) | `scrape_product`, `scrape_availability`, `scrape_store_locations_sitemap`, `scrape_store_locations`, `scrape_search` |
| [threads](threads-scraper/) | [threads.py](threads-scraper/threads.py) | `scrape_thread`, `scrape_profile` |
| [ticketmaster](ticketmaster-scraper/) | [ticketmaster.py](ticketmaster-scraper/ticketmaster.py) | `scrape_artist`, `scrape_discovery` |
| [tiktok](tiktok-scraper/) | [tiktok.py](tiktok-scraper/tiktok.py) | `scrape_posts`, `scrape_comments`, `scrape_profiles`, `scrape_search`, `scrape_channel` |
| [tripadvisor](tripadvisor-scraper/) | [tripadvisor.py](tripadvisor-scraper/tripadvisor.py) | `scrape_location_data`, `scrape_search`, `scrape_hotel` |
| [trustpilot](trustpilot-scraper/) | [trustpilot.py](trustpilot-scraper/trustpilot.py) | `scrape_company`, `scrape_search`, `scrape_reviews` |
| [twitter](twitter-scraper/) | [twitter.py](twitter-scraper/twitter.py) | `scrape_tweet`, `scrape_profile` |
| [vestiairecollective](vestiairecollective-scraper/) | [vestiairecollective.py](vestiairecollective-scraper/vestiairecollective.py) | `find_hidden_data`, `scrape_products`, `scrape_search` |
| [walmart](walmart-scraper/) | [walmart.py](walmart-scraper/walmart.py) | `scrape_products`, `scrape_search` |
| [wellfound](wellfound-scraper/) | [wellfound.py](wellfound-scraper/wellfound.py) | `scrape_search`, `scrape_companies` |
| [yellowpages](yellowpages-scraper/) | [yellowpages.py](yellowpages-scraper/yellowpages.py) | `scrape_search`, `scrape_pages` |
| [yelp](yelp-scraper/) | [yelp.py](yelp-scraper/yelp.py) | `scrape_pages`, `scrape_reviews`, `scrape_search` |
| [youtube](youtube-scraper/) | [youtube.py](youtube-scraper/youtube.py) | `scrape_video`, `scrape_comments`, `scrape_channel`, `scrape_channel_videos`, `scrape_search`, `scrape_shorts`, `find_value`, `find_transcript_items`, `scrape_transcript` |
| [zillow](zillow-scraper/) | [zillow.py](zillow-scraper/zillow.py) | `scrape_search`, `scrape_properties` |
| [zoominfo](zoominfo-scraper/) | [zoominfo.py](zoominfo-scraper/zoominfo.py) | `scrape_comapnies`, `scrape_directory`, `scrape_faqs` |
| [zoopla](zoopla-scraper/) | [zoopla.py](zoopla-scraper/zoopla.py) | `scrape_properties`, `scrape_search` |
| [zoro](zoro-scraper/) | [zoro.py](zoro-scraper/zoro.py) | `scrape_product`, `scrape_search_listing` |

## Attribution and license

Adapted from [scrapfly/scrapfly-scrapers](https://github.com/scrapfly/scrapfly-scrapers)
at the revision recorded in [NOTICE](NOTICE). Original notices and sample data
are retained. This derivative is licensed under **OSL-3.0**, pursuant to section
17(d) of the upstream NPOSL-3.0. Read [LICENSE](LICENSE) before using, modifying
or redistributing it; use constitutes assent to its terms. AdsCrawl's SDK is a
separate package with its own license. No upstream endorsement is implied.
