"""The blend of a clip (2.186.0): how long it fades in when it takes over from the clip before it.

Metin's screen recording of 27 Nov 2026 (long work dress, the change of two loops): book and hand showed
double. Measured: these loops move from their first picture, and the stage blended every loop for 0.8 s;
in that time the old clip stands on its last picture while the new one is already under way. No begin
mark, end mark or lead heals that, only a shorter blend for such a clip."""
import asyncio
import json
import re
import shutil
import subprocess

import pytest

from app import ganzes_page, memory, memory_web, naht_page


def test_the_blend_of_a_clip_is_stored_checked_and_given_to_the_app(tmp_path, monkeypatch):
    assert memory_web._blende_read() == {}
    assert memory_web._blende_set("schwarz/gluecklich2", 0.1004)
    assert memory_web._blende_set("schwarz/gluecklich3", "0.05")
    assert memory_web._blende_read() == {"schwarz/gluecklich2": 0.1, "schwarz/gluecklich3": 0.05}
    for bad in (0, 0.04, 0.81, 3, -1, "x", None, True):
        assert not memory_web._blende_set("schwarz/gluecklich2", bad)
    assert memory_web._blende_set("schwarz/gluecklich3", 0.8)  # the default: no entry
    assert memory_web._blende_read() == {"schwarz/gluecklich2": 0.1}
    # the list of clips carries it as "b", only for clips that are there
    folder = tmp_path / "clips" / "schwarz"
    folder.mkdir(parents=True)
    (folder / "gluecklich2.mp4").write_bytes(b"x")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    assert memory_web._blende_set("schwarz/gibtesnicht", 0.2)
    assert memory_web.list_outfits()["schwarz"]["b"] == {"gluecklich2": 0.1}


def test_the_blend_is_part_of_the_reset_point():
    assert memory_web._blende_set("kurz/a", 0.1)
    ganzes_page.stand_save()
    assert memory_web._blende_set("kurz/a", 0.3) and memory_web._blende_set("kurz/b", 0.2)
    assert ganzes_page.stand_info()["geaendert"] == ["kurz/a", "kurz/b"]
    assert ganzes_page.stand_restore()["zurueck"] == ["kurz/a", "kurz/b"]
    assert memory_web._blende_read() == {"kurz/a": 0.1}
    # a reset point from before 2.186.0 has no blends: going back to it means none
    import os
    path = os.environ["LEYLA_STAND"]
    old = json.load(open(path))
    old.pop("blende")
    json.dump(old, open(path, "w"))
    assert ganzes_page.stand_restore()["ok"] and memory_web._blende_read() == {}


def test_the_stage_and_both_tool_pages_use_the_blend_of_the_clip_that_comes_in():
    app = open(memory_web.__file__, encoding="utf-8").read()
    # only for a tight hand over (loops, a talk clip, a touch in the green window), and only the clip that comes in
    assert "const FD=tight&&!soft&&FADE[lp]!==undefined?FADE[lp]:0;" in app
    assert "b.style.transitionDuration=FD?FD+'s':'';handMeasure(tight&&cont,a,b,PRE);b.play()" in app
    # the old clip always goes out in the 0.8 s of the CSS, whatever blend it came in with
    assert "if(tok===STOK){a.style.transitionDuration='';a.classList.remove('on');}" in app
    assert "FADE[k+'/'+c]=outs[k].b[c]" in app and "LEAD=L;FADE=FD;" in app
    assert memory_web.FADE_DEFAULT == naht_page.HAND_FADE == 0.8
    naht = re.search(r"<script>(.*)</script>", naht_page.PAGE, re.S).group(1)
    assert naht.count("b.v.style.transition='opacity '+fadeOf(a,b)+'s'") == 2 and "FADE_MIN=0.05" in naht
    ganz = re.search(r"<script>(.*)</script>", ganzes_page.PAGE, re.S).group(1)
    assert "if(opt.cont&&!soft&&FADE[pth]!==undefined)b.style.transition='opacity '+FADE[pth]+'s';" in ganz
    assert "\\" not in ganzes_page.PAGE and "\\" not in naht_page.PAGE


async def _post(port: int, path: str, body: dict) -> dict:
    raw = json.dumps(body).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
    await writer.drain()
    out = (await reader.read()).decode()
    writer.close()
    return json.loads(out.split("\r\n\r\n", 1)[1])


