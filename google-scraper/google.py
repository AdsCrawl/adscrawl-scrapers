# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for google.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import os
import re
import operator
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlparse
from loguru import logger as log
from typing import Dict, List, TypedDict
from adscrawl_scrapers import Request, ScraperClient, Response, ScrapeError


CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",
    'render': True,
}


class NoResults(Exception):
    "Raised when requesting pagination without results"
    pass


# Google no longer embeds destination URLs in the SERP HTML. Each organic result
# now links to an opaque redirect: /goto?url=<encrypted token>. The token can't be
# decoded locally, so the only way to get the real URL is to request the redirect.
GOTO_PREFIX = "/goto?url="


def parse_place(response: Response) -> Dict:
    """parse Google Maps place"""

    def aria_with_label(label):
        """gets aria element as is"""
        return selector.css(f"*[aria-label*='{label}']::attr(aria-label)")

    def aria_no_label(label):
        """gets aria element as text with label stripped off (None when the place has no such label, e.g. no phone)"""
        text = aria_with_label(label).get("")
        return text.split(label, 1)[1].strip() if label in text else None

    selector = response.selector
    result = {
        "name": "".join(selector.css("h1::text").getall()).strip(),
        "category": selector.xpath(
            "//button[contains(@jsaction, 'category')]/text()"
        ).get(),
        # most of the data can be extracted through accessibility labels:
        "address": aria_no_label("Address: "),
        "website": aria_no_label("Website: "),
        "phone": aria_no_label("Phone: "),
        "review_count": aria_with_label(" reviews").get(),
        # to extract star numbers from text we can use regex pattern for numbers: "\d+"
        "stars": aria_with_label(" stars").re(r"\d+.*\d+")[0],
        "5_stars": aria_with_label("5 stars").re(r"(\d+) review")[0],
        "4_stars": aria_with_label("4 stars").re(r"(\d+) review")[0],
        "3_stars": aria_with_label("3 stars").re(r"(\d+) review")[0],
        "2_stars": aria_with_label("2 stars").re(r"(\d+) review")[0],
        "1_stars": aria_with_label("1 stars").re(r"(\d+) review")[0],
    }
    return result


@managed
async def scrape_google_map_places(urls: List[str]) -> List[Dict]:
    """scrape google map place pages"""
    data = []
    js = [
        {"type": 'click', 'selector': "button[aria-label='Search']"},
        {"type": 'waitForSelector', 'selector': "//button[contains(@jsaction, 'reviewlegaldisclosure')]"}
    ]
    to_scrape = [
        Request(
            url=url,
            **BASE_CONFIG,
            actions=js
        )
        for url in urls
    ]
    log.info(f"scraping {len(to_scrape)} google map place pages")
    async for response in CLIENT.fetch_many(to_scrape):
        # a failed request comes back as an error object: log it and skip the page
        if isinstance(response, ScrapeError):
            log.error(f"failed to scrape a google map place page: {response}")
            continue
        data.append(parse_place(response))
    return data


@managed
async def find_google_map_places(query: str) -> List[Dict]:
    script = """
        function waitCss(selector, n=1, require=false, timeout=5000) {
            console.log(selector, n, require, timeout);
            var start = Date.now();
            while (Date.now() - start < timeout){
                if (document.querySelectorAll(selector).length >= n){
                    return document.querySelectorAll(selector);
                }
            }
            if (require){
                throw new Error(`selector "${selector}" timed out in ${Date.now() - start} ms`);
            } else {
                return document.querySelectorAll(selector);
            }
        }

        var results = waitCss("div[aria-label*='Results for'] div a", 10, false);
        return Array.from(results).map((el) => el.getAttribute("href"));
    """
    log.info(f"scraping google map place pages for query: {query}")
    response = await CLIENT.fetch(
        Request(
            url=f"https://www.google.com/maps/search/{query.replace(' ', '+')}/?hl=en",
            render=True,
            javascript=script,
            waitForSelector="//div[contains(@aria-label, 'Results for')]//div/a",
            countryCode="US",
        )
    )
    urls = response.javascript
    # keep only place links and make relative ones absolute: the Scrapfly API rejects URLs without http(s)
    urls = [urljoin("https://www.google.com", url) for url in urls if url and "/maps/place/" in url]
    return urls


