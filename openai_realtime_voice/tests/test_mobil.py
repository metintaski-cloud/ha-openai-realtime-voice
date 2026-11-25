"""Light copies of the heavy 4K clips for the phone on the go (2.141.0, Metin: on mobile data
the 29 Mbit clip stalled, an 11 Mbit copy in full 4K played smoothly)."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import time

import pytest

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

    async def encode(src, dst, *rate):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        if "_klein" not in dst:
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

    async def encode(src, dst, *rate):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        if "_klein" not in dst:
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


def test_copies_from_an_older_cap_are_made_again(tmp_path):
    """2.141.1: the cap went from 10M to 8M, existing copies must be redone once."""
    m, paths = _setup(tmp_path)
    made = []

    async def probe(path):
        return 29_000_000 if "schwer" in path else 5_000_000

    async def encode(src, dst, *rate):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        if "_klein" not in dst:
            made.append(src)
        return True

    m._probe, m._encode = probe, encode
    asyncio.run(m.scan())
    m.index["schwarz/schwer"]["cap"] = "10M"
    asyncio.run(m.scan())
    asyncio.run(m.scan())
    assert made.count(paths["schwarz/schwer"]) == 2
    assert m.index["schwarz/schwer"]["cap"] == mobil.CAP


def test_peak_not_average_decides(tmp_path):
    """2.141.4: nacht/tanz14 averages 10 Mbit (under the old limit of 12) but peaks at 16 and stalled."""
    lines = "\n".join(f"{i/24:.3f},{(80_000 if 48 <= i < 72 else 40_000)}" for i in range(240))
    assert mobil.peak_of(lines) == 24 * 80_000 * 8
    assert mobil.peak_of("") == 0 and mobil.peak_of("N/A,12\nbad") == 0


def test_old_index_entries_are_measured_again_and_keep_their_copy(tmp_path):
    m, paths = _setup(tmp_path)
    made = []

    async def probe(path):
        return 16_000_000

    async def encode(src, dst, *rate):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        if "_klein" not in dst:
            made.append(src)
        return True

    m._probe, m._encode = probe, encode
    asyncio.run(m.scan())
    made.clear()
    for v in m.index.values():
        v.pop("peak")
        v["rate"] = 10_000_000
    asyncio.run(m.scan())
    assert all(v["peak"] == 16_000_000 for v in m.index.values())
    assert made == [], "copies already made at the current cap are kept"


def test_a_wide_clip_gets_a_phone_sized_copy_even_when_light(tmp_path):
    """2.143.0: a calm 4K clip (peak under 9 Mbit) still made the phone warm decoding 2352 px."""
    m, paths = _setup(tmp_path)
    made = []

    async def probe(path):
        return 5_000_000

    async def width(path):
        return 2352 if "schwer" in path else 1176

    async def encode(src, dst, *rate):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"light")
        if "_klein" not in dst:
            made.append(src)
        return True

    m._probe, m._width, m._encode = probe, width, encode
    asyncio.run(m.scan())
    assert made == [paths["schwarz/schwer"]]


def _small_setup(tmp_path, peaks):
    media = tmp_path / "media" / "kurz"
    media.mkdir(parents=True)
    paths = {}
    for n in peaks:
        (media / f"{n}.mp4").write_bytes(b"x" * 100)
        paths[f"kurz/{n}"] = str(media / f"{n}.mp4")
    m = mobil.Mobil(lambda: paths, str(tmp_path / "mobil"))
    made = []

    async def probe(path):
        return peaks[os.path.basename(path)[:-4]]

    async def encode(src, dst, rate=mobil.MAX_RATE, buf=mobil.BUF):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"small" if rate == mobil.SMALL_RATE else b"light")
        made.append((os.path.basename(src)[:-4], rate, buf))
        return True

    async def width(path):
        return 1080

    m._probe, m._encode, m._width = probe, encode, width
    return m, paths, made


def test_a_small_copy_for_a_line_that_cannot_carry_the_light_one(tmp_path):
    """2.172.0 (Metin on mobile data, 25 Nov 2026: the picture waited for data 20 times in two minutes): every
    clip above 3 Mbit/s gets a second copy at 2 Mbit/s. One per scan and the loops first, so a clip he has just
    swapped in never waits for its light copy behind the small ones."""
    m, paths, made = _small_setup(tmp_path, {"tanz": 29_000_000, "gluecklich4": 29_000_000,
                                             "po": 5_000_000, "ruhig": 2_000_000})
    assert asyncio.run(m.scan()) is True
    light = [x for x in made if x[1] == mobil.MAX_RATE]
    assert sorted(x[0] for x in light) == ["gluecklich4", "tanz"], "both light copies in the first scan"
    assert [x for x in made if x[1] != mobil.MAX_RATE] == [("gluecklich4", "2M", "3M")], "one small copy, a loop"
    assert asyncio.run(m.scan()) is True and asyncio.run(m.scan()) is False
    assert [x[0] for x in made if x[1] == "2M"] == ["gluecklich4", "po", "tanz"], "po too, ruhig is light enough"
    assert asyncio.run(m.scan()) is False and len(made) == 5, "nothing is made twice"
    st = m.status()
    assert st["small"] == 3 and st["small_ready"] == 3 and st["small_rate"] == "2M"
    # what the server hands out
    o = paths["kurz/tanz"]
    assert open(m.copy_for("kurz/tanz", o, small=True), "rb").read() == b"small"
    assert open(m.copy_for("kurz/tanz", o), "rb").read() == b"light"
    assert open(m.copy_for("kurz/po", paths["kurz/po"], small=True), "rb").read() == b"small"
    assert not m.copy_for("kurz/po", paths["kurz/po"]), "po has no light copy, the original is light enough"
    assert not m.copy_for("kurz/ruhig", paths["kurz/ruhig"], small=True)


def test_small_copy_follows_a_replaced_clip_and_a_failure_does_not_spin(tmp_path):
    m, paths, made = _small_setup(tmp_path, {"gluecklich": 29_000_000})
    asyncio.run(m.scan())
    o = paths["kurz/gluecklich"]
    later = time.time() + 100
    os.utime(o, (later, later))
    assert not m.copy_for("kurz/gluecklich", o, small=True), "an old small copy is never served"
    asyncio.run(m.scan())
    assert [x[1] for x in made] == ["7M", "2M", "7M", "2M"]
    os.remove(o)
    paths.clear()
    asyncio.run(m.scan())
    assert not os.path.exists(m.small_path("kurz/gluecklich")) and not os.path.exists(m.copy_path("kurz/gluecklich"))
    # a clip whose small copy cannot be made is tried once per start, the scan reports no more work
    m2, paths2, made2 = _small_setup(tmp_path / "b", {"gluecklich": 5_000_000})

    async def broken(src, dst, rate=mobil.MAX_RATE, buf=mobil.BUF):
        made2.append(rate)
        return False

    m2._encode = broken
    assert asyncio.run(m2.scan()) is False and asyncio.run(m2.scan()) is False
    assert made2 == ["2M"] and m2.status()["failed"] == ["kurz/gluecklich (klein)"]


def test_the_server_sends_the_small_copy_only_for_m2(tmp_path, monkeypatch):
    media = tmp_path / "media"
    (media / "kurz").mkdir(parents=True)
    (media / "kurz" / "tanz.mp4").write_bytes(b"ORIGINAL")
    (media / "kurz" / "kuss.mp4").write_bytes(b"ORIGINAL")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(media))
    for folder, body in (("mobil", b"LIGHT"), ("mobil_klein", b"SMALL")):
        (tmp_path / folder / "kurz").mkdir(parents=True)
        (tmp_path / folder / "kurz" / "tanz.mp4").write_bytes(body)
    (tmp_path / "mobil" / "kurz" / "kuss.mp4").write_bytes(b"LIGHT")
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

    assert asyncio.run(get("/clips/kurz/tanz.mp4?v=1")) == b"ORIGINAL"
    assert asyncio.run(get("/clips/kurz/tanz.mp4?v=1&m=1")) == b"LIGHT"
    assert asyncio.run(get("/clips/kurz/tanz.mp4?v=1&m=2")) == b"SMALL"
    assert asyncio.run(get("/clips/kurz/kuss.mp4?v=1&m=2")) == b"LIGHT", "no small copy yet: the light one"
    monkeypatch.setattr(memory_web, "MOBIL", None)


def test_the_page_takes_the_small_copy_only_while_her_picture_keeps_waiting(tmp_path):
    """Three waits within a minute switch to m=2, a line measured as fast keeps it off, 9 Mbit/s brings the light
    copy back after three minutes at the earliest, and the choice is kept for half an hour."""
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    app = open(memory_web.__file__, encoding="utf-8").read()
    block = re.search(r"let SLOW=false,SLOWAT=0.*?\nfunction tierNow\(\)\{[^\n]*\n", app, re.S).group(0)
    assert "+tierNow();" in app and "NETSTALL++;slowStall();stallSeen();" in app and "slowJudge(kbps);" in app
    assert "light=src.includes('m=2')?2:src.includes('m=1')?1:0" in app
    path = tmp_path / "slow.js"
    path.write_text("""
