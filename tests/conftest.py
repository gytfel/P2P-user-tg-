import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_telegram_keys(monkeypatch):
    """Тесты не должны подхватывать настоящий .env и логиниться в Telegram."""
    import tgparser.cli

    monkeypatch.setattr(tgparser.cli, "load_env", lambda: None)
    for key in ("TG_API_ID", "TG_API_HASH", "TG_PROXY"):
        # setenv + delenv: после теста переменная вернётся к исходному состоянию,
        # даже если код (мастер настройки) запишет её напрямую в os.environ
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
