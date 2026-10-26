import asyncio
import csv

import httpx
from conftest import fixture

import tgparser.web as web
from tgparser import statuses as st
from tgparser.cli import main
from tgparser.pipeline import UsernameChecker
from tgparser.web import FragmentChecker, FragmentResult, TmeResult

# Имитация t.me и fragment.com:
TAKEN_ON_TME = {"durov", "bitcoin", "abab"}
FRAGMENT_PAGES = {"qzxw": "fragment_available.html", "news": "fragment_sold.html"}


def handler(request: httpx.Request) -> httpx.Response:
    name = request.url.path.rsplit("/", 1)[-1]
    if request.url.host == "t.me":
        if name == "brokenpage" and name not in TAKEN_ON_TME:
            return httpx.Response(503)
        page = "tme_user.html" if name in TAKEN_ON_TME else "tme_empty.html"
        return httpx.Response(200, text=fixture(page))
    if name in FRAGMENT_PAGES:
        return httpx.Response(200, text=fixture(FRAGMENT_PAGES[name]))
    return httpx.Response(200, text=fixture("fragment_search.html"))


def mock_make_client(proxy=None, timeout=20.0):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


class FakeTme:
    def __init__(self, taken):
        self.taken = taken

    async def check(self, username):
        return TmeResult(username in self.taken, "Someone")


class FakeFragment:
    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    async def check(self, username):
        self.calls.append(username)
        return FragmentResult(self.statuses.get(username, "not listed"))


class FakeApi:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = []

    async def check(self, username):
        self.calls.append(username)
        return self.verdicts.get(username)


def check(checker, name):
    return asyncio.run(checker.check(name, "test"))


def test_pipeline_statuses():
    fragment = FakeFragment({"qzxw": "available", "news": "sold", "lotsa": "for sale"})
    api = FakeApi({"freeone": (st.FREE, "api: свободен"), "resrvd": (st.INVALID, "api: запрещён")})
    checker = UsernameChecker(FakeTme({"durov"}), fragment, api)

    assert check(checker, "durov").status == st.TAKEN
    assert check(checker, "qzxw").status == st.FRAGMENT
    assert check(checker, "news").status == st.TAKEN
    assert check(checker, "lotsa").status == st.FRAGMENT
    assert check(checker, "zzzq").status == st.UNAVAILABLE  # 4 символа, не на Fragment
    assert check(checker, "freeone").status == st.FREE
    assert check(checker, "resrvd").status == st.INVALID
    assert check(checker, "nothing").status == st.LIKELY_FREE  # API не ответил
    assert check(checker, "1abcd").status == st.INVALID
    assert "durov" not in fragment.calls  # занятые на t.me дальше не проверяем
    assert "zzzq" not in api.calls  # 4-символьные не тратят лимит API


def test_no_fragment_for_long_names():
    fragment = FakeFragment({})
    checker = UsernameChecker(FakeTme(set()), fragment, None, fragment_for_long=False)
    assert check(checker, "abcdef").status == st.LIKELY_FREE
    assert check(checker, "abcd").status == st.UNAVAILABLE
    assert fragment.calls == ["abcd"]


def test_unexpected_exception_becomes_error():
    class Boom:
        async def check(self, username):
            raise RuntimeError("boom")

    result = check(UsernameChecker(Boom()), "abcdef")
    assert result.status == st.ERROR and "boom" in result.detail


def test_fragment_checker_404(monkeypatch):
    async def go():
        transport = httpx.MockTransport(lambda r: httpx.Response(404))
        async with httpx.AsyncClient(transport=transport) as client:
            return await FragmentChecker(client, 0).check("abcd")

    assert asyncio.run(go()).status == "not listed"


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row["username"]: row for row in csv.DictReader(f)}