let NOW=1e12,PHONEON=true,NETAT=0;const STORE={};const out={};
const localStorage={getItem:k=>k in STORE?STORE[k]:null,setItem:(k,v)=>{STORE[k]=String(v);},removeItem:k=>{delete STORE[k];}};
Date.now=()=>NOW;function lightNow(){return PHONEON;}
""" + block + """
out.start=tierNow();
slowStall();NOW+=5000;slowStall();out.two=tierNow();
NOW+=70000;slowStall();out.old_ones_do_not_count=tierNow();
NOW+=5000;slowStall();NOW+=5000;slowStall();out.three=tierNow();out.kept=!!STORE.lslow;
NOW+=60000;slowJudge(12000);out.fast_but_too_early=tierNow();
NOW+=130000;slowJudge(4400);out.still_slow=tierNow();
slowJudge(9000);out.fast=tierNow();out.forgotten=!STORE.lslow;
NETAT=NOW;slowStall();slowStall();slowStall();slowStall();out.fast_line_waits_do_not_switch=tierNow();
NOW+=400000;slowStall();NOW+=1000;slowStall();NOW+=1000;slowStall();out.measure_too_old=tierNow();
PHONEON=false;out.pc=tierNow();
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "start": "&m=1", "two": "&m=1", "old_ones_do_not_count": "&m=1", "three": "&m=2", "kept": True,
        "fast_but_too_early": "&m=2", "still_slow": "&m=2", "fast": "&m=1", "forgotten": True,
        "fast_line_waits_do_not_switch": "&m=1", "measure_too_old": "&m=2", "pc": ""}
    # the choice survives a restart for half an hour
    path.write_text("""
let NOW=1e12;const STORE={lslow:String(NOW-29*60000)};const out={};
const localStorage={getItem:k=>k in STORE?STORE[k]:null,setItem:(k,v)=>{STORE[k]=String(v);},removeItem:k=>{delete STORE[k];}};
Date.now=()=>NOW;function lightNow(){return true;}var NETAT=0;
const boot=()=>{""" + block + """return {tierNow,slowJudge};};
let a=boot();out.after_29_min=a.tierNow();a.slowJudge(20000);out.back_at_home_at_once=a.tierNow();
STORE.lslow=String(NOW-31*60000);out.after_31_min=boot().tierNow();
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"after_29_min": "&m=2", "back_at_home_at_once": "&m=1", "after_31_min": "&m=1"}