async def test_the_blend_is_set_and_read_over_http(tmp_path):
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert (await _post(port, "/api/blende", {"name": "schwarz/gluecklich2", "fade": 0.1}))["ok"]
        assert not (await _post(port, "/api/blende", {"name": "ohneordner", "fade": 0.1}))["ok"]
        assert not (await _post(port, "/api/blende", {"name": "schwarz/gluecklich2", "fade": 2}))["ok"]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /api/blende HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        got = json.loads((await reader.read()).decode().split("\r\n\r\n", 1)[1])
        writer.close()
    finally:
        server.close()
    assert got == {"schwarz/gluecklich2": 0.1}


def _h264(path, seconds: int, hue: int) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=240x360:rate=24:duration={seconds}", "-vf", f"hue=h={hue}",
                    "-c:v", "libx264", "-preset", "veryfast", "-b:v", "400k", "-g", "24",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)


async def test_in_a_browser_the_stage_blends_a_loop_as_long_as_its_blend_says(tmp_path, monkeypatch):
    """Measured on the stage of the app, picture by picture: how long the clip that comes in needs from
    nearly invisible to nearly solid, and how much of the stage the two videos cover in that time."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, name in enumerate(("gluecklich4", "gluecklich5")):
            _h264(folder / (name + ".mp4"), 4, i * 90)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    assert memory_web._blende_set("kurz/gluecklich5", 0.1)
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    hands = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(1.0)
            await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;
              const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));
              window.H=[];const vs=[document.getElementById('svid'),document.getElementById('svid2')];let sv=SV,cur=null,first=true;
              const samp=()=>{const now=performance.now();
               if(SV!==sv){sv=SV;if(first)first=false;cur={n:vs[SV].dataset.pth||'',t0:now,a:0,b:0,min:1};window.H.push(cur);}
               if(cur&&now-cur.t0<2500){const o=parseFloat(getComputedStyle(vs[SV]).opacity);if(!cur.a&&o>0.02)cur.a=now;if(!cur.b&&o>0.95)cur.b=now;
                let gap=1;for(const v of vs)gap*=1-parseFloat(getComputedStyle(v).opacity)*(v.readyState>=2?1:0);cur.min=Math.min(cur.min,1-gap);}
               requestAnimationFrame(samp);};samp();}""")
            for _ in range(260):
                await asyncio.sleep(0.1)
                hands = await page.evaluate("()=>window.H.filter(h=>h.b&&performance.now()-h.t0>2500).map(h=>({n:h.n,ms:Math.round(h.b-h.a),min:h.min}))")
                if len(hands) >= 2 and {"kurz/gluecklich4", "kurz/gluecklich5"} <= {h["n"] for h in hands[1:]}:
                    break
            await browser.close()
    finally:
        server.close()
    later = hands[1:]  # the very first clip comes onto an empty stage
    short = [h for h in later if h["n"] == "kurz/gluecklich5"]
    soft = [h for h in later if h["n"] == "kurz/gluecklich4"]
    assert short and soft, hands
    assert all(h["ms"] < 250 for h in short), hands        # 0.1 s: nearly a cut
    assert all(h["ms"] > 400 for h in soft), hands         # the 0.8 s of the CSS (0.95 is reached after about 0.6 s)
    assert all(h["min"] > 0.98 for h in short), hands      # the stage stays covered: the old clip goes only after the new one is solid
    assert all(h["min"] > 0.85 for h in soft), hands       # the old clip, which came in short, still goes out slowly