def test_cli_end_to_end_and_resume(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(web, "make_client", mock_make_client)

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    names = tmp_path / "names.txt"
    names.write_text("durov\nqzxw\nnews\nqzxwa\nfreename\n@BitCoin\nbrokenpage\n", encoding="utf-8")
    out = tmp_path / "out"
    args = ["check", str(names), "--out", str(out), "--tme-delay", "0", "--fragment-delay", "0"]

    assert main(args) == 0
    rows = read_csv(out / "results.csv")
    assert {n: r["status"] for n, r in rows.items()} == {
        "durov": st.TAKEN,
        "bitcoin": st.TAKEN,
        "qzxw": st.FRAGMENT,
        "news": st.TAKEN,
        "qzxwa": st.FRAGMENT,
        "freename": st.LIKELY_FREE,
        "brokenpage": st.ERROR,
    }
    assert rows["qzxw"]["detail"] == "fragment: available, 10 TON"
    assert (out / "likely_free.txt").read_text(encoding="utf-8").startswith("@freename\t")
    fragment_lines = (out / "fragment.txt").read_text(encoding="utf-8").splitlines()
    assert [l.split("\t")[0] for l in fragment_lines] == ["@qzxw", "@qzxwa"]
    printed = capsys.readouterr().out
    assert "@freename" in printed and "@durov" not in printed

    # Повторный запуск проверяет только ошибки.
    TAKEN_ON_TME.add("brokenpage")
    try:
        assert main(args) == 0
    finally:
        TAKEN_ON_TME.discard("brokenpage")
    assert read_csv(out / "results.csv")["brokenpage"]["status"] == st.TAKEN
    with open(out / "results.csv", encoding="utf-8-sig") as f:
        assert len(f.read().splitlines()) == 1 + 7 + 1


def test_cli_dry_run(capsys):
    assert main(["short", "--preset", "pretty", "--dry-run", "--limit", "3"]) == 0
    assert capsys.readouterr().out.splitlines() == ["aaaa\tshort:pretty", "bbbb\tshort:pretty", "cccc\tshort:pretty"]


def test_cli_bad_pattern(capsys):
    assert main(["short", "--pattern", "1abc", "--dry-run"]) == 2
    assert "начинаться с буквы" in capsys.readouterr().err


def test_cli_stops_when_site_is_down(tmp_path, monkeypatch, capsys):
    requests = []

    def down(request):
        requests.append(request)
        return httpx.Response(503)

    monkeypatch.setattr(web, "make_client", lambda proxy=None: httpx.AsyncClient(transport=httpx.MockTransport(down)))

    async def no_sleep(_):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    out = tmp_path / "out"
    code = main(["short", "--preset", "pretty", "--out", str(out), "--tme-delay", "0", "--concurrency", "2"])
    assert code == 1
    assert "ошибок подряд" in capsys.readouterr().err
    errors = read_csv(out / "results.csv")
    assert 30 <= len(errors) <= 32 and all(r["status"] == st.ERROR for r in errors.values())


def test_search_continues_without_api_when_offline(tmp_path, monkeypatch, capsys):
    import tgparser.cli as cli

    class OfflineApi:
        stopped = False

        async def start(self):
            raise ConnectionError("Connection to Telegram failed 3 time(s)")

        async def stop(self):
            OfflineApi.stopped = True

    monkeypatch.setattr(web, "make_client", mock_make_client)
    monkeypatch.setattr(cli, "make_api_checker", lambda args, required: None if args.no_api else OfflineApi())
    out = tmp_path / "out"
    assert main(["check", "freename", "--out", str(out), "--tme-delay", "0", "--fragment-delay", "0"]) == 0
    assert read_csv(out / "results.csv")["freename"]["status"] == st.LIKELY_FREE
    assert OfflineApi.stopped
    assert "Продолжаю без Telegram API" in capsys.readouterr().err


def test_short_names_do_not_connect_to_api(tmp_path, monkeypatch):
    import tgparser.cli as cli

    made = []
    monkeypatch.setattr(web, "make_client", mock_make_client)
    monkeypatch.setattr(cli, "make_api_checker", lambda args, required: made.append(1))
    out = tmp_path / "out"
    assert main(["check", "qzxw", "news", "--out", str(out), "--tme-delay", "0", "--fragment-delay", "0"]) == 0
    assert made == []  # только 4-символьные — API не нужен
    assert main(["check", "freename", "--out", str(out), "--tme-delay", "0", "--fragment-delay", "0"]) == 0
    assert made == [1]
