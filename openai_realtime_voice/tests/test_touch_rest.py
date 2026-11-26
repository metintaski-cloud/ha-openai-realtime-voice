"""After a touch clip she rests: the loop that follows runs through once before the next touch counts (2.174.0).

Metin, 26 Nov 2026, on the phone app: "ich kann viele Berührungen hintereinander machen und das wirkt dann sehr
unruhig ... kann man nicht einen Mischer dazwischen machen ... den Moment, wo der Kreis auf grün kommt, als jetzt
tippen? dann muss dieser Clip zu Ende gehen, damit dieser Clip nicht abgebrochen wird". Before, only the touch clip
itself was protected: the moment it ended, the next touch cut the loop that had just started."""
import shutil
import subprocess

import pytest

from app import memory_web


def test_the_rest_is_in_the_page_and_a_touch_during_red_is_not_kept():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "zBlocked=()=>!!ZPEND||Date.now()<ZBUSY||Date.now()<ZREST" in page
    assert "Date.now()-ZT<700||zBlocked())return;" in page            # the stage takes no touch while blocked
    assert "const zDone=()=>{ZBUSY=0;ZCOLNOW='';ZRESTGO=false;ZREST=Date.now()+ZREST_MAX;" in page   # the rest starts
    assert "function stageNext(b){if(ZREST)ZRESTGO=true;" in page     # the loop is in its last seconds ...
    assert "const go=()=>{if(ZRESTGO)zFree();" in page                # ... and the swap to the next clip ends the rest
    assert "zGame(z,true)" not in page                                # no more lost hits for a late touch


async def test_a_touch_in_the_rest_does_nothing_and_the_first_loop_runs_to_its_end(tmp_path, monkeypatch):
    import asyncio

    from app import memory
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, (name, dur) in enumerate((("gluecklich4", 3), ("gluecklich5", 3), ("gluecklich6", 3), ("brust", 2))):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"testsrc2=size=240x360:rate=24:duration={dur}", "-vf", f"hue=h={i * 60}",
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
            await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;
              const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""")
            await asyncio.sleep(1.5)
            r = await page.evaluate("""async()=>{
              const vs=[document.getElementById('svid'),document.getElementById('svid2')],ring=document.getElementById('ztimer');
              const st=document.getElementById('stage'),R=st.getBoundingClientRect(),ar=1176/1764;let w=R.width,h=w/ar;if(h<R.height){h=R.height;w=h*ar;}
              const tap=()=>st.onpointerdown(new PointerEvent('pointerdown',{clientX:R.left+(R.width-w)/2+0.5*w,clientY:R.top+(R.height-h)/2+0.23*h,button:0}));
              const cur=()=>vs[SV].getAttribute('src')||'',touchOn=()=>vs.some(v=>v.classList.contains('on')&&(v.getAttribute('src')||'').includes('/brust.mp4'));
              const until=(f,ms)=>new Promise(r=>{const t0=performance.now(),t=()=>{if(f())r(true);else if(performance.now()-t0>ms)r(false);else setTimeout(t,20);};t();});
              const sleep=ms=>new Promise(r=>setTimeout(r,ms)),green=()=>ring.classList.contains('go');
              const out={};await sleep(250);out.greenAtStart=green();
              tap();out.first=await until(touchOn,3000);await sleep(250);out.redInTouch=!green();
              // zDone comes 3 s before the end of a touch clip (preload), so for this 2 s clip at once: these seconds used to be open
              out.blockedInTouch=zBlocked();ZT=0;tap();await sleep(300);out.tapInTouchIgnored=touchOn()&&zBlocked();
              // her touch clip ends, the loop starts: this is the moment that used to be open for the next touch
              out.loopBack=await until(()=>/gluecklich/.test(cur())&&vs[SV].classList.contains('on'),8000);
              const loop=cur(),t1=performance.now();out.resting=Date.now()<ZREST;await sleep(300);out.redInRest=!green();
              ZT=0;tap();await sleep(700);out.tapInRestIgnored=cur()===loop&&Date.now()>=ZBUSY&&Date.now()<ZREST;
              // the loop runs to its end and hands over: now the ring is green and she takes the touch at once
              out.freed=await until(()=>!ZREST,8000);out.restMs=Math.round(performance.now()-t1);
              out.handedOver=cur()!==loop;await sleep(150);out.greenAfterRest=green();out.nowWindow=ZT_GREEN();
              ZT=0;tap();out.second=await until(touchOn,3000);
              return out;}""")
            await browser.close()
    finally:
        server.close()
    assert r["greenAtStart"], r                     # before any touch she is free
    assert r["first"] and r["redInTouch"], r        # the touch clip plays, the ring is red
    assert r["blockedInTouch"] and r["tapInTouchIgnored"], r   # new: not even in the last 3 s of the touch clip
    assert r["loopBack"] and r["resting"] and r["redInRest"], r
    assert r["tapInRestIgnored"], r                 # new: a tap right after the touch clip does not cut the loop
    assert r["freed"] and r["handedOver"], r        # the rest ends when that loop is through
    assert r["restMs"] > 2000, r                    # the 3 s loop really ran (hand over about 0.3 s before its end)
    assert r["greenAfterRest"] and r["nowWindow"], r
    assert r["second"], r                           # and then her reaction comes at once
