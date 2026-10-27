# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for google.com/search (Google Jobs vertical).

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

from datetime import datetime
import os
from typing import List, Optional, TypedDict
import re
from adscrawl_scrapers import Response, Request, ScraperClient

client = ScraperClient()

BASE_CONFIG = {
    'render': True,
}

SCROLL_JS = """
return (async () => {
    const isEnd = () => {
        const result = document.evaluate(
            '//*[contains(text(),"No more jobs")]',
            document,
            null,
            XPathResult.FIRST_ORDERED_NODE_TYPE,
            null
        );
        return !!result.singleNodeValue;
    };
    while (!isEnd()) {
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 1000));
    }
})()
"""


class JobResult(TypedDict):
    title: str
    company: Optional[str]
    location: Optional[str]
    posted_date: Optional[str]
    schedule_type: Optional[str]
    salary_range: Optional[str]
    description: Optional[str]
    qualifications: List[str]
    source_board: Optional[str]
    application_url: Optional[str]
    job_id: Optional[str]


class JobSearch(TypedDict):
    query: str
    location: str
    search_date: str
    jobs: List[JobResult]


def build_search_url(
    query: str,
    location: str,
    hl: str = "en",
    gl: str = "us",
    date_filter: Optional[str] = None,
) -> str:
    """Build a Google Jobs search URL using the udm=8 vertical tab."""
    url = (
        f"https://www.google.com/search?"
        f"q={query.replace(' ', '+')}+job+near+{location.replace(' ', '+')}"
        f"&udm=8&hl={hl}&gl={gl}"
    )
    if date_filter:
        url += f"&tbs={date_filter}"
    return url


def _parse_metadata(card) -> tuple[Optional[str], Optional[str], Optional[str]]:
    posted_date = salary_range = schedule_type = None
    for span in card.css("span.Yf9oye"):
        aria = span.attrib.get("aria-label", "")
        text = span.css("::text").get("").strip()
        if not text:
            continue
        if aria.startswith("Posted "):
            posted_date = text
        elif aria.startswith("Salary "):
            salary_range = text
        elif aria.startswith("Employment Type "):
            schedule_type = text
    return posted_date, salary_range, schedule_type


def _parse_location_and_source(loc_raw: str) -> tuple[Optional[str], Optional[str]]:
    """Split 'City, ST • via LinkedIn' into location and job board."""
    if " via " in loc_raw:
        location_part, source_part = loc_raw.split(" via ", 1)
        location = location_part.replace("•", "").strip() or None
        source = source_part.strip() or None
        return location, source
    return loc_raw.replace("•", "").strip() or None, None


def _extract_job_id(card) -> Optional[str]:
    share_url = card.attrib.get("data-share-url", "")
    match = re.search(r"htidocid=([^&]+)", share_url)
    return match.group(1) if match else None


def _extract_application_url(card) -> Optional[str]:
    for anchor in card.css("a[href]"):
        label = " ".join(anchor.css("::text").getall())
        if "Apply" in label:
            return anchor.attrib.get("href", "").strip() or None
    return None


def _extract_qualifications(card) -> List[str]:
    for heading in card.css("h4.XzFqK"):
        if "Qualifications" not in (heading.css("::text").get("") or ""):
            continue
        parent = heading.xpath("..")
        return [
            text
            for li in parent.css("li")
            if (text := li.css("::text").get("").strip())
        ]
    return []


def _extract_description(card) -> Optional[str]:
    text_parts = (
        card.css("span.OOyDTc::text").getall()
        + card.css("span.ejCXj::text").getall()
    )
    lines = [part.strip() for part in text_parts if part.strip()]
    return "\n".join(lines) if lines else None


def _parse_job_card(card) -> Optional[JobResult]:
    title = card.css(".tNxQIb.PUpOsf::text").get("").strip()
    if not title:
        return None

    location, source_board = _parse_location_and_source(
        card.css("div.wHYlTd.FqK3wc.MKCbgd::text").get("").strip()
    )
    posted_date, salary_range, schedule_type = _parse_metadata(card)

    return JobResult(
        title=title,
        company=card.css("div.wHYlTd.MKCbgd.a3jPc::text").get("").strip() or None,
        location=location,
        posted_date=posted_date,
        schedule_type=schedule_type,
        salary_range=salary_range,
        description=_extract_description(card),
        qualifications=_extract_qualifications(card),
        source_board=source_board,
        application_url=_extract_application_url(card),
        job_id=_extract_job_id(card),
    )


def parse_job_cards(response: Response) -> List[JobResult]:
    jobs: List[JobResult] = []
    for card in response.selector.css(".EimVGf"):
        if job := _parse_job_card(card):
            jobs.append(job)
    return jobs


@managed
async def scrape_jobs(
    query: str,
    location: str,
    language: str = "en",
    country_code: str = "us",
    date_filter: Optional[str] = None,
) -> JobSearch:
    """Scrape Google Jobs for the given query and location."""
    url = build_search_url(query, location, language, country_code, date_filter)
    response = await client.fetch(
        Request(
            url,
            javascript=SCROLL_JS,
            waitMs=3000,
            **BASE_CONFIG,
        )
    )
    return JobSearch(
        query=query,
        location=location,
        search_date=datetime.now().strftime("%Y-%m-%d"),
        jobs=parse_job_cards(response),
    )
