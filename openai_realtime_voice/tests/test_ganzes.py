"""The page /ganzes: one outfit as a whole, its loops in a row and the touch clips in between."""
import asyncio
import json
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
                     "freizeithinten", "freizeitbrust", "gluecklich"):
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
            # pause, one picture on and back, and dragging through the clip: it stays on this clip
            await page.click("#pp")
            held = await page.evaluate("()=>[PAUSED,SOLO,document.getElementById(SV?'v1':'v0').paused,CUR]")
            assert held[:3] == [True, True, True]
            t0 = await page.evaluate("()=>document.getElementById(SV?'v1':'v0').currentTime")
            await page.click("#ff")
            await page.click("#ff")
            await page.click("#fb")
            t1 = await page.evaluate("()=>document.getElementById(SV?'v1':'v0').currentTime")
            assert abs((t1 - t0) - 1 / 24) < 0.005
            await page.evaluate("()=>{const p=document.getElementById('pos');p.value='2.5';p.oninput();p.onchange();}")
            await asyncio.sleep(0.4)
            now = await page.evaluate("()=>[document.getElementById(SV?'v1':'v0').currentTime,document.getElementById(SV?'v1':'v0').paused,CUR]")
            assert abs(now[0] - 2.5) < 0.01 and now[1] is True and now[2] == held[3]  # paused where he dragged it
            assert "2.50 / 4.0" in await page.inner_text("#ptime")
            await page.click("#pp")
            await asyncio.sleep(0.5)
            assert await page.evaluate("()=>document.getElementById(SV?'v1':'v0').paused") is False
            await page.click("#weiter")
            await page.wait_for_function("()=>!SOLO&&!PAUSED&&CUR.startsWith('freizeitgluecklich')", timeout=9000)
            # which loops take part: a tap takes one out or back in, the round goes on with the others
            await page.click("button[data-loop='3']")
            assert await page.evaluate("()=>Object.keys(OFF)") == ["freizeitgluecklich3"]
            await page.click("#seq")  # at random
            part = set()
            for _ in range(3):
                await page.click("#nxt")
                await asyncio.sleep(0.9)
                part.add(await page.evaluate("()=>CUR"))
            assert part == {"freizeitgluecklich", "freizeitgluecklich2"}  # never the third, never twice in a row
            await page.click("#seq")
            await page.click("button[data-loop='1']")
            await page.click("button[data-loop='2']")  # the last one cannot be taken out
            assert await page.evaluate("()=>Object.keys(OFF).sort()") == ["freizeitgluecklich", "freizeitgluecklich3"]
            await page.wait_for_function("()=>CUR==='freizeitgluecklich2'", timeout=6000)
            assert (await page.inner_text("button[data-loop='2']")).startswith("▶")
            await page.click("button[data-loop='1']")
            await page.click("button[data-loop='3']")
            assert await page.evaluate("()=>Object.keys(OFF)") == []
            # fine tempo steps of one hundredth, and back to 1
            await page.click("#rp")
            await page.click("#rp")
            await page.click("#rm")
            assert await page.inner_text("#rlab") == "1.01"
            assert abs(await page.evaluate("()=>document.getElementById(SV?'v1':'v0').playbackRate") - 1.01) < 1e-6
            await page.click("#r1")
            assert await page.inner_text("#rlab") == "1.00"
            # 2.189.0 (Metin, 27 Nov 2026, 15:10: "Kannst du die Schleifen von 1 bis 10 machen, jetzt ist es 1 bis 3. Und das gleiche mit
            # Gesicht, Brust, Bauch, Po"; his choice when asked: ten places, the ones without a clip grey): every row has ten places
            rows = await page.evaluate("""()=>{const row=b=>[...b.querySelectorAll('button')].map(x=>[x.textContent.replace('▶ ',''),!!x.dataset.n,x.disabled,x.classList.contains('leer')]);
              return {loops:row(document.getElementById('loops')),touch:[...document.querySelectorAll('#touch .bar')].map(r=>[r.querySelector('.z').textContent,row(r)])};}""")
            assert [x[0] for x in rows["loops"]] == [str(i) for i in range(1, 11)]
            assert [x[1:] for x in rows["loops"]] == [[True, False, False]] * 3 + [[False, True, True]] * 7   # three loops, seven free places
            assert [z for z, _ in rows["touch"]] == ["Gesicht", "Brust", "Bauch", "Po"]                     # all four, also the empty ones
            assert [sum(1 for x in r if x[1]) for _, r in rows["touch"]] == [0, 1, 0, 1]
            assert all(len(r) == 10 and [x[0] for x in r] == [str(i) for i in range(1, 11)] for _, r in rows["touch"])
            assert all(x[2] and x[3] for _, r in rows["touch"] for x in r if not x[1])                      # a free place does nothing
            # the loops at random like the app, or in order: one button
            await page.click("#seq")
            assert "zufällig" in await page.inner_text("#seq") and await page.evaluate("()=>SEQ") is False
            await page.click("#seq")
            assert "der Reihe nach" in await page.inner_text("#seq") and await page.evaluate("()=>SEQ") is True
            await page.click("button[data-n=freizeitpo8]")
            state = await watch(1.0)
            assert state["cur"] == "freizeithinten" and state["muted"] is False  # she turns first, with sound
            await watch(9.0)
            # 2.188.0 (Metin, 27 Nov 2026, 14:22: "dass der Clip immer Schleife läuft, bis ich erneut auf diese Clip-Button klicke"):
            # then the touch clip, and it stays: after more than its 4 s it still runs, alone and marked
            turn = seen.index("freizeithinten")
            order = ["freizeitgluecklich", "freizeitgluecklich2", "freizeitgluecklich3"]
            assert seen[turn + 1:] == ["freizeitpo8"], seen
            held = await page.evaluate("()=>[CUR,HOLD,SOLO,vis().paused,document.querySelector('button[data-n=freizeitpo8]').classList.contains('run')]")
            assert held == ["freizeitpo8", "freizeitpo8", True, False, True], held
            t_a = await page.evaluate("()=>vis().currentTime")
            await asyncio.sleep(1.0)
            assert await page.evaluate("()=>vis().currentTime") != t_a   # it really plays
            await page.click("button[data-n=freizeitbrust]")           # another one takes over and stays too
            await page.wait_for_function("()=>CUR==='freizeitbrust'&&SOLO&&HOLD==='freizeitbrust'", timeout=9000)
            last = await page.evaluate("()=>LAST")                      # the loop the page counts as seen last
            await page.click("button[data-n=freizeitbrust]")           # the same button again: on with the loop after the last one
            await page.wait_for_function("()=>!SOLO&&HOLD===''&&CUR.startsWith('freizeitgluecklich')", timeout=9000)
            await asyncio.sleep(0.3)
            assert last in order and await page.evaluate("()=>CUR") == order[(order.index(last) + 1) % 3], (last, seen)
            assert (await page.evaluate("()=>document.getElementById(SV?'v1':'v0').muted")) is True
            tempo_first = await page.evaluate("()=>CUR")  # the loop that gets the tempo here
            await page.evaluate("()=>{const r=document.getElementById('rate');r.value='1.5';r.oninput();}")
            await page.click("#mk")
            await asyncio.sleep(0.4)
            assert memory_web._tempo_read()[-1]["rate"] == 1.5
            assert memory_web._tempo_read()[-1]["name"] == "kurz/" + tempo_first
            # sound: a touch clip can lose its whole sound for the app, or only a stretch of it
            assert await page.is_disabled("#tonb")  # a loop runs: loops never have sound
            await page.click("button[data-n=freizeitpo8]")
            await page.wait_for_function("()=>CUR==='freizeitpo8'", timeout=9000)
            # 2.185.0: the piece is taken from the picture on the stage, one step after the other (Metin: sound "genauso", cut and
            # loudness "als eine Einheit")
            await page.evaluate("()=>{halt();vis().currentTime=1;}")
            await asyncio.sleep(0.3)
            assert await page.is_disabled("#tb") and await page.is_disabled("#sadd")
            await page.click("#ta")
            await page.evaluate("()=>{vis().currentTime=2.5;}")
            await asyncio.sleep(0.3)
            await page.click("#tb")
            assert "Stück von 1.00 bis 2.50 s: Ton gelöscht (Stille)" in await page.inner_text("#slab")
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
            bar = await page.locator("#trans").bounding_box()
            assert bar["y"] + bar["height"] == box["y"] and bar["width"] == 400  # pause and drag sit right above it
            await page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + 20)
            await page.mouse.down()
            await page.mouse.move(box["x"] + box["width"] * 0.4, box["y"] + 20, steps=4)
            await page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 20, steps=4)
            await page.mouse.up()
            picked = await page.evaluate("()=>[TV.a,TV.b]")
            assert abs(picked[0] - 1.0) < 0.06 and abs(picked[1] - 2.0) < 0.06, picked
            assert "von " + f"{picked[0]:.2f}" in await page.inner_text("#slab")
            # quieter and louder: heard at once here, kept for the app with "Lautstärke merken"
            # a part of the clip quieter: stored as a stretch with its loudness, beside the silent one
            await page.click("#vm")
            await page.click("#vm")
            assert await page.inner_text("#vlab") == "80 %"
            await page.click("#sadd")
            await page.wait_for_function("()=>(STUMM['kurz/freizeitpo8']||[]).length>=1&&!TV")
            kept = ganzes_page.ton_read()["stumm"]["kurz/freizeitpo8"]      # a new piece takes the place of the ones it lies over
            assert len(kept) == 1 and kept[0][2] == 0.8 and abs(kept[0][0] - picked[0]) < 0.011 and abs(kept[0][1] - picked[1]) < 0.011
            await page.evaluate("()=>{vis().currentTime=(STUMM['kurz/freizeitpo8'][0][0]+STUMM['kurz/freizeitpo8'][0][1])/2;}")
            await asyncio.sleep(0.2)
            assert abs(await page.evaluate("()=>document.getElementById(SV?'v1':'v0').volume") - 0.56) < 0.001
            assert "Ton auf 80 %" in await page.inner_text("#slist")
            # the whole clip quieter: that is the loudness of the clip, heard at once, kept with the same button
            await page.click("#tall")
            await page.click("#vm")
            assert await page.inner_text("#vlab") == "90 %" and "Der ganze Clip: Ton auf 90 %" in await page.inner_text("#slab")
            await asyncio.sleep(0.15)
            assert abs(await page.evaluate("()=>document.getElementById(SV?'v1':'v0').volume") - 0.63) < 0.001
            await page.click("#sadd")
            await page.wait_for_function("()=>VOL['kurz/freizeitpo8']===0.9&&!TV")
            assert ganzes_page.ton_read()["laut"] == {"kurz/freizeitpo8": 0.9}
            assert "der ganze Clip auf 90 %" in await page.inner_text("#slist")
            await page.click("#tall")                       # it starts from what is stored
            assert await page.inner_text("#vlab") == "90 %"
            await page.click("#v1b")
            await page.click("#sadd")
            await page.wait_for_function("()=>!VOL['kurz/freizeitpo8']&&!TV")
            assert ganzes_page.ton_read()["laut"] == {}
            await page.click("#tonb")
            await page.wait_for_function("()=>MUTE['kurz/freizeitpo8']===1")
            assert ganzes_page.ton_read()["aus"] == ["kurz/freizeitpo8"]
            assert await page.evaluate("()=>document.getElementById(SV?'v1':'v0').muted") is True
            await page.click("#tonb")
            await page.wait_for_function("()=>!MUTE['kurz/freizeitpo8']")
            assert ganzes_page.ton_read()["aus"] == []
            await page.click("#slist a")
            await page.wait_for_function("()=>!STUMM['kurz/freizeitpo8']")
            await page.click("#pp")                          # he had stopped the clip to take the pieces: on again
            assert await page.evaluate("()=>PAUSED") is False
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
            # (the tempo was stored twice in this test, for the loop that ran then and the one that runs now;
            #  which loops those are depends on where the touch cut in, so both counts are right)
            changed = sorted({"kurz/" + tempo_first, "kurz/" + seen[-1]})
            want = ("1 Clip ist" if len(changed) == 1 else "2 Clips sind") + " seitdem anders: " + ", ".join(changed)
            assert want in await page.inner_text("#rinfo")
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
    assert "else n=roundPick(RND,v,LAST);" in js              # in rounds, as stageLoop of the app does (2.168.2)
    assert "sel=all.filter(n=>!OFF[n])" in js                 # and only among the loops that take part


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
            assert "Tempo 1.01" in await page.inner_text("#slab")
            # 2.185.0 (Metin, with a photo of this page: "Hast du dafür keine Bezeichnung gegeben? Ich sehe hier gar nichts"): three parts
            # with a heading and a sentence each, and a name over every slider
            heads = await page.evaluate("()=>[...document.querySelectorAll('.sec h2')].map(h=>h.textContent)")
            assert heads == ["1 · Tempo des ganzen Clips", "2 · Anfang und Ende", "3 · Ein Stück mit eigenem Tempo"]
            assert await page.evaluate("()=>document.querySelectorAll('.sec .cap').length") >= 7
            await browser.close()
    finally:
        server.close()
    assert errors == []


