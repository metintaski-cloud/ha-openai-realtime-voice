import pytest

from app import planer, spott, ticker


@pytest.fixture(autouse=True)
def _ticker_in_tmp(tmp_path, monkeypatch):
    """Pushes in tests must not create /data (lamp show state would land there and leak into
    other tests, as it did once the news line wrote its file, and again in 2.89.0 when the
    voice unlock started to read and save Leyla's mood)."""
    monkeypatch.setattr(ticker, "PATH", str(tmp_path / "ticker.json"))
    monkeypatch.setattr(planer, "PATH", str(tmp_path / "planer.json"))  # plans never in /data
    monkeypatch.setattr(spott, "PATH", str(tmp_path / "spott.json"))  # who made fun of her: never in /data
    monkeypatch.setenv("LEYLA_MOOD_PATH", str(tmp_path / "mood.json"))
    monkeypatch.setenv("LEYLA_STAND", str(tmp_path / "tempo_stand.json"))  # reset point of the clip values
    for key in ("TEMPO", "KURVE", "SCHNITT", "TON", "VORLAUF", "BLENDE"):  # a reset writes all of them: never into /data
        monkeypatch.setenv("LEYLA_" + key, str(tmp_path / ("clip_" + key.lower() + ".json")))
    monkeypatch.setenv("LEYLA_MOBIL", "0")  # no background encoder in tests (2.141.0)
    monkeypatch.setenv("LEYLA_MOBIL_DIR", str(tmp_path / "mobil"))
    monkeypatch.setenv("LEYLA_REMINDERS_PATH", str(tmp_path / "reminders.json"))
    monkeypatch.setenv("LEYLA_SAID_PATH", str(tmp_path / "said.json"))
    monkeypatch.setenv("LEYLA_DIARY_PATH", str(tmp_path / "diary.json"))
    monkeypatch.setenv("LEYLA_IDEAS_PATH", str(tmp_path / "ideas.json"))
