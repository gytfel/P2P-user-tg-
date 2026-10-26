"""Правила юзернеймов Telegram.

- символы: a-z, 0-9 и «_» (регистр не важен);
- первый символ — только буква (не цифра и не «_»);
- нельзя заканчивать на «_» и ставить «__» подряд;
- 5–32 символа можно занять бесплатно в самом Telegram;
- 4 символа существуют только как коллекционные юзернеймы на Fragment.
"""
from __future__ import annotations

import re

MIN_LEN_COLLECTIBLE = 4
MIN_LEN_REGULAR = 5
MAX_LEN = 32

_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{%d,%d}$" % (MIN_LEN_COLLECTIBLE - 1, MAX_LEN - 1))
_LINK_PREFIX_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|fragment\.com/username)/", re.I)
_NOT_ALLOWED_RE = re.compile(r"[^a-z0-9_]")


def normalize(raw: str) -> str:
    """Приводит «@Name», «t.me/Name», «Coca-Cola» и т.п. к виду name / cocacola."""
    name = _LINK_PREFIX_RE.sub("", raw.strip()).lstrip("@").lower()
    return _NOT_ALLOWED_RE.sub("", name)


def is_valid(name: str) -> bool:
    return bool(_USERNAME_RE.match(name)) and not name.endswith("_") and "__" not in name


def is_collectible_only(name: str) -> bool:
    """4-символьные юзернеймы нельзя занять бесплатно — только купить на Fragment."""
    return len(name) < MIN_LEN_REGULAR
