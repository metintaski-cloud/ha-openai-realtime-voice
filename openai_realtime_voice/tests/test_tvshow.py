"""2.195.0, Leyla herself on the living room TV.

Metin, 28 Nov 2026, 01:19: "quasi möchte ich Leila im Wohnzimmer sagen, hey Leila, zeig dich im Fernseher oder zeig
dich oder komm mal her, und dass sie dann quasi automatisch im Fernseher erscheint." And for her night outfit, 01:21:
"im Fernseher soll nicht gefragt werden, Passwort eingeben oder so ... Die Sperre soll automatisch drin sein. Nur die
Leila kann das freigeben, indem ich Passwort sage." Children are in that room.

So: the page of the TV (?tv=1) never asks for the code word and never keeps one, its state route never gives the
night outfit by itself, and the release exists only as a function of a talk in which the code word was said.
"""
import asyncio
import json
import shutil
import subprocess

import pytest

from app import memory, memory_web, tvshow


class FakeTv:
    available = True
    tv_remote = "remote.android_tv"

    def __init__(self, front="de.exaring.waipu", state="on", opens=True):
        self.front, self.state, self.opens, self.calls = front, state, opens, []

    async def _state(self):
        return self.state

    async def _power(self, on):
        self.calls.append(("power", on))
        self.state = "on"
        return {"done": "Fernseher eingeschaltet"}

    async def _activity(self):
        return self.front

    async def _service(self, domain, service, data):
        self.calls.append((domain, service, dict(data)))
        act = data.get("activity", "")
        if "tv=1" in act and self.opens:
            self.front = tvshow.BROWSER
        elif act.startswith("waipu"):
            self.front = "de.exaring.waipu"

    async def _wait_activity(self, test, limit_s):
        return test(self.front.lower())

    async def _tv_key(self, command, *more):
        self.calls.append(("key", command))
        self.front = "com.google.android.tvlauncher"


class FakeMood:
    def __init__(self, outfit="nacht"):
        self.outfit, self.worn = outfit, []

    def status(self):
        return {"mood": "verliebt", "low": False, "label": "verliebt", "cheer": 0, "level": "gut", "silent": False,
                "rose": "ready", "touch_ok": True, "outfit": self.outfit, "game": {"hits": ["po"]}}

    def wear(self, outfit):
        self.worn.append(outfit)
        self.outfit = outfit
        return True


def test_the_tv_never_gets_the_night_outfit_by_itself():
    show = tvshow.TvShow(FakeTv(), FakeMood("nacht"), url="")
    st = show.page_state()
    assert st["outfit"] == "freizeit" and st["mood"] == "verliebt"
    assert set(st) == set(tvshow.PAGE_KEYS)                   # nothing of the rose, the game or the touch
    show.night_until = 1e12
    assert show.page_state()["outfit"] == "nacht"             # released: as she is
    assert show.page_state(now=2e12)["outfit"] == "freizeit"  # the release runs out by itself
    assert tvshow.TvShow(FakeTv(), FakeMood("arbeit"), url="").page_state()["outfit"] == "arbeit"
    assert tvshow.TvShow(FakeTv(), None, url="").page_state() == {}
    assert show.url == tvshow.DEFAULT_URL and "tv=1" in show.url


def test_only_a_talk_after_the_code_word_may_release_it():
    refused = tvshow.night_gate({"action": "nacht_frei"}, {"unlocked": False, "metin_known": True})
    assert "error" in refused                                 # his name alone is not the code word
    for word in ("Nachtkleid", "Codewort", "Sperre"):         # what she is told must not put the words in her mouth
        assert word not in refused["error"]
    assert tvshow.night_gate({"action": "nacht_frei"}, {"unlocked": True}) is None
    for action in ("zeigen", "weg", "nacht_zu"):              # appearing, leaving and locking are open to the family
        assert tvshow.night_gate({"action": action}, {}) is None
    tool = tvshow.SHOW_TOOL["parameters"]
    assert tool["required"] == list(tool["properties"]) and tool["additionalProperties"] is False


async def test_she_appears_and_every_appearance_starts_locked():
    tv = FakeTv(state="off")
    show = tvshow.TvShow(tv, FakeMood("nacht"), url="")
    show.night_until = 1e12                                   # left over from before
    out = await show.run({"action": "zeigen"})
    assert "done" in out and tv.front == tvshow.BROWSER
    assert tv.calls[0] == ("power", True)                     # the TV was off
    assert tv.calls[1] == ("remote", "turn_on", {"entity_id": "remote.android_tv", "activity": tvshow.DEFAULT_URL})
    assert not show.night_open() and show.page_state()["outfit"] == "freizeit"
    blind = FakeTv(opens=False)                               # the TV does not open the page: never "done"
    out = await tvshow.TvShow(blind, FakeMood(), url="").run({"action": "zeigen"})
    assert "error" in out and len(blind.calls) == tvshow.SHOW_TRIES


