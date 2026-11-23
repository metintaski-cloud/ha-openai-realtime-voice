"""Cut marks (2.144.0, Metin: "dass ich die Endungen selber einstellen und schneiden kann"):
begin and end of a clip on the stage, set in the tester, stored by the server; the files stay whole."""
import asyncio
import json
import os

from app import memory_web


def test_marks_are_stored_checked_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("LEYLA_SCHNITT", str(tmp_path / "s.json"))
    assert memory_web._schnitt_set("schwarz/freizeitpo", 0.5, 8.46)
    assert memory_web._schnitt_set("nacht/tanz4", 0, 7.5)
    assert memory_web._schnitt_set("nacht/kuss", 1.2, 0), "only a later begin, end stays the real end"
    assert not memory_web._schnitt_set("nacht/tanz5", 3, 3.2), "less than half a second left"
    assert not memory_web._schnitt_set("nacht/tanz5", "x", 2)
    assert memory_web._schnitt_read() == {"schwarz/freizeitpo": [0.5, 8.46], "nacht/tanz4": [0.0, 7.5],
                                          "nacht/kuss": [1.2, 0.0]}
    assert memory_web._schnitt_set("nacht/tanz4", 0, 0)
    assert "nacht/tanz4" not in memory_web._schnitt_read(), "0 and 0 removes the marks"


def test_clips_carry_the_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_web, "CLIPS_DIR", "")
    monkeypatch.setattr(memory_web, "MEDIA_CLIPS", str(tmp_path / "media"))
    os.makedirs(tmp_path / "media" / "nacht")
    (tmp_path / "media" / "nacht" / "tanz4.mp4").write_bytes(b"x")
    for k in ("LEYLA_SCHNITT", "LEYLA_KURVE", "LEYLA_TEMPO"):
        monkeypatch.setenv(k, str(tmp_path / (k + ".json")))
    memory_web._schnitt_set("nacht/tanz4", 0.3, 7.5)
    memory_web._schnitt_set("nacht/weg", 0, 2)
    assert memory_web.list_outfits()["nacht"]["s"] == {"tanz4": [0.3, 7.5]}


def test_the_tester_saves_marks_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("LEYLA_SCHNITT", str(tmp_path / "s.json"))

    async def call(method, path, body=None):
        server = await memory_web.start_http(memory_web.memory.MemoryStore(str(tmp_path / "m.json")),
                                             None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        raw = json.dumps(body).encode() if body is not None else b""
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"{method} {path} HTTP/1.1\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return json.loads(data.split(b"\r\n\r\n", 1)[1])

    assert asyncio.run(call("POST", "/api/schnitt", {"name": "kurz/po2", "start": 0, "end": 6.25})) == {"ok": True}
    assert asyncio.run(call("POST", "/api/schnitt", {"name": "kurz/po3", "start": 5, "end": 5.1})) == {"ok": False}
    assert asyncio.run(call("GET", "/api/schnitt")) == {"kurz/po2": [0.0, 6.25]}


def test_the_stage_and_the_tester_know_the_marks():
    page = memory_web.PAGE
    assert "function endOf(v)" in page and "cutStart(" in page
    assert "endOf(a)-PRE-a.currentTime" in page, "the hand over counts from the end mark"
    assert "/api/schnitt" in memory_web.TEMPO_PAGE and "Schnitt merken" in memory_web.TEMPO_PAGE
