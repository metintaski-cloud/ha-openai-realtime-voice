"""The page /naht: the end of one clip over the beginning of the next, as a see through stencil."""
import asyncio
import json
import re
import shutil
import subprocess

import pytest

from app import ganzes_page, memory, memory_web, naht_page


def script() -> str:
    return re.search(r"<script>(.*)</script>", naht_page.PAGE, re.S).group(1)


def test_the_script_is_sound_javascript(tmp_path):
    assert "\\" not in naht_page.PAGE  # a raw string: a backslash would reach the browser as it is
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    path = tmp_path / "naht.js"
    path.write_text(script(), encoding="utf-8")
    done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_it_shows_the_hand_over_of_a_loop_as_the_app_does_it():
    """The marks set here are only right when the page lays the same two pictures on each other as
    the stage of the app. On 25 Nov 2026 marks were computed twice with the wrong hand over."""
    js, app = script(), open(memory_web.__file__, encoding="utf-8").read()
    assert f"HAND_PRE={naht_page.HAND_PRE},HAND_OFF={naht_page.HAND_OFF},HAND_FADE={naht_page.HAND_FADE}" in js
    # a loop is handed over tight: PRE 0.25 s, the old clip fades from 300 ms on, the new one fades in 0.8 s
    assert "const PRE0=tight?0.25:0.8,OFF=tight?300:850" in app
    # the lead of the clip that comes in replaces the 0.25 s, only for a loop hand over
    assert "PRE=tight&&LEAD[lp]!==undefined?LEAD[lp]:PRE0;" in app and "LEAD[k+'/'+c]=outs[k].l[c]" in app
    assert naht_page.HAND_PRE == memory_web.LEAD_DEFAULT
    assert app.count("TIGHT=true;") == 3 and "function stageLoop" in app
    # the extra clip of the happy loop comes in like a loop too, and the page /naht lists it as one more loop
    assert "{TIGHT=true;stagePlay(['gluecklichextra'],b);}" in app
    assert "base(n)===PRE+'gluecklich'||base(n)===PRE+'gluecklichextra'" in js
    assert "#stage video{opacity:0;transition:opacity .8s}" in app
    assert (naht_page.HAND_PRE, naht_page.HAND_OFF, naht_page.HAND_FADE) == (0.25, 300, 0.8)
    assert "LOOP_PRE=0.25,LOOP_OFF=300" in re.search(r"<script>(.*)</script>", ganzes_page.PAGE, re.S).group(1)


def test_the_lead_of_a_clip_is_stored_checked_and_given_to_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LEYLA_VORLAUF", str(tmp_path / "v.json"))
    assert memory_web._vorlauf_read() == {}
    assert memory_web._vorlauf_set("kurz/freizeitgluecklich2", 0.4126)
    assert memory_web._vorlauf_set("kurz/gluecklich", "0")
    assert memory_web._vorlauf_read() == {"kurz/freizeitgluecklich2": 0.413, "kurz/gluecklich": 0.0}
    for bad in (-0.1, 1.6, "x", None, True):
        assert not memory_web._vorlauf_set("kurz/gluecklich", bad)
    assert memory_web._vorlauf_set("kurz/gluecklich", 0.25)  # the default: no entry
    assert memory_web._vorlauf_read() == {"kurz/freizeitgluecklich2": 0.413}
    (tmp_path / "v.json").write_text('{"a/b": 9, "c/d": "x", "e/f": 0.5}')  # a broken value is not used
    assert memory_web._vorlauf_read() == {"e/f": 0.5}
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    for name in ("freizeitgluecklich", "freizeitgluecklich2"):
        (folder / (name + ".mp4")).write_bytes(b"x")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    (tmp_path / "v.json").write_text('{"kurz/freizeitgluecklich2": 0.4, "kurz/gibtesnicht": 0.3}')
    assert memory_web.list_outfits()["kurz"]["l"] == {"freizeitgluecklich2": 0.4}