async def test_she_leaves_and_the_programme_comes_back():
    tv = FakeTv()
    show = tvshow.TvShow(tv, FakeMood(), url="")
    await show.run({"action": "zeigen"})
    show.night_until = 1e12
    out = await show.run({"action": "weg"})
    assert "done" in out and tv.front == "de.exaring.waipu" and not show.night_open()
    assert tv.calls[-1][2]["activity"] == "waipu://tv"        # the way that starts the app while it runs behind
    assert "war nicht" in (await show.run({"action": "weg"}))["done"]


async def test_the_release_shows_her_night_outfit_and_ends_when_her_page_is_gone(monkeypatch):
    monkeypatch.setattr(tvshow, "WATCH_S", 0.02)
    tv, mood = FakeTv(), FakeMood("arbeit")
    show = tvshow.TvShow(tv, mood, url="")
    out = await show.run({"action": "nacht_frei"})            # not on the TV yet: she appears first
    assert "done" in out and tv.front == tvshow.BROWSER and mood.worn == ["nacht"]
    assert show.page_state()["outfit"] == "nacht"
    await asyncio.sleep(0.08)
    assert show.night_open()                                  # her page is in front: it stays
    tv.front = "com.google.android.tvlauncher"                # somebody pressed Home on the remote
    await asyncio.sleep(0.1)
    assert not show.night_open() and show.page_state()["outfit"] == "freizeit"
    await show.run({"action": "nacht_frei"})
    assert show.night_open()
    assert "gesperrt" in (await show.run({"action": "nacht_zu"}))["done"] and not show.night_open()

    class Broken(FakeTv):
        async def _activity(self):
            raise RuntimeError("no answer")
    show = tvshow.TvShow(Broken(), FakeMood(), url="")
    show.night_until = 1e12
    assert "error" in await show.run({"action": "weg"}) and not show.night_open()   # an error locks


def test_the_bridge_offers_it_with_its_gate(tmp_path, monkeypatch):
    from app import main as m
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("LEYLA_HEART_PATH", str(tmp_path / "heart.json"))
    bridge = m.LiveVoiceBridge()
    assert bridge.tvshow.available and bridge.tvshow.mood is bridge.mood
    spec = bridge._tools["leyla_fernseher"]
    assert spec["gate"] is tvshow.night_gate and spec["run"] == bridge.tvshow.run
    assert spec["log"]({"action": "nacht_frei"}, {"done": "x"}) == "nacht_frei -> done"
    names = [t.get("name") for ok, t, _, _ in bridge._capabilities() if ok and t]
    assert "leyla_fernseher" in names
    assert "leyla_fernseher" not in bridge._plan_schemas()    # a tool with a gate is never part of a plan
    session = bridge._session_start()["session"]
    assert tvshow.SHOW_BACKEND_HINT in session["delegation"]["responses"]["instructions"]


async def _get(port, path):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read()
    writer.close()
    return raw.split(b"\r\n\r\n", 1)[1].decode()


async def test_the_state_route_of_the_tv_needs_no_code_word_and_gives_only_what_is_released(tmp_path):
    show = tvshow.TvShow(FakeTv(), FakeMood("nacht"), url="")
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1",
                                         port=0, code_phrase="Leyla habibi", tvstate=show.page_state)
    port = server.sockets[0].getsockname()[1]
    try:
        assert json.loads(await _get(port, "/api/tv"))["outfit"] == "freizeit"
        show.night_until = 1e12
        assert json.loads(await _get(port, "/api/tv?t=1"))["outfit"] == "nacht"
    finally:
        server.close()
    bare = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m2.json")), None, host="127.0.0.1", port=0)
    try:
        assert json.loads(await _get(bare.sockets[0].getsockname()[1], "/api/tv")) == {}
    finally:
        bare.close()


def test_the_tv_view_is_in_the_page():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "const TV=/[?&]tv=1(&|$)/.test(location.search);" in page
    assert "c=TV?null:localStorage.getItem('lcode')" in page          # a stored code word is never read there
    assert "if(home&&!CODE&&!TV)root.appendChild(privBox());" in page  # and no field to type one
    assert "showChat=(!!CODE||TV)&&home;" in page
    assert "onpointerdown=ev=>{if(TV||ev.button>0||" in page           # no touch on the TV
    assert "if(TV)once=once.filter(n=>n!=='kuss');" in page            # no kiss toward the room
    assert "html.tv body>*:not(#chat),html.tv #chat>*:not(#stage){display:none!important}" in page


