"""Точная проверка через Telegram API (метод account.checkUsername).

Нужен обычный аккаунт Telegram и API_ID / API_HASH с https://my.telegram.org.
Лучше использовать запасной аккаунт: при частых проверках Telegram даёт FloodWait.
"""
from __future__ import annotations

import asyncio
import sys
import time
from getpass import getpass

from . import statuses as st


class TelegramApiChecker:
    def __init__(self, api_id: int, api_hash: str, session: str, interval: float, max_flood_wait: int):
        from telethon import TelegramClient

        self.client = TelegramClient(session, api_id, api_hash)
        # FloodWait обрабатываем сами, чтобы писать в лог и уметь остановиться.
        self.client.flood_sleep_threshold = 0
        self.interval = interval
        self.max_flood_wait = max_flood_wait
        self.enabled = True
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def start(self) -> None:
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
