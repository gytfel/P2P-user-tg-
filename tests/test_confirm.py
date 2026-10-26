import argparse
import asyncio
import csv

import pytest

import tgparser.cli as cli
from tgparser import statuses as st
from tgparser.pipeline import Result
from tgparser.storage import ResultStore


class FakeApi:
    def __init__(self, verdicts, disable_after=None):
        self.verdicts = verdicts
        self.disable_after = disable_after
        self.enabled = True
        self.calls = []
        self.started = self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def check(self, username):
        if self.disable_after is not None and len(self.calls) >= self.disable_after:
            self.enabled = False
            return None
        self.calls.append(username)
        return self.verdicts.get(username)


@pytest.fixture
def results(tmp_path):
    out = tmp_path / "out"
    store = ResultStore(out)
    for name, status in [
        ("bayern", st.LIKELY_FREE),
        ("kriptoobmen", st.LIKELY_FREE),
        ("someword", st.LIKELY_FREE),
        ("durov", st.TAKEN),
    ]:
        store.add(Result(name, "test", status, "t.me: профиля нет"))
    store.write_findings()
    store.close()
    return out


def statuses(out):
    with open(out / "results.csv", newline="", encoding="utf-8-sig") as f:
        return {row["username"]: row["status"] for row in csv.DictReader(f)}


def no_sleep(monkeypatch):
    async def fake(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", fake)


def test_confirm_removes_reserved(results, monkeypatch, capsys):
    api = FakeApi(
        {
            "bayern": (st.INVALID, "api: зарезервирован или запрещён"),
            "kriptoobmen": (st.FREE, "api: свободен"),
            "someword": (st.TAKEN, "api: занят"),
        }
    )
    monkeypatch.setattr(cli, "make_api_checker", lambda args, required: api)
    assert cli.main(["confirm", "--out", str(results)]) == 0

    assert statuses(results) == {
        "bayern": st.INVALID,
        "kriptoobmen": st.FREE,
        "someword": st.TAKEN,
        "durov": st.TAKEN,
    }
    assert api.calls == ["bayern", "someword", "kriptoobmen"]  # короткие первыми, занятые не трогаем
    assert api.started and api.stopped
    assert (results / "free.txt").read_text(encoding="utf-8").startswith("@kriptoobmen\t")
    assert not (results / "likely_free.txt").exists()
    assert "[зарезервирован] @bayern" in capsys.readouterr().out


def test_confirm_stops_on_long_flood_wait(results, monkeypatch, capsys):
    api = FakeApi({"bayern": (st.INVALID, "api: зарезервирован")}, disable_after=1)
    monkeypatch.setattr(cli, "make_api_checker", lambda args, required: api)
    assert cli.main(["confirm", "--out", str(results)]) == 1
    assert "FloodWait" in capsys.readouterr().err
    left = statuses(results)
    assert left["bayern"] == st.INVALID
    assert left["someword"] == left["kriptoobmen"] == st.LIKELY_FREE  # проверятся в следующий раз


def test_confirm_needs_keys(results):
    with pytest.raises(SystemExit, match="TG_API_ID"):
        cli.main(["confirm", "--out", str(results)])


def api_args(**kw):
    defaults = dict(no_api=False, session="s", api_delay=0, max_flood_wait=10)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class FakeTelegramApiChecker:
    def __init__(self, *args, proxy=None):
        self.args = args
        self.proxy = proxy


def test_api_turns_on_when_keys_present(monkeypatch):
    import tgparser.telegram_api

    monkeypatch.setattr(tgparser.telegram_api, "TelegramApiChecker", FakeTelegramApiChecker)
    assert cli.make_api_checker(api_args(), required=False) is None  # ключей нет — без API
    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "abc")
    checker = cli.make_api_checker(api_args(), required=False)
    assert isinstance(checker, FakeTelegramApiChecker) and checker.args[:2] == (123, "abc")
    assert checker.proxy is None
    monkeypatch.setenv("TG_PROXY", "socks5://127.0.0.1:1080")
    assert cli.make_api_checker(api_args(), required=False).proxy == "socks5://127.0.0.1:1080"
    assert cli.make_api_checker(api_args(no_api=True), required=False) is None


def test_api_flag_requires_keys():
    with pytest.raises(SystemExit, match="TG_API_ID"):
        cli.make_api_checker(api_args(), required=True)


def test_api_and_no_api_conflict():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["check", "abcde", "--api", "--no-api"])


class OfflineApi(FakeApi):
    async def start(self):
        raise ConnectionError("Connection to Telegram failed 3 time(s)")


def test_confirm_without_connection_explains(results, monkeypatch):
    monkeypatch.setattr(cli, "make_api_checker", lambda args, required: OfflineApi({}))
    with pytest.raises(SystemExit, match="VPN"):
        cli.main(["confirm", "--out", str(results)])
    assert statuses(results)["bayern"] == st.LIKELY_FREE
