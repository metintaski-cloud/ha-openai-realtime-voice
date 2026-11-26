"""She must never stand still as a picture because a mood has no clip, and never answer Metin in English."""
import json
import re
import shutil
import subprocess

import pytest

from app import chat, memory_web


def test_a_hurt_leyla_in_a_work_dress_plays_the_happy_loop_instead_of_standing_still(tmp_path):
    """25 Nov 2026: she was hurt, the work dresses have no sad clips any more, and the stage showed only her picture."""
    node = shutil.which("node")
    if not node:
        pytest.skip("no node here")
    app = open(memory_web.__file__, encoding="utf-8").read()
    picks = re.search(r"function clipVars\(b\)\{.*?\n(?=/\* light copies)", app, re.S).group(0)
    assert "function clipFor(st){" in picks
    path = tmp_path / "pick.js"
    path.write_text("""
let STM=null,CLIPS=[],NIGHT=[];const CHANGE=['umziehen'];
""" + picks + """
const work=['begruessung','brust','gesicht','gluecklich4','gluecklich5','gluecklich6','gluecklichextra','po','umziehen'];
const out={};
const run=(key,clips,night,st)=>{CLIPS=clips;NIGHT=night;STM=st;out[key]=clipFor(st);};
run('hurt_work',work,[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_hard_work',work,[],{low:true,level:'schwer',mood:'sauer',outfit:'arbeit'});
run('jealous_work',work,[],{low:true,level:'leicht',mood:'eifersuechtig',outfit:'arbeit'});
run('good_work',work,[],{low:false,mood:'verliebt',outfit:'arbeit'});
run('hurt_work_with_sad',work.concat(['traurigleicht','traurigleicht2']),[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
run('hurt_leisure',['freizeitgluecklich','freizeitgluecklich2'],[],{low:true,level:'leicht',mood:'traurig',outfit:'freizeit'});
run('hurt_leisure_jealous',['freizeitgluecklich','freizeiteifersuechtig'],[],{low:true,level:'mittel',mood:'traurig',outfit:'freizeit'});
run('hurt_night',[],['gluecklich','gluecklich2'],{low:true,level:'leicht',mood:'einsam',outfit:'nacht'});
run('nothing',['begruessung'],[],{low:true,level:'leicht',mood:'traurig',outfit:'arbeit'});
console.log(JSON.stringify(out));
""", encoding="utf-8")
    done = subprocess.run([node, str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "hurt_work": "gluecklich", "hurt_hard_work": "gluecklich", "jealous_work": "gluecklich",
        "good_work": "gluecklich", "hurt_work_with_sad": "traurigleicht",   # a sad clip still wins when there is one
        "hurt_leisure": "gluecklich", "hurt_leisure_jealous": "eifersuechtig", "hurt_night": "gluecklich",
        "nothing": None}


def test_she_never_answers_metin_in_english():
    """He cannot read English; on 25 Nov 2026 the speech recogniser wrote "Hello." and she answered in English."""
    for rules in (chat.CHAT_STYLE, chat.CHAT_KOPF):
        assert "versteht kein Englisch. Antworte ihm nie auf Englisch." in rules
        assert "antworte auf Deutsch" in rules


def test_where_a_request_came_from():
    assert memory_web.net_kind("100.101.5.9") == "tailscale" and memory_web.net_kind("100.64.0.1") == "tailscale"
    assert memory_web.net_kind("100.63.0.1") == "sonst" and memory_web.net_kind("100.128.0.1") == "sonst"
    assert memory_web.net_kind("192.168.2.57", "192.168.2.240") == "wlan"
    assert memory_web.net_kind("192.168.2.240", "192.168.2.240") == "host" and memory_web.net_kind("127.0.0.1") == "host"
    assert memory_web.net_kind("") == "sonst"


async def test_the_page_reports_how_fast_clips_arrive(tmp_path):
    """Numbers only: kbit/s of a short probe, the wait for the first byte, how often the picture waited.
    2.171.1: the probe is small, cut off after 3 s and never runs while the picture itself waits; a line that
    brought nothing is reported as 0."""
    import asyncio

    from app import memory
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "async function netProbe()" in app and "headers:{Range:'bytes=0-299999'}" in app and "NETSTALL++" in app
    assert "setTimeout(()=>ac.abort(),3000)" in app and "signal:ac.signal" in app and "Date.now()-NETAT<60000" in app
    assert "if(!v.paused&&!v.ended&&v.readyState<3){post('/api/netstats',{kbps:0,ttfb:0,stalls:st,light,wait:1})" in app
    memory_web.NET.clear()
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]

    async def call(method: str, body: dict | None = None) -> str:
        raw = json.dumps(body).encode() if body is not None else b""
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"{method} /api/netstats HTTP/1.1\r\nHost: x\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
        await writer.drain()
        out = (await reader.read()).decode()
        writer.close()
        return out.split("\r\n\r\n", 1)[1]
    try:
        for kbps, stalls in ((9000, 0), (2500, 2), (7000, 0)):
            assert json.loads(await call("POST", {"kbps": kbps, "ttfb": 120, "stalls": stalls, "light": 1, "code": "x"}))["ok"]
        assert not json.loads(await call("POST", {"kbps": "schnell", "text": "nothing personal is kept"}))["ok"]
        assert not json.loads(await call("POST", {"kbps": -5}))["ok"]
        assert json.loads(await call("POST", {"kbps": 0, "ttfb": 0, "stalls": 3, "light": 1, "wait": 1}))["ok"]
        got = json.loads(await call("GET"))
    finally:
        server.close()
        memory_web.NET.clear()
    assert got["n"] == 4 and got["host"] == {"n": 4, "kbps_median": 7000, "kbps_min": 0, "kbps_p10": 0,
                                             "kbps_max": 9000, "ttfb_median": 120, "stalls": 5, "wartend": 1}
    assert set(got["letzte"][0]) == {"at", "weg", "kbps", "ttfb", "stalls", "light", "wait"}


