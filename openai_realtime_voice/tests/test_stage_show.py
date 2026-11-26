"""An incoming clip fades in only once it really shows frames (2.174.3).

Metin's screen recording of 26 Nov 2026 (Galaxy S10): for the first moment after the swap to the touch clip with sound a
purple veil lay over the picture and grew with the fade. Black had become magenta and cream greenish, so the phone was
showing an unfinished picture of the incoming clip while it faded in. On the PC the same hand over is clean, so this
test can only hold the rule, not the veil: nothing of the incoming clip is visible before its frames run."""
import shutil
import subprocess

import pytest

from app import memory, memory_web


def test_the_rule_is_in_the_page():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "b.classList.add('pre');b.requestVideoFrameCallback(()=>b.requestVideoFrameCallback(show));setTimeout(show,SHOW_MAX_MS);}else show();" in page
    assert "#stage video.pre{opacity:.01;transition:none}" in page
    assert "(v.classList.contains('on')||v.classList.contains('pre'))" in page   # the ring and the touch window count a waiting clip as on screen


async def test_nothing_of_the_incoming_clip_shows_before_its_frames_run(tmp_path, monkeypatch):
    import asyncio
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, name in enumerate(("gluecklich4", "gluecklich5", "gluecklich6")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc2=size=240x360:rate=24:duration=3", "-vf", f"hue=h={i * 60}",
                            "-c:v", "libx264", "-preset", "veryfast", "-b:v", "400k", "-g", "24",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(folder / (name + ".mp4"))], check=True)
    except subprocess.CalledProcessError:
        pytest.skip("this ffmpeg cannot write H.264")
    monkeypatch.setattr(memory_web, "CLIPS_DIR", str(tmp_path / "clips"))
    monkeypatch.setattr(memory_web, "MOBIL", None)
    server = await memory_web.start_http(memory.MemoryStore(str(tmp_path / "m.json")), None,
                                         host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with playwright.async_playwright() as p:
            try:
                browser = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            except Exception:
                pytest.skip("no browser here")
            page = await browser.new_page(viewport={"width": 400, "height": 820})
            await page.goto(f"http://127.0.0.1:{port}/")
            await asyncio.sleep(1.0)
            await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;touchAsk=()=>null;
              const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""")
            await asyncio.sleep(1.5)
            r = await page.evaluate("""async()=>{
              const vs=[document.getElementById('svid'),document.getElementById('svid2')];const op=v=>parseFloat(getComputedStyle(v).opacity);
              const swap=()=>new Promise(r=>{const s0=SV,t=()=>{if(SV!==s0)r();else requestAnimationFrame(t);};t();});
              const watch=async()=>{await swap();const b=vs[SV],a=vs[1-SV],t0=performance.now();const o={preAtSwap:b.classList.contains('pre'),onAtSwap:b.classList.contains('on'),newOpacityAtSwap:op(b),oldOpacityAtSwap:op(a)};
                let min=1;await new Promise(r=>{const t=()=>{const cover=1-(1-op(a)*(a.readyState>=2?1:0))*(1-op(b)*(b.readyState>=2?1:0));min=Math.min(min,cover);
                  if(b.classList.contains('on')&&!o.onAfter)o.onAfter=Math.round(performance.now()-t0);if(performance.now()-t0>2000)r();else requestAnimationFrame(t);};t();});
                o.minCover=+min.toFixed(2);o.late=SHOWLATE;o.shown=b.classList.contains('on')&&!b.classList.contains('pre')&&op(b)>0.98;return o;};
              const out={normal:[await watch(),await watch()]};
              // a phone that never reports a frame: the clip must still come in, after the limit
              HTMLVideoElement.prototype.requestVideoFrameCallback=function(){return 0;};
              out.silent=await watch();out.max=SHOW_MAX_MS;return out;}""")
            await browser.close()
    finally:
        server.close()
    for o in r["normal"]:
        assert o["preAtSwap"] and not o["onAtSwap"], r          # at the swap the new clip only waits
        assert o["newOpacityAtSwap"] <= 0.02 and o["oldOpacityAtSwap"] > 0.98, r
        assert o["shown"] and o["late"] < 250, r                # it fades in once two of its frames were shown
        assert o["minCover"] > 0.85, r
    s = r["silent"]
    assert s["shown"] and r["max"] - 30 <= s["late"] <= r["max"] + 200, r   # no frame report: it comes in after the limit
    assert s["minCover"] > 0.85, r