def _clips(folder, names):
    folder.mkdir(parents=True)
    for i, name in enumerate(names):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=size=240x360:rate=24:duration=4", "-vf", f"hue=h={i * 45}",
                        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "400k", "-g", "24",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(folder / (name + ".mp4"))], check=True)


async def test_on_the_tv_only_her_stage_shows_and_a_locked_night_outfit_leaves_at_once(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    try:
        _clips(tmp_path / "clips" / "kurz", ("gluecklich", "gluecklich2", "freizeitgluecklich", "freizeitgluecklich2"))
        _clips(tmp_path / "clips" / "nacht", ("gluecklich", "gluecklich2"))
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    show = tvshow.TvShow(FakeTv(), FakeMood("nacht"), url="")
    show.night_until = 1e12                                   # released when the page opens
    store = memory.MemoryStore(str(tmp_path / "m.json"))
    server = await memory_web.start_http(store, None, host="127.0.0.1", port=0, code_phrase="Leyla habibi",
                                         tvstate=show.page_state)
    port = server.sockets[0].getsockname()[1]
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            posts = []
            page.on("request", lambda r: posts.append(r.post_data or "") if r.method == "POST" else None)
            await page.add_init_script("try{localStorage.setItem('lcode','geheim')}catch(e){}")
            await page.goto(f"http://127.0.0.1:{port}/?tv=1")
            src = "()=>[svid,svid2].map(v=>v.classList.contains('on')?(v.getAttribute('src')||''):'').join('|')"
            for _ in range(60):
                await asyncio.sleep(0.25)
                if "/clips/nacht/" in await page.evaluate(src):
                    break
            seen = await page.evaluate("""()=>{const vis=e=>{const r=e.getBoundingClientRect(),c=getComputedStyle(e);return c.display!=='none'&&c.visibility!=='hidden'&&r.width>0&&r.height>0;};
              const st=document.getElementById('stage').getBoundingClientRect();
              return {code:CODE,outfit:STM&&STM.outfit,stageH:Math.round(st.height),stageW:Math.round(st.width),
                shown:[...document.querySelectorAll('body *')].filter(e=>vis(e)&&!e.closest('#stage')&&e.id!=='chat').map(e=>e.id||e.tagName),
                inputs:[...document.querySelectorAll('input,textarea,button')].filter(vis).length,
                edge:[...document.querySelectorAll('#zedge,#ztimer')].filter(vis).length,
                on:[svid,svid2].map(v=>v.classList.contains('on')?(v.getAttribute('src')||''):'').join('|')};}""")
            assert seen["code"] is None                        # the code word stored in this browser was not read
            assert seen["outfit"] == "nacht" and "/clips/nacht/" in seen["on"] and "&m=1" in seen["on"]
            assert seen["stageH"] == 720 and seen["stageW"] == 480          # her whole figure, as high as the screen
            assert seen["shown"] == [] and seen["inputs"] == 0              # nothing but her, nothing to type into
            assert seen["edge"] == 0                                        # no clip timer light at the edge of her picture (2.197.1)
            show.night_until = 0.0                             # locked again
            t0 = asyncio.get_running_loop().time()
            gone = None
            for _ in range(80):
                await asyncio.sleep(0.1)
                on = await page.evaluate("()=>[svid,svid2].filter(v=>getComputedStyle(v).opacity>0.02&&(v.getAttribute('src')||'').includes('/clips/nacht/')).length")
                if not on and await page.evaluate("()=>STM.outfit") == "freizeit":
                    gone = asyncio.get_running_loop().time() - t0
                    break
            assert gone is not None and gone < 5.5, gone      # within one question of the page (every 4 s)
            for _ in range(40):
                await asyncio.sleep(0.25)
                if "freizeitgluecklich" in await page.evaluate(src):
                    break
            after = await page.evaluate("()=>({on:[svid,svid2].map(v=>v.classList.contains('on')?(v.getAttribute('src')||''):'').join('|'),img:document.querySelector('#stage .fig img').src})")
            assert "freizeitgluecklich" in after["on"] and "/clips/nacht/" not in after["on"]
            assert "/clips/nacht/" not in after["img"]
            assert all('"code"' not in body for body in posts)   # the page of the TV never sends a code word
            await browser.close()
    finally:
        server.close()


def test_she_learns_about_the_night_outfit_on_the_tv_only_after_the_code_word(tmp_path, monkeypatch):
    from app import main as m
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "x")
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("LEYLA_HEART_PATH", str(tmp_path / "heart.json"))
    bridge = m.LiveVoiceBridge()
    unlock = dict(bridge._code_notes())["unlock"]
    assert tvshow.UNLOCK_NOTE in unlock
    start = json.dumps(bridge._session_start(), ensure_ascii=False)   # what every talk in the room starts with
    live = bridge._session_start()["session"]["instructions"]
    assert "Nachtkleid" not in live and "nacht_frei" not in live      # her live voice knows nothing of it before
    assert tvshow.SHOW_LIVE in live
    assert tvshow.UNLOCK_NOTE not in start
    bridge.tvshow.url = "aus"                                         # no TV view: no word about it
    assert tvshow.UNLOCK_NOTE not in dict(bridge._code_notes())["unlock"]


