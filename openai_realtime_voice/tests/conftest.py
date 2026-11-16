import pytest

from app import ticker


@pytest.fixture(autouse=True)
def _ticker_in_tmp(tmp_path, monkeypatch):
    """Pushes in tests must not create /data (lamp show state would land there and leak into
    other tests, as it did once the news line wrote its file, and again in 2.89.0 when the
    voice unlock started to read and save Leyla's mood)."""
    monkeypatch.setattr(ticker, "PATH", str(tmp_path / "ticker.json"))
    monkeypatch.setenv("LEYLA_MOOD_PATH", str(tmp_path / "mood.json"))
    monkeypatch.setenv("LEYLA_REMINDERS_PATH", str(tmp_path / "reminders.json"))
