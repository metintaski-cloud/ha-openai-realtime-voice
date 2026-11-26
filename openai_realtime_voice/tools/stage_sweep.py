"""Touch her at every moment of a loop and measure whether the picture ever blanks or cuts hard.

Made on 25 Nov 2026 after Metin saw a flicker at some touches (fixed in 2.172.1). It starts the real app page
with made up clips in a headless browser, waits for a loop change, touches her N ms later (19 offsets across a
4 s loop, the chest and the po with its turn before, on a fast and on a throttled line) and samples every
animation frame until she is back in the loop:
  Deckung  = 1 - (1 - opacity of video 1 with a picture) * (1 - the same for video 2); 1 means fully covered,
             about 0.96 is the normal blend of a tight hand over, far less is a flicker
  harte Schnitte = the top video changed from one frame to the next with no blend
Run from openai_realtime_voice:  python3 tools/stage_sweep.py   (about 12 minutes; needs ffmpeg and playwright)
Result on 2.172.1: 76 touches, lowest cover 0.96, no hard cut, her reaction came every time.
"""
import asyncio, subprocess, os, sys, tempfile, json
sys.path.insert(0, os.getcwd())
tmp = tempfile.mkdtemp()
for k in ("SCHNITT","TEMPO","TON","STAND","VORLAUF","KURVE"): os.environ["LEYLA_"+k] = tmp + "/" + k + ".json"
os.environ["LEYLA_MOBIL_DIR"] = tmp + "/mobil"
from app import memory, memory_web
from playwright.async_api import async_playwright
def enc(path, hue, dur=4):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg","-v","error","-y","-f","lavfi","-i",f"testsrc2=size=480x720:rate=24:duration={dur}","-vf",f"hue=h={hue}","-c:v","libx264","-preset","veryfast","-b:v","800k","-g","24","-pix_fmt","yuv420p","-movflags","+faststart",path],check=True)
JS = """async([delay,zy])=>{
  const vs=[document.getElementById('svid'),document.getElementById('svid2')];
  // wait until she is back in a loop and free
  await new Promise(r=>{const t=()=>{const v=vs[SV];if(Date.now()>=ZBUSY&&Date.now()>=ZREST&&!ZPEND&&/gluecklich/.test(v.getAttribute('src')||'')&&v.classList.contains('on'))r();else setTimeout(t,50);};t();});
  const sv0=SV;await new Promise(r=>{const t=()=>{if(SV!==sv0)r();else requestAnimationFrame(t);};t();});
  await new Promise(r=>setTimeout(r,delay));
  const st=document.getElementById('stage'),R=st.getBoundingClientRect(),ar=1176/1764;let w=R.width,h=w/ar;if(h<R.height){h=R.height;w=h*ar;}
  let min=1,at=0,run=true,pop=0,shown=0,prev=null;const t0=performance.now();
  const samp=()=>{if(!run)return;let gap=1;const row=vs.map(v=>parseFloat(getComputedStyle(v).opacity)*(v.readyState>=2?1:0));
    for(const o of row)gap*=1-o;const c=1-gap;if(c<min){min=c;at=Math.round(performance.now()-t0);}
    // a pop: the video on top changes from one frame to the next with no blend (top = zIndex 1)
    const top=vs.findIndex(v=>v.style.zIndex==='1');const key=top+'|'+(vs[top]?vs[top].getAttribute('src'):'');
    if(prev&&prev.key!==key&&row[top]>0.9)pop++;prev={key};
    if(vs.some(v=>v.classList.contains('on')&&/brust|po|hinten/.test(v.getAttribute('src')||'')))shown=1;
    requestAnimationFrame(samp);};samp();
  st.onpointerdown(new PointerEvent('pointerdown',{clientX:R.left+(R.width-w)/2+0.5*w,clientY:R.top+(R.height-h)/2+zy*h,button:0}));
  // until her reaction is through and she has been back in the loop for 1.2 s
  await new Promise(r=>{let back=0;const t=()=>{const v=vs[SV];const inloop=Date.now()>=ZBUSY&&/gluecklich/.test(v.getAttribute('src')||'')&&v.classList.contains('on');
    if(inloop){if(!back)back=performance.now();if(performance.now()-back>1200)return r();}else back=0;if(performance.now()-t0>25000)return r();setTimeout(t,50);};t();});
  run=false;return {min:+min.toFixed(2),at,pop,shown,ms:Math.round(performance.now()-t0)};}"""
async def main():
    for i,n in enumerate(("gluecklich4","gluecklich5","gluecklich6")): enc(f"{tmp}/clips/kurz/{n}.mp4", i*50)
    for i,n in enumerate(("brust","po","hinten")): enc(f"{tmp}/clips/kurz/{n}.mp4", 180+i*40, 3)
    memory_web.CLIPS_DIR = tmp + "/clips"; memory_web.MOBIL=None
    s = await memory_web.start_http(memory.MemoryStore(tmp + "/m.json"), None, host="127.0.0.1", port=0)
    port = s.sockets[0].getsockname()[1]; errs=[]
    offsets=[0,30,100,200,300,450,600,800,860,950,1200,1800,2400,3000,3300,3500,3650,3740,3800]
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        for label,mbit in (("schnelle Leitung",0),("langsame Leitung (1 Mbit/s)",1.0)):
            for zone,zy in (("Brust",0.23),("Po mit Umdrehen davor",0.50)):
                pg = await b.new_page(viewport={"width": 400, "height": 820}); pg.on("pageerror", lambda e: errs.append(str(e)))
                await pg.goto(f"http://127.0.0.1:{port}/"); await asyncio.sleep(1.0)
                if mbit:
                    cdp=await pg.context.new_cdp_session(pg); await cdp.send("Network.enable"); await cdp.send("Network.setCacheDisabled",{"cacheDisabled":True}); await cdp.send("Network.emulateNetworkConditions",{"offline":False,"latency":150,"downloadThroughput":int(mbit*125000),"uploadThroughput":60000})
                await pg.evaluate("""async()=>{CODE='x';STM={mood:'verliebt',low:false,level:'gut',outfit:'arbeit',game:{done:true}};LASTST=STM;const sp=document.getElementById('splash');if(sp)sp.remove();
                  touchAsk=()=>null;
                  document.getElementById('chat').style.display='block';document.body.classList.add('chatfull');document.getElementById('stage').style.display='block';await clipsLoad();stagePlay([],clipFor(STM));}""")
                await asyncio.sleep(2.0)
                res=[]
                for d in offsets:
                    r = await pg.evaluate(JS, [d, zy]); res.append((d,r)); print('  ',d,r,flush=True)
                bad=[(d,r) for d,r in res if r["min"]<0.85 or r["pop"] or not r["shown"]]
                print(f"ERGEBNIS {label}, {zone}: {len(res)} Berührungen, kleinste Deckung {min(r['min'] for d,r in res)}, harte Schnitte {sum(r['pop'] for d,r in res)}, Reaktion kam {sum(r['shown'] for d,r in res)} mal")
                for d,r in bad: print("   auffällig bei", d, "ms:", r)
                await pg.close()
        await b.close()
    s.close(); print("Fehler:", errs)
asyncio.run(main())