def parse_rich_snippets(response: Response):
    selector = response.selector
    snippet = selector.xpath(
        "//h2[re:test(.,'complementary results','i')]/following-sibling::div[1]"
    )
    data = {
        "title": snippet.xpath(".//*[@data-attrid='title']//text()").get(),
        "subtitle": snippet.xpath(".//*[@data-attrid='subtitle']//text()").get(),
        "website": snippet.xpath(
            ".//a[@data-attrid='visit_official_site']/@href"
        ).get(),
        "description": snippet.xpath(
            ".//div[@data-attrid='description']//span//text()"
        ).get(),
        "description_more_link": snippet.xpath(
            ".//div[@data-attrid='description']//@href"
        ).get(),
    }
    # get summary info rows
    data["info"] = {}
    for row in snippet.xpath(".//div[@data-md]/div/div/div[span]"):
        label = row.xpath(".//span/text()").get()
        value = row.xpath(".//a/text()").get()
        data["info"][label] = value
    # get social media links
    data["socials"] = {}
    for profile in snippet.xpath(
        ".//div[@data-attrid='kc:/common/topic:social media presence']//g-link/a"
    ):
        label = profile.xpath(".//text()").get()
        url = profile.xpath(".//@href").get()
        data["socials"][label] = url
    return data


def parse_keywords(response: Response) -> List[str]:
    """parse keywords from google search pages"""
    selector = response.selector
    related_search = []

    for suggestion in selector.xpath("//div[.//span[contains(text(), 'search for')]]/following-sibling::div//a[contains(@href, '/search')]"):
            text = "".join(suggestion.xpath(".//text()").getall())
            text = "".join(suggestion.xpath(".//text()").getall()).strip()
            if len(text.split()) > 2:
                related_search.append(text)


    people_ask_for = [question.strip() for question in selector.css(".related-question-pair .CSkcDe::text").getall() if question.strip()]
    return {"related_search": related_search, "people_ask_for": people_ask_for}


# AI Mode markup changes frequently. Override these selectors after inspecting
# the current page in your locale; missing answer markup raises an error.
AI_ANSWER_SELECTOR = os.getenv("ADSCRAWL_GOOGLE_AI_ANSWER_SELECTOR", '[data-container-id="main-col"]')
AI_SOURCES_SELECTOR = os.getenv("ADSCRAWL_GOOGLE_AI_SOURCES_SELECTOR", '[data-container-id="rhs-col"] a[href^="http"]')


class AiModeSource(TypedDict):
    title: str
    url: str
    snippet: str | None


class AiModeResult(TypedDict):
    query: str
    answer: str
    sources: List[AiModeSource]
    captured_at: str


@managed
async def scrape_keywords(query: str) -> List[str]:
    """request google search page for keyword data"""
    response = await CLIENT.fetch(
        Request(
            f"https://www.google.com/search?hl=en&q={quote(query)}", **BASE_CONFIG
        )
    )
    data = parse_keywords(response)
    log.success(
        f"scraped {len(data['related_search'])} related search kws and {len(data['people_ask_for'])} FAQs"
    )
    return data


def parse_serp(response: Response) -> List[Dict]:
    """parse search results from google search page"""
    results = []
    selector = response.selector
    has_data = selector.xpath("//h1[contains(text(),'Search Results')]").get()
    if not has_data:
        raise NoResults("No search results found")

    if "start" not in response.url:
        position = 0
    else:
        position = int(response.url.split("start=")[-1])

    for box in selector.xpath(
        "//div[@id='search']/div/div/div"
    ):
        title = box.xpath(".//h3/text()").get()
        url = box.xpath(".//h3/../@href").get()
        description = "".join(box.xpath(".//div[@data-sncf]//text()").getall())
        if not title or not url:
            continue

        if url.startswith("/"):
            url = "https://www.google.com" + url
        position += 1
        results.append(
            {
                "position": position,
                "title": title,
                "url": url,
                "origin": box.xpath(".//div[*[cite]]/div/span/text()").get(),
                "domain": parse_domain(url),
                "description": description.split(" — ")[-1] if description else None,
                "date": parse_date(box),
            }
        )
    results.sort(key=lambda x: x["position"])
    return results


def parse_domain(url: str) -> str:
    """get the bare domain of a URL"""
    return urlparse(url).netloc.replace("www.", "")


# either an absolute date ("Sep 10, 2026") or a relative one ("2 years ago")
DATE_PATTERN = re.compile(
    r"[A-Z][a-z]{2,8} \d{1,2}, \d{4}"
    r"|\d+ (?:second|minute|hour|day|week|month|year)s? ago"
)


def parse_date(box) -> str:
    """parse the publication date of a search result, if it shows one"""
    # most results put the date in front of the snippet: "Sep 10, 2026 — ..."
    date = box.xpath(".//span[contains(text(),' —')]/span/text()").get()
    if date:
        return date
    # video results show it next to the view count: "3.2K+ views · 2 years ago"
    meta = "".join(box.xpath(".//div[*[cite]]//text()").getall())
    match = DATE_PATTERN.search(meta)
    return match.group(0) if match else None


