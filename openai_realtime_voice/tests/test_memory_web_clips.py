"""Stage clips come from the Home Assistant media folder once it holds a look (2.107.0)."""
import os

from app import memory_web


def test_clips_dir_prefers_media_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_web, "CLIPS_DIR", "")
    monkeypatch.setattr(memory_web, "MEDIA_CLIPS", str(tmp_path / "media"))
    assert memory_web.clips_dir() == memory_web.BUILTIN_CLIPS
    os.makedirs(tmp_path / "media" / "schwarz")
    assert memory_web.clips_dir() == memory_web.BUILTIN_CLIPS  # empty look does not count yet
    (tmp_path / "media" / "schwarz" / "gluecklich.mp4").write_bytes(b"x")
    assert memory_web.clips_dir() == str(tmp_path / "media")
    outs = memory_web.list_outfits()
    assert outs["schwarz"]["v"] > 0
    del outs["schwarz"]["v"]
    assert outs == {"schwarz": {"clips": ["gluecklich"], "body": False}}
    monkeypatch.setattr(memory_web, "CLIPS_DIR", "/elsewhere")
    assert memory_web.clips_dir() == "/elsewhere"
