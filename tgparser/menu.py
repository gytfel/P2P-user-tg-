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
    return Path(f"{cli.DEFAULT_SESSION}.session").exists()


def save_env(api_id: str, api_hash: str, path: Path | None = None) -> Path:
    """Записывает ключи в .env, остальные строки файла оставляет как были."""
    path = path or cli.ENV_FILE
    lines = []
    if path.exists():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith(("TG_API_ID=", "TG_API_HASH="))
        ]
    lines += [f"TG_API_ID={api_id}", f"TG_API_HASH={api_hash}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _ask(prompt: str, valid: Callable[[str], object], error: str) -> str | None:
    while True:
        value = input(prompt).strip()
        if not value:
            return None
        if valid(value):
            return value
        print(error)


def setup_api() -> bool:
    print(SETUP_HELP)
    api_id = _ask("api_id: ", str.isdigit, "api_id — это только цифры, попробуйте ещё раз.")
    if not api_id:
        print("Настройка отменена.")
        return False
    api_hash = _ask("api_hash: ", API_HASH_RE.match, "api_hash — 32 символа (цифры и буквы a-f), попробуйте ещё раз.")
    if not api_hash:
        print("Настройка отменена.")
        return False
    path = save_env(api_id, api_hash)
    os.environ["TG_API_ID"], os.environ["TG_API_HASH"] = api_id, api_hash
    print(f"Ключи сохранены в {path}")
    print("\nТеперь вход в Telegram — один раз, дальше парсер входит сам.")
    return login()


def login() -> bool:
    async def go() -> None:
        from .telegram_api import TelegramApiChecker

        api = TelegramApiChecker(
            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"], str(cli.DEFAULT_SESSION), 0, 0
        )
        try:
            await api.start()
        finally:
            await api.stop()

    try:
        asyncio.run(go())
    except ImportError:
        print("Не установлен telethon. Запустите start.bat ещё раз или: py -m pip install telethon")
        return False
    except (KeyboardInterrupt, EOFError):
        print("\nВход отменён.")
        return False
    except Exception as e:
        print(f"Не удалось войти: {e}\nПроверьте api_id и api_hash и попробуйте ещё раз (пункт настройки в меню).")
        return False
    print("Готово: Telegram API настроен.")
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
    if not logged_in():
        return "Telegram API: ключи есть, вход выполнится при первом поиске"
    return "Telegram API: настроен"


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
