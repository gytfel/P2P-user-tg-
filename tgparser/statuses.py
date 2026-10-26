"""Итоговые статусы проверки."""

FREE = "free"  # Telegram API подтвердил: можно занять бесплатно
LIKELY_FREE = "likely_free"  # на t.me нет профиля и не продаётся на Fragment; точно — через --api
FRAGMENT = "fragment"  # можно получить только на Fragment: аукцион, ставка или покупка
TAKEN = "taken"  # занят: есть профиль/канал/бот или куплен на Fragment
UNAVAILABLE = "unavailable"  # 4 символа, но на Fragment сейчас не продаётся
INVALID = "invalid"  # Telegram не даёт его занять: в приложении «Некорректное имя» (резерв, бренд)
ERROR = "error"  # проверка не удалась — при следующем запуске проверится снова

LABELS = {
    FREE: "СВОБОДЕН",
    LIKELY_FREE: "ВЕРОЯТНО СВОБОДЕН",
    FRAGMENT: "FRAGMENT",
    TAKEN: "занят",
    UNAVAILABLE: "недоступен",
    INVALID: "зарезервирован",
    ERROR: "ошибка",
}

# Находки, которые выводим сразу и сохраняем в отдельные файлы.
FINDINGS = (FREE, LIKELY_FREE, FRAGMENT)
