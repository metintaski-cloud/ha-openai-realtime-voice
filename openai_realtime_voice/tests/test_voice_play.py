"""One voice at a time, and a long press on the play button saves her voice reply (2.174.2).

Metin, 26 Nov 2026: "wenn ich 2 mal auf play drücke, dann kommen zwei Stimmen". And for a mouth clip in her real
voice he needs her reply as a file; the visible download arrow was removed in 2.143.1 at his wish."""
import base64
import io
import struct
import wave

import pytest

from app import memory, memory_web


def _wav(seconds=3.0, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", 3000 if (i // 20) % 2 else -3000) for i in range(int(seconds * rate))))
    return base64.b64encode(buf.getvalue()).decode()


def test_the_page_plays_through_one_door():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert page.count("new Audio(AUDIO.get(id))") == 1          # every voice reply starts in playAudio
    assert "if(PLAY){const o=PLAY;PLAY=null;try{o.pause();}catch(e){}}if(same)return;" in page
    assert "playBtn(b,m.aid)" in page and "b.onclick=()=>playAudio(m.aid)" not in page
    assert "\\u2B07" not in page                                 # still no visible download arrow


async def test_a_second_press_never_gives_two_voices_and_a_long_press_saves(tmp_path):
    import asyncio
    playwright = pytest.importorskip("playwright.async_api")
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 820}, accept_downloads=True)
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(1.0)
            r = await page.evaluate("""async(b64)=>{const sp=document.getElementById('splash');if(sp)sp.remove();
              AUDIO.set('a1','data:audio/wav;base64,'+b64);AUDIO.set('a2','data:audio/wav;base64,'+b64);
              const sleep=ms=>new Promise(r=>setTimeout(r,ms)),out={};
              playAudio('a1');await sleep(400);const one=PLAY;out.firstPlays=!!one&&!one.paused;
              playAudio('a2');await sleep(400);const two=PLAY;out.otherStopsFirst=one.paused&&!!two&&two!==one&&!two.paused;
              playAudio('a2');await sleep(300);out.samePressStops=two.paused&&PLAY===null;
              playAudio('a2');await sleep(300);const three=PLAY;out.thirdPressPlaysAgain=!!three&&!three.paused;
              playAudio('a1');playAudio('a1');playAudio('a1');await sleep(400);out.quickPresses=[one,two,three].every(x=>x.paused);
              if(PLAY){PLAY.pause();}
              // the button: a short press plays, a long press saves and does not play
              CHAT.length=0;CHAT.push({role:'leyla',text:'x',aid:'a1'});document.getElementById('chat').style.display='block';chatDraw();
              const b=document.querySelector('#clog .play');out.button=!!b;if(!b)return out;
              b.dispatchEvent(new PointerEvent('pointerdown'));await sleep(100);b.dispatchEvent(new PointerEvent('pointerup'));b.click();await sleep(300);
              out.shortPressPlays=!!PLAY&&!PLAY.paused;if(PLAY)PLAY.pause();await sleep(100);
              window.__b=document.querySelector('#clog .play');return out;}""", _wav())
            async with page.expect_download(timeout=8000) as dl:
                await page.evaluate("""async()=>{const b=window.__b;b.dispatchEvent(new PointerEvent('pointerdown'));await new Promise(r=>setTimeout(r,900));
                  b.dispatchEvent(new PointerEvent('pointerup'));b.click();}""")
            d = await dl.value
            saved = tmp_path / "s.wav"
            await d.save_as(str(saved))
            after = await page.evaluate("()=>({playing:!!PLAY&&!PLAY.paused,info:CHAT.some(m=>m.role==='info'&&m.text.includes('gespeichert'))})")
            await browser.close()
    finally:
        server.close()
    assert r["firstPlays"] and r["otherStopsFirst"], r        # a new voice stops the one that plays
    assert r["samePressStops"] and r["thirdPressPlaysAgain"], r
    assert r["quickPresses"], r
    assert r["button"] and r["shortPressPlays"], r
    assert d.suggested_filename.startswith("Leyla_Stimme_") and d.suggested_filename.endswith(".wav")
    with wave.open(str(saved)) as w:
        assert w.getnframes() == 24000                         # the file is her reply, whole
    assert not after["playing"] and after["info"], after       # the long press saved and did not play