async def test_a_touch_right_after_a_loop_change_never_blanks_the_picture(tmp_path, monkeypatch):
    """2.172.1 (Metin, 25 Nov 2026: "wenn ich auf berühren klicke, kommt so ein Flackern, nicht immer"): for 0.8 s
    after a swap the old video is still the picture he sees. A touch in that time loaded her reaction into it and
    blanked it; 50 ms after a loop change 93 % of the picture was gone for a moment. Measured here picture by
    picture: how much of the stage the two videos cover together."""
    import asyncio
    import os

    from app import memory
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, (name, dur) in enumerate((("gluecklich4", 4), ("gluecklich5", 4), ("gluecklich6", 4), ("brust", 3))):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=size=240x360:rate=24:duration={dur}", "-vf", f"hue=h={i * 60}",
                            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "400k", "-g", "24",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(folder / (name + ".mp4"))], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "const wt=FADEEND-performance.now();if(wt>0)setTimeout(start,wt);else start();}" in app
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    got = {}
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            for delay in (50, 150):
                page = await browser.new_page(viewport={"width": 400, "height": 820})
                await page.goto(f"http://127.0.0.1:{port}/")
                await asyncio.sleep(1.0)
                await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;
                  const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
                  document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""")
                await asyncio.sleep(1.5)
                got[delay] = await page.evaluate("""async(delay)=>{
                  const vs=[document.getElementById('svid'),document.getElementById('svid2')],sv0=SV;
                  await new Promise(r=>{const t=()=>{if(SV!==sv0)r();else requestAnimationFrame(t);};t();});
                  await new Promise(r=>setTimeout(r,delay));
                  const st=document.getElementById('stage'),R=st.getBoundingClientRect(),ar=1176/1764;let w=R.width,h=w/ar;if(h<R.height){h=R.height;w=h*ar;}
                  let min=1,run=true,touch='';
                  const samp=()=>{if(!run)return;let gap=1;for(const v of vs){gap*=1-parseFloat(getComputedStyle(v).opacity)*(v.readyState>=2?1:0);
                    if(v.classList.contains('on')&&(v.getAttribute('src')||'').includes('/brust.mp4'))touch='shown';}
                   min=Math.min(min,1-gap);requestAnimationFrame(samp);};samp();
                  /* since 2.174.1 a touch is only taken in the green window before a hand over, so the moment right after a
                     swap is reached by a wished scene only: the clip is shown directly, as stageScene does */
                  stageShow('brust',false,()=>stageLoop(clipFor(STM)),true);
                  await new Promise(r=>setTimeout(r,2600));run=false;return {min,touch};}""", delay)
                await page.close()
            await browser.close()
    finally:
        server.close()
    for delay, r in got.items():
        assert r["min"] > 0.85, (delay, r)          # the natural dip of a tight hand over is about 0.9
        assert r["touch"] == "shown", (delay, r)    # and her reaction still comes


async def test_on_a_wide_screen_she_is_shown_whole_and_the_phone_stays_as_it_is(tmp_path, monkeypatch):
    """2.172.2 (Metin, 25 Nov 2026, photo of his PC monitor: only her middle, far too big): on a screen wider than
    high the stage has the shape of the clips and stands in the middle; upright it fills the screen as before.
    The touch zones go by the stage box, so the chest is still the chest."""
    import asyncio

    from app import memory
    playwright = pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    got = {}
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                pytest.skip("no browser here")
            for key, (w, h) in {"pc": (1920, 1080), "phone": (400, 820)}.items():
                page = await browser.new_page(viewport={"width": w, "height": h})
                await page.goto(f"http://127.0.0.1:{port}/")
                await asyncio.sleep(0.6)
                got[key] = await page.evaluate("""()=>{const sp=document.getElementById('splash');if(sp)sp.remove();
                  document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');
                  const st=document.getElementById('stage');st.style.display='block';const r=st.getBoundingClientRect();
                  const at=(fx,fy)=>zoneAt({clientX:r.left+fx*r.width,clientY:r.top+fy*r.height});
                  return {x:Math.round(r.left),w:Math.round(r.width),h:Math.round(r.height),
                          fit:getComputedStyle(st.querySelector('video')).objectFit,
                          zones:[at(.5,.09),at(.5,.23),at(.5,.36),at(.5,.5),at(.05,.23)]};}""")
                await page.close()
            await browser.close()
    finally:
        server.close()
    pc, phone = got["pc"], got["phone"]
    assert (pc["w"], pc["h"], pc["x"]) == (720, 1080, 600), pc           # 2:3, full height, in the middle
    assert (phone["w"], phone["h"], phone["x"]) == (400, 820, 0), phone  # as before
    for g in (pc, phone):
        assert g["fit"] == "cover" and g["zones"][:4] == ["gesicht", "brust", "bauch", "po"], g
    assert pc["zones"][4] is None
