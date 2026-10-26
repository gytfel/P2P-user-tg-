"""Порядок проверок одного юзернейма и параллельный запуск."""
from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from . import statuses as st
from .rules import is_collectible_only, is_valid
from .web import FRAGMENT_BUYABLE, FRAGMENT_OWNED, CheckError


class TooManyErrors(Exception):
    """Слишком много ошибок подряд — сайт недоступен или нас ограничили."""


@dataclass
class Result:
    username: str
    source: str
    status: str
    detail: str = ""


class UsernameChecker:
    """t.me → fragment.com → Telegram API; дешёвые проверки отсеивают занятые раньше."""

    def __init__(self, tme, fragment=None, api=None, fragment_for_long: bool = True):
        self.tme = tme
        self.fragment = fragment
        self.api = api
        self.fragment_for_long = fragment_for_long

    async def check(self, username: str, source: str) -> Result:
        try:
            return await self._check(username, source)
        except CheckError as e:
            return Result(username, source, st.ERROR, str(e))
        except Exception as e:  # одна сбойная проверка не должна останавливать весь прогон
            return Result(username, source, st.ERROR, f"{type(e).__name__}: {e}")

    async def _check(self, username: str, source: str) -> Result:
        if not is_valid(username):
            return Result(username, source, st.INVALID, "не проходит правила Telegram")

        tme = await self.tme.check(username)
        if tme.exists:
            return Result(username, source, st.TAKEN, f"t.me: {tme.detail}")

        short = is_collectible_only(username)
        fragment_detail = ""
        if self.fragment and (short or self.fragment_for_long):
            fragment = await self.fragment.check(username)
            fragment_detail = fragment.detail
            if fragment.status in FRAGMENT_BUYABLE:
                return Result(username, source, st.FRAGMENT, fragment_detail)
            if fragment.status in FRAGMENT_OWNED:
                return Result(username, source, st.TAKEN, fragment_detail)

        if short:
            # 4 символа нельзя занять бесплатно, а на Fragment он сейчас не продаётся.
            return Result(username, source, st.UNAVAILABLE, fragment_detail or "только через Fragment")

        if self.api:
            verdict = await self.api.check(username)
            if verdict:
                return Result(username, source, *verdict)

        return Result(username, source, st.LIKELY_FREE, "t.me: профиля нет")


async def run_checks(
    candidates: Iterable[tuple[str, str]],
    checker: UsernameChecker,
    on_result,
    concurrency: int,
    total: int | None = None,
    progress_every: float = 15.0,
    max_errors_in_row: int = 30,
) -> Counter:
    queue: asyncio.Queue = asyncio.Queue(maxsize=concurrency * 4)
    stats: Counter = Counter()
    started = time.monotonic()
    last_progress = started
    reported = 0
    errors_in_row = 0

    def progress() -> None:
        nonlocal reported
        done = reported = sum(stats.values())
        speed = done / max(time.monotonic() - started, 1e-9)
        of_total = f"/{total}" if total else ""
        eta = ""
        if total and speed > 0:
            eta = f", осталось ~{_fmt_duration((total - done) / speed)}"
        counts = ", ".join(f"{st.LABELS[k]}: {v}" for k, v in stats.most_common())
        print(f"[{done}{of_total}] {speed:.1f}/с{eta} | {counts}", file=sys.stderr, flush=True)

    async def worker() -> None:
        nonlocal last_progress, errors_in_row
        while True:
            item = await queue.get()
            if item is None:
                return
            result = await checker.check(*item)
            stats[result.status] += 1
            on_result(result)
            errors_in_row = errors_in_row + 1 if result.status == st.ERROR else 0
            if errors_in_row >= max_errors_in_row:
                raise TooManyErrors(f"{errors_in_row} ошибок подряд, последняя: {result.detail}")
            if time.monotonic() - last_progress >= progress_every:
                last_progress = time.monotonic()
                progress()

    async def produce() -> None:
        for item in candidates:
            await queue.put(item)
        for _ in workers:
            await queue.put(None)

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    producer = asyncio.create_task(produce())
    try:
        await asyncio.gather(producer, *workers)
    finally:
        for task in (producer, *workers):
            task.cancel()
        if sum(stats.values()) != reported:
            progress()
    return stats


def _fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} мин"
    return f"{minutes // 60} ч {minutes % 60} мин"
