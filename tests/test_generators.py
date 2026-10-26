import itertools

import pytest

from tgparser.generators import iter_pattern, iter_shapes, iter_short, iter_words
from tgparser.rules import is_valid


def test_pattern_counts():
    assert sum(1 for _ in iter_pattern("LLLL")) == 26**4
    assert sum(1 for _ in iter_pattern("xDDD")) == 1000
    assert list(itertools.islice(iter_pattern("CVCV"), 3)) == ["baba", "babe", "babi"]


def test_alnum_never_starts_with_digit():
    names = list(iter_pattern("LAAA"))
    assert len(names) == 26 * 36**3
    assert all(n[0].isalpha() for n in names)


def test_shapes():
    names = list(iter_shapes(["aaaa", "abab"]))
    assert "aaaa" in names and "zzzz" in names
    assert "abab" in names and "zyzy" in names
    assert "aaaa" not in names[26:]  # abab — разные буквы
    assert len(names) == 26 + 26 * 25


def test_short_dedupes_and_marks_source():
    items = list(iter_short(["pretty"], ["LLLL"]))
    names = [n for n, _ in items]
    assert len(names) == len(set(names)) == 26**4
    assert dict(items)["aaaa"] == "short:pretty"
    assert dict(items)["qzxw"] == "short:LLLL"


def test_short_shuffle_is_reproducible():
    a = [n for n, _ in itertools.islice(iter_short(["pretty"], shuffle=True, seed=7), 50)]
    b = [n for n, _ in itertools.islice(iter_short(["pretty"], shuffle=True, seed=7), 50)]
    assert a == b
    assert a != [n for n, _ in itertools.islice(iter_short(["pretty"]), 50)]


@pytest.mark.parametrize("pattern", ["1LLL", "_LLL", "DLLL", "LL", "LLLQ"])
def test_bad_patterns_fail_immediately(pattern):
    with pytest.raises(ValueError):
        iter_short(patterns=[pattern])


def test_bad_preset_fails_immediately():
    with pytest.raises(ValueError):
        iter_short(["nope"])


def test_builtin_lists_are_valid_and_unique():
    items = list(iter_words(["crypto", "companies", "en", "ru"], 4, 32))
    names = [n for n, _ in items]
    assert len(names) == len(set(names))
    assert all(is_valid(n) for n in names)
    sources = {s for _, s in items}
    assert sources == {"crypto", "companies", "en", "ru"}
    assert dict(items)["bitcoin"] == "crypto"  # первый список побеждает


def test_words_length_filter(tmp_path):
    custom = tmp_path / "mine.txt"
    custom.write_text("# comment\nabcd\nAbcde\nCoca-Cola\n1abcde\nverylongword\n", encoding="utf-8")
    assert list(iter_words([str(custom)], 5, 10)) == [("abcde", "mine"), ("cocacola", "mine")]