def test_the_lead_is_part_of_the_reset_point(tmp_path, monkeypatch):
    assert memory_web._vorlauf_set("kurz/a", 0.5)
    ganzes_page.stand_save()
    assert memory_web._vorlauf_set("kurz/a", 0.9) and memory_web._vorlauf_set("kurz/b", 0.1)
    assert ganzes_page.stand_info()["geaendert"] == ["kurz/a", "kurz/b"]
    assert ganzes_page.stand_restore()["zurueck"] == ["kurz/a", "kurz/b"]
    assert memory_web._vorlauf_read() == {"kurz/a": 0.5}
    # a reset point from before 2.166.0 has no leads: going back to it means none
    import json as _json, os as _os
    path = _os.environ["LEYLA_STAND"]
    old = _json.load(open(path))
    old.pop("vorlauf")
    _json.dump(old, open(path, "w"))
    assert ganzes_page.stand_restore()["ok"] and memory_web._vorlauf_read() == {}


async def _get(port: int, path: str) -> str:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    raw = (await reader.read()).decode()
    writer.close()
    return raw


async def test_the_page_is_served_and_the_whole_outfit_page_links_to_it(tmp_path):
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    try:
        port = server.sockets[0].getsockname()[1]
        page = await _get(port, "/naht?a=kurz/freizeitgluecklich")
        whole = await _get(port, "/ganzes")
    finally:
        server.close()
    assert page.startswith("HTTP/1.1 200") and "Naht: Schleifen als Ebenen" in page and 'href="/ganzes"' in page
    assert 'href="/naht"' in whole


