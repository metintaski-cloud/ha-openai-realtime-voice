"""The chat in step on his devices (2.173.0, Metin, 26 Nov 2026: "dass ich auf Handy schreibe und auf PC Monitor
sehe", "also synchron", "1 Sekunde geht so"). What one device sends and what she answers reaches the other at
once. The sentences here are made up."""
import asyncio
import json
import time

import pytest

from app import memory, memory_web

CODE = "Leyla Sonne Mond"   # the made up code word of the tests


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    memory_web.SYNC.clear()
    memory_web.SYNC_SEQ[0] = 0
    memory_web.SYNC_WAKE.clear()
    monkeypatch.setattr(memory_web, "SYNC_WAIT_S", 1.0)
    yield
    memory_web.SYNC.clear()
    memory_web.SYNC_SEQ[0] = 0


async def test_a_device_gets_what_the_others_sent_and_never_its_own_lines():
    w = memory_web.sync_wait
    assert await w(-1, "pc") == {"events": [], "last": 0}          # new here: only the number, at once
    memory_web.sync_add("handy", "user", text="Guten Morgen")
    memory_web.sync_reply("handy", {"reply": "Guten Morgen, Schatz", "scene": "kuss", "mood": {"mood": "froh"},
                                    "audio": "AAAA", "voice_id": "v1", "proposals": [{"x": 1}], "email": {"to": "a"}})
    got = await w(0, "pc")
    assert got["last"] == 2 and [e["kind"] for e in got["events"]] == ["user", "leyla"]
    assert got["events"][0] == {"id": 1, "kind": "user", "text": "Guten Morgen"}
    assert got["events"][1]["j"] == {"reply": "Guten Morgen, Schatz", "scene": "kuss", "mood": {"mood": "froh"}}
    t0 = time.monotonic()
    assert await w(0, "handy") == {"events": [], "last": 2}        # his own lines do not come back, and no waiting
    assert time.monotonic() - t0 < 0.2
    assert await w(99, "pc") == {"events": [], "last": 2}          # a number from before a restart
    for bad in (None, "3", 1.5, True, -4):
        assert (await w(bad, "pc"))["events"] == []
    memory_web.sync_reply("handy", None)                           # she could not answer: the other screen says so too
    assert (await w(2, "pc"))["events"][0]["j"] == {"error": True}


async def test_the_other_device_is_woken_at_once_and_an_idle_wait_ends_by_itself():
    async def later():
        await asyncio.sleep(0.15)
        memory_web.sync_add("handy", "user", text="Bist du da?")
    asyncio.ensure_future(later())
    t0 = time.monotonic()
    got = await memory_web.sync_wait(0, "pc")
    took = time.monotonic() - t0
    assert [e["text"] for e in got["events"]] == ["Bist du da?"] and 0.1 < took < 0.4, took
    t0 = time.monotonic()
    assert await memory_web.sync_wait(1, "pc") == {"events": [], "last": 1}   # nothing comes: back after the wait
    assert 0.9 < time.monotonic() - t0 < 1.5
    assert not memory_web.SYNC_WAKE, "no waiter is left behind"


async def _post(port: int, path: str, body: dict) -> dict:
    raw = json.dumps(body).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(raw)}\r\n\r\n".encode() + raw)
    await writer.drain()
    out = (await reader.read()).decode()
    writer.close()
    return json.loads(out.split("\r\n\r\n", 1)[1])


async def test_over_http_only_with_the_code_word_and_every_way_of_the_chat_is_passed_on(tmp_path):
    async def chat(history, message):
        return {"reply": "Antwort auf: " + message, "scene": "tanzen", "proposals": [{"p": 1}]}

    async def voice(history, audio, mime, stream=False):
        return {"heard": "wie spät ist es", "reply": "Kurz nach acht", "voice_id": "v9", "t": {}}

    async def touch(history, zone):
        return {"reply": "Hihi", "audio": "AAAA"}

    async def chat_new():
        return None
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1",
                                         port=0, code_phrase=CODE, chat=chat, voice=voice, touch=touch,
                                         chat_new=chat_new)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await _post(port, "/api/sync", {"after": -1, "dev": "pc"}) == {"error": True}
        assert await _post(port, "/api/sync", {"after": -1, "dev": "pc", "code": "falsch"}) == {"error": True}
        assert await _post(port, "/api/sync", {"after": -1, "dev": "pc", "code": CODE}) == {"events": [], "last": 0}
        await _post(port, "/api/chat", {"history": [], "message": "Hallo du", "code": CODE, "dev": "handy"})
        await _post(port, "/api/chat", {"history": [], "message": "ohne Code Wort", "dev": "handy"})   # not passed on
        await _post(port, "/api/chat_voice", {"history": [], "audio": "AAAA", "mime": "audio/webm", "stream": True,
                                              "code": CODE, "dev": "handy"})
        await _post(port, "/api/chat_touch", {"history": [], "zone": "gesicht", "code": CODE, "dev": "handy"})
        await _post(port, "/api/chat_new", {"code": CODE, "dev": "handy"})
        got = await _post(port, "/api/sync", {"after": 0, "dev": "pc", "code": CODE})
    finally:
        server.close()
    shown = [(e["kind"], e.get("text") or (e.get("j") or {}).get("reply") or "") for e in got["events"]]
    assert shown == [("user", "Hallo du"), ("leyla", "Antwort auf: Hallo du"),
                     ("user", "🎤 wie spät ist es"), ("leyla", "Kurz nach acht"),
                     ("leyla", "Hihi"), ("new", "")], shown
    assert got["events"][1]["j"] == {"reply": "Antwort auf: Hallo du", "scene": "tanzen"}   # no cards, no audio
    assert all("audio" not in (e.get("j") or {}) and "voice_id" not in (e.get("j") or {}) for e in got["events"])
    assert all("dev" not in e for e in got["events"])


