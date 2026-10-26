"""Источники кандидатов: списки реальных слов и 4-символьные комбинации."""
from __future__ import annotations

import itertools
import random
import string
from pathlib import Path
from typing import Iterable, Iterator

from .rules import MIN_LEN_COLLECTIBLE, is_valid, normalize

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

BUILTIN_LISTS = {
    "crypto": "crypto.txt",
    "companies": "companies.txt",
    "en": "words_en.txt",
    "ru": "words_ru.txt",
}

VOWELS = "aeiouy"
CONSONANTS = "bcdfghjklmnpqrstvwxz"

# Классы символов в шаблонах: L — буква, V — гласная, C — согласная,
# D — цифра, A — буква или цифра. Строчные буквы, цифры и «_» — сами себя.
PATTERN_CLASSES = {
    "L": string.ascii_lowercase,
    "V": VOWELS,
    "C": CONSONANTS,
    "D": string.digits,
    "A": string.ascii_lowercase + string.digits,
}

# Формы «красивых» юзернеймов: одинаковые буквы — одинаковые символы.
PRETTY_SHAPES = ("aaaa", "abab", "aabb", "abba", "aaab", "abbb", "aaba", "abaa")

SHORT_PRESETS = {
    "pretty": [],  # формы из PRETTY_SHAPES, ~4.6 тыс.
    "pronounceable": ["CVCV", "VCVC", "CVVC", "CVCC", "CCVC"],
    "letters": ["LLLL"],  # все буквенные, 456 976
    "alnum": ["LAAA"],  # буква + буквы/цифры, ~1.2 млн
}


def resolve_list(name: str) -> tuple[str, Path]:
    """Встроенный список по имени (crypto, companies, en, ru) или путь к своему файлу."""
    if name in BUILTIN_LISTS:
        return name, DATA_DIR / BUILTIN_LISTS[name]
    path = Path(name)
    return path.stem, path


def read_wordlist(path: Path) -> Iterator[str]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            # «@name<TAB>source<TAB>detail» из файлов находок — берём только имя
            line = line.split("\t", 1)[0].split("#", 1)[0].strip()
            if line:
                yield normalize(line)


def iter_words(lists: Iterable[str], min_len: int, max_len: int) -> Iterator[tuple[str, str]]:
    """Слова из списков без повторов; при дубле побеждает первый список."""
    seen: set[str] = set()
    for item in lists:
        source, path = resolve_list(item)
        for word in read_wordlist(path):
            if word in seen or not min_len <= len(word) <= max_len or not is_valid(word):
                continue
            seen.add(word)
            yield word, source


def expand_pattern(pattern: str) -> list[str]:
    positions = []
    for ch in pattern:
        if ch in PATTERN_CLASSES:
            positions.append(PATTERN_CLASSES[ch])
        elif ch in string.ascii_lowercase + string.digits + "_":
            positions.append(ch)
        else:
            raise ValueError(f"неизвестный символ в шаблоне {pattern!r}: {ch!r}")
    return positions


def iter_pattern(pattern: str) -> Iterator[str]:
    for combo in itertools.product(*expand_pattern(pattern)):
        name = "".join(combo)
        if is_valid(name):
            yield name


def iter_shapes(shapes: Iterable[str] = PRETTY_SHAPES, alphabet: str = string.ascii_lowercase) -> Iterator[str]:
    for shape in shapes:
        symbols = list(dict.fromkeys(shape))
        for combo in itertools.permutations(alphabet, len(symbols)):
            mapping = dict(zip(symbols, combo))
            yield "".join(mapping[c] for c in shape)


def iter_short(
    presets: Iterable[str] = (),
    patterns: Iterable[str] = (),
    shuffle: bool = False,
    seed: int | None = None,
) -> Iterator[tuple[str, str]]:
    """Короткие юзернеймы по пресетам и шаблонам, без повторов.

    Ошибки в пресетах и шаблонах выбрасываются сразу, при вызове.
    """
    sources: list[tuple[str, Iterable[str]]] = []
    for preset in presets:
        if preset not in SHORT_PRESETS:
            raise ValueError(f"неизвестный пресет {preset!r}, есть: {', '.join(SHORT_PRESETS)}")
        if preset == "pretty":
            sources.append(("short:pretty", iter_shapes()))
        sources.extend((f"short:{p}", iter_pattern(p)) for p in SHORT_PRESETS[preset])
    for pattern in patterns:
        if len(pattern) < MIN_LEN_COLLECTIBLE:
            raise ValueError(f"шаблон {pattern!r} короче {MIN_LEN_COLLECTIBLE} символов")
        if not set(expand_pattern(pattern)[0]) & set(string.ascii_lowercase):
            raise ValueError(f"шаблон {pattern!r}: юзернейм должен начинаться с буквы")
        sources.append((f"short:{pattern}", iter_pattern(pattern)))
    return _merge_short(sources, shuffle, seed)


def _merge_short(
    sources: list[tuple[str, Iterable[str]]], shuffle: bool, seed: int | None
) -> Iterator[tuple[str, str]]:
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for source, names in sources:
        for name in names:
            if name in seen or not is_valid(name):
                continue
            seen.add(name)
            if shuffle:
                items.append((name, source))
            else:
                yield name, source
    if shuffle:
        random.Random(seed).shuffle(items)
        yield from items
