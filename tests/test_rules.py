import pytest

from tgparser.rules import is_collectible_only, is_valid, normalize


@pytest.mark.parametrize("name", ["abcd", "a1b2", "a_bc", "bitcoin", "x" * 32, "durov"])
def test_valid(name):
    assert is_valid(name)


@pytest.mark.parametrize(
    "name",
    ["abc", "1abc", "_abc", "abc_", "ab__cd", "x" * 33, "ab-cd", "абвгд", ""],
)
def test_invalid(name):
    assert not is_valid(name)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("@Durov", "durov"),
        ("https://t.me/Durov", "durov"),
        ("t.me/bitcoin", "bitcoin"),
        ("https://fragment.com/username/news", "news"),
        ("Coca-Cola", "cocacola"),
        ("McDonald's", "mcdonalds"),
        ("crypto.com", "cryptocom"),
        ("  Ozon Bank ", "ozonbank"),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_collectible_only():
    assert is_collectible_only("abcd")
    assert not is_collectible_only("abcde")
