import os

import pytest

import tgparser.cli as cli
import tgparser.menu as menu


def feed(monkeypatch, answers):
    answers = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)
    return seen


def test_save_env_keeps_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# мой комментарий\nTG_API_ID=1\nOTHER=x\n", encoding="utf-8")
    menu.save_env({"TG_API_ID": "123", "TG_API_HASH": "a" * 32}, env)
    assert env.read_text(encoding="utf-8") == f"# мой комментарий\nOTHER=x\nTG_API_ID=123\nTG_API_HASH={'a' * 32}\n"
    assert os.environ["TG_API_ID"] == "123"


def test_setup_validates_and_saves(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(menu, "login", lambda: True)
    feed(monkeypatch, ["abc", "123", "short", "0123456789abcdef0123456789ABCDEF"])
    assert menu.setup_api()
    assert "только цифры" in capsys.readouterr().out
    assert os.environ["TG_API_ID"] == "123"
    assert "TG_API_HASH=0123456789abcdef0123456789ABCDEF" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert menu.api_configured()


def test_setup_can_be_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    feed(monkeypatch, [""])
    assert not menu.setup_api()
    assert not (tmp_path / ".env").exists()


def test_menu_runs_selected_search(monkeypatch, calls):
    feed(monkeypatch, ["н", "1", "", "5", "", "0"])
    assert menu.run_menu() == 0
    assert calls == [["words", "--lists", "crypto,companies"], ["short"]]


def test_menu_custom_names(monkeypatch, calls):
    feed(monkeypatch, ["н", "6", "@bayern kriptoobmen", "", "0"])
    menu.run_menu()
    assert calls == [["check", "@bayern", "kriptoobmen"]]


def test_menu_confirm_asks_for_keys_first(tmp_path, monkeypatch, calls):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    feed(monkeypatch, ["н", "7", "", "", "0"])  # отказались вводить api_id
    menu.run_menu()
    assert calls == []


def test_menu_offers_setup_on_start(monkeypatch, calls):
    started = []
    monkeypatch.setattr(menu, "setup_api", lambda: started.append(1) or True)
    feed(monkeypatch, ["д", "0"])
    menu.run_menu()
    assert started == [1]


def test_menu_ignores_unknown_choice(monkeypatch, calls, capsys):
    feed(monkeypatch, ["н", "42", "abc", "0"])
    assert menu.run_menu() == 0
    assert capsys.readouterr().out.count("Нет такого пункта") == 2


def test_main_without_args_opens_menu(monkeypatch):
    monkeypatch.setattr(menu, "run_menu", lambda: 7)
    assert cli.main([]) == 7


def test_setup_command(monkeypatch):
    monkeypatch.setattr(menu, "setup_api", lambda: True)
    assert cli.main(["setup"]) == 0


def test_setup_reuses_saved_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    menu.save_env({"TG_API_ID": "123", "TG_API_HASH": "a" * 32})
    logins = []
    monkeypatch.setattr(menu, "login", lambda: logins.append(1) or True)
    feed(monkeypatch, ["н"])  # не вводить ключи заново
    assert menu.setup_api()
    assert logins == [1]


class FlakyTelegram:
    """Первый вход падает по таймауту, следующий — успешный."""

    instances = []

    def __init__(self, *args, proxy=None):
        self.proxy = proxy
        self.account = "@tester"
        FlakyTelegram.instances.append(self)

    async def start(self):
        if len(FlakyTelegram.instances) == 1:
            raise ConnectionError("Connection to Telegram failed 3 time(s)")

    async def stop(self):
        pass


@pytest.fixture
def flaky(tmp_path, monkeypatch):
    import tgparser.telegram_api

    FlakyTelegram.instances = []
    monkeypatch.setattr(tgparser.telegram_api, "TelegramApiChecker", FlakyTelegram)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    menu.save_env({"TG_API_ID": "123", "TG_API_HASH": "a" * 32})
    return tmp_path / ".env"


def test_login_asks_for_proxy_after_timeout(flaky, monkeypatch, capsys):
    feed(monkeypatch, ["не прокси", "socks5://user:pass@1.2.3.4:1080"])
    assert menu.login()
    out = capsys.readouterr().out
    assert "VPN" in out and "Не похоже на прокси" in out
    assert [t.proxy for t in FlakyTelegram.instances] == [None, "socks5://user:pass@1.2.3.4:1080"]
    assert "TG_PROXY=socks5://user:pass@1.2.3.4:1080" in flaky.read_text(encoding="utf-8")
    assert "TG_USER=@tester" in flaky.read_text(encoding="utf-8")
    assert menu._status() == "Telegram API: настроен, аккаунт @tester (через прокси)"


def test_login_retry_after_vpn(flaky, monkeypatch):
    feed(monkeypatch, ["", "д"])  # прокси не нужен — включили VPN, пробуем ещё раз
    assert menu.login()
    assert len(FlakyTelegram.instances) == 2
    assert "TG_PROXY" not in flaky.read_text(encoding="utf-8")


def test_login_gives_up(flaky, monkeypatch):
    feed(monkeypatch, ["", "н"])
    assert not menu.login()


def test_login_can_remove_bad_proxy(flaky, monkeypatch):
    menu.save_env({"TG_PROXY": "socks5://9.9.9.9:1"})
    feed(monkeypatch, ["-"])
    assert menu.login()
    assert [t.proxy for t in FlakyTelegram.instances] == ["socks5://9.9.9.9:1", ""]
    assert "TG_PROXY=\n" in flaky.read_text(encoding="utf-8")
    assert "(через прокси)" not in menu._status()


def test_status_before_login(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")
    assert "не настроен" in menu._status()
    menu.save_env({"TG_API_ID": "123", "TG_API_HASH": "a" * 32})
    assert "вход ещё не выполнен" in menu._status()
