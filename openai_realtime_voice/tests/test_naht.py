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
    assert "const PRE=tight?0.25:0.8,OFF=tight?300:850" in app
    assert app.count("TIGHT=true;") == 2 and "function stageLoop" in app
    assert "#stage video{opacity:0;transition:opacity .8s}" in app
    assert (naht_page.HAND_PRE, naht_page.HAND_OFF, naht_page.HAND_FADE) == (0.25, 300, 0.8)
    assert "LOOP_PRE=0.25,LOOP_OFF=300" in re.search(r"<script>(.*)</script>", ganzes_page.PAGE, re.S).group(1)


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
    assert page.startswith("HTTP/1.1 200") and "Naht: Ende und Anfang" in page and 'href="/ganzes"' in page
    assert 'href="/naht"' in whole


def _clip(path, seconds: int) -> None:
    """A tiny clip a browser without H.264 can play (VP9 and Opus in an MP4 file)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=96x144:rate=24:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:v", "libvpx-vp9", "-b:v", "60k",
                    "-g", "12", "-c:a", "libopus", "-b:a", "24k", "-f", "mp4", str(path)], check=True)


async def test_in_a_browser_the_two_pictures_follow_the_marks_and_one_button_stores_both(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name, seconds in (("freizeitgluecklich", 4), ("freizeitgluecklich2", 6), ("freizeitpo8", 3),
                              ("gluecklich", 3)):
            _clip(folder / (name + ".mp4"), seconds)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    cut = tmp_path / "schnitt.json"
    monkeypatch.setenv("LEYLA_SCHNITT", str(cut))
    monkeypatch.setenv("LEYLA_TEMPO", str(tmp_path / "tempo.json"))
    cut.write_text(json.dumps({"kurz/freizeitgluecklich": [0.5, 3.5], "kurz/freizeitgluecklich2": [0.2, 5.0]}))
    (tmp_path / "tempo.json").write_text(json.dumps([{"name": "kurz/freizeitgluecklich2", "rate": 2}]))
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
            page = await browser.new_page(viewport={"width": 400, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/naht?a=kurz/freizeitgluecklich&b=kurz/freizeitgluecklich2")

            async def state() -> dict:
                return await page.evaluate(
                    "()=>({a:A,b:B,ta:va.currentTime,tb:vb.currentTime,ea:Number(ea.value),bb:Number(bb.value),"
                    "op:getComputedStyle(vb).opacity,blend:getComputedStyle(vb).mixBlendMode,"
                    "pa:va.paused,pb:vb.paused,look:look.selectedOptions[0].textContent,"
                    "names:[...sa.options].map(o=>o.value),busy:document.body.classList.contains('busy'),"
                    "save:save.classList.contains('on')})")

            async def settled() -> dict:
                for _ in range(60):
                    await asyncio.sleep(0.1)
                    st = await state()
                    if not st["busy"]:
                        await asyncio.sleep(0.15)
                        return await state()
                return await state()
            st = await settled()
            assert st["look"] == "Kurzes Freizeitkleid" and (st["a"], st["b"]) == ("freizeitgluecklich", "freizeitgluecklich2")
            assert st["names"][:2] == ["freizeitgluecklich", "freizeitgluecklich2"]  # the loops first
            assert "gluecklich" not in st["names"]                                   # the work dress is another outfit
            assert (st["ea"], st["bb"]) == (3.5, 0.2)                                # the stored marks
            # 0.25 s into the hand over the old clip stands on its end mark, the new one has run 0.25 s at tempo 2
            assert abs(st["ta"] - 3.5) < 0.05 and abs(st["tb"] - 0.7) < 0.05
            assert st["pa"] and st["pb"] and st["op"] == "0.5" and not st["save"]
            # earlier in the hand over the old clip has not reached its end yet
            await page.evaluate("()=>{const t=document.getElementById('tau');t.value='0';t.oninput();}")
            st = await settled()
            assert abs(st["ta"] - 3.25) < 0.05 and abs(st["tb"] - 0.2) < 0.05
            await page.evaluate("()=>{const t=document.getElementById('tau');t.value='0.25';t.oninput();}")
            # one picture back at the end, one picture on at the begin
            await page.click("#am")
            await page.click("#bp")
            st = await settled()
            assert (st["ea"], st["bb"]) == (3.458, 0.242) and st["save"]
            assert abs(st["ta"] - 3.458) < 0.05 and abs(st["tb"] - 0.742) < 0.05
            # a thousandth of a second on and back (Metin, 01:43)
            await page.click("#ap3")
            assert (await state())["ea"] == 3.459
            await page.click("#am3")
            await page.click("#bm3")
            await page.click("#bp3")
            st = await settled()
            assert (st["ea"], st["bb"]) == (3.458, 0.242)
            # the difference picture and back to see through
            await page.click("#diff")
            st = await state()
            assert st["blend"] == "difference" and st["op"] == "1"
            await page.click("#o0")
            st = await state()
            assert st["blend"] == "normal" and st["op"] == "0"
            await page.click("#o50")
            # the hand over in real time ends by itself and comes back to the stencil
            await page.click("#play")
            await asyncio.sleep(0.6)
            assert await page.evaluate("()=>PLAYING")
            for _ in range(80):
                await asyncio.sleep(0.1)
                if not await page.evaluate("()=>PLAYING"):
                    break
            st = await settled()
            assert not await page.evaluate("()=>PLAYING") and st["pa"] and st["pb"] and st["op"] == "0.5"
            assert abs(st["ta"] - 3.458) < 0.05
            # one button stores the end of the one and the begin of the other, their other marks stay
            await page.click("#save")
            await asyncio.sleep(0.4)
            stored = json.loads(cut.read_text())
            assert stored == {"kurz/freizeitgluecklich": [0.5, 3.458], "kurz/freizeitgluecklich2": [0.242, 5.0]}
            st = await state()
            assert not st["save"]
            # a third stencil on top (Metin, 01:45): a touch clip with its end, moved and stored the same way
            third = await page.evaluate("()=>[...sc.options].map(o=>[o.value,o.textContent])")
            assert third[0] == ["", "keine"] and third[1] == ["freizeitpo8", "Po (freizeitpo8)"]
            assert await page.evaluate("()=>getComputedStyle(vc).opacity") == "0"
            await page.select_option("#sc", "freizeitpo8")
            await page.click("#cend")
            st = await settled()
            c = await page.evaluate("()=>({t:vc.currentTime,v:Number(cc.value),op:getComputedStyle(vc).opacity,p:vc.paused})")
            assert abs(c["v"] - 3.0) < 0.05 and abs(c["t"] - c["v"]) < 0.05 and c["op"] == "0.5" and c["p"]
            await page.click("#cm1")
            await page.click("#cm1")
            await page.click("#cm1")
            await page.click("#save")
            await asyncio.sleep(0.4)
            stored = json.loads(cut.read_text())
            assert stored["kurz/freizeitpo8"][0] == 0 and abs(stored["kurz/freizeitpo8"][1] - (c["v"] - 0.03)) < 0.0011
            assert stored["kurz/freizeitgluecklich"] == [0.5, 3.458]  # the others stay
            await page.click("#cbeg")
            st = await settled()
            assert await page.evaluate("()=>Number(cc.value)") == 0
            await page.click("#cp1")
            await page.click("#save")
            await asyncio.sleep(0.4)
            assert json.loads(cut.read_text())["kurz/freizeitpo8"][0] == 0.01
            await page.select_option("#sc", "")
            assert await page.evaluate("()=>getComputedStyle(vc).opacity") == "0"
            # the same clip on both sides: one entry with both marks
            await page.select_option("#sb", "freizeitgluecklich")
            st = await settled()
            assert st["bb"] == 0.5
            await page.click("#bp1")
            await page.click("#save")
            await asyncio.sleep(0.4)
            assert json.loads(cut.read_text())["kurz/freizeitgluecklich"] == [0.51, 3.458]
            # the end at the real end and the begin at zero mean: no mark
            await page.evaluate("()=>{ea.value=ea.max;bb.value='0';ea.oninput();}")
            await page.click("#save")
            await asyncio.sleep(0.4)
            assert "kurz/freizeitgluecklich" not in json.loads(cut.read_text())
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
