"""Меню для запуска без командной строки (start.bat) и мастер настройки Telegram API."""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Callable

from . import cli

API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
YES = {"д", "да", "y", "yes", "l"}  # «l» — это «д» на английской раскладке

SETUP_HELP = """
Настройка Telegram API — нужна, чтобы отсеивать зарезервированные имена
(те, на которые приложение пишет «Некорректное имя»).

  1. Откройте https://my.telegram.org и войдите по номеру телефона
     (код придёт в Telegram).
  2. Нажмите «API development tools».
  3. Если попросит создать приложение — впишите любые App title и Short name
     (например myparser) и нажмите «Create application».
  4. Скопируйте сюда api_id (число) и api_hash (32 символа).

Лучше использовать запасной аккаунт. Пустой ввод + Enter — отмена.
"""


def api_configured() -> bool:
    return os.environ.get("TG_API_ID", "").strip().isdigit() and bool(os.environ.get("TG_API_HASH", "").strip())


def logged_in() -> bool:
    """Вход подтверждён: после успешного входа аккаунт записывается в .env (TG_USER)."""
    return bool(os.environ.get("TG_USER", "").strip())


save_env = cli.save_env


def _valid_proxy(value: str) -> bool:
    from .telegram_api import proxy_kwargs

    try:
        return bool(proxy_kwargs(value))
    except ValueError:
        return False


def _ask(prompt: str, valid: Callable[[str], object], error: str) -> str | None:
    while True:
        value = input(prompt).strip()
        if not value:
            return None
        if valid(value):
            return value
        print(error)


def setup_api() -> bool:
    if api_configured():
        print(f"\nКлючи API уже сохранены (api_id {os.environ['TG_API_ID']}).")
        if input("Ввести api_id и api_hash заново? [д/н]: ").strip().lower() in YES and not _ask_keys():
            return False
    elif not _ask_keys():
        return False
    print("\nВход в Telegram — один раз, дальше парсер входит сам.")
    return login()


def _ask_keys() -> bool:
    print(SETUP_HELP)
    api_id = _ask("api_id: ", str.isdigit, "api_id — это только цифры, попробуйте ещё раз.")
    if not api_id:
        print("Настройка отменена.")
        return False
    api_hash = _ask("api_hash: ", API_HASH_RE.match, "api_hash — 32 символа (цифры и буквы a-f), попробуйте ещё раз.")
    if not api_hash:
        print("Настройка отменена.")
        return False
    print(f"Ключи сохранены в {save_env({'TG_API_ID': api_id, 'TG_API_HASH': api_hash})}")
    return True


def _ask_proxy() -> bool:
    """Спрашивает прокси после неудачного подключения; True — пробовать подключиться снова."""
    print("\nВставьте прокси вида socks5://адрес:порт или socks5://логин:пароль@адрес:порт.")
    current = os.environ.get("TG_PROXY", "").strip()
    if current:
        print(f"Сейчас указан: {current} (введите - чтобы убрать его)")
    while True:
        value = input("Прокси (или включите VPN и просто нажмите Enter): ").strip()
        if not value:
            break
        if value == "-":
            save_env({"TG_PROXY": ""})
            print("Прокси убран.")
            return True
        if _valid_proxy(value):
            print(f"Прокси сохранён в {save_env({'TG_PROXY': value})}")
            return True
        print("Не похоже на прокси. Пример: socks5://user:pass@1.2.3.4:1080 — попробуйте ещё раз.")
    return input("Попробовать подключиться ещё раз (например, после включения VPN)? [д/н]: ").strip().lower() in YES


