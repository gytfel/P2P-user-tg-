"""Итоговые статусы проверки."""

FREE = "free"  # Telegram API подтвердил: можно занять бесплатно
LIKELY_FREE = "likely_free"  # на t.me нет профиля и не продаётся на Fragment; точно — через --api
FRAGMENT = "fragment"  # можно получить только на Fragment: аукцион, ставка или покупка
TAKEN = "taken"  # занят: есть профиль/канал/бот или куплен на Fragment
UNAVAILABLE = "unavailable"  # 4 символа, но на Fragment сейчас не продаётся
INVALID = "invalid"  # Telegram не даёт его занять: в приложении «Некорректное имя» (резерв, бренд)
ERROR = "error"  # проверка не удалась — при следующем запуске проверится снова

LABELS = {
    FREE: "СВОБОДЕН — можно занять",
    LIKELY_FREE: "НЕ ПРОВЕРЕН",
    FRAGMENT: "ТОЛЬКО КУПИТЬ НА FRAGMENT",
    TAKEN: "занят",
    UNAVAILABLE: "недоступен",
    INVALID: "зарезервирован",
    ERROR: "ошибка",
}

# Находки, которые выводим сразу и сохраняем в отдельные файлы.
FINDINGS = (FREE, LIKELY_FREE, FRAGMENT)

# Пояснение в начале каждого файла находок.
FINDINGS_HEADERS = {
    FREE: "Проверено Telegram API: эти юзернеймы можно занять бесплатно прямо сейчас.",
    LIKELY_FREE: (
        "НЕ проверены через Telegram API (для этого нужен VPN). Среди них много зарезервированных —\n"
        "на них приложение пишет «Некорректное имя». Чтобы отсеять их: включите VPN и выберите\n"
        "в меню «Перепроверить найденные через Telegram API» — подтверждённые перейдут в free.txt."
    ),
    FRAGMENT: (
        "Эти юзернеймы НЕЛЬЗЯ занять в приложении (там будет «Некорректное имя») —\n"
        "их можно только купить на fragment.com за TON. Ссылка — в конце строки."
    ),
}


def fragment_link(username: str) -> str:
    return f"https://fragment.com/username/{username}"