async def test_in_a_browser_the_outfit_page_sets_hard_or_soft_shows_it_and_stores_it(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, name in enumerate(("freizeitgluecklich", "freizeitgluecklich2")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=96x144:rate=24:duration=4",
                            "-c:v", "libvpx-vp9", "-b:v", "60k", "-g", "12", "-an", "-f", "mp4",
                            str(folder / (name + ".mp4"))], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors, seen = [], {}
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1200, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/ganzes?clip=kurz/freizeitgluecklich2")
            await page.wait_for_function("()=>CUR==='freizeitgluecklich2'", timeout=9000)
            await page.evaluate("()=>halt()")
            text = lambda i: page.evaluate("(i)=>document.getElementById(i).textContent", i)
            assert (await text("blab"), await text("llab"), await text("binfo")) == ("0.80", "0.25", "So ist es gemerkt.")
            await page.click("#bh")                                   # hard: blend and lead as measured
            assert (await text("blab"), await text("llab"), await text("binfo")) == ("0.10", "0.10", "Noch nicht gemerkt.")
            await page.click("#bp")
            await page.click("#lm")
            assert (await text("blab"), await text("llab")) == ("0.15", "0.05")
            assert memory_web._blende_read() == {} and memory_web._vorlauf_read() == {}   # nothing stored yet
            await page.click("#bh")
            # look at it: the loop before plays its end, then this clip takes over with the short blend
            await page.evaluate("""()=>{window.SEEN=[];window.TR={};const t=()=>{if(CUR&&window.SEEN[window.SEEN.length-1]!==CUR){window.SEEN.push(CUR);
              window.TR[CUR]=[vis().style.transition,vis().currentTime];}requestAnimationFrame(t);};t();}""")
            await page.click("#bseh")
            await page.wait_for_function("()=>window.SEEN.includes('freizeitgluecklich')&&window.SEEN[window.SEEN.length-1]==='freizeitgluecklich2'", timeout=12000)
            seen = await page.evaluate("()=>({s:window.SEEN,t:window.TR})")
            await page.evaluate("()=>halt()")
            await page.click("#bsave")
            await page.wait_for_function("()=>document.getElementById('binfo').textContent==='So ist es gemerkt.'", timeout=4000)
            assert memory_web._blende_read() == {"kurz/freizeitgluecklich2": 0.1}
            assert memory_web._vorlauf_read() == {"kurz/freizeitgluecklich2": 0.1}
            # 2.190.0: the end of this clip does not fit the base pose: one tick, stored at once
            assert not await page.is_checked("#bweich")
            await page.check("#bweich")
            await page.wait_for_function("()=>!!SOFT['kurz/freizeitgluecklich2']", timeout=4000)
            assert memory_web._ende_read() == {"kurz/freizeitgluecklich2": True}
            await page.uncheck("#bweich")
            await page.wait_for_function("()=>!SOFT['kurz/freizeitgluecklich2']", timeout=4000)
            assert memory_web._ende_read() == {}
            await page.click("#bw")                                   # soft again: the defaults, no entries
            await page.click("#bsave")
            await page.wait_for_function("()=>document.getElementById('binfo').textContent==='So ist es gemerkt.'", timeout=4000)
            assert memory_web._blende_read() == {} and memory_web._vorlauf_read() == {}
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
    assert seen["t"]["freizeitgluecklich"][1] > 1.5, seen             # the clip before: only its last two seconds
    assert "0.1s" in seen["t"]["freizeitgluecklich2"][0], seen        # and this one came in with its blend


async def test_in_a_browser_the_naht_page_has_the_blend_as_one_more_slider(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for name in ("freizeitgluecklich", "freizeitgluecklich2"):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=96x144:rate=24:duration=4",
                            "-c:v", "libvpx-vp9", "-b:v", "60k", "-g", "12", "-an", "-f", "mp4",
                            str(folder / (name + ".mp4"))], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write VP9")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    assert memory_web._blende_set("kurz/freizeitgluecklich2", 0.2)
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    G1, G2 = "freizeitgluecklich", "freizeitgluecklich2"
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1000, "height": 800})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/naht?a=kurz/{G1}&b=kurz/{G2}")
            await page.wait_for_function("()=>LAY.length===2&&LAY.every(L=>L.d)", timeout=9000)
            fd = lambda: page.evaluate("()=>Object.fromEntries(LAY.map(L=>[L.n,L.fd]))")
            assert await fd() == {G1: 0.8, G2: 0.2}
            key = lambda name, k: f".lay[data-n='{name}'] [data-k='{k}']"
            await page.click(key(G1, "mb"))                           # the slider of this layer is now its blend
            assert await page.evaluate(f"()=>{{const p=document.querySelector(\"{key(G1, 'pos')}\");return [p.min,p.max,p.value];}}") == ["0.05", "0.8", "0.8"]
            for _ in range(3):
                await page.click(key(G1, "m1"))
            assert (await fd())[G1] == 0.77 and "Blende" in await page.inner_text(key(G1, "lab"))
            await page.evaluate("()=>setVal(LAY[0],'b',0)")
            assert (await fd())[G1] == 0.05                           # never below one picture
            await page.evaluate("()=>setVal(LAY[0],'b',0.1)")
            await page.click(key(G2, "b0"))                           # back to the normal blend
            assert await fd() == {G1: 0.1, G2: 0.8}
            assert await page.inner_text("#sinfo") == "Noch nicht gemerkt."
            await page.click("#save")
            await page.wait_for_function("()=>document.getElementById('sinfo').textContent.startsWith('Gemerkt')", timeout=4000)
            assert memory_web._blende_read() == {"kurz/" + G1: 0.1}
            await browser.close()
    finally:
        server.close()
    assert not errors, errors