async def _tv_page(tmp_path, monkeypatch, init, script, names=("gluecklich", "gluecklich2", "gluecklich3")):
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    try:
        _clips(tmp_path / "clips" / "kurz", names)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    memory_web.DIAG.clear()
    show = tvshow.TvShow(FakeTv(), FakeMood("arbeit"), url="")
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1",
                                         port=0, tvstate=show.page_state)
    port = server.sockets[0].getsockname()[1]
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            if init:
                await page.add_init_script(init)
            await page.goto(f"http://127.0.0.1:{port}/?tv=1")
            out = await page.evaluate(script)
            await browser.close()
    finally:
        server.close()
    return out, [d.get("ev", "") for d in memory_web.DIAG]


WATCH = """async()=>{const sleep=ms=>new Promise(r=>setTimeout(r,ms)),seen=[],two=[];let gap=0,t0=performance.now(),still=0;
  PRE
  while(performance.now()-t0<LIMIT){await sleep(100);const on=[svid,svid2].filter(v=>v.getAttribute('src'));if(on.length>1)two.push(1);
    const v=[svid,svid2][SV],n=(v.getAttribute('src')||'').split('?')[0].split('/').pop();if(n&&seen[seen.length-1]!==n)seen.push(n);
    const c=document.getElementById('tvfreeze'),pic=(v.classList.contains('on')&&v.readyState>=2)||(c&&c.style.display==='block');
    if(seen.length&&!pic){still+=100;gap=Math.max(gap,still);}else still=0;}
  return {seen,two:two.length,gap,tv1:TV1,stored:localStorage.getItem('ltv1'),svid2:svid2.getAttribute('src')||''};}"""


async def test_the_tv_plays_clip_after_clip_with_one_video(tmp_path, monkeypatch):
    out, diag = await _tv_page(tmp_path, monkeypatch, "try{localStorage.setItem('ltv1','1')}catch(e){}",
                               WATCH.replace("PRE", "").replace("LIMIT", "14000"))
    assert out["tv1"] and len(out["seen"]) >= 3 and len(set(out["seen"])) >= 2, out   # she goes on after the first clip
    assert out["two"] == 0 and out["svid2"] == ""             # never two videos at once
    assert out["gap"] <= 300, out                             # between two clips her last picture stays, no black
    assert any(e.startswith("tv start one win=1280x720 dpr=1") for e in diag), diag
    assert any(e.startswith("tv ok one clip=240x360 box=480x720") for e in diag), diag


async def test_a_tv_that_cannot_run_two_videos_switches_by_itself(tmp_path, monkeypatch):
    # the second video of the stage never gets a clip, as on a TV with one decoder: the first clip plays and stands
    block = """const iv=setInterval(()=>{const vs=[svid,svid2];const run=vs.find(v=>v.getAttribute('src')&&!v.paused&&v.currentTime>0.2);if(!run||TV1)return;clearInterval(iv);
      const o=vs[1-vs.indexOf(run)];Object.defineProperty(o,'src',{configurable:true,get(){return ''},set(x){}});window.BLOCKED=o;},50);
      const un=setInterval(()=>{if(TV1&&window.BLOCKED){delete window.BLOCKED.src;window.BLOCKED=null;clearInterval(un);}},50);"""
    out, diag = await _tv_page(tmp_path, monkeypatch, "try{localStorage.removeItem('ltv1')}catch(e){}",
                               WATCH.replace("PRE", block).replace("LIMIT", "24000"))
    assert out["tv1"] and out["stored"] == "1", (out, diag)   # found out by itself and remembered on this TV
    assert len(out["seen"]) >= 3, (out, diag)                 # and she moves again
    assert any(e.startswith("tv start dual") for e in diag) and any(e.startswith("tv stuck dual a=") for e in diag), diag
    assert any(e.startswith("tv ok one") for e in diag), diag


def test_what_the_tv_page_reports_reaches_the_log_as_technical_words_only():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert 'logger.info("TV page: %s", re.sub(r"[^a-z0-9 =/.-]", "", str(d["ev"])[:90]))' in page
    assert "const want=!!(!TV&&STM&&STM.outfit==='freizeit'&&PET.length" in page   # no cat video on the TV
