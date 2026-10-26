"""Пересобирает data/words_en.txt и data/words_ru.txt из частотных словарей wordfreq.

    pip install wordfreq
    python scripts/build_wordlists.py [--en 50000] [--ru 30000]

Слова идут от самых частых к редким: чем выше слово, тем ценнее юзернейм.
Данные wordfreq: https://github.com/rspeer/wordfreq (CC BY-SA 4.0).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from wordfreq import top_n_list

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MIN_LEN, MAX_LEN = 5, 15

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def translit(word: str) -> str | None:
    out = []
    for ch in word:
        if ch not in TRANSLIT:
            return None
        out.append(TRANSLIT[ch])
    return "".join(out)


def write(path: Path, header: str, words: list[str]) -> None:
    seen: set[str] = set()
    unique = [w for w in words if MIN_LEN <= len(w) <= MAX_LEN and not (w in seen or seen.add(w))]
    path.write_text(header + "\n".join(unique) + "\n", encoding="utf-8")
    print(f"{path}: {len(unique)} слов")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--en", type=int, default=50000, help="сколько частых английских слов брать")
    parser.add_argument("--ru", type=int, default=30000, help="сколько частых русских слов брать")
    args = parser.parse_args()

    en = [w for w in top_n_list("en", args.en) if w.isascii() and w.isalpha()]
    write(
        DATA_DIR / "words_en.txt",
        "# Частые английские слова (wordfreq, CC BY-SA 4.0), от частых к редким\n",
        en,
    )

    ru = [t for t in (translit(w) for w in top_n_list("ru", args.ru)) if t]
    write(
        DATA_DIR / "words_ru.txt",
        "# Частые русские слова в транслите (wordfreq, CC BY-SA 4.0), от частых к редким\n",
        ru,
    )


if __name__ == "__main__":
    main()
