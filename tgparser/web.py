"""Проверка через публичные страницы t.me и fragment.com (без аккаунта Telegram)."""
from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class CheckError(Exception):
    """Проверку не удалось выполнить (сеть, бан по частоте, неизвестная страница)."""


class RateLimiter:
    """Минимальный интервал между запросами к одному сайту.

    После 429 интервал растёт, после серии успешных запросов — возвращается к базовому.
    """

    def __init__(self, interval: float, max_interval: float = 10.0):
        self.base = self.interval = interval
        self.max_interval = max_interval
        self._next_at = 0.0
        self._ok_streak = 0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            self._next_at = max(now, self._next_at) + self.interval
        if delay > 0:
            await asyncio.sleep(delay)

    def penalize(self) -> None:
        self._ok_streak = 0
        self.interval = min(max(self.interval * 1.5, 0.5), self.max_interval)

    def reward(self) -> None:
        self._ok_streak += 1
        if self._ok_streak >= 50 and self.interval > self.base:
            self._ok_streak = 0
            self.interval = max(self.base, self.interval / 1.25)


def make_client(proxy: str | None = None, timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
        proxy=proxy,
    )


async def fetch(client: httpx.AsyncClient, url: str, limiter: RateLimiter, retries: int = 4) -> httpx.Response:
    last_error = ""
    for attempt in range(retries + 1):
        await limiter.wait()
        try:
            response = await client.get(url)
        except httpx.HTTPError as e:
            last_error = f"{type(e).__name__}: {e}"
        else:
            if response.status_code not in RETRY_STATUSES:
                limiter.reward()
                return response
            last_error = f"HTTP {response.status_code}"
            if response.status_code == 429:
                limiter.penalize()
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < retries:
                    await asyncio.sleep(min(int(retry_after), 300))
                    continue
        if attempt < retries:
            await asyncio.sleep(2 ** (attempt + 1))
    raise CheckError(f"{url}: {last_error}")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


# ---------------------------------------------------------------- t.me

_TME_TITLE_RE = re.compile(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', re.S)
_TME_EXTRA_RE = re.compile(r'<div class="tgme_page_extra"[^>]*>(.*?)</div>', re.S)
_TME_EMPTY_MARKERS = ("tgme_username_link", "you can contact @")


@dataclass
class TmeResult:
    exists: bool
    detail: str = ""


def parse_tme(page: str) -> TmeResult:
    """Есть профиль (человек, канал, группа, бот) — заголовок с именем.

    Нет профиля — заглушка «If you have Telegram, you can contact @name right away».
    Такой юзернейм свободен ИЛИ зарезервирован / продаётся на Fragment.
    """
    title = _TME_TITLE_RE.search(page)
    if title:
        extra = _TME_EXTRA_RE.search(page)
        detail = _text(title.group(1))
        if extra:
            detail = f"{detail} ({_text(extra.group(1))})"
        return TmeResult(True, detail)
    if any(marker in page for marker in _TME_EMPTY_MARKERS):
        return TmeResult(False)
    raise CheckError("t.me: неизвестная страница (капча или изменилась вёрстка)")


class TmeChecker:
    def __init__(self, client: httpx.AsyncClient, interval: float):
        self.client = client
        self.limiter = RateLimiter(interval)

    async def check(self, username: str) -> TmeResult:
        response = await fetch(self.client, f"https://t.me/{username}", self.limiter)
        return parse_tme(response.text)


# ---------------------------------------------------------- fragment.com

_FRAGMENT_HEADER_STATUS_RE = re.compile(r'class="[^"]*tm-section-header-status[^"]*"[^>]*>(.*?)<', re.S)
_FRAGMENT_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_FRAGMENT_ROW_STATUS_RE = re.compile(r'class="[^"]*table-cell-status-thin[^"]*"[^>]*>(.*?)<', re.S)
_FRAGMENT_PRICE_RE = re.compile(r'icon-ton[^"]*"[^>]*>\s*([\d][\d,.]*)\s*<')

# Можно получить: начать аукцион, сделать ставку или купить сразу.
FRAGMENT_BUYABLE = {"available", "on auction", "for sale"}
# Уже у кого-то: куплен как NFT или занят в Telegram.
FRAGMENT_OWNED = {"sold", "taken"}


@dataclass
class FragmentResult:
    status: str  # available / on auction / for sale / sold / taken / unavailable / not listed
    price_ton: str = ""

    @property
    def detail(self) -> str:
        price = f", {self.price_ton} TON" if self.price_ton else ""
        return f"fragment: {self.status}{price}"


def parse_fragment(page: str, username: str) -> FragmentResult:
    """Статус со страницы fragment.com/username/<name> или из таблицы поиска."""
    status_match = _FRAGMENT_HEADER_STATUS_RE.search(page)
    scope = page
    if not status_match:
        # Страницы нет — fragment показал поиск; ищем строку ровно с этим юзернеймом.
        href = f'href="/username/{username}"'
        row = next((r for r in _FRAGMENT_ROW_RE.findall(page) if href in r), None)
        if row is None:
            return FragmentResult("not listed")
        scope = row
        status_match = _FRAGMENT_ROW_STATUS_RE.search(row)
        if not status_match:
            return FragmentResult("not listed")
    status = _text(status_match.group(1)).lower()
    price = _FRAGMENT_PRICE_RE.search(scope) if status in FRAGMENT_BUYABLE else None
    return FragmentResult(status, price.group(1) if price else "")


class FragmentChecker:
    def __init__(self, client: httpx.AsyncClient, interval: float):
        self.client = client
        self.limiter = RateLimiter(interval)

    async def check(self, username: str) -> FragmentResult:
        response = await fetch(self.client, f"https://fragment.com/username/{username}", self.limiter)
        if response.status_code == 404:
            return FragmentResult("not listed")
        return parse_fragment(response.text, username)
