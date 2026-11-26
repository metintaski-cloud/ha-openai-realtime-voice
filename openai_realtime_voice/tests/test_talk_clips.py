"""Her talk clips come in and go out at a hand over, never in the middle of a clip (2.175.0).

Until 2.174.3 `stageTalk` started the talk clip the moment her voice began (a cut into the running clip, also into a
touch clip) and put the loop back the moment she fell silent. Metin wants every change on the stage seamless ("muss
nahtlos sein", 26 Nov 2026), and he does not want every talk clip to end in the base pose ("sie endet immer mit Arm
auf Hüfte ... möchte diese monotonen Endungen vermeiden"), so there are two kinds of talk clips:

- `spricht`: base pose to base pose, one after the other while she talks;
- `sprichtrein` (base pose into a talk pose), `sprichtpose` (talk pose to talk pose), `sprichtraus` (back to the base
  pose). While she stands in the talk pose she takes no touch, because a touch clip begins in the base pose.
"""
import shutil
import subprocess

import pytest

from app import memory_web


def test_the_talk_chain_is_in_the_page():
    page = open(memory_web.__file__, encoding="utf-8").read()
    talk = page.split("function stageTalk(on)")[1].split("function moodShow")[0]
    assert "stageLoop(t)" not in talk and "stagePlay([]" not in talk          # no cut in, no cut out
    assert "if(DANCING||Date.now()<ZBUSY||ZPEND)return;" in talk               # a touch clip, a scene, a dance run on
    assert "CONT=live;" in talk                                               # her clip waits for the hand over
    assert "if(TALKING&&!talkOn()&&!DANCING&&talkStep())return;" in page       # she joins at the next hand over
    assert "ZKISS=false;if(TALKING&&talkStep())return;stageLoop(clipFor(STM));};" in page   # also after a touch clip
    assert "const zBlocked=()=>!!ZPEND||Date.now()<ZBUSY||talkPose()||!zOpen();" in page    # no touch in the talk pose
    assert "DANCING||talkOn())))stagePlay(once,clipFor(st));}" in page         # a new mood waits for the chain's end


def _clips(folder, names, dur=4):
    folder.mkdir(parents=True)
    for i, name in enumerate(names):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=size=240x360:rate=24:duration={dur}", "-vf", f"hue=h={i * 45}",
                        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "400k", "-g", "24",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(folder / (name + ".mp4"))], check=True)


async def _run(tmp_path, monkeypatch, names, script):
    import asyncio

    from app import memory
    playwright = pytest.importorskip("playwright.async_api")
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg here")
    try:
        _clips(tmp_path / "clips" / "kurz", names)
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
              document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));
              const vs=[document.getElementById('svid'),document.getElementById('svid2')];
              window.T={vs,cur:()=>(vs[SV].getAttribute('src')||'').split('?')[0].split('/').pop().replace('.mp4',''),
                until:(f,ms)=>new Promise(r=>{const t0=performance.now(),t=()=>{if(f())r(true);else if(performance.now()-t0>ms)r(false);else requestAnimationFrame(t);};t();}),
                sleep:ms=>new Promise(r=>setTimeout(r,ms)),min:1,run:true,log:[]};
              const R=document.getElementById('stage').getBoundingClientRect(),ar=1176/1764;let w=R.width,h=w/ar;if(h<R.height){h=R.height;w=h*ar;}
              T.tap=()=>{ZT=0;document.getElementById('stage').onpointerdown(new PointerEvent('pointerdown',{clientX:R.left+(R.width-w)/2+0.5*w,clientY:R.top+(R.height-h)/2+0.23*h,button:0}));};
              let last='';const samp=()=>{if(!T.run)return;let gap=1;for(const v of vs)gap*=1-parseFloat(getComputedStyle(v).opacity)*(v.readyState>=2?1:0);T.min=Math.min(T.min,1-gap);
                const c=T.cur();if(c!==last){const o=vs[1-SV];T.log.push({clip:c,prev:last,prevAt:o&&o.duration?+o.currentTime.toFixed(2):0,prevLen:o&&o.duration?+o.duration.toFixed(2):0});last=c;}requestAnimationFrame(samp);};samp();}""")
            await asyncio.sleep(1.5)
            await page.evaluate("T.min=1")                 # the picture counts from the first clip on, not from the empty stage
            r = await page.evaluate(script)
            await browser.close()
    finally:
        server.close()
    return r


def _seamless(r):
    """every change after the first clip happened at the end of the clip before it, and the picture never blanked"""
    for step in r["log"][1:]:
        assert step["prevAt"] >= step["prevLen"] - 0.7, (step, r)
    assert r["min"] > 0.85, r


async def test_a_simple_talk_clip_comes_in_and_goes_out_at_a_hand_over(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "spricht", "spricht2", "brust"), """async()=>{
      const out={};await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);const loop0=T.cur();
      stageTalk(true);await T.sleep(400);out.noCutIn=T.cur()===loop0;                      // her voice begins: the loop runs on
      out.talkCame=await T.until(()=>/^spricht/.test(T.cur()),5000);const t1=T.cur();
      out.second=await T.until(()=>/^spricht/.test(T.cur())&&T.cur()!==t1,7000);           // she still talks: the other talk clip
      await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);const t2=T.cur();
      stageTalk(false);await T.sleep(400);out.noCutOut=T.cur()===t2;                       // she falls silent: the talk clip runs on
      out.loopBack=await T.until(()=>/^gluecklich/.test(T.cur()),5000);
      await T.sleep(700);out.staysLoop=await T.until(()=>/^gluecklich/.test(T.cur())&&T.cur()!==(T.log[T.log.length-1]||{}).clip,1)||/^gluecklich/.test(T.cur());
      // she says one short thing and is silent again before her talk clip came in: the loop simply goes on
      await T.until(()=>zLeft()!==null&&zLeft()>2.9&&zLeft()<3.4,9000);const n0=T.log.length;stageTalk(true);await T.sleep(300);stageTalk(false);
      await T.until(()=>T.log.length>n0,6000);out.shortTalkNoClip=/^gluecklich/.test(T.cur());
      await T.sleep(600);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["noCutIn"] and r["talkCame"] and r["second"], r
    assert r["noCutOut"] and r["loopBack"] and r["staysLoop"], r
    assert r["shortTalkNoClip"], r
    _seamless(r)