def test_a_clip_that_ends_off_the_pose_is_stored_and_listed(tmp_path, monkeypatch):
    """2.190.0. Measured 27 Nov 2026: a loop set hard also comes in hard after a clip whose last picture is another
    pose (a dance: 9 away where 1 is a fit). Such a clip is marked; after it the stage blends softly."""
    assert memory_web._ende_read() == {}
    assert memory_web._ende_set("kurz/freizeittanz3", True) and memory_web._ende_set("kurz/freizeitpo8", True)
    for bad in (1, "ja", None, 0.5):
        assert not memory_web._ende_set("kurz/freizeitpo8", bad)
    assert memory_web._ende_set("kurz/freizeitpo8", False)
    assert memory_web._ende_read() == {"kurz/freizeittanz3": True}
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    (folder / "freizeittanz3.mp4").write_bytes(b"x")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    assert memory_web._ende_set("kurz/gibtesnicht", True)
    assert memory_web.list_outfits()["kurz"]["w"] == ["freizeittanz3"]
    # part of the reset point
    ganzes_page.stand_save()
    assert memory_web._ende_set("kurz/freizeittanz3", False)
    assert "kurz/freizeittanz3" in ganzes_page.stand_info()["geaendert"]
    ganzes_page.stand_restore()
    assert memory_web._ende_read() == {"kurz/freizeittanz3": True, "kurz/gibtesnicht": True}
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "const soft=!!SOFT[document.getElementById(SV?'svid2':'svid').dataset.pth||''];" in app
    assert "PRE=tight&&!soft&&LEAD[lp]!==undefined?LEAD[lp]:PRE0;" in app and "LEAD=L;FADE=FD;SOFT=SO;" in app


async def test_the_soft_end_is_set_over_http(tmp_path):
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert (await _post(port, "/api/ende", {"name": "kurz/freizeittanz3", "weich": True}))["ok"]
        assert not (await _post(port, "/api/ende", {"name": "kurz/freizeittanz3", "weich": "ja"}))["ok"]
        assert not (await _post(port, "/api/ende", {"name": "ohneordner", "weich": True}))["ok"]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /api/ende HTTP/1.1\r\nHost: x\r\n\r\n")
        await writer.drain()
        got = json.loads((await reader.read()).decode().split("\r\n\r\n", 1)[1])
        writer.close()
    finally:
        server.close()
    assert got == ["kurz/freizeittanz3"]


async def test_in_a_browser_a_hard_loop_blends_softly_after_a_clip_that_ends_off_the_pose(tmp_path, monkeypatch):
    """Both loops are set hard (blend 0.1 s). One of them is marked as ending off the pose: the loop after it
    comes in with the soft 0.8 s, the loop after the other one with its 0.1 s."""
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, name in enumerate(("gluecklich4", "gluecklich5")):
            _h264(folder / (name + ".mp4"), 4, i * 90)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    for name in ("kurz/gluecklich4", "kurz/gluecklich5"):
        assert memory_web._blende_set(name, 0.1)
    assert memory_web._ende_set("kurz/gluecklich4", True)
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    hands = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(1.0)
            await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;
              const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));
              window.H=[];const vs=[document.getElementById('svid'),document.getElementById('svid2')];let sv=SV,cur=null;
              const samp=()=>{const now=performance.now();
               if(SV!==sv){sv=SV;cur={n:vs[SV].dataset.pth||'',t0:now,a:0,b:0};window.H.push(cur);}
               if(cur&&now-cur.t0<2500){const o=parseFloat(getComputedStyle(vs[SV]).opacity);if(!cur.a&&o>0.02)cur.a=now;if(!cur.b&&o>0.95)cur.b=now;}
               requestAnimationFrame(samp);};samp();}""")
            for _ in range(260):
                await asyncio.sleep(0.1)
                hands = await page.evaluate("()=>window.H.filter(h=>h.b&&performance.now()-h.t0>2500).map(h=>({n:h.n,ms:Math.round(h.b-h.a)}))")
                if len(hands) >= 2 and {"kurz/gluecklich4", "kurz/gluecklich5"} <= {h["n"] for h in hands[1:]}:
                    break
            await browser.close()
    finally:
        server.close()
    later = hands[1:]
    after_soft_end = [h for h in later if h["n"] == "kurz/gluecklich5"]   # comes after gluecklich4, which ends off the pose
    after_good_end = [h for h in later if h["n"] == "kurz/gluecklich4"]
    assert after_soft_end and after_good_end, hands
    assert all(h["ms"] > 400 for h in after_soft_end), hands             # soft, although the loop itself is set hard
    assert all(h["ms"] < 250 for h in after_good_end), hands