def _clip(path, seconds: int) -> None:
    """A tiny clip a browser without H.264 can play (VP9 and Opus in an MP4 file)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=96x144:rate=24:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:v", "libvpx-vp9", "-b:v", "60k",
                    "-g", "12", "-c:a", "libopus", "-b:a", "24k", "-f", "mp4", str(path)], check=True)


async def test_in_a_browser_every_loop_is_its_own_layer(tmp_path, monkeypatch):
    """Metin, 02:15: each loop on its own, faded in or out, see through or not, over its full
    length, shortened on the time axis one by one; then one button stores everything."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name, seconds in (("freizeitgluecklich", 4), ("freizeitgluecklich2", 6), ("freizeitgluecklich3", 4),
                              ("freizeitpo8", 3), ("gluecklich", 3)):
            _clip(folder / (name + ".mp4"), seconds)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    cut, leads = tmp_path / "schnitt.json", tmp_path / "vorlauf.json"
    monkeypatch.setenv("LEYLA_SCHNITT", str(cut))
    monkeypatch.setenv("LEYLA_VORLAUF", str(leads))
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    monkeypatch.setenv("LEYLA_KURVE", str(tmp_path / "clip_kurve.json"))
    cut.write_text(json.dumps({"kurz/freizeitgluecklich": [0.5, 3.5], "kurz/freizeitgluecklich2": [0.2, 5.0]}))
    leads.write_text(json.dumps({"kurz/freizeitgluecklich2": 0.4}))
    (tmp_path / "tempo.json").write_text(json.dumps([{"name": "kurz/freizeitgluecklich2", "rate": 2}]))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    G1, G2, G3 = "freizeitgluecklich", "freizeitgluecklich2", "freizeitgluecklich3"
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1000, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/naht?a=kurz/{G1}&b=kurz/{G2}")

            async def state() -> dict:
                rows = await page.evaluate(
                    "()=>LAY.map(L=>({n:L.n,on:L.on,op:L.op,t:L.t,s:L.s,e:L.e,ld:L.ld,d:L.d,mode:L.mode,play:!!L.play,"
                    "vt:L.v.currentTime,vop:getComputedStyle(L.v).opacity,blend:getComputedStyle(L.v).mixBlendMode,"
                    "paused:L.v.paused,z:Number(getComputedStyle(L.v).zIndex)}))")
                return {r["n"]: r for r in rows}

            async def settled() -> dict:
                for _ in range(80):
                    await asyncio.sleep(0.1)
                    if not await page.evaluate("()=>document.body.classList.contains('busy')||LAY.some(L=>!L.d)"):
                        break
                await asyncio.sleep(0.2)
                return await state()

            def key(name: str, k: str) -> str:
                return f".lay[data-n='{name}'] [data-k='{k}']"
            st = await settled()
            assert list(st) == [G1, G2, G3]                       # every loop is a layer, the work dress is another outfit
            assert await page.evaluate("()=>look.selectedOptions[0].textContent") == "Kurzes Freizeitkleid"
            # the hand over from the address: the old one on its last picture, the new one where the app has it then
            assert st[G1]["on"] and st[G1]["vop"] == "1" and (st[G1]["s"], st[G1]["e"], st[G1]["t"]) == (0.5, 3.5, 3.5)
            assert st[G2]["on"] and st[G2]["vop"] == "0.5" and (st[G2]["s"], st[G2]["e"], st[G2]["ld"]) == (0.2, 5.0, 0.4)
            assert st[G2]["t"] == 1.0                             # 0.2 + 0.4 s of lead at tempo 2
            assert abs(st[G1]["vt"] - 3.5) < 0.05 and abs(st[G2]["vt"] - 1.0) < 0.05 and st[G2]["z"] > st[G1]["z"]
            assert not st[G3]["on"] and st[G3]["vop"] == "0" and (st[G3]["s"], st[G3]["e"]) == (0, st[G3]["d"])
            assert all(r["paused"] for r in st.values())
            # each layer is faded in and out and made see through on its own
            await page.check(key(G3, "on"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='30';e.oninput();}", key(G3, "op"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='40';e.oninput();}", key(G1, "op"))
            st = await settled()
            assert (st[G1]["vop"], st[G2]["vop"], st[G3]["vop"]) == ("0.4", "0.5", "0.3")
            await page.uncheck(key(G3, "on"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='100';e.oninput();}", key(G1, "op"))
            assert (await state())[G3]["vop"] == "0"
            # the slider and its fine steps move what is chosen: here the end of loop 1, the picture follows
            await page.click(key(G1, "me"))
            await page.click(key(G1, "fm"))
            st = await settled()
            assert (st[G1]["e"], st[G1]["t"]) == (3.458, 3.458) and abs(st[G1]["vt"] - 3.458) < 0.05
            assert st[G2]["e"] == 5.0 and st[G2]["t"] == 1.0      # the other loop is not touched
            await page.click(key(G1, "p3"))
            assert (await state())[G1]["e"] == 3.459
            await page.click(key(G1, "m3"))
            assert await page.evaluate("()=>save.classList.contains('on')")
            assert "noch nicht gemerkt" in await page.inner_text(key(G1, "lab"))
            # the beginning of loop 2 and its lead
            await page.click(key(G2, "ms"))
            assert (await state())[G2]["t"] == 0.2                # choosing a mark shows its picture
            await page.click(key(G2, "p1"))
            await page.click(key(G2, "ml"))
            await page.click(key(G2, "p1"))
            await page.click(key(G2, "p1"))
            st = await settled()
            assert (st[G2]["s"], st[G2]["ld"]) == (0.21, 0.42)
            await page.click(key(G2, "l0"))
            assert (await state())[G2]["ld"] == 0.25
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='0.6';e.oninput();}", key(G2, "pos"))
            assert (await state())[G2]["ld"] == 0.6
            # the time axis: one bar per loop over its full length, each shortened on its own
            ax = await page.evaluate("()=>{const r=ax.getBoundingClientRect();return {x:r.left,y:r.top,pps:axPps(),h:r.height}}")
            assert ax["h"] == 26 + 3 * 26 and ax["pps"] > 100

            async def drag(row: int, t_from: float, t_to: float) -> None:
                y = ax["y"] + await page.evaluate("(i)=>axY(i)", row) + 10
                x0, x1 = [ax["x"] + await page.evaluate("(t)=>axX(t)", t) for t in (t_from, t_to)]
                await page.mouse.move(x0, y)
                await page.mouse.down()
                await page.mouse.move((x0 + x1) / 2, y)
                await page.mouse.move(x1, y)
                await page.mouse.up()
            await drag(0, 3.458, 2.958)                           # the end of loop 1 half a second shorter
            await drag(2, 0, 1.0)                                 # the beginning of loop 3 one second shorter
            st = await settled()
            assert abs(st[G1]["e"] - 2.958) < 0.02 and st[G1]["s"] == 0.5
            assert abs(st[G3]["s"] - 1.0) < 0.02 and st[G3]["e"] == st[G3]["d"] and st[G2]["s"] == 0.21
            await drag(2, 2.5, 3.0)                               # inside the bar: the play head, the marks stay
            st = await settled()
            assert abs(st[G3]["t"] - 3.0) < 0.02 and abs(st[G3]["s"] - 1.0) < 0.02
            # the white line never leaves the blue part (Metin, 03:41): not past its end, not before its beginning
            await drag(0, 2.0, 3.9)
            st = await settled()
            assert st[G1]["t"] == st[G1]["e"] and abs(st[G1]["e"] - 2.958) < 0.02 and abs(st[G1]["vt"] - st[G1]["e"]) < 0.05
            await drag(0, 2.0, 0.05)
            st = await settled()
            assert (st[G1]["t"], st[G1]["s"]) == (0.5, 0.5)
            assert await page.evaluate("(k)=>{const e=document.querySelector(k);return [Number(e.min),Number(e.max)]}",
                                       key(G1, "pos")) == [0.5, st[G1]["e"]]
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='9';e.oninput();}", key(G1, "pos"))
            assert (await state())[G1]["t"] == st[G1]["e"]
            await drag(2, st[G3]["s"], 9.0)                       # at least half a second always stays
            st = await settled()
            assert abs(st[G3]["s"] - (st[G3]["e"] - 0.5)) < 0.001
            await drag(2, st[G3]["s"], 1.0)
            await drag(0, 2.958, 3.458)
            # one loop plays on its own from its beginning to its end mark, the others stand still
            await page.click(key(G1, "gs"))
            await settled()
            await page.click(key(G1, "play"))
            await asyncio.sleep(0.8)
            st = await state()
            assert st[G1]["play"] and not st[G1]["paused"] and 0.6 < st[G1]["t"] < 2.6 and st[G2]["paused"] and st[G3]["paused"]
            await page.click(key(G1, "play"))
            st = await settled()
            assert not st[G1]["play"] and st[G1]["paused"] and abs(st[G1]["vt"] - st[G1]["t"]) < 0.05 and st[G1]["t"] > 0.6
            await page.click(key(G1, "play"))                     # to its end mark, there it stops by itself
            for _ in range(60):
                await asyncio.sleep(0.1)
                if not (await state())[G1]["play"]:
                    break
            st = await settled()
            assert not st[G1]["play"] and abs(st[G1]["t"] - st[G1]["e"]) < 0.001 and abs(st[G1]["e"] - 3.458) < 0.02
            # all visible layers at once (Metin, 02:29): they start together, the hidden one stays where it is
            await page.click("#gall")
            st = await settled()
            assert (st[G1]["t"], st[G2]["t"], st[G3]["t"]) == (st[G1]["s"], st[G2]["s"], st[G3]["s"])
            await page.click("#pall")
            await asyncio.sleep(0.8)
            st = await state()
            assert st[G1]["play"] and st[G2]["play"] and not st[G1]["paused"] and not st[G2]["paused"]
            assert not st[G3]["play"] and st[G3]["paused"] and st[G3]["t"] == st[G3]["s"]
            assert await page.inner_text("#pall") == "⏸ alle anhalten"
            # they run in step: loop 2 plays at tempo 2, so it has come twice as far from its beginning
            a1, a2 = st[G1]["vt"] - st[G1]["s"], st[G2]["vt"] - st[G2]["s"]
            assert a1 > 0.3 and abs(a2 - 2 * a1) < 0.25, (a1, a2)
            await page.click("#pall")
            st = await settled()
            assert all(r["paused"] and not r["play"] for r in st.values()) and abs(st[G2]["vt"] - st[G2]["t"]) < 0.05
            assert await page.inner_text("#pall") == "▶ alle sichtbaren abspielen"
            # every layer has its own tempo under its see through slider (Metin, 02:39), also while it plays
            assert await page.evaluate("()=>LAY.map(L=>L.rt)") == [1, 2, 1]
            await page.evaluate("()=>save.click()")
            await asyncio.sleep(0.5)
            assert not await page.evaluate("()=>save.classList.contains('on')")
            await page.click(key(G2, "r1"))
            assert await page.evaluate("()=>save.classList.contains('on')") and await page.inner_text(key(G2, "rtlab")) == "1.00"
            await page.click(key(G1, "rp"))
            await page.click(key(G1, "rp"))
            await page.click("#gall")
            await settled()
            await page.click("#pall")
            await asyncio.sleep(0.5)
            assert await page.evaluate("()=>LAY.map(L=>L.v.playbackRate)") == [1.02, 1, 1]
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='0.5';e.oninput();}", key(G1, "rt"))
            assert await page.evaluate("()=>LAY[0].v.playbackRate") == 0.5
            await page.click("#pall")
            await settled()
            await page.click(key(G1, "rm"))
            await page.click("#save")
            await asyncio.sleep(0.6)
            stored = {i["name"]: i["rate"] for i in json.loads((tmp_path / "tempo.json").read_text())}
            assert stored["kurz/" + G1] == 0.49 and stored["kurz/" + G2] == 1
            assert memory_web.list_outfits()["kurz"]["r"] == {G1: 0.49}  # tempo 1 is no entry for the app
            await page.click(key(G1, "r1"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='2';e.oninput();}", key(G2, "rt"))
            await page.click("#save")
            await asyncio.sleep(0.6)
            assert memory_web.list_outfits()["kurz"]["r"] == {G2: 2}
            # a stretch with its own tempo inside a loop (Metin, 05:10 and 05:27: Kling has tempo inside the tempo)
            kurve = tmp_path / "clip_kurve.json"
            await page.click(key(G1, "mt"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='1.2';e.oninput();}", key(G1, "pos"))
            await page.click(key(G1, "ka"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='2.2';e.oninput();}", key(G1, "pos"))
            await page.click(key(G1, "kb"))
            assert "von 1.200 bis 2.200 s" in await page.inner_text(key(G1, "klab"))
            # every press shows (Metin, 05:50): the button lights up and carries the time it took
            assert await page.inner_text(key(G1, "ka")) == "Stück Anfang: 1.200 s"
            assert await page.inner_text(key(G1, "kb")) == "Stück Ende: 2.200 s"
            assert await page.evaluate("(k)=>document.querySelector(k).classList.contains('hit')", key(G1, "kb"))
            assert await page.evaluate("(k)=>document.querySelector(k).classList.contains('on')", key(G1, "kadd"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='0.5';e.oninput();}", key(G1, "kr"))
            await page.click(key(G1, "kadd"))
            assert await page.evaluate("()=>LAY[0].k") == [[1.2, 2.2, 0.5]]
            assert await page.inner_text(key(G1, "ka")) == "Stück Anfang hier"
            assert "1.200 bis 2.200 s: Tempo 0.50" in await page.inner_text(key(G1, "klist"))
            assert await page.evaluate("()=>save.classList.contains('on')")
            # a second stretch that overlaps cuts the first one, it does not lie on top of it
            await page.evaluate("()=>{const L=LAY[0];L.ka=2.0;L.kb=2.6;L.kr=1.5;}")
            await page.click(key(G1, "kadd"))
            assert await page.evaluate("()=>LAY[0].k") == [[1.2, 2.0, 0.5], [2.0, 2.6, 1.5]]
            # it plays that way: the tempo of the clip outside, the tempo of the stretch inside
            base = await page.evaluate("()=>LAY[0].rt")
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='0.9';e.oninput();}", key(G1, "pos"))
            await settled()
            await page.click(key(G1, "play"))
            got = {}
            for _ in range(90):
                await asyncio.sleep(0.05)
                t, r, playing = await page.evaluate("()=>[LAY[0].v.currentTime,LAY[0].v.playbackRate,!!LAY[0].play]")
                zone = "vor" if t < 1.15 else "erstes" if 1.3 < t < 1.9 else "zweites" if 2.1 < t < 2.5 else "nach" if t > 2.7 else ""
                if zone and playing:
                    got[zone] = r
                if t > 2.9 or not playing:
                    break
            await page.evaluate("()=>{if(LAY[0].play)document.querySelector(\".lay[data-n='freizeitgluecklich'] [data-k='play']\").click();}")
            assert got == {"vor": base, "erstes": 0.5, "zweites": 1.5, "nach": base}, got
            await page.click("#save")
            await asyncio.sleep(0.6)
            assert json.loads(kurve.read_text()) == {"kurz/" + G1: [[1.2, 2.0, 0.5], [2.0, 2.6, 1.5]]}
            assert memory_web.list_outfits()["kurz"]["k"] == {G1: [[1.2, 2.0, 0.5], [2.0, 2.6, 1.5]]}
            assert not await page.evaluate("()=>save.classList.contains('on')")
            # taking the stretches away again
            await page.click(key(G1, "klist") + " button[data-kdel='1']")
            await page.click(key(G1, "klist") + " button[data-kdel='0']")
            assert await page.evaluate("()=>LAY[0].k") == []
            await page.click("#save")
            await asyncio.sleep(0.6)
            assert json.loads(kurve.read_text()) == {}
            # the hand over again with the new values, the difference picture, and once in real time
            await page.click("#hv")
            st = await settled()
            assert st[G1]["t"] == st[G1]["e"] and abs(st[G2]["t"] - (0.21 + 0.6 * 2)) < 0.001 and not st[G3]["on"]
            await page.click("#diff")
            st = await state()
            assert st[G2]["blend"] == "difference" and st[G2]["vop"] == "1" and st[G1]["blend"] == "normal"
            await page.click("#diff")
            assert (await state())[G2]["blend"] == "normal"
            # the row for "So spielt es die App": up to five loops (Metin, 02:31), here 1, 2, 3 and 1 again
            assert await page.evaluate("()=>[hf.value,ht.value,h3.value,h4.value,h5.value]") == [G1, G2, G3, "", ""]
            assert await page.evaluate("()=>h3.options[0].textContent") == "nichts mehr"
            await page.select_option("#h4", G1)
            await page.click("#play")
            await asyncio.sleep(0.6)
            assert await page.evaluate("()=>PLAYING")
            tops = []
            for _ in range(220):
                await asyncio.sleep(0.1)
                if not await page.evaluate("()=>PLAYING"):
                    break
                moving = [n for n, r in (await state()).items() if not r["paused"]]
                tops.append(len(moving))
            assert await page.evaluate("()=>window.SEEN") == [G1, G2, G3, G1]
            assert max(tops) <= 2 and tops.count(0) < 12             # never more than the old and the new clip at once, no gap
            st = await settled()
            assert not await page.evaluate("()=>PLAYING") and all(r["paused"] for r in st.values())
            assert (st[G1]["vop"], st[G2]["vop"]) == ("1", "0.5") and abs(st[G1]["vt"] - st[G1]["e"]) < 0.05
            # the mixer (Metin, 02:57): the ticked loops in random order without end, seamless, values change while it runs
            await page.check(key(G3, "on"))
            await page.click("#mix")
            await asyncio.sleep(0.5)
            assert await page.evaluate("()=>PLAYING&&MIX==='rnd'") and await page.inner_text("#mix") == "⏸ anhalten"
            moving, tempo_seen = [], False
            for step in range(170):
                await asyncio.sleep(0.1)
                st = await state()
                moving.append(sum(1 for r in st.values() if not r["paused"]))
                if step == 20:                                    # a change while it runs does not stop it
                    await page.click(key(G1, "rp"))
                    await page.click(key(G2, "me"))
                    await page.click(key(G2, "m1"))
                    assert await page.evaluate("()=>PLAYING&&MIX")
                if step == 60:
                    await page.uncheck(key(G3, "on"))             # loop 3 no longer takes part
                    cut_at = len(await page.evaluate("()=>window.SEEN"))
            seen, late = await page.evaluate("()=>[window.SEEN,window.LATE]")
            assert await page.evaluate("()=>PLAYING&&MIX")       # it never ends by itself
            assert len(seen) >= 5 and all(x != y for x, y in zip(seen, seen[1:])), seen  # never the same loop twice in a row
            assert G3 not in seen[cut_at + 1:], (seen, cut_at)
            assert max(moving) <= 2 and moving.count(0) < 12      # the old and the new clip at most, and no gap
            assert all(-1 <= x <= 120 for x in late), late        # each hand over began at the picture it was planned for
            assert "letzte Übergabe" in await page.inner_text("#minfo")
            assert (await state())[G2]["e"] == 4.99 and await page.evaluate("()=>LAY[0].rt") == 1.01
            await page.click("#mix")
            st = await settled()
            assert not await page.evaluate("()=>PLAYING||MIX") and all(r["paused"] for r in st.values())
            assert await page.inner_text("#mix") == "▶ gemischt"
            # the second mixer (Metin, 04:57) always runs 1, 2, 3 and round again
            await page.check(key(G3, "on"))
            await page.click("#mixs")
            for _ in range(160):
                await asyncio.sleep(0.1)
                if len(await page.evaluate("()=>window.SEEN||[]")) >= 5:
                    break
            assert await page.evaluate("()=>window.SEEN.slice(0,5)") == [G1, G2, G3, G1, G2]
            assert await page.evaluate("()=>MIX") == "seq" and await page.inner_text("#mixs") == "⏸ anhalten"
            await page.click("#mix")                              # the other button changes over to the mixed one
            await asyncio.sleep(0.6)
            assert await page.evaluate("()=>PLAYING&&MIX") == "rnd" and await page.inner_text("#mixs") == "▶ der Reihe nach: 1, 2, 3"
            await page.click("#mix")
            await settled()
            assert not await page.evaluate("()=>PLAYING")
            await page.click(key(G2, "p1"))
            await page.click(key(G1, "rm"))
            await page.check(key(G3, "on"))
            await page.uncheck(key(G3, "on"))
            # another clip as a layer: the touch clips have their names
            options = await page.evaluate("()=>[...add.options].map(o=>o.textContent)")
            assert options[1] == "Po (freizeitpo8)"
            await page.select_option("#add", "freizeitpo8")
            st = await settled()
            assert list(st)[3] == "freizeitpo8" and st["freizeitpo8"]["on"] and st["freizeitpo8"]["vop"] == "0.5"
            assert await page.evaluate("()=>ax.getBoundingClientRect().height") == 26 + 4 * 26
            # one button stores every mark and lead that changed, nothing else
            e1, s3 = st[G1]["e"], st[G3]["s"]
            await page.click("#save")
            await asyncio.sleep(0.6)
            assert json.loads(cut.read_text()) == {"kurz/" + G1: [0.5, e1], "kurz/" + G2: [0.21, 5.0], "kurz/" + G3: [s3, 0]}
            assert json.loads(leads.read_text()) == {"kurz/" + G2: 0.6}
            assert not await page.evaluate("()=>save.classList.contains('on')")
            # a change that is not stored can be taken back
            await page.click(key(G3, "ms"))
            await page.click(key(G3, "p1"))
            assert await page.evaluate("()=>save.classList.contains('on')")
            await page.click("#back")
            st = await state()
            assert st[G3]["s"] == s3 and not await page.evaluate("()=>save.classList.contains('on')")
            # the beginning at zero and the end at the real end mean: no mark
            await page.click(key(G3, "ms"))
            await page.evaluate("(k)=>{const e=document.querySelector(k);e.value='0';e.oninput();}", key(G3, "pos"))
            await page.click("#save")
            await asyncio.sleep(0.5)
            assert "kurz/" + G3 not in json.loads(cut.read_text())
            await browser.close()
    finally:
        server.close()
    assert not errors, errors


async def test_the_stage_reports_how_exactly_a_loop_handed_over(tmp_path):
    """Numbers only: how late against the plan, how long to the first picture, the lead."""
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "handMeasure(tight&&cont,a,b,PRE);b.play()" in app and "requestVideoFrameCallback" in app
    memory_web.HAND.clear()
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def post(body: dict) -> str:
        raw = json.dumps(body).encode()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"POST /api/handstats HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(raw)).encode() + b"\r\n\r\n" + raw)
        await writer.drain()
        out = (await reader.read()).decode()
        writer.close()
        return out
    try:
        for late, first in ((4, 30), (12, 45), (-3, 38), (60, 120), (8, 41)):
            assert '"ok": true' in await post({"late": late, "first": first, "lead": 250, "name": "kurz/x"})
        assert '"ok": false' in await post({"late": "x", "text": "nothing personal is kept"})
        got = json.loads((await _get(port, "/api/handstats")).split("\r\n\r\n", 1)[1])
    finally:
        server.close()
        memory_web.HAND.clear()
    assert got["n"] == 5 and got["late"] == {"median": 8, "min": -3, "max": 60, "p90": 60}
    assert got["first"]["median"] == 41 and set(got["letzte"][0]) == {"at", "late", "first", "lead"}


async def test_in_a_browser_a_loop_comes_in_as_early_as_its_lead_says(tmp_path, monkeypatch):
    """The page /ganzes hands over like the stage of the app: with a lead of 1.2 s the second loop
    starts 1.2 s before the end of the first one, not 0.25 s."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name in ("freizeitgluecklich", "freizeitgluecklich2"):
            _clip(folder / (name + ".mp4"), 4)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setenv("LEYLA_VORLAUF", str(tmp_path / "vorlauf.json"))
    assert memory_web._vorlauf_set("kurz/freizeitgluecklich2", 1.2)
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    seen = {}
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 800})
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=kurz/freizeitgluecklich")
            # note where the old clip is at the moment each loop comes in
            await page.evaluate("""()=>{window.IN={};const t=()=>{const vs=[v0,v1];
              if(CUR&&window.IN[CUR]===undefined){const old=vs[1-SV];window.IN[CUR]=old.currentTime||0;}requestAnimationFrame(t);};t();}""")
            for _ in range(120):
                await asyncio.sleep(0.1)
                seen = await page.evaluate("()=>window.IN")
                if "freizeitgluecklich2" in seen and len(seen) >= 2 and any(
                        k == "freizeitgluecklich" and i for i, k in enumerate(seen)):
                    break
            await asyncio.sleep(4.5)
            seen = await page.evaluate("()=>window.IN")
            await browser.close()
    finally:
        server.close()
    assert abs(seen["freizeitgluecklich2"] - (4 - 1.2)) < 0.3, seen  # 1.2 s before the end of a 4 s clip


def test_the_scripts_of_the_app_page_and_the_tester_are_sound_javascript(tmp_path):
    """The stage of the app was changed for the lead and the measuring; a slip there would stop the whole app."""
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    for name in ("PAGE", "TEMPO_PAGE"):
        path = tmp_path / (name + ".js")
        path.write_text("\n;\n".join(re.findall(r"<script>(.*?)</script>", getattr(memory_web, name), re.S)),
                        encoding="utf-8")
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert done.returncode == 0, name + ": " + done.stderr


def test_loops_come_in_rounds_every_one_once_before_one_comes_again(tmp_path):
    """Metin, 04:44: 1, 2, 3, then 2, 3, 2 and loop 1 only much later is wrong. The app, the page
    /ganzes and the mixer use the same function."""
    def fn(text: str) -> str:
        return re.search(r"function roundPick\(R,v,cur\)\{.*?return n;\}", text, re.S).group(0)
    app = open(memory_web.__file__, encoding="utf-8").read()
    picks = fn(app)
    assert fn(ganzes_page.PAGE) == picks and fn(naht_page.PAGE) == picks
    assert "roundPick(LROUND[b]||(LROUND[b]={}),v,cf)" in app and "TIGHT=true;stageShow(o[" not in app
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    path = tmp_path / "round.js"
    path.write_text(picks + """
const out={};for(const n of [2,3,5]){const v=[...Array(n)].map((x,i)=>'s'+(i+1)),R={},seq=[];let cur='';
 for(let i=0;i<n*400;i++){cur=roundPick(R,v,cur);seq.push(cur);}
 const count={},last={};let gap=0,twice=0;seq.forEach((x,i)=>{count[x]=(count[x]||0)+1;if(i&&seq[i-1]===x)twice++;if(last[x]!==undefined)gap=Math.max(gap,i-last[x]);last[x]=i;});
 out[n]={count:Object.values(count),gap,twice};}
// a loop is taken out while a round runs, and one alone just repeats
const R={},seq=[];let cur='';for(let i=0;i<30;i++){cur=roundPick(R,i<10?['a','b','c']:['a','b'],cur);seq.push(cur);}
out.left=seq.slice(11).includes('c');out.one=[roundPick({},['x'],'x'),roundPick({},['x'],'')];
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    for n in (2, 3, 5):
        assert got[str(n)]["count"] == [400] * n          # every loop exactly as often as the others
        assert got[str(n)]["twice"] == 0                  # never the same loop twice in a row
        assert got[str(n)]["gap"] <= 2 * n - 1            # at the latest it comes again at the end of the next round
    assert got["left"] is False and got["one"] == ["x", "x"]


def test_the_app_follows_a_stretch_with_its_own_tempo_picture_by_picture():
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "if(fol){const s0=b.src,rf=()=>{" in app and "requestAnimationFrame(rf)" in app
    memory_web._kurve_set("kurz/x", [[1.2345, 2.0004, 0.5], [0, 0.3, 9], ["a", 1, 1]])
    assert memory_web._kurve_read()["kurz/x"] == [[1.234, 2.0, 0.5]] or memory_web._kurve_read()["kurz/x"] == [[1.235, 2.0, 0.5]]
