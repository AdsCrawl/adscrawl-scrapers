"""Offline checks for the US wave-3 scraper fixes.

These do not call AdsCrawl. A live US retest still has to run on a box with an API key.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from adscrawl_scrapers import Response, ScrapeError

ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path):
    name = "wave3_" + path.parent.name.replace("-", "_") + "_" + path.stem
    cached = __import__("sys").modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    __import__("sys").modules[name] = module
    spec.loader.exec_module(module)
    return module


def _html(title="Store"):
    return Response("https://example.com/final", f"<html><title>{title}</title></html>", status_code=200)


async def test_etsy_reads_the_document_without_navigating_to_it(monkeypatch):
    module = load_module(ROOT / "etsy-scraper/etsy.py")
    listing = "https://www.etsy.com/listing/971370843"
    calls = []

    async def fetch(request):
        calls.append(request)
        if len(calls) == 1:
            return Response(request.url, "<html><title>Access denied</title></html>", status_code=403)
        return _html("Etsy")

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    page = await module._fetch_document(listing, waitForSelector="//div[@data-search-pagination]", autoScroll=True)
    assert page.status_code == 200
    assert [item.url for item in calls] == [listing, listing]
    assert calls[0].binary is True and calls[1].binary is True
    assert calls[0].session is None and calls[1].session is None
    assert calls[0].waitForSelector is None and calls[0].autoScroll is False
    assert calls[0].headers["Referer"] == module._HOME
    assert calls[0].userAgentOs == "windows"
    assert calls[0].timeoutMs == 45_000


async def test_ebay_document_uses_one_session_for_homepage_and_item(monkeypatch):
    module = load_module(ROOT / "ebay-scraper/ebay.py")
    item = "https://www.ebay.com/itm/177439887865"
    calls = []

    async def fetch(request):
        calls.append(request)
        return _html("eBay")

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    monkeypatch.setattr(module.CLIENT, "close_session", AsyncMock())
    await module._fetch_document(item)
    assert [item.url for item in calls] == [module._HOME, item]
    assert calls[0].session and calls[0].session == calls[1].session
    assert calls[1].headers["Referer"] == module._HOME
    assert calls[0].raiseOnHttpError is False and calls[1].raiseOnHttpError is False


async def test_yelp_reviews_fetch_in_page_and_retry_connect(monkeypatch):
    module = load_module(ROOT / "yelp-scraper/yelp.py")
    biz = "https://www.yelp.com/biz/vons-1000-spirits-seattle-4"
    biz_html = '<html><title>Vons</title><meta name="yelp-biz-id" content="biz123"></html>'
    api = json.dumps([{"data": {"business": {"reviews": {"edges": []}, "reviewCount": 0}}}])
    calls = []

    async def fetch(request):
        calls.append(request)
        if len(calls) == 1:
            raise ScrapeError("AdsCrawl CDP connection failed", code="CONNECT_FAILED")
        if "gql" in request.url:
            return Response(request.url, api, status_code=200)
        if request.url.rstrip("/") == "https://www.yelp.com":
            return _html("Yelp")
        return Response(request.url, biz_html, status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    closed = AsyncMock()
    monkeypatch.setattr(module.CLIENT, "close_session", closed)
    assert await module.scrape_reviews(biz, max_reviews=10) == []
    assert calls[0].url == biz and calls[0].binary is True
    assert calls[1].url == biz and calls[1].binary is True
    assert "gql/batch" in calls[2].url and calls[2].method == "POST" and calls[2].binary is True
    assert calls[1].session == calls[2].session
    assert calls[0].session != calls[1].session
    assert module._HOME not in [item.url for item in calls]
    assert calls[2].timeoutMs == 45_000
    assert closed.await_count == 2


async def test_threads_closes_named_sessions_before_the_next_post(monkeypatch):
    module = load_module(ROOT / "threads-scraper/threads.py")
    module.CLIENT.concurrency = 1
    module._GATE.update(loop=None, concurrency=None, semaphore=None)
    events = []
    state = {"active": 0, "max": 0}

    async def fetch(request):
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        await asyncio.sleep(0.02)
        state["active"] -= 1
        events.append(("fetch", request.session))
        return Response(request.url, "<html></html>", status_code=200)

    async def close(name):
        events.append(("close", name))

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    monkeypatch.setattr(module.CLIENT, "close_session", close)
    urls = [
        "https://www.threads.net/t/C8H5FiCtESk/",
        "https://www.threads.net/t/C8CTu0iswgv",
    ]
    results = await asyncio.wait_for(
        asyncio.gather(*[module.scrape_thread(url) for url in urls], return_exceptions=True),
        2,
    )
    assert all(isinstance(result, ValueError) for result in results)
    assert state["max"] == 1
    assert [kind for kind, _name in events] == ["fetch", "close", "fetch", "close"]
    assert events[0][1] == events[1][1]
    assert events[2][1] == events[3][1]
    assert events[0][1] != events[2][1]


async def test_linkedin_guest_pages_stop_before_the_extra_login_page(monkeypatch):
    module = load_module(ROOT / "linkedin-scraper/linkedin.py")
    html = """
    <html><title>Python Developer jobs | LinkedIn</title>
    <span class="job-count">1,000+</span>
    <section class="results-list"><ul><li>
      <div>
        <a href="https://www.linkedin.com/jobs/view/1"><span>Engineer</span></a>
        <div class="info">
          <h4><a href="https://www.linkedin.com/company/acme">Acme</a></h4>
          <div><span>Remote</span></div>
          <div><time datetime="2026-01-01"></time></div>
        </div>
      </div>
    </li></ul></section></html>
    """
    calls = []

    async def fetch(request):
        calls.append(request)
        return Response(request.url, html, status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    jobs = await module.scrape_job_search("Python Developer", "United States", max_pages=3)
    assert jobs and jobs[0]["title"] == "Engineer"
    starts = []
    for request in calls:
        query = request.url.split("start=", 1)
        if len(query) == 2:
            starts.append(int(query[1].split("&", 1)[0]))
            assert request.render is False
            assert request.headers["Referer"].startswith("https://www.linkedin.com/jobs/search?")
    assert starts == [25, 50]


async def test_linkedin_company_retries_timeout_on_www(monkeypatch):
    module = load_module(ROOT / "linkedin-scraper/linkedin.py")
    calls = []

    async def fetch(request):
        calls.append(request.url)
        if len(calls) == 1:
            raise ScrapeError("Remote browser request failed or timed out", code="TIMEOUT")
        return Response(request.url, "<html><title>Microsoft | LinkedIn</title></html>", status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    await module.scrape_company(["https://linkedin.com/company/microsoft"])
    assert calls[0] == calls[1] == "https://www.linkedin.com/company/microsoft"
    assert calls[2] == "https://www.linkedin.com/company/microsoft/life"


async def test_tunnel_gets_one_new_browser(monkeypatch):
    cases = [
        (
            ROOT / "airbnb-scraper/airbnb.py",
            "scrape_listings",
            ("Paris",),
            {"max_pages": 1},
            "<html></html>",
        ),
        (
            ROOT / "goat-scraper/goat.py",
            "scrape_search",
            ("pumar dark",),
            {"max_pages": 1},
            json.dumps({"data": {"productsList": [{"id": "1"}], "totalResults": 1}}),
        ),
        (
            ROOT / "goodreads-scraper/goodreads.py",
            "scrape_reviews",
            ("https://www.goodreads.com/book/show/1",),
            {},
            "<html></html>",
        ),
        (
            ROOT / "google-play-scraper/google_play.py",
            "scrape_reviews",
            ("com.whatsapp",),
            {"max_reviews": 1},
            "",
        ),
    ]
    for path, name, args, kwargs, body in cases:
        module = load_module(path)
        seen = {"n": 0}

        async def fetch(request, seen=seen, body=body):
            seen["n"] += 1
            if seen["n"] == 1:
                code = "BROWSER_ERROR" if "google-play" in str(path) else "ERR_TUNNEL_CONNECTION_FAILED"
                raise ScrapeError("Browser navigation or interaction failed", code=code)
            return Response(request.url, body, status_code=200)

        monkeypatch.setattr(module.CLIENT, "fetch", fetch)
        await getattr(module, name)(*args, **kwargs)
        assert seen["n"] == 2, path.name


async def test_google_play_reviews_use_an_in_page_fetch(monkeypatch):
    module = load_module(ROOT / "google-play-scraper/google_play.py")
    calls = []

    async def fetch(request):
        calls.append(request)
        return Response(request.url, "", status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    assert await module.scrape_reviews("com.whatsapp", max_reviews=1) == []
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].binary is True
    assert calls[0].url.startswith("https://play.google.com/_/PlayStoreUi/data/batchexecute")
    assert "f.req=" in calls[0].body


async def test_airbnb_property_loads_without_waiting_for_reviews(monkeypatch):
    module = load_module(ROOT / "airbnb-scraper/airbnb.py")
    calls = []

    async def fetch(request):
        calls.append(request)
        return Response(request.url, "<html></html>", status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    monkeypatch.setattr(module, "parse_property", lambda response: {"url": response.url, "id": "1"})
    result = await module.scrape_properties(
        ["https://www.airbnb.com/rooms/1"],
        check_in="2026-11-04",
        check_out="2026-11-11",
    )
    assert result == [{"url": calls[0].url, "id": "1"}]
    assert len(calls) == 1
    assert calls[0].waitForResponse is None
    assert calls[0].waitMs == 8000
    assert "check_in=2026-11-04" in calls[0].url


def test_emirates_search_url_matches_the_widget_payload():
    import base64
    from urllib.parse import unquote

    module = load_module(ROOT / "emirates-scraper/emirates.py")
    url = module._search_results_url("JFK", "DXB", "2026-11-04", "2026-11-11")
    assert url.startswith("https://www.emirates.com/booking/search-results/?searchRequest=")
    payload = json.loads(base64.b64decode(unquote(url.split("searchRequest=", 1)[1])))
    assert payload == {
        "journeyType": "RETURN",
        "bookingType": "REVENUE",
        "passengers": [{"type": "ADT", "count": 1}],
        "segments": [
            {"departure": "JFK", "arrival": "DXB", "travelDate": "2026-11-04", "cabinClass": "Y"},
            {"departure": "DXB", "arrival": "JFK", "travelDate": "2026-11-11", "cabinClass": "Y"},
        ],
    }
    one_way = module._search_results_url("JFK", "DXB", "2026-11-04")
    one_way_payload = json.loads(base64.b64decode(unquote(one_way.split("searchRequest=", 1)[1])))
    assert one_way_payload["journeyType"] == "ONEWAY"
    assert len(one_way_payload["segments"]) == 1


async def test_emirates_warms_the_book_page_before_search_results(monkeypatch):
    module = load_module(ROOT / "emirates-scraper/emirates.py")
    calls = []

    async def fetch(request):
        calls.append(request)
        searches = [item for item in calls if "search-results" in item.url]
        if "search-results" in request.url and len(searches) == 1:
            return Response(
                "https://www.emirates.com/error/accessrestricted.html",
                "<html></html>",
                status_code=200,
            )
        return Response(request.url, "<html></html>", status_code=200)

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    closed = AsyncMock()
    monkeypatch.setattr(module.CLIENT, "close_session", closed)
    monkeypatch.setattr(module, "parse_branded_fares", lambda response: {
        "currency": {"sale": {"code": "USD"}},
        "lowestFare": {"total": [{"amount": 10}]},
        "bounds": [],
    })
    result = await module.scrape_flights("JFK", "DXB", "2026-12-01", return_date="2026-12-08")
    assert [item.url for item in calls[:2]] == [
        "https://www.emirates.com/us/english/book/",
        calls[1].url,
    ]
    assert "/booking/search-results/" in calls[1].url
    assert calls[0].session == calls[1].session
    assert calls[2].url == calls[0].url
    assert "/booking/search-results/" in calls[3].url
    assert calls[2].session == calls[3].session
    assert calls[0].session != calls[2].session
    assert calls[1].headers["Referer"] == "https://www.emirates.com/us/english/book/"
    assert all(action.get("selector") != "button.rsw-submit-button" for action in calls[0].actions)
    assert closed.await_count == 2
    assert result["origin"] == "JFK" and result["flights"] == []


async def test_perplexity_retries_signup_wall_with_a_new_session(monkeypatch):
    module = load_module(ROOT / "perplexity-scraper/perplexity.py")
    answer = (
        'data: {"final": true, "query_str": "How does photosynthesis work", '
        '"blocks": [{"workflow_block": {"steps": [{"items": [{"payload": {"text_payload": '
        '{"variant": "answer", "text": "Plants convert light into chemical energy."}}}]}]}}], '
        '"related_queries": []}\n'
    )
    calls = []

    async def fetch(request):
        calls.append(request)
        if request.method == "POST" and sum(item.method == "POST" for item in calls) == 1:
            return Response(request.url, "Sign up and repeat your request.", status_code=200)
        if request.method == "POST":
            return Response(request.url, answer, status_code=200)
        return _html("Perplexity")

    monkeypatch.setattr(module.CLIENT, "fetch", fetch)
    closed = AsyncMock()
    monkeypatch.setattr(module.CLIENT, "close_session", closed)
    result = await module.scrape_answer("How does photosynthesis work")
    assert "light" in result["answer_markdown"]
    assert [item.url for item in calls] == [module._HOME, module._ASK, module._HOME, module._ASK]
    assert calls[0].session == calls[1].session
    assert calls[2].session == calls[3].session
    assert calls[0].session != calls[2].session
    assert calls[1].render is False
    assert calls[1].headers["referer"] == module._HOME
    assert closed.await_count == 2
