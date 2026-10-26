"""Точная проверка через Telegram API (метод account.checkUsername).

Нужен обычный аккаунт Telegram и API_ID / API_HASH с https://my.telegram.org.
Лучше использовать запасной аккаунт: при частых проверках Telegram даёт FloodWait.
"""
from __future__ import annotations

import asyncio
import sys
import time
from getpass import getpass
from urllib.parse import unquote, urlsplit

from . import statuses as st

PROXY_SCHEMES = ("socks5", "socks4", "http")
CONNECT_TIMEOUT = 60

CONNECT_HELP = """Не удалось подключиться к серверам Telegram.
Скорее всего, провайдер мешает прямому подключению: приложение Telegram обходит это само,
а парсеру нужен VPN или прокси.
  - включите VPN на компьютере (приложение для всего компьютера, не расширение браузера)
    и попробуйте снова;
  - или укажите SOCKS5/HTTP-прокси: пункт «Настроить Telegram API» в меню
    (или строка TG_PROXY=socks5://логин:пароль@адрес:порт в файле .env)."""


def proxy_kwargs(url: str | None) -> dict:
    """Прокси для Telethon из строки socks5://логин:пароль@адрес:порт, socks4://… или http://…"""
    if not url or not url.strip():
        return {}
    parts = urlsplit(url.strip())
    try:
        port = parts.port
    except ValueError:
        port = None
    if parts.scheme not in PROXY_SCHEMES or not parts.hostname or not port:
        raise ValueError(
            f"не понимаю прокси {url!r}: нужен вид socks5://адрес:порт или socks5://логин:пароль@адрес:порт "
            "(также socks4:// и http://)"
        )
    return {
        "proxy": {
            "proxy_type": parts.scheme,
            "addr": parts.hostname,
            "port": port,
            "username": unquote(parts.username) if parts.username else None,
            "password": unquote(parts.password) if parts.password else None,
            "rdns": True,
        }
    }


class TelegramApiChecker:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session: str,
        interval: float,
        max_flood_wait: int,
        proxy: str | None = None,
    ):
        from telethon import TelegramClient

        self.client = TelegramClient(session, api_id, api_hash, connection_retries=3, **proxy_kwargs(proxy))
        # FloodWait обрабатываем сами, чтобы писать в лог и уметь остановиться.
        self.client.flood_sleep_threshold = 0
        self.interval = interval
        self.max_flood_wait = max_flood_wait
        self.enabled = True
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def start(self) -> None:
        # Общий таймаут: при «замедлении» Telegram соединение открывается, но данные не идут,
        # и без него подключение висело бы бесконечно.
        await asyncio.wait_for(self.client.connect(), CONNECT_TIMEOUT)
        # При первом запуске спросит телефон и код, дальше берёт сессию из файла.
        await self.client.start(
            phone=lambda: input("Номер телефона (например +79991234567): ").strip(),
            code_callback=lambda: input("Код подтверждения из Telegram: ").strip(),
            password=lambda: getpass("Облачный пароль (двухэтапная аутентификация, ввод скрыт): "),
        )
        me = await self.client.get_me()
        print(f"Telegram API: вошли как @{me.username or me.id}", file=sys.stderr)

    async def stop(self) -> None:
        await self.client.disconnect()

    async def check(self, username: str) -> tuple[str, str] | None:
        """(статус, пояснение) или None, если API сейчас не может ответить."""
        from telethon import errors, functions

        async with self._lock:
            for _ in range(3):
                if not self.enabled:
                    return None
                pause = self._last_call + self.interval - time.monotonic()
                if pause > 0:
                    await asyncio.sleep(pause)
                self._last_call = time.monotonic()
                try:
                    free = await self.client(functions.account.CheckUsernameRequest(username=username))
                except errors.FloodWaitError as e:
                    if e.seconds > self.max_flood_wait:
                        self.enabled = False
                        print(
                            f"\nTelegram API: FloodWait {e.seconds} с — больше лимита {self.max_flood_wait} с, "
                            "дальше проверяю только через t.me/fragment",
                            file=sys.stderr,
                        )
                        return None
                    print(f"\nTelegram API: FloodWait, жду {e.seconds} с", file=sys.stderr)
                    await asyncio.sleep(e.seconds + 1)
                    continue
                except errors.UsernamePurchaseAvailableError:
                    return st.FRAGMENT, "api: можно купить на Fragment"
                except errors.UsernameOccupiedError:
                    return st.TAKEN, "api: занят"
                except errors.UsernameInvalidError:
                    return st.INVALID, "api: зарезервирован или запрещён"
                except errors.RPCError as e:
                    print(f"\nTelegram API: @{username}: {e.message}", file=sys.stderr)
                    return None
                return (st.FREE, "api: свободен") if free else (st.TAKEN, "api: занят")
            return None