async def test_into_the_talk_pose_through_it_and_back(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtpose2",
                                           "sprichtraus", "brust"), """async()=>{
      const out={},ring=document.getElementById('ztimer');await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);
      stageTalk(true);out.rein=await T.until(()=>T.cur()==='sprichtrein',5000);
      // in the talk pose the ring stays red and a tap does nothing, also in the window before the hand over
      await T.until(()=>zLeft()!==null&&zLeft()<1.5&&zLeft()>0.6,6000);out.redInPose=!ring.classList.contains('go')&&zBlocked();T.tap();await T.sleep(200);out.tapIgnored=Date.now()>=ZBUSY;
      out.pose=await T.until(()=>/^sprichtpose/.test(T.cur()),5000);const p1=T.cur();
      out.pose2=await T.until(()=>/^sprichtpose/.test(T.cur())&&T.cur()!==p1,7000);        // she still talks: another clip in the talk pose
      await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);stageTalk(false);   // silent: the way back comes at the hand over
      out.raus=await T.until(()=>T.cur()==='sprichtraus',5000);
      out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      out.order=T.log.map(x=>x.clip.replace(/[0-9]+$/,''));
      await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["rein"] and r["redInPose"] and r["tapIgnored"], r
    assert r["pose"] and r["pose2"] and r["raus"] and r["loop"], r
    order = r["order"]
    i = order.index("sprichtrein")
    assert order[i:i + 5] == ["sprichtrein", "sprichtpose", "sprichtpose", "sprichtraus", "gluecklich"], r
    _seamless(r)


async def test_a_touch_clip_is_not_interrupted_and_she_joins_after_it(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "spricht", "brust"), """async()=>{
      const out={};out.window=await T.until(()=>!zBlocked()&&zLeft()!==null,9000);T.tap();
      out.touch=await T.until(()=>T.cur()==='brust',4000);await T.sleep(800);
      stageTalk(true);await T.sleep(1200);out.touchRunsOn=T.cur()==='brust';                // her answer to the touch begins: the touch clip stays
      out.talkAfter=await T.until(()=>T.cur()==='spricht',6000);                           // and her talk clip follows it
      stageTalk(false);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["window"] and r["touch"] and r["touchRunsOn"] and r["talkAfter"] and r["loop"], r
    _seamless(r)


async def test_a_short_word_brings_no_talk_pose_and_talking_again_on_the_way_back_leads_in_again(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtraus"), """async()=>{
      const out={};await T.until(()=>zLeft()!==null&&zLeft()>2.9&&zLeft()<3.4,9000);const n0=T.log.length;
      stageTalk(true);await T.sleep(300);stageTalk(false);                                 // silent again before the way in came
      await T.until(()=>T.log.length>n0,6000);out.noRein=/^gluecklich/.test(T.cur());
      await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);stageTalk(true);
      out.rein=await T.until(()=>T.cur()==='sprichtrein',5000);await T.sleep(600);stageTalk(false);   // one sentence: in, and straight back
      out.raus=await T.until(()=>T.cur()==='sprichtraus',7000);await T.sleep(600);stageTalk(true);    // she talks again on the way back
      out.reinAgain=await T.until(()=>T.cur()==='sprichtrein',7000);await T.sleep(300);stageTalk(false);
      out.rausAgain=await T.until(()=>T.cur()==='sprichtraus',7000);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      out.order=T.log.map(x=>x.clip.replace(/[0-9]+$/,''));await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["noRein"] and r["rein"] and r["raus"] and r["reinAgain"] and r["rausAgain"] and r["loop"], r
    order = r["order"]
    i = order.index("sprichtrein")
    assert order[i:i + 5] == ["sprichtrein", "sprichtraus", "sprichtrein", "sprichtraus", "gluecklich"], r
    _seamless(r)
