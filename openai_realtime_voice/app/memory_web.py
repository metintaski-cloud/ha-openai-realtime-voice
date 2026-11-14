"""
A small web page for Leyla's memory: the open lists with a box in front of every entry and
one button that deletes the ticked entries. Opened on the phone in the home network and put
on the home screen, it works like an app and refreshes itself every few seconds.

The private list is never shown here. There is no login on purpose: the page is only
reachable from the home network. Deleting removes the entry from the memory file and
brings the Home Assistant to-do list in line (todo_sync.kick).

Plain asyncio HTTP, no extra dependency. Pure helpers (`snapshot`, `delete_items`) take a
MemoryStore, so tests need no network.
"""
import asyncio
import json
import logging
import os
from typing import Optional

from app import memory

logger = logging.getLogger(__name__)

TITLES = ((memory.FAMILY, "Familie und Haushalt"),
          (memory.FRIENDS, "Freunde und Verwandte"),
          (memory.LEYLA, "Leylas eigene Geschichte"))
MAX_BODY = 64 * 1024
ICON_PATH = os.path.join(os.path.dirname(__file__), "memory_icon.png")


def snapshot(store: memory.MemoryStore) -> dict:
    data = store.load_all()
    return {"lists": [{"kind": k, "title": t, "items": data.get(k, [])} for k, t in TITLES]}


def delete_items(store: memory.MemoryStore, items) -> int:
    """Delete (kind, text) pairs from the open lists, return how many were removed."""
    wanted: dict = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("kind") in dict(TITLES) and isinstance(it.get("text"), str):
            wanted.setdefault(it["kind"], set()).add(it["text"])
    removed = 0
    for kind, texts in wanted.items():
        facts = store.load(kind)
        keep = [f for f in facts if f not in texts]
        if len(keep) != len(facts):
            removed += len(facts) - len(keep)
            store.save(keep, kind)
    return removed


def edit_item(store: memory.MemoryStore, kind, old, new) -> bool:
    """Replace one entry in place. False when it is unknown, empty, too long or a duplicate."""
    if kind not in dict(TITLES) or not isinstance(old, str) or not isinstance(new, str):
        return False
    new = " ".join(new.split())
    if not new or len(new) > memory.MAX_FACT_CHARS:
        return False
    facts = store.load(kind)
    if old not in facts or (new != old and new in facts):
        return False
    if new != old:
        facts[facts.index(old)] = new
        store.save(facts, kind)
    return True


SEP = " | "


def edit_folder(store: memory.MemoryStore, kind, old, fields) -> Optional[str]:
    """Replace the points of one entry ("Person: Metin | Zugehörigkeit: ... | Alter: 45"): the first part
    (the name) stays, `fields` become the rest in the given order. Returns the new text, or None when the entry
    is unknown or changed meanwhile (`old` must be what is stored now), too long or a duplicate."""
    if kind not in dict(TITLES) or not isinstance(old, str) or not isinstance(fields, list):
        return None
    clean = []
    for f in fields:
        if not isinstance(f, str):
            return None
        f = " ".join(f.replace(SEP, " / ").split())
        if f:
            clean.append(f)
    new = SEP.join([old.split(SEP)[0]] + clean)
    if len(new) > memory.MAX_FACT_CHARS:
        return None
    facts = store.load(kind)
    if old not in facts or (new != old and new in facts):
        return None
    if new != old:
        facts[facts.index(old)] = new
        store.save(facts, kind)
    return new


def move_items(store: memory.MemoryStore, lists) -> bool:
    """Apply a new order and distribution of the open lists. Only accepted when it holds
    exactly the entries that are stored now (nothing lost, nothing new), so a page that is
    out of date cannot overwrite what Leyla learned meanwhile."""
    if not isinstance(lists, dict):
        return False
    new = {}
    for kind, _ in TITLES:
        v = lists.get(kind)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return False
        new[kind] = v
    cur = store.load_all()
    if sorted(x for k, _ in TITLES for x in cur.get(k, [])) != sorted(
            x for v in new.values() for x in v):
        return False
    if len(new[memory.LEYLA]) > memory.MAX_LEYLA:
        return False
    if any(new[k] != cur.get(k, []) for k, _ in TITLES):
        store.save_all(new)
    return True


PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#08103a">
<meta name="mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" sizes="512x512" href="/icon.png?v=5">
<link rel="apple-touch-icon" href="/icon.png?v=5">
<title>Leyla Gedächtnis</title>
<style>
html{background:#08103a}
:root{color-scheme:dark;--cy:#22d3ee;--bl:#3b82f6;--vi:#a855f7;--mg:#d946ef}
body{margin:0;background:radial-gradient(120% 60% at 50% 0,#14206b 0,#08103a 45%,#040822 100%) fixed;color:#e8ecff;font:17px/1.4 system-ui,sans-serif;padding-bottom:96px}
header{display:flex;align-items:center;gap:12px;padding:16px}
header img{width:44px;height:44px;border-radius:11px;box-shadow:0 0 14px #3b82f688}
h1{font-size:21px;margin:0;background:linear-gradient(90deg,var(--cy),var(--vi),var(--mg));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{font-size:14px;margin:22px 16px 6px;color:var(--cy);text-transform:uppercase;letter-spacing:.08em;text-shadow:0 0 10px #22d3ee66}
label{display:flex;gap:14px;align-items:flex-start;margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;box-shadow:0 0 12px #3b82f622 inset}
label.on{background:#3a1457cc;border-color:var(--mg);box-shadow:0 0 14px #d946ef55}
input[type=checkbox]{width:24px;height:24px;flex:none;margin-top:2px;accent-color:var(--vi)}
.t{flex:1;word-break:break-word}.t b{color:#fff}.t small{display:block;color:#9fb4ff}
.empty{margin:0 16px;padding:8px 0;color:#7b8ccf}
.list:has(label) .empty{display:none}
label{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
textarea{-webkit-user-select:text;user-select:text;width:100%;box-sizing:border-box;min-height:140px;font:inherit;color:#fff;background:#060c33;border:1px solid var(--bl);border-radius:10px;padding:8px}
.row{display:flex;gap:10px;margin-top:8px}.row button{padding:10px;font-size:16px;background:linear-gradient(90deg,var(--bl),var(--vi));box-shadow:none}.row .no{background:#2a3468}
.ph{margin:0 12px 8px;border:2px dashed var(--cy);border-radius:12px;background:#22d3ee14}
.float{position:fixed;left:8px;right:8px;z-index:10;pointer-events:none;background:#1a1f6e;border:1px solid var(--cy);border-radius:12px;box-shadow:0 8px 24px #000a,0 0 18px #22d3ee66;opacity:.97;margin:0}
#back{display:none;width:auto;font-size:26px;line-height:1;padding:6px 14px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
.fold .t{position:relative;padding-right:26px}.fold .t::after{content:'\\203A';position:absolute;right:2px;top:50%;margin-top:-18px;font-size:34px;color:var(--cy)}
.add{margin:4px 12px;width:calc(100% - 24px);display:block;background:#1b2a6b;border:1px solid var(--cy);box-shadow:none;font-size:16px;padding:12px}
.addbox{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid var(--cy);border-radius:12px}
#snd{width:auto;margin-left:auto;font-size:14px;padding:8px 12px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
#bar{position:fixed;left:0;right:0;bottom:0;padding:12px 16px;background:#060b2ae6;border-top:1px solid #3b82f655;backdrop-filter:blur(6px)}
button{width:100%;font-size:18px;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,var(--vi),var(--mg));color:#fff;box-shadow:0 0 16px #a855f777}
button:disabled{background:#1b2152;color:#6c79b8;box-shadow:none}
#splash{position:fixed;inset:0;z-index:100;background:#08103a;display:flex;align-items:center;justify-content:center;transition:opacity .45s}
#splash.out{opacity:0;pointer-events:none}
.sp{position:relative;width:220px;height:220px}
.sp img{position:absolute;left:50%;top:50%;width:128px;height:128px;margin:-64px 0 0 -64px;border-radius:28px;animation:pulse 1.6s ease-in-out infinite}
.sp svg{position:absolute;inset:0;transform:rotate(-90deg);filter:drop-shadow(0 0 8px #a855f7aa)}
.trk{fill:none;stroke:#ffffff14;stroke-width:6}
.rg{fill:none;stroke:url(#rg);stroke-width:6;stroke-linecap:round;stroke-dasharray:100;stroke-dashoffset:100;animation:fill 1.9s cubic-bezier(.5,0,.2,1) forwards}
@keyframes fill{to{stroke-dashoffset:0}}
@keyframes pulse{50%{transform:scale(1.05)}}
@media (prefers-reduced-motion:reduce){.rg{animation-duration:.1s}.sp img{animation:none}}
</style></head><body>
<div id="splash"><div class="sp"><img src="/icon.png?v=5" alt=""><svg viewBox="0 0 200 200"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#a855f7"/><stop offset="1" stop-color="#d946ef"/></linearGradient></defs><circle class="trk" cx="100" cy="100" r="90"/><circle class="rg" cx="100" cy="100" r="90" pathLength="100"/></svg></div></div>
<header><button id="back">&#8249;</button><img src="/icon.png?v=5" alt=""><h1>Leyla Gedächtnis</h1><button id="snd"></button></header><div id="root"></div>
<div id="bar"><button id="del" disabled>Markierte löschen</button></div>
<script>
let view=null,sel=new Set(),last='',editing=false,dragging=false,justDragged=0,AC=null,soundOn=true;
try{soundOn=localStorage.getItem('snd')!=='0'}catch(e){}
function bus(){if(!AC){AC=new(window.AudioContext||window.webkitAudioContext)();const m=AC.createGain();m.gain.value=.9;
 const d=AC.createDelay();d.delayTime.value=.11;const fb=AC.createGain();fb.gain.value=.32;const wet=AC.createGain();wet.gain.value=.4;
 m.connect(AC.destination);m.connect(d);d.connect(fb);fb.connect(d);d.connect(wet);wet.connect(AC.destination);AC.bus=m;}
 if(AC.state==='suspended')AC.resume();return AC.bus;}
function sw(type,f1,f2,dur,vol,at,c1,c2){const t=AC.currentTime+(at||0),o=AC.createOscillator(),f=AC.createBiquadFilter(),g=AC.createGain();
 o.type=type;o.frequency.setValueAtTime(f1,t);o.frequency.exponentialRampToValueAtTime(f2,t+dur);
 f.type='lowpass';f.frequency.setValueAtTime(c1||6000,t);f.frequency.exponentialRampToValueAtTime(c2||6000,t+dur);
 g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(vol,t+.01);g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
 o.connect(f);f.connect(g);g.connect(AC.bus);o.start(t);o.stop(t+dur+.05);}
function synth(fn){if(!soundOn)return;try{bus();fn();}catch(e){}}
const snd={
 on:()=>synth(()=>{sw('sawtooth',500,1500,.14,.07,0,900,5000);sw('sine',1000,3000,.14,.08,0);}),
 off:()=>synth(()=>{sw('sawtooth',1400,420,.14,.06,0,5000,700);sw('sine',1300,600,.12,.06,0);}),
 pick:()=>synth(()=>{sw('square',700,1100,.09,.04,0,3000,3000);sw('sine',1400,2200,.1,.06,.04);}),
 drop:()=>synth(()=>{sw('triangle',1100,1100,.08,.1,0);sw('triangle',740,740,.14,.1,.07);}),
 save:()=>synth(()=>{[880,1320,1760].forEach((f,i)=>{sw('sawtooth',f,f*1.01,.12,.05,i*.07,4000,4000);sw('sine',f*2,f*2,.12,.05,i*.07);});}),
 del:()=>synth(()=>{sw('sawtooth',1800,90,.45,.09,0,6000,200);sw('square',900,60,.4,.04,0,2500,150);})};
function sndLabel(){const b=document.getElementById('snd');b.textContent=soundOn?'Ton an':'Ton aus';}
const key=(k,t)=>k+'\\u0000'+t;
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
const SEP=' | ';
function parts(t){const p=t.split(SEP);return {head:p[0],fields:p.slice(1),folder:p[0].startsWith('Person:')||p.length>1};}
function title(h){return h.startsWith('Person:')?h.slice(7).trim():h;}
function fmt(t){if(view)return esc(t);const p=parts(t);if(!p.folder)return esc(t);
 const keys=p.fields.map(x=>{const i=x.indexOf(':');return i>0?x.slice(0,i):x.slice(0,18)}).slice(0,4).join(', ');
 return '<b>'+esc(title(p.head))+'</b><small>'+p.fields.length+(p.fields.length==1?' Punkt':' Punkte')+(keys?': '+esc(keys):'')+'</small>';}
async function saveFields(fields){if(!view)return false;
 const r=await fetch('/api/folder',{method:'POST',body:JSON.stringify({kind:view.kind,old:view.text,fields})});
 const j=await r.json();if(j.ok)view.text=j.text;return j.ok;}
function openFolder(kind,head){view={kind,head,text:''};sel=new Set();last='';history.pushState({f:1},'');window.scrollTo(0,0);snd.on();load();}
function closeFolder(){view=null;sel=new Set();last='';load();}
window.addEventListener('popstate',()=>{if(view)closeFolder();});
document.getElementById('back').onclick=()=>history.back();
function startEdit(span,kind,text,saver){editing=true;span.onclick=null;span.innerHTML='';
 const ta=document.createElement('textarea');ta.value=text;
 const row=document.createElement('div');row.className='row';
 const ok=document.createElement('button');ok.textContent='Speichern';
 const no=document.createElement('button');no.textContent='Abbrechen';no.className='no';
 no.onclick=()=>{editing=false;last='';load();};
 ok.onclick=async()=>{ok.disabled=true;let good;
  if(saver)good=ta.value.trim()?await saver(ta.value):false;
  else{const r=await fetch('/api/edit',{method:'POST',body:JSON.stringify({kind,old:text,new:ta.value})});good=(await r.json()).ok;}
  if(!good){alert('Nicht gespeichert: leer, zu lang oder schon vorhanden.');ok.disabled=false;return;}
  snd.save();editing=false;last='';load();};
 row.append(ok,no);span.append(ta,row);ta.focus();}
function makeRow(kind,t){const lab=document.createElement('label');lab._t=t;
 const cb=document.createElement('input');cb.type='checkbox';cb.checked=sel.has(key(kind,t));lab.className=cb.checked?'on':'';
 cb.onchange=()=>{const k=key(lab.parentNode.dataset.kind,t);cb.checked?(sel.add(k),snd.on()):(sel.delete(k),snd.off());lab.classList.toggle('on',cb.checked);upd();};
 const s=document.createElement('span');s.className='t';s.innerHTML=fmt(t);
 const pt=parts(t),isFolder=!view&&pt.folder;if(isFolder)lab.classList.add('fold');
 s.onclick=e=>{e.preventDefault();if(Date.now()-justDragged<700)return;const kd=lab.parentNode.dataset.kind;
  if(isFolder)return openFolder(kd,pt.head);
  if(view){const fl=[...document.querySelectorAll('.list label')].map(x=>x._t),i=fl.indexOf(t);
   return startEdit(s,kd,t,v=>{fl[i]=v;return saveFields(fl);});}
  startEdit(s,kd,t);};
 lab.append(cb,s);attachDrag(lab);return lab;}
function render(d){const root=document.getElementById('root');root.innerHTML='';const all=new Set();
 const back=document.getElementById('back'),h1=document.querySelector('h1');
 let found=null;
 if(view){const l=d.lists.find(x=>x.kind===view.kind);const t=l&&l.items.find(x=>parts(x).head===view.head);if(t){found={l,t};}else view=null;}
 back.style.display=view?'block':'none';h1.textContent=view?title(view.head):'Leyla Gedächtnis';
 if(found){view.text=found.t;const fields=parts(found.t).fields;
  const box=document.createElement('div');box.className='list';box.dataset.kind=found.l.kind;
  const h=document.createElement('h2');h.textContent='Punkte ('+fields.length+')';box.appendChild(h);
  const e=document.createElement('div');e.className='empty';e.textContent='leer';box.appendChild(e);
  for(const f of fields){all.add(key(found.l.kind,f));box.appendChild(makeRow(found.l.kind,f));}
  root.appendChild(box);
  const add=document.createElement('button');add.className='add';add.textContent='+ Punkt hinzufügen';
  add.onclick=()=>{if(editing)return;const bx=document.createElement('div');bx.className='addbox';const sp=document.createElement('span');bx.appendChild(sp);
   root.insertBefore(bx,add);add.style.display='none';startEdit(sp,found.l.kind,'',v=>saveFields([...fields,v]));};
  root.appendChild(add);
 }else{
 for(const l of d.lists){const box=document.createElement('div');box.className='list';box.dataset.kind=l.kind;
  const h=document.createElement('h2');h.textContent=l.title+' ('+l.items.length+')';box.appendChild(h);
  const e=document.createElement('div');e.className='empty';e.textContent='leer';box.appendChild(e);
  for(const t of l.items){all.add(key(l.kind,t));box.appendChild(makeRow(l.kind,t));}
  root.appendChild(box);}}
 sel=new Set([...sel].filter(x=>all.has(x)));upd();}
function upd(){const b=document.getElementById('del');b.disabled=!sel.size;b.textContent=sel.size?sel.size+' markierte löschen':'Markierte löschen';}
let clone=null,ph=null,dragLab=null,offY=0,lastY=0,raf=0;
function attachDrag(lab){let timer=null,sx=0,sy=0;
 lab.addEventListener('touchstart',e=>{const n=e.target.tagName;if(editing||n==='INPUT'||n==='TEXTAREA'||n==='BUTTON')return;
  const t=e.touches[0];sx=t.clientX;sy=t.clientY;clearTimeout(timer);timer=setTimeout(()=>beginDrag(lab,sy),450);},{passive:true});
 lab.addEventListener('touchmove',e=>{const t=e.touches[0];
  if(!dragging){if(Math.abs(t.clientX-sx)+Math.abs(t.clientY-sy)>10)clearTimeout(timer);return;}
  e.preventDefault();lastY=t.clientY;moveDrag();},{passive:false});
 const end=()=>{clearTimeout(timer);if(dragging)endDrag();};
 lab.addEventListener('touchend',end);lab.addEventListener('touchcancel',end);
 lab.addEventListener('contextmenu',e=>e.preventDefault());}
function beginDrag(lab,y){snd.pick();dragging=true;dragLab=lab;lastY=y;if(navigator.vibrate)navigator.vibrate(30);
 const r=lab.getBoundingClientRect();offY=y-r.top;
 clone=lab.cloneNode(true);clone.className='float';clone.style.top=r.top+'px';clone.style.width=r.width+'px';
 ph=document.createElement('div');ph.className='ph';ph.style.height=r.height+'px';
 document.body.appendChild(clone);lab.parentNode.insertBefore(ph,lab);lab.style.display='none';scrollLoop();}
function moveDrag(){clone.style.top=(lastY-offY)+'px';
 const el=document.elementFromPoint(window.innerWidth/2,lastY);if(!el)return;
 const row=el.closest('label');
 if(row&&row!==dragLab&&row.parentNode.classList.contains('list')){const r=row.getBoundingClientRect();
  row.parentNode.insertBefore(ph,lastY<r.top+r.height/2?row:row.nextSibling);return;}
 const box=el.closest('.list');if(!box)return;
 if(el.tagName==='H2')box.insertBefore(ph,el.nextSibling.nextSibling);else if(el===box||el.classList.contains('empty'))box.appendChild(ph);}
function scrollLoop(){if(!dragging)return;
 if(lastY<120)window.scrollBy(0,-14);else if(lastY>window.innerHeight-150)window.scrollBy(0,14);
 moveDrag();raf=requestAnimationFrame(scrollLoop);}
async function endDrag(){snd.drop();dragging=false;cancelAnimationFrame(raf);justDragged=Date.now();
 ph.parentNode.insertBefore(dragLab,ph);ph.remove();clone.remove();dragLab.style.display='';
 const lists={};document.querySelectorAll('.list').forEach(b=>{lists[b.dataset.kind]=[...b.querySelectorAll('label')].map(x=>x._t);});
 try{if(view)await saveFields(lists[view.kind]);else await fetch('/api/move',{method:'POST',body:JSON.stringify({lists})});}catch(e){}
 last='';load();}
async function load(){if(editing||dragging)return;try{const r=await fetch('/api/lists');const s=await r.text();if(s!==last){last=s;render(JSON.parse(s));}}catch(e){}}
document.getElementById('del').onclick=async()=>{if(!sel.size||!confirm(sel.size+(view?' Punkte':' Einträge')+' endgültig löschen?'))return;
 if(view){const rest=[...document.querySelectorAll('.list label')].map(x=>x._t).filter(t=>!sel.has(key(view.kind,t)));
  await saveFields(rest);snd.del();sel=new Set();last='';load();return;}
 const items=[...sel].map(x=>{const i=x.indexOf('\\u0000');return {kind:x.slice(0,i),text:x.slice(i+1)}});
 await fetch('/api/delete',{method:'POST',body:JSON.stringify({items})});snd.del();sel=new Set();last='';load();};
document.getElementById('snd').onclick=()=>{soundOn=!soundOn;try{localStorage.setItem('snd',soundOn?'1':'0')}catch(e){}sndLabel();if(soundOn)snd.on();};
sndLabel();load();setInterval(load,4000);
(function(){const sp=document.getElementById('splash');let gone=false;
 const hide=()=>{if(gone)return;gone=true;sp.classList.add('out');setTimeout(()=>sp.remove(),600);};
 sp.onclick=hide;setTimeout(hide,2100);})();
</script></body></html>"""

MANIFEST = json.dumps({"name": "Leyla Gedächtnis", "short_name": "Leyla", "start_url": "/",
                       "display": "standalone", "background_color": "#08103a",
                       "theme_color": "#08103a",
                       "id": "/", "scope": "/",
                       "icons": [{"src": "/icon.png?v=5", "sizes": sz, "type": "image/png",
                                  "purpose": "any"} for sz in ("192x192", "512x512")]})


async def _respond(writer, status: str, ctype: str, body: str) -> None:
    raw = body.encode("utf-8")
    writer.write((f"HTTP/1.1 {status}\r\nContent-Type: {ctype}; charset=utf-8\r\n"
                  f"Content-Length: {len(raw)}\r\nCache-Control: no-store\r\n"
                  "Connection: close\r\n\r\n").encode() + raw)
    await writer.drain()


async def _handle(store, sync, reader, writer) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        lines = head.decode("latin-1").split("\r\n")
        method, path = (lines[0].split(" ") + ["", ""])[:2]
        path = path.split("?")[0]
        length = 0
        for ln in lines[1:]:
            if ln.lower().startswith("content-length:"):
                length = min(int(ln.split(":", 1)[1].strip() or 0), MAX_BODY)
        body = await asyncio.wait_for(reader.readexactly(length), timeout=10) if length else b""
        if method == "GET" and path == "/":
            await _respond(writer, "200 OK", "text/html", PAGE)
        elif method == "GET" and path == "/icon.png":
            with open(ICON_PATH, "rb") as f:
                raw = f.read()
            writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: {len(raw)}\r\n"
                          "Cache-Control: no-cache\r\nConnection: close\r\n\r\n").encode() + raw)
            await writer.drain()
        elif method == "GET" and path == "/manifest.json":
            await _respond(writer, "200 OK", "application/manifest+json", MANIFEST)
        elif method == "GET" and path == "/api/lists":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(snapshot(store), ensure_ascii=False))
        elif method == "POST" and path == "/api/edit":
            d = json.loads(body or b"{}") or {}
            ok = edit_item(store, d.get("kind"), d.get("old"), d.get("new"))
            if ok and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/folder":
            d = json.loads(body or b"{}") or {}
            new = edit_folder(store, d.get("kind"), d.get("old"), d.get("fields"))
            if new is not None and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"ok": new is not None, "text": new}, ensure_ascii=False))
        elif method == "POST" and path == "/api/move":
            ok = move_items(store, (json.loads(body or b"{}") or {}).get("lists"))
            if ok and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/delete":
            n = delete_items(store, (json.loads(body or b"{}") or {}).get("items"))
            if n:
                logger.info("Memory page: %d entries deleted", n)
                if sync:
                    sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"removed": n}))
        else:
            await _respond(writer, "404 Not Found", "text/plain", "not found")
    except Exception as e:
        logger.debug("Memory page request failed: %s", e)
        try:
            await _respond(writer, "400 Bad Request", "text/plain", "bad request")
        except Exception:
            pass
    finally:
        writer.close()


async def start_http(store: memory.MemoryStore, sync: Optional[object] = None,
                     host: str = "0.0.0.0", port: int = 8082):
    server = await asyncio.start_server(lambda r, w: _handle(store, sync, r, w), host, port)
    logger.info("Memory page on port %d", port)
    return server
