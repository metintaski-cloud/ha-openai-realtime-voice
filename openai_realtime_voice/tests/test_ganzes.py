"""The page /ganzes: one outfit as a whole, its loops in a row and the touch clips in between."""
import asyncio
import re
import shutil
import subprocess
import time

import pytest

from app import ganzes_page, memory, memory_web


def script() -> str:
    return re.search(r"<script>(.*)</script>", ganzes_page.PAGE, re.S).group(1)


def test_the_script_is_sound_javascript(tmp_path):
    assert "\\" not in ganzes_page.PAGE  # a raw string: a backslash would reach the browser as it is
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    path = tmp_path / "ganzes.js"
    path.write_text(script(), encoding="utf-8")
    done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_it_hands_over_like_the_stage_of_the_app():
    js = script()
    app = memory_web.PAGE if hasattr(memory_web, "PAGE") else open(memory_web.__file__, encoding="utf-8").read()
    assert "PRELOAD_S=3" in js and "PRELOAD_S=3" in app      # the next clip loads this long before the end
    assert "LOOP_PRE=0.25" in js and "tight?0.25:0.8" in app  # a loop blends only at the very end
    assert "'.35s'" in js and "opacity .35s" in app           # a touch fades in at once
    for zone in ("gesicht", "brust", "bauch", "po", "povorne", "mix", "hinten"):
        assert "'" + zone + "'" in js or zone in js
    assert "/api/tempo" in js and "/tempo?clip=" in js


async def _get(port: int, path: str) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    raw = (await reader.read()).decode()
    writer.close()
    return raw


async def test_the_page_is_served_and_the_tester_links_to_it(tmp_path):
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        page = await _get(port, "/ganzes?clip=kurz/freizeitpo8")
        tester = await _get(port, "/tempo")
    finally:
        server.close()
    assert page.startswith("HTTP/1.1 200") and "Outfit als Ganzes" in page and 'href="/tempo"' in page
    assert 'href="/ganzes"' in tester


