"""Her voice in the app: loud enough, set by Metin himself, and never above full scale (2.172.2).

Metin, 25 Nov 2026: "Leyla spricht viel zu leise", on the PC and in the phone app. Her voice went out at 105 %
(voice messages) and at 100 % with no limiter at all (live talk)."""
import asyncio

import pytest

from app import memory, memory_web


def test_every_way_her_voice_goes_out_takes_the_loud_path():
    app = open(memory_web.__file__, encoding="utf-8").read()
    assert "VVOL=2;" in app and "s.connect(liveOut(ctx));" in app and "s.connect(ctx.destination)" not in app
    assert app.count(".connect(voiceOut())") == 2, "voice messages and the streamed voice"
    assert "function voiceOut(){if(!VOUT){" in app and "VOUT=loudOut(VCTX);" in app


async def test_in_a_browser_the_slider_sets_her_voice_and_nothing_leaves_above_full_scale(tmp_path):
    playwright = pytest.importorskip("playwright.async_api")
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
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(0.6)
            got = await page.evaluate("""async()=>{const o={};
              o.start=voiceOut().gain.value;
              const lc=new AudioContext();o.live=liveOut(lc).gain.value;o.live_same=liveOut(lc)===liveOut(lc);
              // the menu shows the slider only to him (with the code word)
              menuOpen=true;CODE='';drawMenu();o.without_code=!!document.getElementById('mvoice');
              CODE='x';drawMenu();const r=document.querySelector('#mvoice input');o.slider=[r.min,r.max,r.value];
              r.value=300;r.oninput();o.after=[voiceOut().gain.value,liveOut(lc).gain.value,localStorage.getItem('lvoice'),document.querySelector('#mvoice small').textContent];
              voiceVol(9);o.top=VVOL;voiceVol(0);o.bottom=VVOL;
              // what leaves: a loud source through the same chain, rendered offline
              const render=async(gain,peak)=>{VVOL=gain;const sr=24000,n=sr*2,c=new OfflineAudioContext(1,n,sr),b=c.createBuffer(1,n,sr),d=b.getChannelData(0);
                for(let i=0;i<n;i++){const t=i/sr;d[i]=peak*Math.pow(Math.max(0,Math.sin(2*Math.PI*2*t)),2)*Math.sin(2*Math.PI*180*t);}
                const s=c.createBufferSource();s.buffer=b;s.connect(loudOut(c));s.start();const y=(await c.startRendering()).getChannelData(0);
                let p=0,a=0,q=0;for(let i=sr/2;i<n;i++){p=Math.max(p,Math.abs(y[i]));a+=y[i]*y[i];q+=d[i]*d[i];}return [p,10*Math.log10(a/q)];};
              o.quiet_source=await render(2,0.25);o.loud_source=await render(4,0.9);return o;}""")
            await page.close()
            # the choice is kept on the device
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(0.4)
            await page.evaluate("()=>localStorage.setItem('lvoice','1.5')")
            await page.reload()
            await asyncio.sleep(0.4)
            kept = await page.evaluate("()=>voiceOut().gain.value")
            await browser.close()
    finally:
        server.close()
    assert not errors, errors
    assert got["start"] == 2 and got["live"] == 2 and got["live_same"], got
    assert got["without_code"] is False and got["slider"] == ["50", "400", "200"], got
    assert got["after"] == [3, 3, "3", "300 %"], got
    assert got["top"] == 4 and got["bottom"] == 0.5, got
    peak, louder = got["quiet_source"]
    assert peak < 1 and 5.5 < louder < 7, got         # a quiet source at 200 %: about 6.5 dB louder (0.6 of it is the make up gain of the limiter)
    peak, louder = got["loud_source"]
    assert peak <= 1.0 and louder > 2, got            # a loud source at 400 %: louder, and never above full scale
    assert kept == 1.5
