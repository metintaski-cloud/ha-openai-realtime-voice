"""The two buttons bottom right in the chat, Tanz and Zeig (2.184.0).

Metin, 27 Nov 2026: "kannst du mir im App noch 2 Buttons links bauen für tanzen und zeigen", then: "oder besser rechts
unten". They ask for the scene without a chat message; her level decides on the server as in the chat (heart.SCENES)."""
import asyncio
import json

import pytest

from app import memory, memory_web

CODE = "Leyla Sonne Mond"


class Mood:
    def __init__(self, level):
        self.level, self.asked = level, []

    def scene(self, wanted):
        self.asked.append(wanted)
        return {"tanz": {"gut": "tanz", "leicht": "tanztraurig"}, "zeigen": {"gut": "zeigen"},
                "umziehen": {"gut": "umziehen"}}.get(wanted, {}).get(self.level, "")

    def status(self):
        return {"mood": "gluecklich", "level": self.level, "low": self.level != "gut", "label": "x", "outfit": "nacht"}


async def _post(port, body: dict) -> dict:
    raw = json.dumps(body)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(("POST /api/szene HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                  f"Content-Length: {len(raw.encode())}\r\n\r\n{raw}").encode())
    await writer.drain()
    out = (await reader.read()).decode()
    writer.close()
    return json.loads(out.split("\r\n\r\n", 1)[1])


async def test_her_level_decides_and_only_these_two_scenes_can_be_asked(tmp_path, caplog):
    import logging
    for level, tanz, zeigen in (("gut", "tanz", "zeigen"), ("leicht", "tanztraurig", ""), ("schwer", "", "")):
        mood = Mood(level)
        server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / f"{level}.json")), None, host="127.0.0.1",
                                             port=0, code_phrase=CODE, mood=mood)
        port = server.sockets[0].getsockname()[1]
        try:
            with caplog.at_level(logging.INFO):
                a = await _post(port, {"code": CODE, "scene": "tanz"})
                b = await _post(port, {"code": CODE, "scene": "zeigen"})
            assert (a["scene"], a["ok"], a["mood"]["level"]) == (tanz, bool(tanz), level)
            assert (b["scene"], b["ok"]) == (zeigen, bool(zeigen))
            # a scene that changes what she wears is not for a button, and nothing without the code word
            assert (await _post(port, {"code": CODE, "scene": "umziehen"}))["scene"] == ""
            assert await _post(port, {"scene": "tanz"}) == {"scene": "", "ok": False}
            assert mood.asked == ["tanz", "zeigen"]
        finally:
            server.close()
    assert "Memory page: button tanz, she does it" in caplog.text and "button zeigen, she is not in the mood" in caplog.text


PREP = """(o)=>{const sp=document.getElementById('splash');if(sp)sp.remove();CODE='x';
  document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');
  window.ASKED=[];window.PLAYED=[];window.ANSWER=o.answer;
  post=async(path,obj)=>{if(path!=='/api/szene')return {json:async()=>null};ASKED.push([path,obj.scene]);return {json:async()=>ANSWER};};
  stageScene=n=>{PLAYED.push(n);};moodShow=()=>{};
  CLIPS=o.clips;NIGHT=o.night;STM={outfit:o.outfit,mood:'gluecklich',level:'gut'};scnDraw();}"""
STATE = """()=>({off:['ctanz','czeig'].map(i=>document.getElementById(i).classList.contains('off')),asked:ASKED,played:PLAYED,
  info:CHAT.filter(m=>m.role==='info').map(m=>m.text)})"""


async def test_in_a_browser_the_buttons_sit_bottom_right_and_play_what_she_agrees_to(tmp_path):
    playwright = pytest.importorskip("playwright.async_api")
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None, host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    errors = []
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch()
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 412, "height": 869}, has_touch=True)
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(0.5)
            # night dress, she is in the mood
            await page.evaluate(PREP, {"answer": {"ok": True, "scene": "tanz"}, "clips": ["gluecklich4"],
                                       "night": ["gluecklich4", "tanz14", "tanz15", "tanzhf", "zeigenlang3"], "outfit": "nacht"})
            box = await page.evaluate("""()=>['ctanz','czeig','ctype','csend'].map(i=>{const r=document.getElementById(i).getBoundingClientRect();
              return [Math.round(r.left),Math.round(r.top),Math.round(r.right),Math.round(r.bottom)];})""")
            tanz, zeig, field, send = box
            assert tanz[2] == zeig[2] == send[2] == 402          # in a line with the buttons on the right
            assert (tanz[2] - tanz[0], tanz[3] - tanz[1]) == (send[2] - send[0], send[3] - send[1]) == (50, 44)   # as small as those (Metin, 03:57)
            assert tanz[3] < zeig[1] and zeig[3] == field[3]      # one above the other, down to where the text field ends
            assert tanz[0] > field[2] and tanz[1] > send[3]       # beside the text field, below the send button: nothing covered
            await page.click("#ctanz")
            await asyncio.sleep(0.1)
            s = await page.evaluate(STATE)
            assert s["off"] == [False, False] and s["asked"] == [["/api/szene", "tanz"]] and s["played"] == ["tanz"] and s["info"] == []
            await page.evaluate("()=>{ANSWER={ok:true,scene:'zeigen'};}")
            await page.click("#czeig")
            await asyncio.sleep(0.1)
            s = await page.evaluate(STATE)
            assert s["asked"][-1] == ["/api/szene", "zeigen"] and s["played"] == ["tanz", "zeigen"]
            # she is not in the mood: no scene, one line that says so (also for the sad dance no outfit has clips of)
            for answer in ({"ok": False, "scene": ""}, {"ok": True, "scene": "tanztraurig"}):
                await page.evaluate("(a)=>{ANSWER=a;CHAT.length=0;}", answer)
                await page.click("#ctanz")
                await asyncio.sleep(0.1)
                s = await page.evaluate(STATE)
                assert s["played"] == ["tanz", "zeigen"] and s["info"] == ["💃 Dazu ist sie gerade nicht in Stimmung."]
            # the short Freizeit dress has dances but no show: that button is grey and says why, the server is not asked
            await page.evaluate(PREP, {"answer": {"ok": True, "scene": "tanz"}, "clips": ["freizeitgluecklich", "freizeittanz2"],
                                       "night": ["tanz14", "zeigenlang3"], "outfit": "freizeit"})
            await page.evaluate("()=>{CHAT.length=0;}")
            await page.click("#czeig")
            await page.click("#ctanz")
            await asyncio.sleep(0.1)
            s = await page.evaluate(STATE)
            assert s["off"] == [False, True] and s["asked"] == [["/api/szene", "tanz"]] and s["played"] == ["tanz"]
            assert s["info"] == ["✨ Zeigen gibt es nur im Nachtkleid."]
            # a work dress has neither
            await page.evaluate(PREP, {"answer": {"ok": True, "scene": "tanz"}, "clips": ["gluecklich4"], "night": ["tanz14"], "outfit": "arbeit"})
            await page.evaluate("()=>{CHAT.length=0;}")
            await page.click("#ctanz")
            await asyncio.sleep(0.1)
            s = await page.evaluate(STATE)
            assert s["off"] == [True, True] and s["asked"] == [] and s["info"] == ["💃 In diesem Kleid hat sie keinen Tanz."]
            await browser.close()
    finally:
        server.close()
    assert errors == []
