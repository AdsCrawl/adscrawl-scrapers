# Adapted by AdsCrawl from scrapfly/scrapfly-scrapers. See NOTICE.
"""
This is an example web scraper for emirates.com.

To run this scraper set env variable $ADSCRAWL_API_KEY with your AdsCrawl API key:
$ export ADSCRAWL_API_KEY="your key from https://app.adscrawl.net/dashboard/keys/"
"""
from adscrawl_scrapers import managed

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TypedDict
from urllib.parse import urlparse

from loguru import logger as log
from adscrawl_scrapers import Response, Request, ScraperClient, ScrapeError

CLIENT = ScraperClient()

BASE_CONFIG = {
    'countryCode': "US",
    'render': True,
}

BRANDED_FARES_URL = "https://www.emirates.com/service/search-results/branded-fares"

CARRIER_NAMES = {"EK": "Emirates"}
CABIN_NAMES = {"Y": "economy", "W": "premium economy", "J": "business", "F": "first"}

output = Path(__file__).parent / "results"
output.mkdir(exist_ok=True)


class FarePrice(TypedDict):
    amount: int
    currency: str


class FlightResult(TypedDict):
    airline: str
    flight_number: str
    departure_time: str
    departure_airport: str
    arrival_time: str
    arrival_airport: str
    duration: str
    stops: int
    layovers: List[dict]
    price: FarePrice
    cabin_class: str
    plane_model: str
    fare_brand: str
    seats_available: int
    captured_at: str


class FlightSearch(TypedDict):
    locale: str
    trip_type: str
    origin: str
    destination: str
    route: str
    search_date: str
    departure_date: str
    return_date: Optional[str]
    lowest_fare: FarePrice
    flights: List[FlightResult]


def _date_labels(date_iso: str) -> tuple:
    """the two ways the calendar labels a day: "Tuesday, 13  October 2026" or "Tuesday, October 13, 2026\""""
    parsed_date = datetime.strptime(date_iso, "%Y-%m-%d")
    date_label = f"{parsed_date.strftime('%A')}, {parsed_date.day}  {parsed_date.strftime('%B %Y')}"
    date_alt = f"{parsed_date.strftime('%A')}, {parsed_date.strftime('%B')} {parsed_date.day}, {parsed_date.year}"
    return date_label, date_alt


def _date_click_script(date_iso: str) -> str:
    """click the day that is on screen: the calendar also keeps copies of neighbouring months out of view"""
    date_label, date_alt = _date_labels(date_iso)
    return (
        f'var days=[...document.querySelectorAll(\'[aria-label*="{date_label}"],[aria-label*="{date_alt}"]\')];'
        "days.find(d=>d.getClientRects().length&&getComputedStyle(d).visibility!=='hidden')?.click();"
    )


def _date_cell_selector(date_iso: str) -> str:
    """the day in the calendar, whichever label format the page uses (an XPath selector)"""
    date_label, date_alt = _date_labels(date_iso)
    return f'//*[contains(@aria-label,"{date_label}") or contains(@aria-label,"{date_alt}")]'


def _pick_airport_option(code: str) -> str:
    return (
        "var items=[...document.querySelectorAll('[data-testid^=\"options_\"]')];"
        f"items.find(o=>o.textContent.includes('{code}'))?.click();"
    )


def _retype_airport_script(selector: str, code: str) -> str:
    """set the airport code again when the field lost typed letters ("FK" or "K" instead of "JFK"), the way
    the page's own input handling expects it (native value setter + input event)"""
    return (
        f'var field=document.querySelector("{selector}");'
        f"if(field&&field.value!=='{code}'){{"
        f"Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'{code}');"
        "field.dispatchEvent(new Event('input',{bubbles:true}));}"
    )


