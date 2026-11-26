"""She takes a touch only in the green window before a hand over, and her clip comes in at that hand over (2.174.1).

Metin, 26 Nov 2026, on the phone app: "ich kann viele Berührungen hintereinander machen und das wirkt dann sehr
unruhig ... kann man nicht einen Mischer dazwischen machen ... den Moment, wo der Kreis auf grün kommt, als jetzt
tippen? dann muss dieser Clip zu Ende gehen, damit dieser Clip nicht abgebrochen wird". After 2.174.0 (free after one
loop, but a touch still cut into the running clip): "wenn ich bei grünem Kreis drücke, dann muss das ohne Zucken
sauber ablaufen, wenn zur falschen Zeit gedrückt, macht er nichts", "muss nahtlos sein", "am besten innerhalb dieses
grünen Kreises: wenn dort richtig gedrückt wird, dann geht der Clip zu Ende und der neue fängt sauber an".

Before, the touch clip itself was open for the next touch from the moment the stage preloaded the next clip (after as
little as 2.7 s of a 7 s clip), and every touch cut into the running clip with a 0.35 s crossfade."""
import shutil
import subprocess

import pytest

from app import memory_web


def test_the_window_is_in_the_page_and_a_touch_outside_it_is_not_kept():
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "const zBlocked=()=>!!ZPEND||Date.now()<ZBUSY||talkPose()||!zOpen();" in page  # 2.175.0: nor in her talk pose
    assert "Date.now()-ZT<700||zBlocked())return;" in page            # the stage takes no touch while blocked
    assert "return l<=ZWIN&&l>=ZWIN_MIN;}" in page                    # open only shortly before a hand over
    assert "if(src===ZREST)return false;" in page                     # and never on the touch clip itself
    assert "TIGHT=live;CONT=live;" in page                            # her clip comes in at the hand over, like a loop
    touch = page.split("document.getElementById('stage').onpointerdown")[1].split("document.getElementById('crose')")[0]
    assert "opacity .35s" not in touch                                # no more quick cut into the running clip
    assert "zGame(z,true)" not in page                                # no more lost hits


async def test_a_touch_at_green_comes_in_at_the_hand_over_and_any_other_touch_does_nothing(tmp_path, monkeypatch):
    import asyncio

    from app import memory
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    folder = tmp_path / "clips" / "kurz"
    folder.mkdir(parents=True)
    try:
        for i, (name, dur) in enumerate((("gluecklich4", 4), ("gluecklich5", 4), ("gluecklich6", 4), ("brust", 4))):
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
            await page.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;touchAsk=()=>null;
              const sp=document.getElementById('splash');if(sp)sp.remove();document.getElementById('chat').style.display='block';
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""")
            await asyncio.sleep(1.5)
            r = await page.evaluate("""async()=>{
              const vs=[document.getElementById('svid'),document.getElementById('svid2')],ring=document.getElementById('ztimer');
              const st=document.getElementById('stage'),R=st.getBoundingClientRect(),ar=1176/1764;let w=R.width,h=w/ar;if(h<R.height){h=R.height;w=h*ar;}
              const tap=()=>{ZT=0;st.onpointerdown(new PointerEvent('pointerdown',{clientX:R.left+(R.width-w)/2+0.5*w,clientY:R.top+(R.height-h)/2+0.23*h,button:0}));};
              const cur=()=>vs[SV].getAttribute('src')||'',touchOn=()=>vs.some(v=>v.classList.contains('on')&&(v.getAttribute('src')||'').includes('/brust.mp4'));
              const until=(f,ms)=>new Promise(r=>{const t0=performance.now(),t=()=>{if(f())r(true);else if(performance.now()-t0>ms)r(false);else requestAnimationFrame(t);};t();});
              const sleep=ms=>new Promise(r=>setTimeout(r,ms)),green=()=>ring.classList.contains('go');
              const out={};let min=1,run=true;
              const samp=()=>{if(!run)return;let gap=1;for(const v of vs)gap*=1-parseFloat(getComputedStyle(v).opacity)*(v.readyState>=2?1:0);min=Math.min(min,1-gap);requestAnimationFrame(samp);};samp();
              // 1. early in a loop: red, a tap does nothing
              await until(()=>zLeft()!==null&&zLeft()>ZWIN+0.8,9000);await sleep(150);const loop0=cur();out.redEarly=!green()&&zBlocked();
              tap();await sleep(500);out.earlyTapIgnored=!touchOn()&&cur()===loop0&&Date.now()>=ZBUSY;
              // 2. the window opens: green, the tap is taken, and her clip comes in where the loop hands over
              out.window=await until(()=>!zBlocked()&&cur()===loop0,9000);await sleep(150);out.greenInWindow=green();
              const lv=vs[SV],t1=performance.now();tap();out.taken=Date.now()<ZBUSY;
              await sleep(200);out.loopStillRunning=cur()===loop0&&!touchOn();
              out.first=await until(touchOn,4000);out.waitMs=Math.round(performance.now()-t1);out.loopAtSwap=+lv.currentTime.toFixed(2);out.loopLen=+lv.duration.toFixed(2);
              // 3. the touch clip has no window: red to its end, taps do nothing
              const tsrc=cur();let greenInTouch=0,taps=0;
              while(cur()===tsrc){if(green())greenInTouch++;tap();taps++;await sleep(120);if(taps>80)break;}
              out.greenInTouch=greenInTouch;out.tapsInTouch=taps;out.touchRanThrough=/gluecklich/.test(cur())&&!ZPEND&&Date.now()>=ZBUSY;
              // 4. the loop after it: red at first, green in its window, and the next touch is taken there
              await sleep(300);const loop1=cur();out.redAfterTouch=!green();tap();await sleep(300);out.tapAfterTouchIgnored=cur()===loop1&&Date.now()>=ZBUSY;
              out.window2=await until(()=>!zBlocked()&&cur()===loop1,9000);tap();out.second=await until(touchOn,4000);
              await sleep(900);run=false;out.min=+min.toFixed(2);return out;}""")
            await browser.close()
    finally:
        server.close()
    assert r["redEarly"] and r["earlyTapIgnored"], r          # at the wrong time nothing happens
    assert r["window"] and r["greenInWindow"] and r["taken"], r
    assert r["loopStillRunning"] and r["first"], r            # the tap does not cut in ...
    assert r["loopAtSwap"] >= r["loopLen"] - 0.6, r           # ... her clip comes when the loop is at its end
    assert r["waitMs"] <= 2600, r                             # at most the window later
    assert r["greenInTouch"] == 0 and r["tapsInTouch"] > 10 and r["touchRanThrough"], r   # the touch clip runs to its end
    assert r["redAfterTouch"] and r["tapAfterTouchIgnored"], r
    assert r["window2"] and r["second"], r                    # after one whole loop she takes the next touch
    assert r["min"] > 0.85, r                                 # and the picture never blanks
