"""Her talk clips: there when her voice begins, and never a cut on the way back (2.175.0, 2.176.0).

2.176.0 (Metin, 26 Nov 2026, 12:27: "das muss sofort kommen und nicht wenn es eine lange Geschichte wird"): while she
listens (Live, a voice message being recorded) she already takes the talk pose, at a hand over; and when her voice
begins while she is in no talk clip, her clip starts at once with a short soft blend. The text below is from 2.175.0:


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
    assert "stageLoop(t)" not in talk and "stagePlay([]" not in talk          # no cut back into the loop
    assert "TALKOFF=setTimeout(()=>{TALKV=false;talkWant(false);},TALK_HOLD_MS)" in talk   # a breath is not the end of her talking
    assert "if(CLIPS===null||!STM||DANCING||Date.now()<ZBUSY||ZPEND)return;" in talk   # a touch clip, a scene, a dance run on
    assert "if(voice&&on&&k!=='rein'&&k!=='pose'&&k!=='loop'){" in talk          # her voice begins: at once
    assert "CONT=live;" in talk                                               # everything else waits for the hand over
    assert "LIVE=L;mark('ws');stageListen(true);" in page and "stageTalk(false);stageListen(false);" in page   # a live call
    assert "snd.on();stageListen(true);" in page                              # a voice message being recorded
    assert "if(TALKS&&!talkOn()&&!DANCING&&talkStep())return;" in page         # she joins at the next hand over
    assert "ZKISS=false;if(TALKS&&talkStep())return;stageLoop(clipFor(STM));};" in page   # also after a touch clip
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


def _seamless(r, quick=()):
    """every change after the first clip happened at the end of the clip before it (except the ones named in quick:
    her voice began), and the picture never blanked"""
    for i, step in enumerate(r["log"]):
        if i == 0 or step["clip"] in quick and step["prevAt"] < step["prevLen"] - 0.7 and not step.get("used"):
            continue
        assert step["prevAt"] >= step["prevLen"] - 0.7, (step, r)
    assert r["min"] > 0.85, r


MID = "await T.until(()=>zLeft()!==null&&zLeft()>2.6&&zLeft()<3.2,9000);"


async def test_her_voice_begins_and_her_talk_clip_is_there_at_once(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "spricht", "spricht2", "brust"), """async()=>{
      const out={};""" + MID + """const t0=performance.now();
      stageTalk(true);out.talkCame=await T.until(()=>/^spricht/.test(T.cur()),1500);out.ms=Math.round(performance.now()-t0);const t1=T.cur();
      out.second=await T.until(()=>/^spricht/.test(T.cur())&&T.cur()!==t1,7000);           // she still talks: the other talk clip, at the hand over
      """ + MID + """const t2=T.cur();
      stageTalk(false);await T.sleep(1900);out.noCutOut=T.cur()===t2;                      // she falls silent: the talk clip runs on
      out.loopBack=await T.until(()=>/^gluecklich/.test(T.cur()),5000);
      await T.sleep(600);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["talkCame"] and r["ms"] < 1500 and r["second"], r
    assert r["noCutOut"] and r["loopBack"], r
    first = next(x for x in r["log"] if x["clip"].startswith("spricht"))
    assert first["prevAt"] < first["prevLen"] - 0.7, r                                     # it did not wait for the end of the loop
    for step in r["log"][r["log"].index(first) + 1:]:
        assert step["prevAt"] >= step["prevLen"] - 0.7, (step, r)                          # everything after it is seamless
    assert r["min"] > 0.85, r


async def test_while_she_listens_she_takes_the_talk_pose_and_stays_in_it(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtpose2",
                                           "sprichtraus", "brust"), """async()=>{
      const out={},ring=document.getElementById('ztimer');""" + MID + """const l0=T.cur();
      LIVE={test:1};stageListen(true);await T.sleep(400);out.noCut=T.cur()===l0;           // he taps Live: no voice yet, so no cut
      out.rein=await T.until(()=>T.cur()==='sprichtrein',5000);
      // in the talk pose the ring stays red and a tap does nothing, also in the window before the hand over
      await T.until(()=>zLeft()!==null&&zLeft()<1.5&&zLeft()>0.6,6000);out.redInPose=!ring.classList.contains('go')&&zBlocked();T.tap();await T.sleep(200);out.tapIgnored=Date.now()>=ZBUSY;
      const n0=T.log.length;stageTalk(true);await T.sleep(500);out.voiceChangesNothing=T.log.length===n0;   // she is in the pose already
      out.pose=await T.until(()=>/^sprichtpose/.test(T.cur()),5000);const p1=T.cur();stageTalk(false);
      out.pose2=await T.until(()=>/^sprichtpose/.test(T.cur())&&T.cur()!==p1,7000);        // silent, but the call goes on: she stays in the pose
      """ + MID + """LIVE=null;stageListen(false);                                          // he hangs up: the way back comes at the hand over
      out.raus=await T.until(()=>T.cur()==='sprichtraus',5000);
      out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      // a voice message that is thrown away before the way in came: the loop simply goes on
      """ + MID + """const n1=T.log.length;stageListen(true);await T.sleep(300);stageListen(false);
      await T.until(()=>T.log.length>n1,6000);out.thrownAway=/^gluecklich/.test(T.cur());
      out.order=T.log.map(x=>x.clip.replace(/[0-9]+$/,''));await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["noCut"] and r["rein"] and r["redInPose"] and r["tapIgnored"] and r["voiceChangesNothing"], r
    assert r["pose"] and r["pose2"] and r["raus"] and r["loop"] and r["thrownAway"], r
    order = r["order"]
    i = order.index("sprichtrein")
    assert order[i:i + 5] == ["sprichtrein", "sprichtpose", "sprichtpose", "sprichtraus", "gluecklich"], r
    _seamless(r)


async def test_a_voice_message_she_listens_then_her_voice_takes_over(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtraus"), """async()=>{
      const out={};""" + MID + """stageListen(true);out.rein=await T.until(()=>T.cur()==='sprichtrein',5000);
      await T.sleep(500);stageTalk(true);out.listenOver=LISTEN===false&&TALKS===true;      // her answer plays: the voice holds the pose now
      out.pose=await T.until(()=>T.cur()==='sprichtpose',5000);await T.sleep(400);stageTalk(false);
      out.raus=await T.until(()=>T.cur()==='sprichtraus',8000);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["rein"] and r["listenOver"] and r["pose"] and r["raus"] and r["loop"], r
    _seamless(r)


async def test_a_touch_clip_is_not_interrupted_and_she_joins_after_it(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "spricht", "brust"), """async()=>{
      const out={};out.window=await T.until(()=>!zBlocked()&&zLeft()!==null,9000);T.tap();
      out.touch=await T.until(()=>T.cur()==='brust',4000);await T.sleep(800);
      stageTalk(true);await T.sleep(1200);out.touchRunsOn=T.cur()==='brust';                // her answer to the touch begins: the touch clip stays
      out.talkAfter=await T.until(()=>T.cur()==='spricht',6000);                           // and her talk clip follows it
      stageTalk(false);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),9000);
      await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["window"] and r["touch"] and r["touchRunsOn"] and r["talkAfter"] and r["loop"], r
    _seamless(r)


async def test_one_short_answer_in_and_back_and_her_voice_on_the_way_back(tmp_path, monkeypatch):
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtraus"), """async()=>{
      const out={};""" + MID + """stageTalk(true);out.rein=await T.until(()=>T.cur()==='sprichtrein',1500);   // at once
      await T.sleep(300);stageTalk(false);                                                  // one short sentence
      out.raus=await T.until(()=>T.cur()==='sprichtraus',8000);await T.sleep(700);
      stageTalk(true);out.reinAgain=await T.until(()=>T.cur()==='sprichtrein',1500);        // she talks again on the way back: at once
      await T.sleep(300);stageTalk(false);
      out.rausAgain=await T.until(()=>T.cur()==='sprichtraus',8000);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      out.order=T.log.map(x=>x.clip.replace(/[0-9]+$/,''));await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["rein"] and r["raus"] and r["reinAgain"] and r["rausAgain"] and r["loop"], r
    order = r["order"]
    i = order.index("sprichtrein")
    assert order[i:i + 5] == ["sprichtrein", "sprichtraus", "sprichtrein", "sprichtraus", "gluecklich"], r
    assert r["min"] > 0.85, r
    for step in r["log"][1:]:
        if step["clip"] != "sprichtrein":
            assert step["prevAt"] >= step["prevLen"] - 0.7, (step, r)                      # only her voice starts a clip early


async def test_her_voice_coming_in_pieces_still_brings_her_talk_clips(tmp_path, monkeypatch):
    """In a live talk her voice arrives in small pieces and she breathes between sentences: the page hears
    'speaks, silent, speaks' many times a second. That must not keep her talk clips away (Metin, 26 Nov 2026,
    12:08, after a live talk of 35 s in the short work dress: "ist nichts")."""
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "sprichtrein", "sprichtpose", "sprichtpose2",
                                           "sprichtraus"), """async()=>{
      const out={};""" + MID + """
      let flap=true;(async()=>{while(flap){stageTalk(true);await T.sleep(90);stageTalk(false);await T.sleep(30);}})();
      out.rein=await T.until(()=>T.cur()==='sprichtrein',1500);
      out.pose=await T.until(()=>/^sprichtpose/.test(T.cur()),6000);
      flap=false;await T.sleep(200);stageTalk(false);
      out.raus=await T.until(()=>T.cur()==='sprichtraus',9000);out.loop=await T.until(()=>/^gluecklich/.test(T.cur()),7000);
      out.order=T.log.map(x=>x.clip.replace(/[0-9]+$/,''));await T.sleep(300);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["rein"] and r["pose"] and r["raus"] and r["loop"], r
    assert r["order"].count("sprichtrein") == 1, r
    assert r["min"] > 0.85, r


async def test_a_light_runs_around_the_edge_instead_of_the_ring(tmp_path, monkeypatch):
    """2.177.0 (Metin, 26 Nov 2026): the turning ring is replaced by a soft light in the colours of her mist that runs
    around the edge of the picture while the clip runs; while she takes a touch the whole edge glows in those colours,
    not in green."""
    r = await _run(tmp_path, monkeypatch, ("gluecklich4", "gluecklich5", "brust"), """async()=>{
      const out={},e=document.getElementById('zedge'),ring=document.getElementById('ztimer'),us=[...e.querySelectorAll('u')],glow=e.querySelector('i');
      const pos=()=>us.map(u=>u.style.transform).join('|');
      out.inStage=e.parentElement.id==='stage'&&us.length===4;out.ringHidden=getComputedStyle(ring.querySelector('svg')).opacity==='0';
      out.noPointer=getComputedStyle(e).pointerEvents==='none';
      await T.until(()=>zLeft()!==null&&zLeft()>2.6,9000);const a=pos();await T.sleep(500);out.moves=pos()!==a;
      out.blockedDark=zBlocked()&&glow.style.opacity==='0';
      await T.until(()=>!zBlocked()&&zLeft()!==null,9000);await T.sleep(250);out.openGlows=ring.classList.contains('go')&&glow.style.opacity==='1';
      const sh=getComputedStyle(glow).boxShadow;out.notGreen=!/34, 197, 94/.test(sh)&&!/34, 211, 238/.test(sh)&&/56, 168, 255/.test(sh);   // the blue of her mist, no green, no cyan
      T.tap();await T.until(()=>Date.now()<ZBUSY||!!ZPEND,1500);ZGOLD=Date.now()+1500;ZCOLNOW='#ef4444';await T.sleep(300);
      const sh2=getComputedStyle(glow).boxShadow;out.takenViolet=/168, 85, 247/.test(sh2)&&!/239, 68, 68/.test(sh2)&&!/250, 204, 21/.test(sh2)&&glow.style.opacity==='0.85';   // no zone red, no gold
      ZBUSY=0;ZPEND=null;ZREST=T.vs[SV].getAttribute('src');await T.sleep(180);const sh3=getComputedStyle(glow).boxShadow;out.fadesInItsColour=glow.style.opacity==='0'&&/168, 85, 247/.test(sh3)&&!/56, 168, 255/.test(sh3);   // going out, it stays violet
      // one lap per clip: the four pieces take turns, never more than two are on their edge at once
      const seen=new Set();let most=0;for(let i=0;i<70;i++){const on=us.map(u=>!/^translate3d\\(0px, 0px, 0px\\)$/.test(u.style.transform));most=Math.max(most,on.filter(Boolean).length);on.forEach((x,k)=>{if(x)seen.add(k);});await T.sleep(100);}
      out.allFour=seen.size===4;out.most=most;
      // a lap begins and ends at the bottom edge, where the text field is (2.177.2), not at the top left
      await T.until(()=>zLeft()!==null&&zLeft()<0.45&&zLeft()>0.1,9000);await T.sleep(150);                 // the last moment before the hand over: the lap is through
      const m=/translate3d\\((-?[0-9.]+)px/.exec(us[2].style.transform),W=e.clientWidth;out.restX=m?Math.round(-parseFloat(m[1])/W*100):null;
      out.restBottom=out.restX!==null&&out.restX>=68&&out.restX<=72&&/^translate3d\\(0px, 0px, 0px\\)$/.test(us[0].style.transform);T.run=false;out.log=T.log;out.min=+T.min.toFixed(2);return out;}""")
    assert r["inStage"] and r["ringHidden"] and r["noPointer"] and r["moves"], r
    assert r["blockedDark"] and r["openGlows"] and r["notGreen"] and r["takenViolet"] and r["fadesInItsColour"], r
    assert r["allFour"] and r["most"] <= 2 and r["restBottom"], r
