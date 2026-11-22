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
    assert outs["schwarz"].pop("t")["gluecklich"] > 0, "the date of each clip (2.133.8)"
    assert outs == {"schwarz": {"clips": ["gluecklich"], "body": False}}
    monkeypatch.setattr(memory_web, "CLIPS_DIR", "/elsewhere")
    assert memory_web.clips_dir() == "/elsewhere"


def test_clips_carry_his_tempo(tmp_path, monkeypatch):
    """The speed from the tempo tester rides along in clips.json, the files stay untouched
    (2.136.0, Metin: 'Geht da Qualitaet verloren?' - so no re-encoding)."""
    monkeypatch.setattr(memory_web, "CLIPS_DIR", "")
    monkeypatch.setattr(memory_web, "MEDIA_CLIPS", str(tmp_path / "media"))
    os.makedirs(tmp_path / "media" / "nacht")
    for name in ("tanz4.mp4", "tanz5.mp4", "kuss.mp4"):
        (tmp_path / "media" / "nacht" / name).write_bytes(b"x")
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    memory_web._tempo_add("nacht/tanz4", 0.8)
    memory_web._tempo_add("nacht/kuss", 1.0)      # unchanged, no need to carry it
    memory_web._tempo_add("nacht/weggeworfen", 1.3)  # clip no longer there
    memory_web._tempo_add("kurz/tanz", 1.2)       # other look, not in this folder
    assert memory_web.list_outfits()["nacht"]["r"] == {"tanz4": 0.8}


def test_tempo_keeps_a_long_run(tmp_path, monkeypatch):
    """Metin went through all 300 clips in one go; 60 entries were not enough (2.135.7)."""
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    for i in range(300):
        memory_web._tempo_add(f"nacht/tanz{i}", 1.2)
    assert len(memory_web._tempo_read()) == 300