async def test_in_a_browser_the_wheel_rolls_through_the_clips_of_a_field_and_a_piece_gets_its_own_tempo(tmp_path, monkeypatch):
    """2.185.0. Metin, 27 Nov 2026, 04:52 to 05:05: under "1 Kleid" the dress, "rechts daneben tanzen, rechts daneben zeigen. Und in diese
    Kategorie sollen sich die Dateien schon befinden. Und die wähle ich mit Maus-Scroll"; every loop the dress has ("Schleife bis Max");
    "wo ich im ganzen Clip ein Stück schneide und dies schneller oder langsamer machen kann. Aber so, dass es schön übersichtlich ist";
    "während ich diese Anfang und Ende setze, soll natürlich der Clip ... zeigen, wo er steht ... dass das Clip quasi mir ein Indikator ist"."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    try:
        for look, names in (("nacht", ("gluecklich10", "gluecklich4", "gluecklichextra", "tanz27", "tanz14", "tanzhf", "zeigenlang3", "po7")),
                            ("kurz", ("gluecklich4", "freizeitgluecklich", "freizeittanz2", "tanz5"))):
            (tmp_path / "clips" / look).mkdir(parents=True)
            for name in names:
                _clip(tmp_path / "clips" / look / (name + ".mp4"), 3)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("LEYLA_KURVE", str(tmp_path / "kurve.json"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    state = """()=>({loops:[...document.querySelectorAll('#loops button[data-n]')].map(b=>[b.textContent.replace('▶ ',''),b.dataset.n]),
      fields:[...document.querySelectorAll('.wh')].map(e=>[e.querySelector('b').textContent,e.querySelector('span').textContent,e.querySelector('em').textContent,e.classList.contains('run')]),
      lists:{kleid:WH.kleid.list,tanz:WH.tanz.list,zeigen:WH.zeigen.list},cur:CUR,solo:SOLO,muted:vis().muted,name:document.getElementById('name').textContent,
      cards:[...document.querySelectorAll('#panel .card h2')].map(h=>h.textContent)})"""

    async def roll(page, field, way):
        await page.hover(field)
        await page.mouse.wheel(0, 100 * way)
        await asyncio.sleep(0.25)

    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1200, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=nacht/gluecklich4")
            await page.wait_for_function("()=>CUR==='gluecklich4'", timeout=8000)
            s = await page.evaluate(state)
            assert s["cards"] == ["1Kleid", "2Schleifen", "3Berührung", "4Einstellen: der Clip, der läuft", "5Reset für alle Clips"]
            # loop 1 is gluecklich4 as on the page Naht, the extra clip is a loop too and comes last
            assert s["loops"] == [["1", "gluecklich4"], ["2", "gluecklich10"], ["Extra", "gluecklichextra"]]
            # three fields side by side, each holds its clips: the dress (loops first), the dances, the show clips
            assert s["lists"] == {"kleid": ["gluecklich4", "gluecklich10", "gluecklichextra", "po7"], "tanz": ["tanz14", "tanz27", "tanzhf"], "zeigen": ["zeigenlang3"]}
            assert s["fields"][0] == ["Nachtkleid", "glücklich 4", "1 von 4", True] and s["fields"][1][0] == "Tanzen" and s["fields"][2][0] == "Zeigen"
            box = await page.evaluate("()=>[...document.querySelectorAll('.wh')].map(e=>{const r=e.getBoundingClientRect();return [Math.round(r.left),Math.round(r.top)];})")
            assert box[0][1] == box[1][1] == box[2][1] and box[0][0] < box[1][0] < box[2][0]
            # the wheel over a field: the next clip of that field runs at once, alone, and stays
            await roll(page, "#wt", 1)
            await page.wait_for_function("()=>CUR==='tanz14'&&SOLO", timeout=6000)
            s = await page.evaluate(state)
            assert s["fields"][1] == ["Tanzen", "Tanz 14", "1 von 3", True] and s["fields"][0][3] is False
            assert s["muted"] and s["name"] == "nacht/tanz14"           # dances run without sound, as in the app
            await roll(page, "#wt", 1)
            await page.wait_for_function("()=>CUR==='tanz27'&&SOLO", timeout=6000)
            await roll(page, "#wt", 1)
            await roll(page, "#wt", 1)                                  # after the last one comes the first again
            await page.wait_for_function("()=>CUR==='tanz14'&&SOLO", timeout=6000)
            await roll(page, "#wt", -1)                                 # and back
            await page.wait_for_function("()=>CUR==='tanzhf'&&SOLO", timeout=6000)
            await roll(page, "#wz", 1)
            await page.wait_for_function("()=>CUR==='zeigenlang3'&&SOLO", timeout=6000)
            await roll(page, "#wk", 1)                                  # the dress goes on from the clip it showed last
            await page.wait_for_function("()=>CUR==='gluecklich10'&&SOLO", timeout=6000)
            assert (await page.evaluate(state))["fields"][0] == ["Nachtkleid", "glücklich 10", "2 von 4", True]
            await page.click("#wk button[data-d='1']")                  # the arrows do the same, for a finger
            await page.wait_for_function("()=>CUR==='gluecklichextra'&&SOLO", timeout=6000)
            # ---- a piece of this clip slower: begin and end are taken from the picture he sees ----
            await page.evaluate("()=>{halt();vis().currentTime=0.5;}")
            await asyncio.sleep(0.3)
            assert await page.evaluate("()=>['pb','prm','pseh','psave'].every(i=>document.getElementById(i).disabled)")   # one step after the other
            await page.click("#pa")
            await page.click("#pap")                                     # one picture later: the stage shows that picture
            at = await page.evaluate("()=>[PV.a,vis().currentTime,vis().paused]")
            assert abs(at[0] - (0.5 + 1 / 24)) < 0.002 and abs(at[1] - at[0]) < 0.02 and at[2]
            await page.evaluate("()=>{vis().currentTime=1.7;}")
            await asyncio.sleep(0.3)
            await page.click("#pb")
            await page.click("#pbm")
            end = await page.evaluate("()=>[PV.b,vis().currentTime]")
            assert abs(end[0] - (1.7 - 1 / 24)) < 0.002 and abs(end[1] - end[0]) < 0.02
            for _ in range(20):
                await page.click("#prm")
            lab = await page.inner_text("#plab")
            assert "Tempo 0.80" in lab and "noch nicht gemerkt" in lab and await page.inner_text("#prlab") == "0.80"
            bar = await page.evaluate("()=>{const n=document.querySelector('#pbar i.neu'),b=document.getElementById('pbar').getBoundingClientRect(),r=n.getBoundingClientRect();return [(r.left-b.left)/b.width,(r.right-b.left)/b.width,vis().duration];}")
            assert abs(bar[0] - at[0] / bar[2]) < 0.02 and abs(bar[1] - end[0] / bar[2]) < 0.02     # the bar shows where the piece lies
            await page.click("#pseh")                                    # it already plays with its tempo here
            await page.wait_for_function("()=>!vis().paused&&vis().currentTime>PV.a+0.1&&vis().currentTime<PV.b-0.1", timeout=5000)
            assert abs(await page.evaluate("()=>vis().playbackRate") - 0.8) < 0.001
            await page.click("#psave")
            await page.wait_for_function("()=>!PV&&(KURVE['nacht/gluecklichextra']||[]).length===1", timeout=4000)
            assert "Gemerkt: 0.54 bis 1.66 s, Tempo 0.80" in await page.inner_text("#plist")
            kept = json.loads((await _get(port, "/api/kurve")).split("\r\n\r\n", 1)[1])
            assert kept["nacht/gluecklichextra"] == [[0.54, 1.66, 0.8]]
            await page.click("#plist a")                                 # and away again
            await page.wait_for_function("()=>!KURVE['nacht/gluecklichextra']", timeout=4000)
            await page.click("#weiter")                                  # the round of the loops goes on
            await page.wait_for_function("()=>!SOLO&&loops().includes(CUR)", timeout=8000)
            # the short Freizeit dress: its own dance, no show clip; the work dress beside it has its own
            await page.click("#looks button >> text=Kurzes Freizeitkleid")
            await page.wait_for_function("()=>CUR==='freizeitgluecklich'", timeout=8000)
            s = await page.evaluate(state)
            assert s["lists"]["tanz"] == ["freizeittanz2"] and s["lists"]["zeigen"] == [] and s["fields"][2][:2] == ["Zeigen", "nur im Nachtkleid"]
            assert s["fields"][0][0] == "Kurzes Freizeitkleid"
            await roll(page, "#wz", 1)                                   # an empty field does nothing
            await roll(page, "#wt", 1)
            await page.wait_for_function("()=>CUR==='freizeittanz2'&&SOLO", timeout=6000)
            assert (await page.evaluate(state))["fields"][1] == ["Tanzen", "Tanz 2", "1 von 1", True]
            await page.click("#looks button >> text=Kurzes Arbeitskleid")
            await page.wait_for_function("()=>CUR==='gluecklich4'", timeout=8000)
            s = await page.evaluate(state)
            assert s["lists"]["tanz"] == ["tanz5"] and s["loops"] == [["1", "gluecklich4"]]
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
    ganzes_page.ton_laut("kurz/neu", 0.4)
    out = ganzes_page.stand_restore()
    assert out["ok"] and out["zurueck"] == ["kurz/brust", "kurz/neu", "kurz/po", "kurz/tanz", "nacht/tanz4",
                                            "schwarz/po"]
    assert ganzes_page.ton_read() == {"aus": [], "stumm": {}, "laut": {}}
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
def test_the_stage_of_the_app_plays_a_stretch_with_its_loudness():
    assert "b.volume=x?Math.min(1,v0*(x.length>2?x[2]:0)):v0" in memory_web.PAGE


def test_sound_off_and_silent_stretches_are_kept_per_clip(tmp_path):
    assert ganzes_page.ton_read() == {"aus": [], "stumm": {}, "laut": {}}
    assert ganzes_page.ton_set("kurz/freizeitbrust2", True) and ganzes_page.ton_set("schwarz/brust2", True)
    assert ganzes_page.ton_stumm("kurz/po2", [[3, 5], [1, 2.5], [2, 3.2], ["x", 1], [4, 4.01], [-1, 2]])
    assert ganzes_page.ton_read() == {"aus": ["kurz/freizeitbrust2", "schwarz/brust2"], "laut": {},
                                      "stumm": {"kurz/po2": [[1.0, 5.0]]}}  # sorted, joined, nonsense left out
    assert ganzes_page.ton_set("schwarz/brust2", False)
    # 2.185.0: a stretch may be quieter or louder instead of silent, [from, to, factor]. One kind is joined, a later one of
    # another kind wins from where it begins, a factor of 1 changes nothing and is left out, more than the phone gives is not kept
    assert ganzes_page.ton_stumm("kurz/po2", [[1, 3], [2, 4, 0.5], [6, 7, 1], [8, 9, 1.3], [8.5, 9.5, 1.3], [10, 11, 2], [12, 13, 0]])
    assert ganzes_page.ton_read()["stumm"] == {"kurz/po2": [[1.0, 2.0], [2.0, 4.0, 0.5], [8.0, 9.5, 1.3], [12.0, 13.0]]}
    assert ganzes_page.ton_stumm("kurz/po2", [])
    assert ganzes_page.ton_read() == {"aus": ["kurz/freizeitbrust2"], "stumm": {}, "laut": {}}
    # quieter or louder: a factor, 1 is normal and leaves no entry
    assert ganzes_page.ton_laut("kurz/po2", 0.5) and ganzes_page.ton_laut("kurz/brust", 1.4)
    assert ganzes_page.ton_read()["laut"] == {"kurz/brust": 1.4, "kurz/po2": 0.5}
    assert ganzes_page.ton_laut("kurz/po2", 1) and ganzes_page.ton_read()["laut"] == {"kurz/brust": 1.4}
    for wrong in (0, 0.05, 1.5, "0.5", None, True):
        assert not ganzes_page.ton_laut("kurz/po2", wrong)
    assert ganzes_page.ton_read()["aus"] == ["kurz/freizeitbrust2"]  # the other parts stay
    assert ganzes_page.ton_laut("kurz/brust", 1.0)
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
    ganzes_page.ton_laut("kurz/po", 0.6)
    look = memory_web.list_outfits()["kurz"]
    assert look["m"] == ["brust"] and look["ms"] == {"po": [[2.0, 4.0]]} and look["mv"] == {"po": 0.6}
    assert "b.volume=Math.min(1,.7*(VOL[" in open(memory_web.__file__, encoding="utf-8").read()
    src = open(memory_web.__file__, encoding="utf-8").read()
    assert "&&!MUTE[name.includes('/')?name:OUTFIT+'/'+name]" in src  # the stage leaves the sound of these off
    assert "b.volume=x?Math.min(1,v0*(x.length>2?x[2]:0)):v0" in src   # and is silent, quieter or louder inside a stretch (2.185.0)


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


async def test_in_a_browser_the_piece_in_the_bar_is_dragged_with_the_mouse(tmp_path, monkeypatch):
    """2.187.0. Metin, 27 Nov 2026, 13:54, with a photo of the page: "Die Zeit die ich jetzt markiert habe für ein Stück schneller oder
    langsamer. Schön wenn ich den mit der Maus rechts und links länger oder kürzer ziehen könnte." An edge of the piece moves that
    end, the middle moves the whole piece, a drag on an empty bar draws one; the clip shows the picture of the edge that moves.
    The same for the piece of the sound."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    try:
        (tmp_path / "clips" / "kurz").mkdir(parents=True)
        for name in ("gluecklich4", "brust"):
            _clip(tmp_path / "clips" / "kurz" / (name + ".mp4"), 4)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    memory_web._kurve_set("kurz/gluecklich4", [[0.1, 0.6, 1.2]])    # a piece he stored before: yellow in the bar
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors, got = [], {}

    async def drag(page, bar, a, b):
        """Press at share a of the bar, move to share b in steps, let go."""
        await page.locator(bar).scroll_into_view_if_needed()
        box = await page.locator(bar).bounding_box()
        y = box["y"] + box["height"] / 2
        await page.mouse.move(box["x"] + box["width"] * a, y)
        await page.mouse.down()
        for i in range(1, 9):
            await page.mouse.move(box["x"] + box["width"] * (a + (b - a) * i / 8), y)
            await asyncio.sleep(0.02)
        await page.mouse.up()
        await asyncio.sleep(0.15)
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1200, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=kurz/gluecklich4")
            await page.wait_for_function("()=>CUR==='gluecklich4'&&vis().duration>3", timeout=9000)
            pv = "()=>({a:PV&&PV.a,b:PV&&PV.b,t:vis().currentTime,d:vis().duration,paused:vis().paused})"
            near = lambda x, y: abs(x - y) < 0.09
            # 14:02, with a photo of a yellow and a purple piece: "wenn ich mit der Maus an den lila klicke, die Zeit mir angezeigt
            # wird, und wenn ich orange oder braun ... anklicke, dass mir die Zeit, die ich eingestellt habe, auch dort angezeigt
            # wird. Also ich möchte wissen, wie viel Tempo hat links ... und wie viel hat rechts die andere Farbe"
            labels = "()=>[...document.querySelectorAll('#pbar i b')].map(b=>b.textContent)"
            assert await page.evaluate(labels) == ["1.20"]             # the tempo stands in the stored piece
            # 14:06: "Kann ich die auch nachträglich anklicken und bearbeiten, dass ich zum Beispiel nicht mehr 1 möchte, sondern 0,9":
            # a click on the yellow piece takes it into the editor, it turns purple, and storing replaces it
            await drag(page, "#pbar", 0.10, 0.10)
            assert await page.evaluate("()=>[PV.a,PV.b,PV.r,PV.i]") == [0.1, 0.6, 1.2, 0]
            assert await page.inner_text("#plab") == "Gemerktes Stück von 0.10 bis 0.60 s (0.50 s lang), Tempo 1.20"
            assert await page.evaluate("()=>[document.querySelectorAll('#pbar i.alt').length,document.querySelectorAll('#pbar i.neu').length]") == [0, 1]
            await drag(page, "#pbar", 0.90, 0.90)                      # a click beside it, nothing changed: it is let go again
            assert await page.evaluate("()=>PV===null") and await page.evaluate(labels) == ["1.20"]
            await drag(page, "#pbar", 0.10, 0.10)
            await page.click("#prm")
            assert "Tempo 1.19 (Änderung noch nicht gemerkt)" in await page.inner_text("#plab")
            await page.click("#psave")
            await page.wait_for_function("()=>PV===null", timeout=4000)
            assert memory_web._kurve_read() == {"kurz/gluecklich4": [[0.1, 0.6, 1.19]]}   # replaced, not added
            await page.evaluate("()=>halt()")
            await drag(page, "#pbar", 0.30, 0.60)                      # an empty bar: the drag draws a piece
            s = await page.evaluate(pv)
            got["draw"] = s
            assert near(s["a"], 0.30 * s["d"]) and near(s["b"], 0.60 * s["d"]) and s["paused"], s
            assert near(s["t"], s["b"]), s                             # the clip shows the picture of the edge he let go
            assert abs(s["a"] * 24 - round(s["a"] * 24)) < 0.03 and abs(s["b"] * 24 - round(s["b"] * 24)) < 0.03, s   # whole pictures
            assert "Stück von" in await page.inner_text("#plab") and await page.inner_text("#psel") == ""
            assert await page.evaluate(labels) == ["1.19", "1.00"]     # and the tempo of the new piece in the purple one
            await drag(page, "#pbar", 0.60, 0.80)                      # the right edge: longer
            s2 = await page.evaluate(pv)
            assert near(s2["b"], 0.80 * s2["d"]) and s2["a"] == s["a"] and near(s2["t"], s2["b"]), s2
            await drag(page, "#pbar", 0.30, 0.10)                      # the left edge: earlier
            s3 = await page.evaluate(pv)
            assert near(s3["a"], 0.10 * s3["d"]) and s3["b"] == s2["b"] and near(s3["t"], s3["a"]), s3
            await drag(page, "#pbar", 0.10, 0.95)                      # an edge never passes the other one
            s4 = await page.evaluate(pv)
            assert s4["b"] == s3["b"] and 0.07 < s4["b"] - s4["a"] < 0.1, s4
            await drag(page, "#pbar", 0.77, 0.10)                      # the left edge back
            await drag(page, "#pbar", 0.80, 0.50)                      # the right edge again: shorter
            s5 = await page.evaluate(pv)
            assert near(s5["b"], 0.50 * s5["d"]), s5
            await drag(page, "#pbar", 0.30, 0.50)                      # the middle: the whole piece moves, its length stays
            s6 = await page.evaluate(pv)
            got["move"] = [s5, s6]
            assert near(s6["a"] - s5["a"], 0.20 * s6["d"]) and abs((s6["b"] - s6["a"]) - (s5["b"] - s5["a"])) < 0.002, (s5, s6)
            await drag(page, "#pbar", 0.05, 0.05)                      # a click beside the piece: only go there
            s7 = await page.evaluate(pv)
            assert (s7["a"], s7["b"]) == (s6["a"], s6["b"]) and near(s7["t"], 0.05 * s7["d"]), s7
            # that spot lies in the yellow piece: while the purple one waits unsaved, the click only shows what the yellow one holds
            assert await page.inner_text("#psel") == ("Gelbes Stück (gemerkt): von 0.10 bis 0.60 s (0.50 s lang), Tempo 1.19. "
                                                      "Zum Ändern erst das lila Stück merken oder verwerfen.")
            assert await page.evaluate("()=>document.querySelectorAll('#pbar i.alt.sel').length") == 1
            await page.click("#prp")
            assert await page.evaluate(labels) == ["1.19", "1.01"]
            await drag(page, "#pbar", 0.40, 0.40)                      # a click on the purple piece: its line is the one above
            assert await page.inner_text("#psel") == "" and "Tempo 1.01" in await page.inner_text("#plab")
            assert memory_web._kurve_read() == {"kurz/gluecklich4": [[0.1, 0.6, 1.19]]}   # nothing is stored by dragging
            # the same for the sound of a touch clip; drawn from right to left this time
            await page.evaluate("()=>{BUSY=false;touch('Brust','brust');}")
            await page.wait_for_function("()=>CUR==='brust'&&vis().duration>3&&CURSND", timeout=9000)
            tv = "()=>({a:TV&&TV.a,b:TV&&TV.b,t:vis().currentTime,d:vis().duration})"
            await drag(page, "#tbar", 0.70, 0.40)
            t1 = await page.evaluate(tv)
            got["ton"] = t1
            assert near(t1["a"], 0.40 * t1["d"]) and near(t1["b"], 0.70 * t1["d"]), t1
            await drag(page, "#tbar", 0.70, 0.90)
            t2 = await page.evaluate(tv)
            assert near(t2["b"], 0.90 * t2["d"]) and t2["a"] == t1["a"], t2
            assert await page.evaluate("()=>[...document.querySelectorAll('#tbar i b')].map(b=>b.textContent)") == ["aus"]
            # a stored piece of the sound is changed the same way: store it silent, click it, make it half as loud, store again
            await page.click("#sadd")
            await page.wait_for_function("()=>TV===null", timeout=4000)
            stored = ganzes_page.ton_read()["stumm"]["kurz/brust"]
            assert len(stored) == 1 and len(stored[0]) == 2
            await drag(page, "#tbar", 0.60, 0.60)
            assert await page.evaluate("()=>TV&&TV.i") == 0 and (await page.inner_text("#slab")).startswith("Gemerktes Stück von")
            for _ in range(5):
                await page.click("#vm")                                # from silence the first step is 90 percent
            await page.click("#sadd")
            await page.wait_for_function("()=>TV===null", timeout=4000)
            again = ganzes_page.ton_read()["stumm"]["kurz/brust"]
            assert len(again) == 1 and again[0][:2] == stored[0] and again[0][2] == 0.5, again
            # a loop has no sound: its sound bar does nothing
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=kurz/gluecklich4")
            await page.wait_for_function("()=>CUR==='gluecklich4'&&vis().duration>3", timeout=9000)
            await page.evaluate("()=>{document.getElementById('tonstk').style.display='block';}")
            await drag(page, "#tbar", 0.20, 0.50)
            assert await page.evaluate("()=>!TV||TV.a<0||TV.p!==pthNow()")
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
