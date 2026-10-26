import asyncio

import pytest

errors = pytest.importorskip("telethon.errors")

from tgparser import statuses as st  # noqa: E402
from tgparser.telegram_api import TelegramApiChecker  # noqa: E402


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, request):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def make_checker(tmp_path, monkeypatch, answers, max_flood_wait=60):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    checker = TelegramApiChecker(1, "hash", str(tmp_path / "test"), 0, max_flood_wait)
    checker.client = FakeClient(answers)
    return checker, sleeps


@pytest.mark.parametrize(
    "answer, status",
    [
        (True, st.FREE),
        (False, st.TAKEN),
        (errors.UsernamePurchaseAvailableError(None), st.FRAGMENT),
        (errors.UsernameOccupiedError(None), st.TAKEN),
        (errors.UsernameInvalidError(None), st.INVALID),
    ],
)
def test_verdicts(tmp_path, monkeypatch, answer, status):
    checker, _ = make_checker(tmp_path, monkeypatch, [answer])
    assert asyncio.run(checker.check("abcdef"))[0] == status


def test_short_flood_wait_is_waited_out(tmp_path, monkeypatch):
    checker, sleeps = make_checker(tmp_path, monkeypatch, [errors.FloodWaitError(None, capture=30), True])
    assert asyncio.run(checker.check("abcdef"))[0] == st.FREE
    assert 31 in sleeps and checker.enabled


def test_long_flood_wait_disables_api(tmp_path, monkeypatch):
    checker, _ = make_checker(tmp_path, monkeypatch, [errors.FloodWaitError(None, capture=3600)])
    assert asyncio.run(checker.check("abcdef")) is None
    assert not checker.enabled
    assert asyncio.run(checker.check("other")) is None
    assert checker.client.calls == 1