def login() -> bool:
    async def go() -> str:
        from .telegram_api import TelegramApiChecker

        api = TelegramApiChecker(
            int(os.environ["TG_API_ID"]),
            os.environ["TG_API_HASH"],
            str(cli.DEFAULT_SESSION),
            0,
            0,
            proxy=os.environ.get("TG_PROXY"),
        )
        try:
            await api.start()
            return api.account
        finally:
            await api.stop()

    from .telegram_api import CONNECT_HELP

    while True:
        try:
            account = asyncio.run(go())
        except ImportError as e:
            print(f"Не хватает библиотеки ({e.name}). Закройте окно и запустите start.bat ещё раз — он доустановит.")
            return False
        except (KeyboardInterrupt, EOFError):
            print("\nВход отменён.")
            return False
        except ValueError as e:  # неправильный TG_PROXY в .env
            print(f"Прокси: {e}")
            if not _ask_proxy():
                return False
            continue
        except (OSError, asyncio.TimeoutError):
            print(f"\n{CONNECT_HELP}")
            if not _ask_proxy():
                return False
            continue
        except Exception as e:
            print(f"Не удалось войти: {e}\nПроверьте api_id и api_hash (пункт «Настроить Telegram API» в меню).")
            return False
        save_env({"TG_USER": account})
        print(f"Готово: Telegram API настроен, аккаунт {account}.")
        return True


def _run(argv: list[str]) -> None:
    try:
        cli.main(argv)
    except SystemExit as e:  # make_api_checker и argparse сообщают об ошибках через SystemExit
        if isinstance(e.code, str):
            print(e.code)


def _check_custom() -> None:
    items = input("Юзернеймы через пробел (или путь к .txt файлу): ").split()
    if items:
        _run(["check", *items])


def _confirm() -> None:
    if not api_configured():
        print("Для перепроверки нужен Telegram API — сначала настроим его.")
        if not setup_api():
            return
    _run(["confirm"])


def _open_results() -> None:
    cli.DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
    if hasattr(os, "startfile"):
        os.startfile(cli.DEFAULT_OUT)
    else:
        print(cli.DEFAULT_OUT)


MENU: list[tuple[str, Callable[[], object]]] = [
    ("Крипта и компании", lambda: _run(["words", "--lists", "crypto,companies"])),
    ("Все реальные слова: крипта, компании, английские, русские (долго, ~6 ч)", lambda: _run(["words"])),
    ("4-буквенные слова из крипты и компаний (doge, defi, usdt…)", lambda: _run(["words", "--min-len", "4", "--max-len", "4"])),
    ("Красивые 4-символьные: aaaa, abab, abba… (~1 ч)", lambda: _run(["short", "--preset", "pretty"])),
    ("Все 4-символьные: красивые → читаемые → все буквы (долго, ~3 суток)", lambda: _run(["short"])),
    ("Проверить свои юзернеймы", _check_custom),
    ("Перепроверить найденные через Telegram API (убрать «Некорректное имя»)", _confirm),
    ("Настроить Telegram API (api_id и api_hash)", setup_api),
    ("Открыть папку с результатами", _open_results),
]


def _status() -> str:
    if not api_configured():
        return "Telegram API: не настроен — имена с «Некорректное имя» не отсеиваются (пункт 8)"
    via = " (через прокси)" if os.environ.get("TG_PROXY", "").strip() else ""
    if not logged_in():
        return f"Telegram API: ключи есть, но вход ещё не выполнен — включите VPN и выберите пункт 8{via}"
    return f"Telegram API: настроен, аккаунт {os.environ['TG_USER']}{via}"


def run_menu() -> int:
    try:
        print("\n=== Поиск свободных юзернеймов Telegram ===")
        if not api_configured():
            print("\nTelegram API пока не настроен. Без него в находки могут попасть")
            print("зарезервированные имена (приложение пишет на них «Некорректное имя»).")
            if input("Настроить сейчас? [д/н]: ").strip().lower() in YES:
                setup_api()
        while True:
            print(f"\n{_status()}\n")
            for number, (title, _) in enumerate(MENU, 1):
                print(f"  {number}. {title}")
            print("  0. Выход")
            choice = input("\nВведите номер и нажмите Enter: ").strip()
            if choice in ("0", "q", "й", ""):
                if choice:
                    return 0
                continue
            if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
                print("Нет такого пункта.")
                continue
            title, action = MENU[int(choice) - 1]
            print(f"\n=== {title} ===\nОстановить: Ctrl+C (проверенное сохранится, потом продолжится с того же места)\n")
            try:
                action()
            except KeyboardInterrupt:
                print("\nОстановлено.")
            input("\nНажмите Enter, чтобы вернуться в меню...")
    except (KeyboardInterrupt, EOFError):
        return 0