def _clip(path, seconds: int) -> None:
    """A tiny clip a browser without H.264 can play (VP9 and Opus in an MP4 file)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=96x144:rate=24:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:v", "libvpx-vp9", "-b:v", "60k",
                    "-g", "12", "-c:a", "libopus", "-b:a", "24k", "-f", "mp4", str(path)], check=True)


async def test_in_a_browser_loops_run_in_order_and_a_touch_cuts_in_and_hands_back(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name in ("freizeitgluecklich", "freizeitgluecklich2", "freizeitgluecklich3", "freizeitpo8",
                     "freizeithinten", "gluecklich"):
            _clip(folder / (name + ".mp4"), 4)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    seen, errors = [], []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=kurz/freizeitpo8")

            async def watch(seconds: float) -> dict:
                end, state = time.time() + seconds, {}
                while time.time() < end:
                    state = await page.evaluate(
                        "()=>({cur:CUR,muted:document.getElementById(SV?'v1':'v0').muted,"
                        "look:(document.getElementById('look').selectedOptions[0]||{}).textContent||''})")
                    if state["cur"] and (not seen or seen[-1] != state["cur"]):
                        seen.append(state["cur"])
                    await asyncio.sleep(0.1)
                return state
            state = await watch(8.5)
            assert state["look"] == "Kurzes Freizeitkleid"  # from the clip in the address
            assert seen[:3] == ["freizeitgluecklich", "freizeitgluecklich2", "freizeitgluecklich3"]
            # the clip never leaves the view: the stage fills the screen, the settings lie on its left
            # and scroll by themselves, the page itself does not scroll (Metin, 25 Nov 2026, 00:29)
            lay = await page.evaluate("""()=>{const r=id=>document.getElementById(id).getBoundingClientRect();
              const p=document.getElementById('panel');p.scrollTop=p.scrollHeight;window.scrollTo(0,500);
              return {st:r('st'),panel:r('panel'),scrolled:p.scrollTop>0,page:window.scrollY,h:innerHeight,w:innerWidth};}""")
            assert lay["st"]["top"] == 0 and lay["st"]["height"] == lay["h"] and lay["st"]["right"] == lay["w"]
            assert lay["panel"]["left"] == 0 and lay["panel"]["width"] < lay["w"] * 0.6
            assert lay["scrolled"] and lay["page"] == 0
            await page.click("#tog")
            assert not await page.is_visible("#panel")  # the whole clip
            await page.click("#tog")
            assert await page.is_visible("#panel")
            # fine tempo steps of one hundredth, and back to 1
            await page.click("#rp")
            await page.click("#rp")
            await page.click("#rm")
            assert await page.inner_text("#rlab") == "1.01"
            assert abs(await page.evaluate("()=>document.getElementById(SV?'v1':'v0').playbackRate") - 1.01) < 1e-6
            await page.click("#r1")
            assert await page.inner_text("#rlab") == "1.00"
            # the loops at random like the app, or in order: one button
            await page.click("#seq")
            assert "zufällig" in await page.inner_text("#seq") and await page.evaluate("()=>SEQ") is False
            await page.click("#seq")
            assert "der Reihe nach" in await page.inner_text("#seq") and await page.evaluate("()=>SEQ") is True
            await page.click("button[data-n=freizeitpo8]")
            state = await watch(1.0)
            assert state["cur"] == "freizeithinten" and state["muted"] is False  # she turns first, with sound
            await watch(9.0)
            turn = seen.index("freizeithinten")  # then the touch clip, then back to a loop
            assert seen[turn + 1] == "freizeitpo8" and seen[turn + 2].startswith("freizeitgluecklich")
            assert (await page.evaluate("()=>document.getElementById(SV?'v1':'v0').muted")) is True
            await page.evaluate("()=>{const r=document.getElementById('rate');r.value='1.5';r.oninput();}")
            await page.click("#mk")
            await asyncio.sleep(0.4)
            assert memory_web._tempo_read()[-1]["rate"] == 1.5
            assert memory_web._tempo_read()[-1]["name"] == "kurz/" + seen[-1]
            # sound: a touch clip can lose its whole sound for the app, or only a stretch of it
            assert await page.is_disabled("#tonb")  # a loop runs: loops never have sound
            await page.click("button[data-n=freizeitpo8]")
            await page.wait_for_function("()=>CUR==='freizeitpo8'", timeout=9000)
            await page.evaluate("()=>{document.getElementById('sfrom').value='1';document.getElementById('sto').value='2.5';stkShow();}")
            await page.click("#sadd")
            await page.wait_for_function("()=>(STUMM['kurz/freizeitpo8']||[]).length===1")
            assert ganzes_page.ton_read()["stumm"] == {"kurz/freizeitpo8": [[1.0, 2.5]]}
            volumes = await page.evaluate("""async()=>{const v=document.getElementById(SV?'v1':'v0'),out=[];
              for(const t of [0.5,1.2,2.2,2.8]){v.currentTime=t;await new Promise(r=>setTimeout(r,150));out.push([v.volume>0,+v.duration.toFixed(1)]);}return out;}""")
            assert [x[0] for x in volumes] == [True, False, False, True]  # silent only inside the stretch
            assert {x[1] for x in volumes} == {4.0}                       # and the clip keeps its length
            # the picture of the sound: a finger dragged over it selects the stretch
            await page.wait_for_function("()=>(WAVE['kurz/freizeitpo8']||{peaks:[]}).peaks.length>100")
            box = await page.locator("#wave").bounding_box()
            assert box["width"] == 400 and box["y"] + box["height"] == 800  # a strip over the full width at the bottom
            await page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + 20)
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + 20, steps=4)
            await page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 20, steps=4)
            await page.mouse.up()
            picked = await page.evaluate("()=>[Number(document.getElementById('sfrom').value),Number(document.getElementById('sto').value)]")
            assert abs(picked[0] - 1.0) < 0.06 and abs(picked[1] - 2.0) < 0.06, picked
            assert "von " + f"{picked[0]:.2f}" in await page.inner_text("#slab")
            await page.click("#tonb")
            await page.wait_for_function("()=>MUTE['kurz/freizeitpo8']===1")
            assert ganzes_page.ton_read()["aus"] == ["kurz/freizeitpo8"]
            assert await page.evaluate("()=>document.getElementById(SV?'v1':'v0').muted") is True
            await page.click("#tonb")
            await page.wait_for_function("()=>!MUTE['kurz/freizeitpo8']")
            assert ganzes_page.ton_read()["aus"] == []
            await page.click("#slist a")
            await page.wait_for_function("()=>!STUMM['kurz/freizeitpo8']")
            # begin and end: only this clip runs while he sets them, in steps of one hundredth
            await page.click("#ap")
            await page.click("#ap")
            await page.click("#em")
            assert await page.evaluate("()=>SOLO") is True and await page.is_visible("#weiter")
            assert "Anfang 0.02 s, Ende 3.9" in await page.inner_text("#clab")
            assert "noch nicht gemerkt" in await page.inner_text("#clab")
            await asyncio.sleep(4.5)  # longer than the clip: it stays on this clip
            assert await page.evaluate("()=>CUR") == "freizeitpo8"
            assert await page.evaluate("()=>document.getElementById(SV?'v1':'v0').paused") is False
            await page.click("#csave")
            await page.wait_for_function("()=>document.getElementById('clab').textContent.includes('(gemerkt)')")
            assert memory_web._schnitt_read()["kurz/freizeitpo8"][0] == 0.02
            await page.click("#cclr")
            await page.wait_for_function("()=>!SCHNITT['kurz/freizeitpo8']")
            assert memory_web._schnitt_read() == {}
            await page.click("#weiter")
            await page.wait_for_function("()=>CUR.startsWith('freizeitgluecklich')&&!SOLO", timeout=9000)
            seen.append(await page.evaluate("()=>CUR"))
            await page.evaluate("()=>{const r=document.getElementById('rate');r.value='1.5';r.oninput();}")
            await page.click("#mk")
            await asyncio.sleep(0.4)
            # the reset button names the clip that differs and puts everything back after a yes
            await asyncio.sleep(0.8)
            assert "1 Clip ist seitdem anders: kurz/" + seen[-1] in await page.inner_text("#rinfo")
            page.once("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
            await page.click("#rst")
            await page.wait_for_function("()=>document.getElementById('rinfo').textContent.includes('Nichts ist')")
            assert ganzes_page._rates(memory_web._tempo_read()) == {}
            assert await page.is_disabled("#rst")
            await browser.close()
    finally:
        server.close()
    assert errors == []


def test_random_loops_never_repeat_the_clip_that_just_ran():
    js = script()
    assert "const o=v.length>1?v.filter(x=>x!==CUR):v" in js  # as stageLoop of the app does


async def test_the_tester_has_fine_steps_for_every_slider(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name in ("gluecklich", "gluecklich2", "po"):
            _clip(folder / (name + ".mp4"), 4)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 900, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/tempo?clip=kurz/po")
            await page.wait_for_selector("button[data-fine='Tempo+']")
            await page.wait_for_function("()=>{const v=document.querySelectorAll('video')[1];return v&&v.duration>0;}")
            names = await page.evaluate("()=>[...document.querySelectorAll('button[data-fine]')].map(b=>b.dataset.fine)")
            assert names == ["Tempo-", "Tempo+", "Anfang-", "Anfang+", "Ende-", "Ende+", "Stück Anfang-",
                             "Stück Anfang+", "Stück Länge-", "Stück Länge+", "Stück Tempo-", "Stück Tempo+"]
            for _ in range(3):
                await page.click("button[data-fine='Tempo+']")
            await page.click("button[data-fine='Tempo-']")
            rate = await page.evaluate("()=>document.querySelectorAll('video')[1].playbackRate")
            assert abs(rate - 1.02) < 1e-6 and "1.02" in await page.inner_text(".v")
            await page.click("button[data-fine='Anfang+']")
            await page.click("button[data-fine='Ende-']")
            marks = await page.inner_text("div.v")
            assert "Anfang 0.01 s" in marks and "Ende 3.9" in marks
            await page.click("button[data-fine='Stück Tempo+']")
            assert "Tempo 1.01" in await page.inner_text("div.t >> nth=2")
            await browser.close()
    finally:
        server.close()
    assert errors == []


# ---- the reset point: all clips back to how they were ----
@pytest.fixture
def values(tmp_path, monkeypatch):
    for key in ("TEMPO", "KURVE", "SCHNITT"):
        monkeypatch.setenv("LEYLA_" + key, str(tmp_path / (key.lower() + ".json")))
    memory_web._tempo_add("kurz/tanz", 1.6)
    memory_web._tempo_add("kurz/gluecklich4", 1.5)
    memory_web._schnitt_set("schwarz/po", 0.5, 8.0)
    memory_web._kurve_set("nacht/tanz4", [[3.5, 5.0, 1.3]])
    return tmp_path


def test_the_reset_point_is_taken_once_and_counts_what_changed(values):
    first = ganzes_page.stand_info()
    assert first["ok"] and first["tempo"] == 2 and first["schnitt"] == 1 and first["kurve"] == 1
    assert first["geaendert"] == []
    memory_web._tempo_add("kurz/tanz", 1.0)             # back to normal speed
    memory_web._tempo_add("kurz/freizeitpo8", 1.2)      # a new one
    memory_web._schnitt_set("schwarz/po", 0, 0)         # cut removed
    memory_web._kurve_set("nacht/tanz4", [[3.5, 5.0, 1.1]])
    memory_web._tempo_add("kurz/gluecklich4", 1.5)      # stored again with the same value: no change
    again = ganzes_page.stand_info()
    assert again["t"] == first["t"]                     # the point itself does not move
    assert again["geaendert"] == ["kurz/freizeitpo8", "kurz/tanz", "nacht/tanz4", "schwarz/po"]


def test_reset_puts_tempo_curve_and_cut_of_all_clips_back(values):
    ganzes_page.stand_info()
    before = (ganzes_page._rates(memory_web._tempo_read()), memory_web._kurve_read(), memory_web._schnitt_read())
    memory_web._tempo_add("kurz/tanz", 0.8)
    memory_web._tempo_add("kurz/neu", 1.9)
    memory_web._schnitt_set("schwarz/po", 1.0, 6.0)
    memory_web._schnitt_set("kurz/neu", 0.2, 0)
    memory_web._kurve_set("nacht/tanz4", [])
    ganzes_page.ton_set("kurz/brust", True)
    ganzes_page.ton_stumm("kurz/po", [[1, 2]])
    out = ganzes_page.stand_restore()
    assert out["ok"] and out["zurueck"] == ["kurz/brust", "kurz/neu", "kurz/po", "kurz/tanz", "nacht/tanz4",
                                            "schwarz/po"]
    assert ganzes_page.ton_read() == {"aus": [], "stumm": {}}
    assert out["geaendert"] == []
    assert (ganzes_page._rates(memory_web._tempo_read()), memory_web._kurve_read(),
            memory_web._schnitt_read()) == before
    assert memory_web.list_outfits is not None  # the page reads the same files for /clips.json


def test_a_new_reset_point_takes_the_values_of_now(values):
    ganzes_page.stand_info()
    memory_web._tempo_add("kurz/tanz", 1.0)
    assert ganzes_page.stand_info()["geaendert"] == ["kurz/tanz"]
    moved = ganzes_page.stand_save()
    assert moved["geaendert"] == [] and moved["tempo"] == 1
    memory_web._tempo_add("kurz/tanz", 1.6)
    ganzes_page.stand_restore()
    assert ganzes_page._rates(memory_web._tempo_read()) == {"kurz/gluecklich4": 1.5}


def test_a_broken_reset_point_is_not_used(values, monkeypatch):
    path = values / "kaputt.json"
    path.write_text('{"t": "gestern"}')
    monkeypatch.setenv("LEYLA_STAND", str(path))
    assert ganzes_page.stand_read() is None and ganzes_page.stand_restore() == {"ok": False}
    assert ganzes_page._rates(memory_web._tempo_read()) == {"kurz/tanz": 1.6, "kurz/gluecklich4": 1.5}


async def test_the_reset_point_over_http_and_taken_at_the_first_start(values):
    server = await memory_web.start_http(memory.MemoryStore(str(values / "m.json")), None,
                                         host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        assert ganzes_page.stand_read() is not None  # taken when the page started
        memory_web._tempo_add("kurz/tanz", 1.0)
        import json as _json
        info = _json.loads((await _get(port, "/api/stand")).split("\r\n\r\n", 1)[1])
        assert info["geaendert"] == ["kurz/tanz"]

        async def post(body: str) -> dict:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(("POST /api/stand HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                          f"Content-Length: {len(body)}\r\n\r\n{body}").encode())
            await writer.drain()
            raw = (await reader.read()).decode()
            writer.close()
            return _json.loads(raw.split("\r\n\r\n", 1)[1])
        assert (await post('{"aktion": "irgendwas"}')) == {"ok": False}
        assert ganzes_page._rates(memory_web._tempo_read()) == {"kurz/gluecklich4": 1.5}  # nothing happened
        back = await post('{"aktion": "zurueck"}')
        assert back["zurueck"] == ["kurz/tanz"]
        assert ganzes_page._rates(memory_web._tempo_read())["kurz/tanz"] == 1.6
    finally:
        server.close()


# ---- sound: off for a whole clip, or silent for a stretch that keeps its length ----
def test_sound_off_and_silent_stretches_are_kept_per_clip(tmp_path):
    assert ganzes_page.ton_read() == {"aus": [], "stumm": {}}
    assert ganzes_page.ton_set("kurz/freizeitbrust2", True) and ganzes_page.ton_set("schwarz/brust2", True)
    assert ganzes_page.ton_stumm("kurz/po2", [[3, 5], [1, 2.5], [2, 3.2], ["x", 1], [4, 4.01], [-1, 2]])
    assert ganzes_page.ton_read() == {"aus": ["kurz/freizeitbrust2", "schwarz/brust2"],
                                      "stumm": {"kurz/po2": [[1.0, 5.0]]}}  # sorted, joined, nonsense left out
    assert ganzes_page.ton_set("schwarz/brust2", False)
    assert ganzes_page.ton_stumm("kurz/po2", [])
    assert ganzes_page.ton_read() == {"aus": ["kurz/freizeitbrust2"], "stumm": {}}
    for bad in ("", "kurz", "../etc/passwd", "kurz/Po 2", None):
        assert not ganzes_page.ton_set(bad, True) and not ganzes_page.ton_stumm(bad, [[1, 2]])
    assert not ganzes_page.ton_stumm("kurz/po2", "1-2")


def test_the_app_is_told_which_clips_are_silent(tmp_path, monkeypatch):
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    for name in ("brust", "po", "gluecklich"):
        (folder / (name + ".mp4")).write_bytes(b"x")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    ganzes_page.ton_set("kurz/brust", True)
    ganzes_page.ton_set("kurz/gibtesnicht", True)
    ganzes_page.ton_stumm("kurz/po", [[2, 4]])
    look = memory_web.list_outfits()["kurz"]
    assert look["m"] == ["brust"] and look["ms"] == {"po": [[2.0, 4.0]]}
    src = open(memory_web.__file__, encoding="utf-8").read()
    assert "&&!MUTE[name.includes('/')?name:OUTFIT+'/'+name]" in src  # the stage leaves the sound of these off
    assert "b.volume=st.some(x=>t>=x[0]&&t<x[1])?0:.7" in src        # and is silent inside a stretch


# ---- the picture of the sound ----
async def test_the_loudness_of_a_clip_over_time(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    loud, half, mute = tmp_path / "laut.mp4", tmp_path / "halb.mp4", tmp_path / "stumm.mp4"
    try:
        _clip(loud, 4)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(loud), "-c:v", "copy", "-af",
                        "volume=enable='between(t,2,4)':volume=0", "-c:a", "libopus", "-f", "mp4", str(half)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(loud), "-c:v", "copy", "-an", "-f", "mp4", str(mute)],
                       check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    w = await ganzes_page.wave(str(loud))
    assert w["ok"] and 3.9 < w["dauer"] < 4.2 and 300 <= len(w["peaks"]) <= ganzes_page.WAVE_BUCKETS
    assert max(w["peaks"]) == 1.0 and min(w["peaks"][5:-5]) > 0.5      # a steady tone
    h = (await ganzes_page.wave(str(half)))["peaks"]
    assert min(h[20:len(h) // 2 - 20]) > 0.5 and max(h[len(h) // 2 + 20:-5]) < 0.05  # second half silent
    assert await ganzes_page.wave(str(mute)) == {"ok": True, "dauer": 0.0, "peaks": []}  # no sound track
    assert await ganzes_page.wave(str(tmp_path / "fehlt.mp4")) == {"ok": False}
    assert await ganzes_page.wave(str(loud)) is w                        # decoded once


async def test_the_picture_of_the_sound_over_http_only_for_real_clips(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        _clip(folder / "po.mp4", 2)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        import json as _json
        good = _json.loads((await _get(port, "/api/wave?clip=kurz/po")).split("\r\n\r\n", 1)[1])
        assert good["ok"] and len(good["peaks"]) > 100
        for bad in ("kurz/gibtesnicht", "../../etc/passwd", ""):
            assert _json.loads((await _get(port, "/api/wave?clip=" + bad)).split("\r\n\r\n", 1)[1]) == {"ok": False}
    finally:
        server.close()