def _fill_airport(field: str, code: str) -> list:
    selector = f"[data-testid^='combobox_{field}'] input"
    return [
        {"type": 'fill', 'selector': selector, 'value': code, 'clear': True},
        {"type": "wait", "milliseconds": 1000},
        # the field sometimes keeps only part of the typed code while the page is busy, set it again then
        {"type": 'evaluate', 'script': _retype_airport_script(selector, code)},
        {"type": "wait", "milliseconds": 1000},
        # wait for the suggestion of the typed airport itself: the list shows other airports first
        {"type": 'waitForSelector', 'selector': f"//*[starts-with(@data-testid,'options_')][contains(.,'{code}')]", 'timeoutMs': 8000},
        {"type": 'evaluate', 'script': _pick_airport_option(code)},
    ]


def _select_date(date_iso: str, field: str, picker: str = "") -> list:
    """open the calendar with the picker field (when given), wait for the day to be drawn, click it and check
    that the date field took it"""
    open_calendar = [{"type": 'click', 'selector': picker, 'timeoutMs': 5000}] if picker else []
    return open_calendar + [
        {"type": "wait", "milliseconds": 1000},
        {"type": 'waitForSelector', 'selector': _date_cell_selector(date_iso), 'timeoutMs': 8000},
        {"type": 'evaluate', 'script': _date_click_script(date_iso)},
        # the search is only sent with both dates set, a click the calendar did not take must fail here
        {"type": 'waitForSelector', 'selector': field, 'timeoutMs': 5000},
    ]


def _build_search_scenario(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
) -> list:
    scenario = [
        {"type": 'click', 'selector': "button[id*='onetrust-accept']", 'timeoutMs': 10000, "optional": True},
        {"type": "wait", "milliseconds": 1000},
    ]

    if not return_date:
        scenario.append(
            {"type": 'evaluate', 'script': "[...document.querySelectorAll('button[role=tab]')].find(b=>b.textContent.trim()==='One way')?.click();"}
        )

    scenario += _fill_airport("Departure", origin)
    scenario += _fill_airport("Arrival", destination)

    if return_date:
        scenario += _select_date(departure_date, "#startDate:not([value=''])", "#startDate")
        # after the departure date the calendar moves on to the return date by itself,
        # so the return day is picked without clicking the return field
        scenario += _select_date(return_date, "#endDate:not([value=''])")
    else:
        scenario += _select_date(
            departure_date, "#date-input0:not([value='']), #startDate:not([value=''])", "#date-input0, #startDate"
        )

    scenario += [
        {"type": 'click', 'selector': "button.rsw-submit-button", 'timeoutMs': 10000},
        {"type": "wait", "milliseconds": 3000},
        {"type": 'click', 'selector': ".bottom-block__continue button", 'timeoutMs': 10000, "optional": True},
        {"type": "wait", "milliseconds": 2000},
    ]
    return scenario


def _format_arrival_time(departure_iso: str, arrival_iso: str) -> str:
    departure = datetime.fromisoformat(departure_iso)
    arrival = datetime.fromisoformat(arrival_iso)
    day_diff = (arrival.date() - departure.date()).days
    return arrival.strftime("%H:%M") + (f"+{day_diff}" if day_diff > 0 else "")


def _parse_layovers(segments: list) -> List[dict]:
    layovers = []
    for segment in segments:
        for stop in segment.get("stopDetails") or []:
            layovers.append({"airport": stop["arrival"], "duration": stop["duration"]})
        if segment.get("connection"):
            layovers.append(
                {"airport": segment["departure"], "duration": segment.get("connectionLayover")}
            )
    return layovers


def parse_branded_fares(response: Response) -> dict:
    """Parse branded-fares API response from captured XHR calls."""
    _xhr_calls = response.network
    for xhr in _xhr_calls:
        url = urlparse(xhr.get("url", ""))
        # the full search results come from the call without query parameters,
        # calls with parameters (leg, pageNumber, ...) only load a part of them
        if not url.path.endswith("search-results/branded-fares") or url.query or not xhr.get("response"):
            continue
        status = xhr["response"].get("status")
        if status != 200:
            # emirates can answer the results request with a redirect to its access restricted page
            if "accessrestricted" in ((xhr["response"].get("headers") or {}).get("location") or ""):
                raise ValueError("emirates.com redirected the flight results request to its access restricted page")
            raise ValueError(
                f"emirates.com answered the branded-fares search results with status {status} instead of flight data"
            )
        return json.loads(xhr["response"]["body"])
    # no flight results were loaded, say whether the browser got to the results page at all
    page_url = response.url or ""
    if "/search-results" not in page_url:
        raise ValueError(f"emirates.com did not open the search results page, the browser ended on {page_url}")
    raise ValueError(
        "emirates.com opened the search results page but the flight results (branded-fares) were not loaded"
    )


