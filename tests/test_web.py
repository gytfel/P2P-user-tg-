import asyncio

import httpx
import pytest
from conftest import fixture

from tgparser.web import CheckError, FragmentChecker, RateLimiter, TmeChecker, fetch, parse_fragment, parse_tme


def test_tme_user():
    r = parse_tme(fixture("tme_user.html"))
    assert r.exists and r.detail == "Pavel Durov (@durov)"


def test_tme_channel():
    r = parse_tme(fixture("tme_channel.html"))
    assert r.exists and "subscribers" in r.detail


def test_tme_empty():
    assert not parse_tme(fixture("tme_empty.html")).exists


def test_tme_unknown_page_is_error():
    with pytest.raises(CheckError):
        parse_tme("<html><body>Just a moment...</body></html>")


def test_fragment_available():
    r = parse_fragment(fixture("fragment_available.html"), "qzxw")
    assert r.status == "available" and r.price_ton == "10"
    assert r.detail == "fragment: available, 10 TON"


def test_fragment_sold_has_no_price():
    r = parse_fragment(fixture("fragment_sold.html"), "news")
    assert r.status == "sold" and r.price_ton == ""


def test_fragment_search_rows():
    page = fixture("fragment_search.html")
    assert parse_fragment(page, "qzxw").status == "unavailable"
    on_auction = parse_fragment(page, "qzxwa")
    assert on_auction.status == "on auction" and on_auction.price_ton == "7"
    assert parse_fragment(page, "other").status == "not listed"


def run(coro):
    return asyncio.run(coro)


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_retries_429(monkeypatch):
    calls = []

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def handler(request):
        calls.append(request.url)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, text=fixture("tme_empty.html"))

    async def go():
        async with mock_client(handler) as client:
            limiter = RateLimiter(0.0)
            r = await fetch(client, "https://t.me/x", limiter)
            return r, limiter

    response, limiter = run(go())
    assert response.status_code == 200 and len(calls) == 3
    assert limiter.interval > 0  # после 429 замедлились


def test_fetch_gives_up(monkeypatch):
    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    async def go():
        async with mock_client(lambda r: httpx.Response(503)) as client:
            await fetch(client, "https://t.me/x", RateLimiter(0.0), retries=2)

    with pytest.raises(CheckError, match="503"):
        run(go())


def test_checkers_hit_right_urls():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "t.me":
            return httpx.Response(200, text=fixture("tme_user.html"))
        return httpx.Response(200, text=fixture("fragment_available.html"))

    async def go():
        async with mock_client(handler) as client:
            tme = await TmeChecker(client, 0).check("durov")
            frag = await FragmentChecker(client, 0).check("qzxw")
            return tme, frag

    tme, frag = run(go())
    assert tme.exists and frag.status == "available"
    assert seen == ["https://t.me/durov", "https://fragment.com/username/qzxw"]
