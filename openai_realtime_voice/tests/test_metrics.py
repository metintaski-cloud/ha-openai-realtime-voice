from app import metrics


def test_record_and_trim(tmp_path, monkeypatch):
    p = tmp_path / "m.jsonl"
    monkeypatch.setattr(metrics, "PATH", str(p))
    metrics.record("ready", connect_to_ready_s=1.23456)
    rows = metrics.load()
    assert rows[0]["event"] == "ready" and rows[0]["connect_to_ready_s"] == 1.235
    monkeypatch.setattr(metrics, "MAX_BYTES", 300)
    for i in range(20):
        metrics.record("x", i=i)
    rows = metrics.load()
    assert 0 < len(rows) < 20 and rows[-1]["i"] == 19


def test_record_never_raises(monkeypatch):
    monkeypatch.setattr(metrics, "PATH", "/nonexistent/dir/m.jsonl")
    metrics.record("ready")


def test_mic_summary():
    out = metrics.mic_summary({"speaking": [(100, 500), (300, 900), (200, 700)], "quiet": []})
    assert out == {"mic_speaking_rms_median": 200, "mic_speaking_peak_max": 900,
                   "mic_speaking_windows": 3}
    assert metrics.mic_summary(None) == {}