def parse_lowest_fare(data: dict) -> FarePrice:
    """Parse search-wide lowest fare from branded-fares API response."""
    currency = data.get("currency", {}).get("sale", {}).get("code", "")
    amount = data["lowestFare"]["total"][0]["amount"]
    return FarePrice(amount=amount, currency=currency)


def parse_flight_offers(data: dict) -> List[FlightResult]:
    """Parse branded-fares API response into flight results"""
    currency = data.get("currency", {}).get("sale", {}).get("code", "")
    flights: List[FlightResult] = []

    for bound in data.get("bounds", []):
        for option in bound.get("options", []):
            segments = option.get("airSegments", [])
            if not segments:
                continue

            first_segment = segments[0]
            last_segment = segments[-1]
            layovers = _parse_layovers(segments)
            departure_time = datetime.fromisoformat(first_segment["departureDateTime"]).strftime("%H:%M")
            arrival_time = _format_arrival_time(
                first_segment["departureDateTime"], last_segment["arrivalDateTime"]
            )
            flight_number = " / ".join(
                f"{segment['carrierCode']} {segment['flightNumber']}"
                for segment in segments
                if segment.get("segmentType") == "FLT"
            )

            for cabin in option.get("cabins", []):
                for brand in cabin.get("brandInformation") or []:
                    if brand.get("status") != "AVAILABLE":
                        continue

                    fare_amount = brand["priceDetails"]["summary"]["total"][0]["amount"]
                    carrier_code = first_segment.get("carrierCode", "")
                    cabin_code = brand.get("cabinClass") or cabin.get("cabinClass", "")
                    flights.append(
                        FlightResult(
                            airline=CARRIER_NAMES.get(carrier_code, carrier_code),
                            flight_number=flight_number,
                            departure_time=departure_time,
                            departure_airport=first_segment["departure"],
                            arrival_time=arrival_time,
                            arrival_airport=last_segment["arrival"],
                            duration=option.get("ondDuration", ""),
                            stops=option.get("numberOfConnections", 0),
                            layovers=layovers,
                            price=FarePrice(
                                amount=fare_amount,
                                currency=currency,
                            ),
                            cabin_class=CABIN_NAMES.get(cabin_code, cabin_code),
                            plane_model=first_segment.get("aircraftType", ""),
                            fare_brand=brand.get("fareBrand", ""),
                            seats_available=brand.get("seatsAvailable", 0),
                            captured_at=datetime.now().isoformat(),
                        )
                    )

    log.success(f"parsed {len(flights)} flight offers")
    return flights

@managed
async def scrape_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    locale: str = "us/english",
) -> FlightSearch:
    """Scrape flights from emirates.com"""
    try:
        response = await CLIENT.fetch(
            Request(
                f"https://www.emirates.com/{locale}/book/",
                **BASE_CONFIG,
                actions=_build_search_scenario(origin, destination, departure_date, return_date),
            )
        )
    except ScrapeError as e:
        # emirates can send the browser to its access restricted page during the search,
        # the next scenario step then fails because the search form is gone
        result = ({"url": e.response.url} if e.response else {})
        if "accessrestricted" in (result.get("url") or ""):
            raise ValueError("emirates.com redirected the search to its access restricted page") from e
        raise
    data = parse_branded_fares(response)
    return FlightSearch(
        locale=locale,
        trip_type="return" if return_date else "one-way",
        origin=origin,
        destination=destination,
        route=f"{origin}-{destination}",
        search_date=datetime.now().strftime("%Y-%m-%d"),
        departure_date=departure_date,
        return_date=return_date,
        lowest_fare=parse_lowest_fare(data),
        flights=parse_flight_offers(data),
    )
