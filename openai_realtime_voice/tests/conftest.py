import pytest

from app import ticker


@pytest.fixture(autouse=True)
def _ticker_in_tmp(tmp_path, monkeypatch):
    """Pushes in tests must not create /data (lamp show state would land there and leak into
    other tests, as it did once the news line wrote its file)."""
    monkeypatch.setattr(ticker, "PATH", str(tmp_path / "ticker.json"))
