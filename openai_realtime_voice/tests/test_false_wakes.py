"""Only false wake recordings are kept, every other microphone recording is deleted."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import main  # noqa: E402


def bridge(tmp_path, enable_recording=False):
    b = object.__new__(main.LiveVoiceBridge)
    b.enable_recording = enable_recording
    b.false_wake_dir = str(tmp_path / "kept")
    return b


def rec(tmp_path, name="input_192_168_2_241_20261113_124500.wav", size=100000):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return str(p)


def test_false_wake_is_kept(tmp_path):
    b = bridge(tmp_path)
    p = rec(tmp_path)
    b._finish_recording(p, "no_speech", {})
    assert not os.path.exists(p)
    assert os.listdir(b.false_wake_dir) == ["falsewake_192_168_2_241_20261113_124500.wav"]


def test_real_conversation_is_deleted(tmp_path):
    b = bridge(tmp_path)
    p = rec(tmp_path)
    b._finish_recording(p, "end_conversation", {})
    assert not os.path.exists(p) and not os.path.exists(b.false_wake_dir)


def test_announcement_without_answer_is_deleted(tmp_path):
    b = bridge(tmp_path)
    p = rec(tmp_path)
    b._finish_recording(p, "no_speech", {"followup": True})
    assert not os.path.exists(p) and not os.path.exists(b.false_wake_dir)


def test_debug_mode_keeps_everything(tmp_path):
    b = bridge(tmp_path, enable_recording=True)
    p = rec(tmp_path)
    b._finish_recording(p, "end_conversation", {})
    assert os.path.exists(p)


def test_oldest_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "FALSE_WAKE_MAX_FILES", 2)
    b = bridge(tmp_path)
    for i in range(4):
        b._finish_recording(rec(tmp_path, f"input_x_2026111{i}_000000.wav"), "no_speech", {})
    assert len(os.listdir(b.false_wake_dir)) == 2
