# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for DHL shipment tracking.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import json
import os
import re
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
# Direct /utapi is HTTP 428. The public page no longer 428s, but this id
# returned no shipment on 2026-11-03 (semantic-mismatch: the result panel
# never rendered). It is the local id from a 2026-05-20 page capture whose
# delivery date was 2026-04-29. DHL drops most delivered ids about 90 days
# after the last event. Official pages only show format samples
# (1234567890, 7777777770), which are not public shipments. No replacement
# with a visible event list could be confirmed offline. A missing shipment
# stays a failure.
# https://browse.sh/skills/dhl.com/track-shipment-18m2jq
EXAMPLE_TRACKING_NUMBER = "146000018487"
_NOT_FOUND_TEXT = (
    "tracking attempt was not successful",
    "could not be found",
    "unable to find",
    "no shipment",
)
_PAGE_READY = (
    ".c-event-log--date, .c-tracking-result-message--content, "
    ".c-tracking-result--container.is-visible"
)

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
    """Event rows on the tracking page. utapi itself is an Akamai challenge."""
    events = []
    for row in response.selector.css("#panel_events tr"):
        date = (row.css(".c-event-log--date::text").get() or "").strip()
        local = (row.css(".c-event-log--localtime::text").get() or "").strip()
        status = " ".join(
            part.strip() for part in row.css(".c-event-log--status::text").getall() if part and part.strip()
        )
        location = (row.css(".c-event-log--location::text").get() or "").strip() or None
        if date or status:
            events.append({
                "timestamp": " ".join(part for part in (date, local) if part) or None,
                "status": None,
                "description": status or None,
                "location": location,
            })
            continue
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


def _visible_text(response: Response) -> str:
    parts = response.selector.css("main ::text, .c-tracking--container ::text").getall()
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    return text or (response.content or "")


def _line_value(text: str, label: str) -> Optional[str]:
    match = re.search(rf"(?m)^{re.escape(label)}\s*:?\s*(.+)$", text)
    return match.group(1).strip() if match else None


def _solved_utapi_payload(response: Response) -> Optional[dict]:
    """A later utapi body that is a shipment document, not the 428 challenge."""
    for call in reversed(response.network or []):
        if "/utapi" not in (call.get("url") or ""):
            continue
        body = ((call.get("response") or {}).get("body")) or ""
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and not data.get("sec-cp-challenge") and "shipments" in data:
            return data
    return None


def _challenge_page(response: Response, text: str) -> bool:
    lowered = f"{text}\n{response.content or ''}".lower()
    if response.status_code in {403, 428, 429}:
        return True
    return any(marker in lowered for marker in (
        "sec-cp-challenge", "sec-cpt-if", "pardon our interruption", "access denied",
    ))


def _page_result(response: Response, tracking_number: str) -> TrackingResult:
    """Prefer a solved utapi document, then the rendered event panel.

    The first utapi response is the Akamai challenge. It is not the shipment.
    """
    data = _solved_utapi_payload(response)
    if data is not None:
        result = _classify_payload(data, tracking_number)
        if result.get("events") or result["classification"] == "empty":
            return result
    events = _events_from_panel(response)
    text = _visible_text(response)
    compact_request = re.sub(r"\s+", "", tracking_number)
    code_line = re.search(r"Tracking Code:?[ \t]*([^\n]+)", text)
    displayed_code = ""
    if code_line:
        pieces = code_line.group(1).split()
        if pieces and all(len(piece) == 1 and piece.isalnum() for piece in pieces):
            displayed_code = "".join(pieces)
        elif pieces:
            displayed_code = re.sub(r"[^A-Za-z0-9]", "", pieces[0])
    if events and len(displayed_code) >= 5 and displayed_code != compact_request:
        log.warning("tracking page showed {} for requested {}", displayed_code, tracking_number)
        return _empty_result(tracking_number, "empty")
    if events:
        return {
            "classification": "success",
            "tracking_number": tracking_number,
            "status": _line_value(text, "Status") or events[0].get("description"),
            "events": events,
            "estimated_delivery": None,
            "origin": _line_value(text, "Origin"),
            "destination": _line_value(text, "Destination"),
        }
    lowered = text.lower()
    if any(phrase in lowered for phrase in _NOT_FOUND_TEXT):
        return _empty_result(tracking_number, "empty")
    if _challenge_page(response, text):
        return _empty_result(tracking_number, "captcha-or-forbidden")
    return _empty_result(tracking_number, "semantic-mismatch")


async def _scrape_tracking_once(tracking_number: str) -> TrackingResult:
    # Do not open /utapi as a document. That request is HTTP 428, and waiting
    # for the first utapi XHR returns the challenge before the page renders.
    url = _build_tracking_url(tracking_number, api_endpoint=False)
    request = Request(
        url,
        timeoutMs=90_000,
        waitMs=3000,
        actions=[
            {
                "type": "waitForSelector",
                "selector": "button#onetrust-reject-all-handler",
                "timeoutMs": 4000,
                "optional": True,
            },
            {"type": "click", "selector": "button#onetrust-reject-all-handler", "optional": True},
            {
                "type": "waitForSelector",
                "selector": _PAGE_READY,
                "state": "attached",
                "timeoutMs": 45_000,
            },
        ],
        **BASE_CONFIG,
    )
    try:
        response = await CLIENT.fetch(request)
    except ScrapeError as error:
        response = error.response
        if response is None or error.code not in {"HTTP_ERROR", "ACTION_FAILED", "SELECTOR_NOT_FOUND", "TIMEOUT"}:
            raise
        log.warning("tracking page for {} ended with {}", tracking_number, error.code)
    return _page_result(response, tracking_number)


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
