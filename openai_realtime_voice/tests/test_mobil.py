"""Light copies of the heavy 4K clips for the phone on the go (2.141.0, Metin: on mobile data
the 29 Mbit clip stalled, an 11 Mbit copy in full 4K played smoothly)."""
import asyncio
import json
import os
import time

from app import memory_web, mobil


def _setup(tmp_path):
    media = tmp_path / "media" / "schwarz"
    media.mkdir(parents=True)
    for n in ("schwer", "leicht"):
        (media / f"{n}.mp4").write_bytes(b"x" * 100)
    paths = {f"schwarz/{n}": str(media / f"{n}.mp4") for n in ("schwer", "leicht")}
    return mobil.Mobil(lambda: paths, str(tmp_path / "mobil")), paths


def test_only_heavy_clips_get_a_copy_and_the_original_stays(tmp_path):
    m, paths = _setup(tmp_path)
    made = []

    async def probe(path):
        return 29_000_000 if "schwer" in path else 5_000_000

    async def encode(src, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        made.append(src)
        return True

    m._probe, m._encode = probe, encode
    asyncio.run(m.scan())
    asyncio.run(m.scan())
    assert made == [paths["schwarz/schwer"]], "one copy, only of the heavy clip, made once"
    assert open(paths["schwarz/schwer"], "rb").read() == b"x" * 100, "original untouched"
    assert m.copy_for("schwarz/schwer", paths["schwarz/schwer"])
    assert not m.copy_for("schwarz/leicht", paths["schwarz/leicht"])
    st = m.status()
    assert st["heavy"] == 1 and st["ready"] == 1


def test_a_replaced_clip_gets_a_new_copy(tmp_path):
    m, paths = _setup(tmp_path)
    count = []

    async def probe(path):
        return 29_000_000

    async def encode(src, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        count.append(src)
        return True

    m._probe, m._encode = probe, encode
    asyncio.run(m.scan())
    later = time.time() + 5
    os.utime(paths["schwarz/schwer"], (later, later))
    assert not m.copy_for("schwarz/schwer", paths["schwarz/schwer"]), "old copy is never served"
    asyncio.run(m.scan())
    assert count.count(paths["schwarz/schwer"]) == 2


def test_the_server_sends_the_copy_only_when_asked(tmp_path, monkeypatch):
    media = tmp_path / "media"
    (media / "schwarz").mkdir(parents=True)
    (media / "schwarz" / "tanz.mp4").write_bytes(b"ORIGINAL")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(media))
    light = tmp_path / "mobil" / "schwarz"
    light.mkdir(parents=True)
    (light / "tanz.mp4").write_bytes(b"LIGHT")
    monkeypatch.setattr(memory_web, "MOBIL", None)
    monkeypatch.setenv("LEYLA_MOBIL_DIR", str(tmp_path / "mobil"))

    async def get(url):
        server = await memory_web.start_http(memory_web.memory.MemoryStore(str(tmp_path / "m.json")),
                                             None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"GET {url} HTTP/1.1\r\n\r\n".encode())
        await w.drain()
        data = await r.read()
        w.close()
        server.close()
        return data.split(b"\r\n\r\n", 1)[1]

    assert asyncio.run(get("/clips/schwarz/tanz.mp4?v=1")) == b"ORIGINAL"
    assert asyncio.run(get("/clips/schwarz/tanz.mp4?v=1&m=1")) == b"LIGHT"
