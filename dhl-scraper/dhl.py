# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for DHL shipment tracking.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import json
import os
from typing import List, Literal, Optional, TypedDict
from urllib.parse import urlencode

from loguru import logger as log
from adscrawl_scrapers import Response, Request, ScraperClient, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",
    'render': True,

}

API_BASE_URL = "https://www.dhl.com/utapi"
TRACKING_PAGE_URL = "https://www.dhl.com/us-en/home/tracking.html"
# Public example in DHL's Shipment Tracking - Unified guide. The documented
# sample response for this number includes a shipment and events. LBAA19526
# returned no shipment on 2026-11-03.
# https://developer.dhl.com/api-reference/shipment-tracking
EXAMPLE_TRACKING_NUMBER = "7777777770"

Classification = Literal["success", "empty", "captcha-or-forbidden", "semantic-mismatch"]


class TrackingEvent(TypedDict):
    timestamp: Optional[str]
    status: Optional[str]
    description: Optional[str]
    location: Optional[str]


class TrackingResult(TypedDict):
    classification: Classification
    tracking_number: str
    status: Optional[str]
    events: List[TrackingEvent]
    estimated_delivery: Optional[str]
    origin: Optional[str]
    destination: Optional[str]


def _build_tracking_url(tracking_number: str, api_endpoint: bool = False) -> str:
    if api_endpoint:
        # Same query the tracking page sends. A bare trackingNumber is what
        # answered HTTP 403 before any shipment JSON.
        query = urlencode({
            "trackingNumber": tracking_number,
            "language": "en",
            "requesterCountryCode": "US",
            "source": "tt",
        })
        return f"{API_BASE_URL}?{query}"
    return f"{TRACKING_PAGE_URL}?tracking-id={tracking_number}&submit=1"


def _empty_result(tracking_number: str, classification: Classification) -> TrackingResult:
    return {
        "classification": classification,
        "tracking_number": tracking_number,
        "status": None,
        "events": [],
        "estimated_delivery": None,
        "origin": None,
        "destination": None,
    }


def _classify_payload(data: dict, tracking_number: str) -> TrackingResult:
    """A challenge or a non-shipment body is not an empty tracking result."""
    if not isinstance(data, dict):
        return _empty_result(tracking_number, "semantic-mismatch")
    if data.get("sec-cp-challenge"):
        return _empty_result(tracking_number, "captcha-or-forbidden")
    if "shipments" not in data:
        return _empty_result(tracking_number, "semantic-mismatch")
    return _parse_tracking_api_response(data, tracking_number)


def _events_from_panel(response: Response) -> List[TrackingEvent]:
    """Event rows rendered on the tracking page when the utapi body is blocked."""
    events = []
    for row in response.selector.css("#panel_events tr"):
        cells = [text.strip() for text in row.css("td::text").getall() if text and text.strip()]
        if len(cells) < 2:
            continue
        events.append({
            "timestamp": cells[0],
            "status": None,
            "description": cells[1],
            "location": cells[2] if len(cells) > 2 else None,
        })
    return events


def _with_panel_events(result: TrackingResult, response: Response, tracking_number: str) -> TrackingResult:
    if result.get("events"):
        return result
    events = _events_from_panel(response)
    if not events:
        return result
    return {
        "classification": "success",
        "tracking_number": tracking_number,
        "status": events[-1]["description"],
        "events": events,
        "estimated_delivery": None,
        "origin": None,
        "destination": None,
    }


def _get_xhr_data(response: Response, url_pattern: str) -> dict:
    """Extract and parse the JSON body of the first XHR call whose URL contains url_pattern."""
    xhr_calls = response.network
    call = next((c for c in xhr_calls if url_pattern in c.get("url", "")), None)
    if not call:
        raise RuntimeError(f"XHR call matching '{url_pattern}' not found — try increasing rendering_wait")
    return json.loads(call["response"]["body"])


def _parse_tracking_api_response(data: dict, tracking_number: str) -> TrackingResult:
    shipment = (data.get("shipments") or [None])[0]

    if not shipment:
        return {
            "classification": "empty", "tracking_number": tracking_number,
            "status": None, "events": [], "estimated_delivery": None,
            "origin": None, "destination": None,
        }

    status = shipment.get("status") or {}
    details = shipment.get("details") or {}
    routes = details.get("dgf:routes") or []

    events = []
    for event in shipment.get("events") or []:
        address = (event.get("location") or {}).get("address") or {}
        events.append(
            {
                "timestamp": event.get("timestamp"),
                "status": event.get("statusCode") or event.get("status"),
                "description": event.get("description"),
                "location": address.get("addressLocality"),
            }
        )

    origin = (shipment.get("origin") or {}).get("address") or {}
    destination = (shipment.get("destination") or {}).get("address") or {}

    return {
        "classification": "success",
        "tracking_number": shipment.get("id") or tracking_number,
        "status": status.get("description") or status.get("statusCode"),
        "events": events,
        "retrieved_at": None,
        "estimated_delivery": routes[0].get("dgf:estimatedArrivalDate") if routes else None,
        "origin": origin.get("addressLocality"),
        "destination": destination.get("addressLocality"),
    }


async def _scrape_tracking_once(tracking_number: str) -> TrackingResult:
    try:
        url = _build_tracking_url(tracking_number, api_endpoint=True)
        response = await CLIENT.fetch(Request(
            url,
            headers={"Accept": "application/json", "Referer": TRACKING_PAGE_URL},
            **BASE_CONFIG,
        ))
        result = _classify_payload(json.loads(response.content), tracking_number)
        if result.get("events"):
            return result
        if result["classification"] == "captcha-or-forbidden":
            log.warning(f"API blocked for {tracking_number}")
    except ScrapeError as error:
        log.warning(f"API failed for {tracking_number}: {error}")
    except json.JSONDecodeError:
        log.warning(f"API returned non-JSON for {tracking_number}")

    url = _build_tracking_url(tracking_number, api_endpoint=False)
    response = await CLIENT.fetch(Request(
        url, waitForResponse="/utapi", timeoutMs=60_000, **BASE_CONFIG,
    ))
    try:
        data = _get_xhr_data(response, "/utapi")
    except (RuntimeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        result = _classify_payload(data, tracking_number)
    else:
        result = _empty_result(tracking_number, "semantic-mismatch")
    return _with_panel_events(result, response, tracking_number)


@managed
async def scrape_tracking(tracking_number: str) -> TrackingResult:
    result = await _scrape_tracking_once(tracking_number)
    # A block is not an empty shipment. One new session, then keep the failure.
    if result["classification"] == "captcha-or-forbidden":
        log.warning(f"retrying {tracking_number} once after a tracking block")
        result = await _scrape_tracking_once(tracking_number)
    if result["classification"] == "success" and result.get("events"):
        log.success("scraped tracking details for {}", tracking_number)
    else:
        log.warning("no tracking details returned for {} ({})", tracking_number, result["classification"])
    return result