@managed
async def resolve_goto_redirects(results: List[Dict]) -> List[Dict]:
    """resolve Google's /goto?url= redirects into the real destination URLs"""

    # dedupe: the same redirect can show up on more than one page
    resolved = {result["url"]: None for result in results if GOTO_PREFIX in result["url"]}
    if not resolved:
        return results

    config = {**BASE_CONFIG, 'render': False}
    to_scrape = [
        # a blocked or dead destination mustn't abort the batch, and it's not worth
        # retrying - the redirect Google returned is all we're after here
        Request(url, **config, raiseOnHttpError=False, )
        for url in resolved
    ]
    log.info(f"resolving {len(to_scrape)} google /goto redirect URLs")
    async for response in CLIENT.fetch_many(to_scrape):
        if isinstance(response, Exception):
            # the redirect is already followed by the time the destination errors,
            # so the failed response still tells us where it pointed to
            error, response = response, getattr(response, "response", None)
            if response is None:
                log.warning(f"failed to resolve a goto URL: {error}")
                continue
        requested = response.request_url
        destination = response.url
        if GOTO_PREFIX in destination:  # no redirect happened
            log.warning(f"goto URL did not redirect: {requested}")
            continue
        resolved[requested] = destination

    for result in results:
        destination = resolved.get(result["url"])
        if destination:
            result["url"] = destination
            result["domain"] = parse_domain(destination)
    log.success(f"resolved {sum(1 for url in resolved.values() if url)}/{len(resolved)} goto URLs")
    return results


@managed
async def scrape_serp(query: str, max_pages: int = None, resolve_goto_urls: bool = True) -> List[Dict]:
    """query google search for serp results"""
    results = []
    results_per_page = 10
    offset = 0 if not max_pages else max_pages * results_per_page  # 10 results per page
    to_scrape = [
        Request(
            f"https://www.google.com/search?hl=en&q={quote(query)}&start={cursor}",
            **BASE_CONFIG,
        )
        for cursor in range(0, offset, 10)
    ]

    log.info(f"scraping {len(to_scrape)} search pages for the query: {query}")
    async for response in CLIENT.fetch_many(to_scrape):
        try:
            data = parse_serp(response)
            results.extend(data)
        except NoResults as e:  # catch any exception
            log.warning(f"Encouterned search page without results")
            continue
        except Exception as e:
            log.error(f"Error occured: {e}")
            continue
    log.success(f"scraped {len(results)} SERP results of the query: {query}")
    if resolve_goto_urls:
        results = await resolve_goto_redirects(results)
    results.sort(key=operator.itemgetter("position"))
    return results

@managed
async def scrape_ai_mode(query: str, hl: str = "en", gl: str = "US") -> AiModeResult:
    """Extract AI Mode answer markup with AdsCrawl's structured extraction API.

    Unlike the upstream LLM prompt, this is deterministic DOM extraction.
    Source cards are optional; a missing answer is an explicit failure.
    """
    from adscrawl import AsyncAdsCrawl
    async with AsyncAdsCrawl() as sdk:
        result = await sdk.spa.extract({
            "url": f"https://www.google.com/search?q={quote(query)}&udm=50&hl={hl}&gl={gl}",
            "countryCode": gl.upper(),
            "waitFor": {"selector": AI_ANSWER_SELECTOR, "timeoutMs": 60_000},
            "fields": {
                "answer": {"source": "dom", "selector": AI_ANSWER_SELECTOR, "value": "text", "required": True},
                "sourceTitles": {"source": "dom", "selector": AI_SOURCES_SELECTOR, "value": "text", "multiple": True},
                "sourceUrls": {"source": "dom", "selector": AI_SOURCES_SELECTOR, "value": "attribute", "attribute": "href", "multiple": True},
            },
        })
    answer = result["data"].get("answer")
    if "answer" in result.get("missingFields", []) or not isinstance(answer, str) or not answer.strip():
        raise ValueError("Google AI Mode answer was not found; inspect the current answer selector")
    sources, seen = [], set()
    titles = result["data"].get("sourceTitles") or []
    for index, url in enumerate(result["data"].get("sourceUrls") or []):
        if not isinstance(url, str) or not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        title = titles[index] if index < len(titles) else ""
        sources.append({"title": title, "url": url, "snippet": None})
    return {"query": query, "answer": answer.strip(), "sources": sources,
            "captured_at": datetime.now(timezone.utc).isoformat()}