async def test_in_two_browsers_what_he_writes_on_one_appears_on_the_other_within_a_second(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(memory_web, "SYNC_WAIT_S", 25.0)

    async def chat(history, message):
        await asyncio.sleep(0.3)   # she thinks
        return {"reply": "Ich höre dich: " + message + " (" + str(len(history)) + ")"}

    async def chat_new():
        return None
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1",
                                         port=0, code_phrase=CODE, chat=chat, chat_new=chat_new)
    port = server.sockets[0].getsockname()[1]
    errors = []
    open_chat = """(code)=>{const sp=document.getElementById('splash');if(sp)sp.remove();CODE=code;
      document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');}"""
    lines = "()=>CHAT.filter(m=>m.role==='user'||m.role==='leyla').map(m=>m.role+': '+m.text)"
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                pytest.skip("no browser here")
            pc = await (await browser.new_context(viewport={"width": 1920, "height": 1080})).new_page()
            phone = await (await browser.new_context(viewport={"width": 400, "height": 820}, has_touch=True,
                                                     is_mobile=True)).new_page()
            for page in (pc, phone):
                page.on("pageerror", lambda e: errors.append(str(e)))
                await page.goto(f"http://127.0.0.1:{port}/")
                await page.evaluate(open_chat, CODE)
            await asyncio.sleep(1.0)   # both are waiting at the server now
            # he writes on the phone
            t0 = time.monotonic()
            await phone.evaluate("()=>{document.getElementById('ctext').value='Hallo vom Handy';chatSend();}")
            await pc.wait_for_function("()=>CHAT.some(m=>m.role==='user'&&m.text==='Hallo vom Handy')", timeout=3000)
            his = time.monotonic() - t0
            await pc.wait_for_function("()=>CHAT.some(m=>m.role==='leyla')", timeout=3000)
            hers = time.monotonic() - t0
            await asyncio.sleep(0.3)
            first = [await pc.evaluate(lines), await phone.evaluate(lines)]
            # and answers from the PC: the thread is one, she gets the lines from the phone as history
            await pc.evaluate("()=>{document.getElementById('ctext').value='und vom PC';chatSend();}")
            await phone.wait_for_function("()=>CHAT.filter(m=>m.role==='leyla').length===2", timeout=3000)
            await asyncio.sleep(0.3)
            second = [await pc.evaluate(lines), await phone.evaluate(lines)]
            # a new chat on one clears the other too
            await phone.evaluate("()=>chatNew()")
            await pc.wait_for_function("()=>CHAT.length===0", timeout=3000)
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
    want = ["user: Hallo vom Handy", "leyla: Ich höre dich: Hallo vom Handy (0)"]
    assert first == [want, want], first
    want = want + ["user: und vom PC", "leyla: Ich höre dich: und vom PC (2)"]
    assert second == [want, want], second           # no line twice, the same order on both
    assert his < 1.0 and 0.3 <= hers < 1.3, (his, hers)   # his line at once, her answer as soon as she has it
    print(f"his line after {his * 1000:.0f} ms, her answer after {hers * 1000:.0f} ms (she thinks 300 ms)")


async def test_a_stored_clip_value_reaches_the_open_app_at_once_without_a_new_start(tmp_path, monkeypatch):
    """2.173.1 (Metin, 26 Nov 2026: "PC Leyla auch synchron mit Outfit als Ganzes, dass, wenn ich ein und umstelle,
    sich das sofort überträgt"): a tempo stored on another page holds for the clip that is running in the app."""
    import shutil
    import subprocess
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=240x360:rate=24:duration=6",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        str(folder / "gluecklich4.mp4")], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    monkeypatch.setattr(memory_web, "SYNC_WAIT_S", 25.0)
    for key in ("TEMPO", "KURVE", "SCHNITT", "VORLAUF"):
        monkeypatch.setenv("LEYLA_" + key, str(tmp_path / (key + ".json")))
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1",
                                         port=0, code_phrase=CODE)
    port = server.sockets[0].getsockname()[1]
    errors = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/")
            await page.evaluate("""async(code)=>{const sp=document.getElementById('splash');if(sp)sp.remove();CODE=code;
              STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;
              document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');
              document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""", CODE)
            await page.wait_for_function("()=>{const v=document.getElementById(SV?'svid2':'svid');return v.classList.contains('on')&&v.currentTime>0.3;}", timeout=8000)
            await asyncio.sleep(0.8)   # the app waits at the server now
            before = await page.evaluate("()=>document.getElementById(SV?'svid2':'svid').playbackRate")
            t0 = time.monotonic()
            for rate in (1.2, 1.4):    # two saves in a row, as "Alles merken" does
                await _post(port, "/api/tempo", {"name": "kurz/gluecklich4", "rate": rate})
            await page.wait_for_function("()=>Math.abs(document.getElementById(SV?'svid2':'svid').playbackRate-1.4)<0.001", timeout=3000)
            took = time.monotonic() - t0
            same_clip = await page.evaluate("()=>[document.getElementById(SV?'svid2':'svid').currentTime>0.3,RATE['kurz/gluecklich4']]")
            await _post(port, "/api/schnitt", {"name": "kurz/gluecklich4", "start": 0.2, "end": 5.5})
            await page.wait_for_function("()=>(SCHNITT['kurz/gluecklich4']||[])[1]===5.5", timeout=3000)
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
    assert before == 1 and took < 1.0 and same_clip == [True, 1.4], (before, took, same_clip)
    assert [e["kind"] for e in memory_web.SYNC] == ["clips"], "saves in a row stay one entry"
