from app import main


def _start(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BACKEND_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("BACKEND_REASONING_EFFORT", value)
    return main.LiveVoiceBridge()._session_start()["session"]["delegation"]["responses"]


def test_unset_keeps_model_default(monkeypatch):
    assert "reasoning" not in _start(monkeypatch, None)
    assert "reasoning" not in _start(monkeypatch, "")
    assert "reasoning" not in _start(monkeypatch, "null")  # what bashio gives for an unset option


def test_effort_is_passed_to_the_backend(monkeypatch):
    assert _start(monkeypatch, "low")["reasoning"] == {"effort": "low"}
    assert _start(monkeypatch, "  Medium ")["reasoning"] == {"effort": "medium"}
