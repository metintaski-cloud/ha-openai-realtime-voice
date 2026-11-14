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
import time
import os
from typing import Optional

from app import memory, ticker

logger = logging.getLogger(__name__)

TITLES = ((memory.FAMILY, "Familie und Haushalt"),
          (memory.FRIENDS, "Freunde und Verwandte"),
          (memory.LEYLA, "Leylas eigene Geschichte"))
PRIVATE_TITLE = (memory.PRIVATE, "Privat, nur für dich")
MAX_BODY = 64 * 1024
CODE_MAX_FAILS = 5        # wrong code words in a row, then the private list is locked for a while
CODE_LOCK_S = 300
_code_fails = {"n": 0, "until": 0.0}
ICON_PATH = os.path.join(os.path.dirname(__file__), "memory_icon.png")
MASKABLE_PATH = os.path.join(os.path.dirname(__file__), "memory_icon_maskable.png")  # full square, no transparent corners
AVATAR_PATH = os.path.join(os.path.dirname(__file__), "leyla_avatar.jpg")  # her picture in the chat


def check_code(typed, phrase: str, now: Optional[float] = None) -> bool:
    """True when the typed words are exactly the code phrase (the name Leyla may be left out).
    After CODE_MAX_FAILS wrong tries every try is refused for CODE_LOCK_S."""
    now = time.time() if now is None else now
    if not phrase or not isinstance(typed, str) or not typed.strip():
        return False
    if now < _code_fails["until"]:
        return False
    if memory.code_words(typed) == memory.code_words(phrase):
        _code_fails["n"] = 0
        return True
    _code_fails["n"] += 1
    if _code_fails["n"] >= CODE_MAX_FAILS:
        _code_fails.update(n=0, until=now + CODE_LOCK_S)
        logger.warning("Memory page: wrong code word %d times, private list locked for %d s",
                       CODE_MAX_FAILS, CODE_LOCK_S)
    return False


def snapshot(store: memory.MemoryStore, titles=TITLES) -> dict:
    data = store.load_all()
    shown = {k: data.get(k, []) for k, _ in titles}
    new = store.fresh()
    fresh = set()
    for facts in shown.values():
        for f in facts:
            head = f.split(" | ")[0]
            mine = {p for p in new if p.startswith(head + "||")}
            if f in new or mine:
                fresh.add(f)
            fresh |= mine
    return {"lists": [{"kind": k, "title": t, "items": shown[k]} for k, t in titles],
            "fresh": sorted(fresh), "ticker": ticker.recent()}


def add_item(store: memory.MemoryStore, kind, text, titles=TITLES) -> bool:
    """Add one new entry at the end of a list. False when empty, too long, a duplicate or full."""
    if kind not in dict(titles) or not isinstance(text, str):
        return False
    text = " ".join(text.split())
    if not text or len(text) > memory.MAX_FACT_CHARS:
        return False
    facts = store.load(kind)
    if text in facts or len(facts) >= memory.MAX_FACTS or (
            kind == memory.LEYLA and len(facts) >= memory.MAX_LEYLA):
        return False
    store.save(facts + [text], kind)
    return True


def delete_items(store: memory.MemoryStore, items, titles=TITLES) -> int:
    """Delete (kind, text) pairs from the open lists, return how many were removed."""
    wanted: dict = {}
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("kind") in dict(titles) and isinstance(it.get("text"), str):
            wanted.setdefault(it["kind"], set()).add(it["text"])
    removed = 0
    for kind, texts in wanted.items():
        facts = store.load(kind)
        keep = [f for f in facts if f not in texts]
        if len(keep) != len(facts):
            removed += len(facts) - len(keep)
            store.save(keep, kind)
    return removed


def edit_item(store: memory.MemoryStore, kind, old, new, titles=TITLES) -> bool:
    """Replace one entry in place. False when it is unknown, empty, too long or a duplicate."""
    if kind not in dict(titles) or not isinstance(old, str) or not isinstance(new, str):
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


def edit_folder(store: memory.MemoryStore, kind, old, fields, titles=TITLES) -> Optional[str]:
    """Replace the points of one entry ("Person: Metin | Zugehörigkeit: ... | Alter: 45"): the first part
    (the name) stays, `fields` become the rest in the given order. Returns the new text, or None when the entry
    is unknown or changed meanwhile (`old` must be what is stored now), too long or a duplicate."""
    if kind not in dict(titles) or not isinstance(old, str) or not isinstance(fields, list):
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


def move_items(store: memory.MemoryStore, lists, titles=TITLES) -> bool:
    """Apply a new order and distribution of the open lists. Only accepted when it holds
    exactly the entries that are stored now (nothing lost, nothing new), so a page that is
    out of date cannot overwrite what Leyla learned meanwhile."""
    if not isinstance(lists, dict):
        return False
    new = {}
    for kind, _ in titles:
        v = lists.get(kind)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return False
        new[kind] = v
    cur = store.load_all()
    if sorted(x for k, _ in titles for x in cur.get(k, [])) != sorted(
            x for v in new.values() for x in v):
        return False
    if len(new[memory.LEYLA]) > memory.MAX_LEYLA:
        return False
    if any(new[k] != cur.get(k, []) for k, _ in titles):
        store.save_all(new)
    return True


PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#000000">
<meta name="mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" sizes="512x512" href="/icon.png?v=5">
<link rel="apple-touch-icon" href="/icon.png?v=5">
<title>Leyla Gedächtnis</title>
<style>
html{background:#000}
:root{color-scheme:dark;--cy:#22d3ee;--bl:#3b82f6;--vi:#a855f7;--mg:#d946ef}
body{margin:0;background:#000;color:#e8ecff;font:17px/1.4 system-ui,sans-serif;padding-bottom:96px}
#pulse{position:relative;height:150px;margin:-6px 0 4px;overflow:hidden;pointer-events:none}
#pulse .beam{position:absolute;left:0;right:0;top:64px;height:2px;margin-top:-1px;background:linear-gradient(90deg,transparent,#3b82f6aa 20%,#22d3ee 50%,#3b82f6aa 80%,transparent);box-shadow:0 0 8px #22d3ee}
#pulse svg{position:absolute;left:50%;top:64px;width:84px;height:76px;margin:-38px 0 0 -42px;overflow:visible;animation:beat 1.6s ease-in-out infinite}
#pulse svg path{filter:drop-shadow(0 0 5px #22d3ee) drop-shadow(0 0 10px #d946ef77)}
#pulse .spark{position:absolute;width:3px;height:3px;border-radius:50%;background:#bae6fd;box-shadow:0 0 6px #7dd3fc;animation:tw 2.4s ease-in-out infinite}
#pulse.bad .beam{background:#64748b55;box-shadow:none}#pulse.bad .spark{display:none}
#pulse.bad svg{animation:none;filter:grayscale(1) opacity(.45)}
#pulse .tick{position:absolute;left:0;right:0;top:118px;height:22px;overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent,#000 8%,#000 88%,transparent);mask-image:linear-gradient(90deg,transparent,#000 8%,#000 88%,transparent)}
#pulse .tick span{position:absolute;left:100%;white-space:nowrap;font-size:14px;line-height:22px;color:#e0f2fe;text-shadow:0 0 8px #22d3ee;animation:crawl linear infinite}
#pulse.bad .tick{display:none}
@keyframes crawl{from{transform:translateX(0)}to{transform:translateX(calc(-100% - 100vw))}}
@keyframes beat{0%,100%{transform:scale(1)}12%{transform:scale(1.12)}24%{transform:scale(.98)}36%{transform:scale(1.07)}50%{transform:scale(1)}}
@keyframes tw{0%,100%{opacity:.1;transform:scale(.6)}50%{opacity:1;transform:scale(1.2)}}
#chat{margin:0 12px 14px;padding:10px;border:1px solid #3b82f655;border-radius:14px;background:#050a24;display:none}
#chat h2{margin:2px 4px 8px}
#chat .chead{display:flex;align-items:center;gap:10px;margin:2px 4px 10px}#chat .chead h2{margin:0}
#chat .chead img{width:44px;height:44px;border-radius:50%;object-fit:cover;border:2px solid #22d3ee;box-shadow:0 0 12px #22d3ee88,0 0 18px #d946ef55}
#clog .lr{display:flex;gap:8px;align-items:flex-end;align-self:flex-start;max-width:92%}#clog .lr img{width:28px;height:28px;border-radius:50%;object-fit:cover;flex:none;border:1px solid #22d3ee88}
#clog .lr .m{max-width:none}
#clog{max-height:38vh;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding:2px}
#clog .m{max-width:85%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-break:break-word;font-size:16px}
#clog .u{align-self:flex-end;background:#3a1457;border:1px solid #d946ef66}
#clog .l{align-self:flex-start;background:#0d1750;border:1px solid #22d3ee55}
#clog .p{align-self:flex-start;max-width:90%;padding:9px 12px;border-radius:12px;background:#0a2a22;border:1px dashed #22c55e;font-size:15px}
#clog .p b{color:#86efac}#clog .p .row{display:flex;gap:8px;margin-top:8px}#clog .p button{flex:1;padding:8px}
#clog .wait{align-self:flex-start;color:#9fb4ff;font-size:14px;padding:2px 6px}
#cin{display:flex;gap:8px;margin-top:10px}#cin textarea{flex:1;min-height:44px;max-height:120px;font:inherit;color:#fff;background:#000;border:1px solid var(--bl);border-radius:10px;padding:9px;resize:vertical}
#cin button{width:auto;padding:0 16px}
header{display:flex;align-items:center;gap:12px;padding:16px}
header img{width:44px;height:44px;border-radius:11px;box-shadow:0 0 14px #3b82f688}
h1{font-size:21px;margin:0;background:linear-gradient(90deg,var(--cy),var(--vi),var(--mg));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{font-size:14px;margin:22px 16px 6px;color:var(--cy);text-transform:uppercase;letter-spacing:.08em;text-shadow:0 0 10px #22d3ee66}
label{display:flex;gap:14px;align-items:flex-start;margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;box-shadow:0 0 12px #3b82f622 inset}
label.new{background:#0c3b2ecc;border-color:#22c55e;box-shadow:0 0 14px #22c55e55}
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
#bar{position:fixed;left:0;right:0;bottom:0;padding:12px 16px;background:#000000e6;border-top:1px solid #3b82f655;backdrop-filter:blur(6px)}
button{width:100%;font-size:18px;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,var(--vi),var(--mg));color:#fff;box-shadow:0 0 16px #a855f777}
button:disabled{background:#1b2152;color:#6c79b8;box-shadow:none}
.card{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.card .n{flex:1;min-width:110px}.card small{display:block;color:#9fb4ff;font-size:13px}
.card input[type=color]{width:52px;height:40px;border:1px solid #3b82f688;border-radius:10px;background:none;padding:2px}
.card button,.lb button{width:auto;font-size:15px;padding:10px 14px;box-shadow:none;background:#1b2a6b;border:1px solid var(--cy)}
.lb{display:flex;gap:10px;margin:4px 12px 8px}.lb button{flex:1}
#lmsg{margin:0 16px 8px;min-height:20px;color:#9fb4ff;font-size:14px}
#rules{position:fixed;inset:0;z-index:20;overflow-y:auto;background:#000;padding-bottom:40px;display:none}
#rules .top{position:sticky;top:0;display:flex;align-items:center;gap:12px;padding:14px 16px;background:#000000ee;backdrop-filter:blur(6px)}
#rules .top button{width:auto;font-size:26px;line-height:1;padding:6px 14px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
#rules p{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;white-space:pre-wrap;word-break:break-word}
#rules ul{margin:8px 0 0;padding-left:20px;white-space:normal}#rules li{margin:6px 0}
#rules .lead{background:none;border:0;color:#9fb4ff;padding:4px 16px}
#splash{position:fixed;inset:0;z-index:100;background:#000;display:flex;align-items:center;justify-content:center;transition:opacity .45s}
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
<header><button id="back">&#8249;</button><img src="/icon.png?v=5" alt=""><h1>Leyla Gedächtnis</h1><button id="snd"></button></header><div id="pulse" class="ok" title="Alles in Ordnung"><div class="tick" id="tick" style="display:none"><span></span></div><i class="spark" style="left:12%;top:30%;animation-delay:0s"></i><i class="spark" style="left:22%;top:68%;animation-delay:0.6s"></i><i class="spark" style="left:31%;top:22%;animation-delay:1.2s"></i><i class="spark" style="left:68%;top:74%;animation-delay:0.3s"></i><i class="spark" style="left:77%;top:28%;animation-delay:0.9s"></i><i class="spark" style="left:88%;top:60%;animation-delay:1.5s"></i><i class="spark" style="left:40%;top:80%;animation-delay:1.8s"></i><i class="spark" style="left:60%;top:18%;animation-delay:2.1s"></i><div class="beam"></div><svg viewBox="0 0 100 90"><defs><linearGradient id="hg" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#f43f5e"/></linearGradient><radialGradient id="hc"><stop offset="0" stop-color="#fff"/><stop offset=".4" stop-color="#7dd3fc"/><stop offset="1" stop-color="#7dd3fc" stop-opacity="0"/></radialGradient></defs><path d="M50 84C20 62 4 46 4 28C4 14 15 4 28 4C38 4 46 10 50 18C54 10 62 4 72 4C85 4 96 14 96 28C96 46 80 62 50 84Z" fill="#0b1650cc" stroke="url(#hg)" stroke-width="3.2" stroke-linejoin="round"/><path d="M14 40H34L40 28L47 54L53 34L58 44H86" fill="none" stroke="#e0f2fe" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/><circle cx="54" cy="38" r="9" fill="url(#hc)"/></svg></div><div id="chat"><div class="chead"><img src="/leyla.jpg" alt=""><h2>Chat mit Leyla</h2></div><div id="clog"></div><div id="cin"><textarea id="ctext" placeholder="Schreib Leyla ..."></textarea><button id="csend">Senden</button></div></div><div id="rules"><div class="top"><button id="rback">&#8249;</button><h1>So ist Leyla</h1></div><div id="rtext"></div></div><div id="root"></div><div id="lamps" style="display:none"></div>
<div id="bar"><button id="del" disabled>Markierte löschen</button></div>
<script>
let CODE=null;
function post(path,obj){if(CODE)obj.code=CODE;return fetch(path,{method:'POST',body:JSON.stringify(obj)});}
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
 const r=await post('/api/folder',{kind:view.kind,old:view.text,fields});
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
  else{const r=await post('/api/edit',{kind,old:text,new:ta.value});good=(await r.json()).ok;}
  if(!good){alert('Nicht gespeichert: leer, zu lang oder schon vorhanden.');ok.disabled=false;return;}
  snd.save();editing=false;last='';load();};
 row.append(ok,no);span.append(ta,row);ta.focus();}
function makeRow(kind,t){const lab=document.createElement('label');lab._t=t;
 const cb=document.createElement('input');cb.type='checkbox';cb.checked=sel.has(key(kind,t));lab.className=cb.checked?'on':'';
 cb.onchange=()=>{const k=key(lab.parentNode.dataset.kind,t);cb.checked?(sel.add(k),snd.on()):(sel.delete(k),snd.off());lab.classList.toggle('on',cb.checked);upd();};
 const s=document.createElement('span');s.className='t';s.innerHTML=fmt(t);
 const pt=parts(t),isFolder=!view&&pt.folder;if(isFolder)lab.classList.add('fold');
 if(FRESH.has(view?view.head+'||'+t:t))lab.classList.add('new');
 s.onclick=e=>{e.preventDefault();if(Date.now()-justDragged<700)return;const kd=lab.parentNode.dataset.kind;
  if(isFolder)return openFolder(kd,pt.head);
  if(view){const fl=[...document.querySelectorAll('.list label')].map(x=>x._t),i=fl.indexOf(t);
   return startEdit(s,kd,t,v=>{fl[i]=v;return saveFields(fl);});}
  startEdit(s,kd,t);};
 lab.append(cb,s);attachDrag(lab);return lab;}
let CHAT=[];try{CHAT=JSON.parse(localStorage.getItem('lchat')||'[]')}catch(e){CHAT=[]}
const KNAME={family:'Familie',friends:'Freunde',leyla:'Leylas Geschichte',private:'Privat'};
function chatSave(){CHAT=CHAT.slice(-40);try{localStorage.setItem('lchat',JSON.stringify(CHAT))}catch(e){}}
function chatDraw(wait){const log=document.getElementById('clog');log.innerHTML='';
 CHAT.forEach((m,i)=>{if(m.role==='prop')return log.appendChild(propCard(m,i));
  const d=document.createElement('div');d.className='m '+(m.role==='user'?'u':'l');d.textContent=m.text;
  if(m.role==='user')return log.appendChild(d);const r=document.createElement('div');r.className='lr';const im=document.createElement('img');im.src='/leyla.jpg';im.alt='';r.append(im,d);log.appendChild(r);});
 if(wait){const w=document.createElement('div');w.className='wait';w.textContent='Leyla schreibt ...';log.appendChild(w);}
 log.scrollTop=log.scrollHeight;}
function diffText(o,n){if(o.indexOf(' | ')<0&&n.indexOf(' | ')<0)return o+'  \u2192  '+n;const a=o.split(' | '),b=n.split(' | ');
 const add=b.filter(x=>!a.includes(x)),gone=a.filter(x=>!b.includes(x));return title(b[0])+': '+[...add.map(x=>'neu: '+x),...gone.map(x=>'weg: '+x)].join('; ');}
function propCard(m,i){const c=document.createElement('div');c.className='p';const p=m.p;
 const what=p.action==='add'?'Merken':p.action==='edit'?'Ändern':'Streichen';
 const h=document.createElement('b');h.textContent=what+' ('+(KNAME[p.kind]||p.kind)+')';c.appendChild(h);
 const t=document.createElement('div');t.textContent=p.action==='add'?p.new:p.action==='edit'?diffText(p.old,p.new):p.old;c.appendChild(t);
 if(m.done){const s=document.createElement('div');s.textContent=m.done;s.style.marginTop='6px';s.style.color='#9fb4ff';c.appendChild(s);return c;}
 const row=document.createElement('div');row.className='row';const y=document.createElement('button');y.textContent='Ja';const n=document.createElement('button');n.textContent='Nein';n.className='no';
 y.onclick=async()=>{y.disabled=n.disabled=true;let ok=false;
  try{if(p.action==='add')ok=(await (await post('/api/add',{kind:p.kind,text:p.new})).json()).ok;
   else if(p.action==='edit')ok=(await (await post('/api/edit',{kind:p.kind,old:p.old,new:p.new})).json()).ok;
   else ok=(await (await post('/api/delete',{items:[{kind:p.kind,text:p.old}]})).json()).removed>0;}catch(e){}
  CHAT[i].done=ok?'Gespeichert':'Ging nicht, der Eintrag hat sich inzwischen geändert';if(ok)snd.save();chatSave();chatDraw();last='';load();};
 n.onclick=()=>{CHAT[i].done='Verworfen';snd.off();chatSave();chatDraw();};
 row.append(y,n);c.appendChild(row);return c;}
async function chatSend(){const ta=document.getElementById('ctext'),msg=ta.value.trim();if(!msg)return;
 const history=CHAT.filter(m=>m.role!=='prop').map(m=>({role:m.role,text:m.text}));
 CHAT.push({role:'user',text:msg});ta.value='';chatSave();chatDraw(true);snd.on();
 let j=null;try{j=await (await post('/api/chat',{history,message:msg})).json();}catch(e){}
 if(!j||j.error||!j.reply){CHAT.push({role:'leyla',text:'Hmm, gerade komme ich nicht durch. Versuch es gleich nochmal.'});}
 else{CHAT.push({role:'leyla',text:j.reply});(j.proposals||[]).forEach(p=>CHAT.push({role:'prop',p}));}
 chatSave();chatDraw();snd.drop();}
document.getElementById('csend').onclick=chatSend;
let FRESH=new Set(),TICK='';
function ticker(list){const t=(list||[]).join('   \u2726   ');if(t===TICK)return;TICK=t;const box=document.getElementById('tick'),sp=box.firstChild;
 box.style.display=t?'block':'none';sp.textContent=t;sp.style.animationDuration=Math.max(10,t.length*0.16)+'s';}
function render(d){FRESH=new Set(d.fresh||[]);ticker(d.ticker);const root=document.getElementById('root');root.innerHTML='';const all=new Set();
 const back=document.getElementById('back'),h1=document.querySelector('h1');
 let found=null;
 if(view){const l=d.lists.find(x=>x.kind===view.kind);const t=l&&l.items.find(x=>parts(x).head===view.head);if(t){found={l,t};}else view=null;}
 back.style.display=view?'block':'none';document.getElementById('pulse').style.display=view?'none':'block';const ch=document.getElementById('chat'),showChat=!!CODE&&!view;if(showChat&&ch.style.display!=='block'){ch.style.display='block';chatDraw();}else if(!showChat)ch.style.display='none';document.getElementById('lamps').style.display=(view||!lampOn)?'none':'block';h1.textContent=view?title(view.head):'Leyla Gedächtnis';
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
  root.appendChild(box);
  const add=document.createElement('button');add.className='add';add.textContent='+ Neuer Eintrag';
  add.onclick=()=>{if(editing)return;const bx=document.createElement('div');bx.className='addbox';const sp=document.createElement('span');bx.appendChild(sp);
   root.insertBefore(bx,add);add.style.display='none';
   startEdit(sp,l.kind,'',async v=>{const r=await post('/api/add',{kind:l.kind,text:v});return (await r.json()).ok;});};
  root.appendChild(add);}
 root.appendChild(privBox());}
 sel=new Set([...sel].filter(x=>all.has(x)));upd();}
function privBox(){const b=document.createElement('div');b.className='lb';
 if(CODE){const r=document.createElement('button');r.textContent='So ist Leyla';r.onclick=openRules;
  const x=document.createElement('button');x.textContent='Private Liste schließen';x.onclick=()=>{CODE=null;try{localStorage.removeItem('lcode')}catch(e){}last='';snd.off();load();};b.append(r,x);return b;}
 const i=document.createElement('input');i.type='password';i.placeholder='Codewort';i.autocomplete='off';
 i.style.cssText='flex:2;font:inherit;color:#fff;background:#060c33;border:1px solid var(--bl);border-radius:10px;padding:10px;min-width:0';
 const o=document.createElement('button');o.textContent='Privat öffnen';
 const go=async()=>{if(!i.value.trim())return;o.disabled=true;let ok=false;
  try{ok=(await (await fetch('/api/unlock',{method:'POST',body:JSON.stringify({code:i.value})})).json()).ok;}catch(e){}
  o.disabled=false;if(ok){CODE=i.value;try{localStorage.setItem('lcode',CODE)}catch(e){}snd.save();last='';load();}else{i.value='';i.placeholder='Falsch, nochmal';snd.del();}};
 o.onclick=go;i.onkeydown=e=>{if(e.key==='Enter')go();};
 i.onfocus=()=>{editing=true;};i.onblur=()=>{setTimeout(()=>{editing=false;},300);};
 b.append(i,o);return b;}
let rulesOpen=false;
async function openRules(){let t='';try{const j=await (await post('/api/rules',{})).json();t=j.text||'';}catch(e){}
 if(!t)return;const box=document.getElementById('rtext');box.innerHTML='';
 const lead=document.createElement('p');lead.className='lead';lead.textContent='Leylas Regeln, so wie sie sie bekommt. Nur zum Lesen; Änderungen sagst du Claude.';box.appendChild(lead);
 for(const block of t.split(/\\n\\s*\\n/)){const lines=block.split('\\n');let i=0;
  if(lines[0]&&lines[0]===lines[0].toUpperCase()&&/[A-ZÄÖÜ]/.test(lines[0])&&!lines[0].startsWith('•')){
   const h=document.createElement('h2');h.textContent=lines[0];box.appendChild(h);i=1;}
  let cur=null;for(;i<lines.length;i++){const ln=lines[i];if(!ln.trim())continue;
   if(ln.trim().startsWith('•')||!cur){cur=document.createElement('p');cur.textContent=ln.trim().replace(/^•\\s*/,'');box.appendChild(cur);}
   else cur.textContent+='\\n'+ln.trim();}}
for(const q of box.querySelectorAll('p:not(.lead)')){const t=q.textContent,m='(Delegation): ',c=t.indexOf(m);if(c<0)continue;
  const parts=t.slice(c+m.length).replace(/[.]$/,'').split('; ');
  q.textContent=t.slice(0,c+m.length-1);const ul=document.createElement('ul');
  for(const x of parts){const li=document.createElement('li');li.textContent=x.charAt(0).toUpperCase()+x.slice(1);ul.appendChild(li);}q.appendChild(ul);}
 const el=document.getElementById('rules');el.style.display='block';el.scrollTop=0;rulesOpen=true;editing=true;history.pushState({r:1},'');snd.on();}
function closeRules(){document.getElementById('rules').style.display='none';rulesOpen=false;editing=false;}
document.getElementById('rback').onclick=()=>history.back();
window.addEventListener('popstate',()=>{if(rulesOpen)closeRules();});
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
 try{if(view)await saveFields(lists[view.kind]);else await post('/api/move',{lists});}catch(e){}
 last='';load();}
function health(ok){const p=document.getElementById('pulse');p.className=ok?'ok':'bad';p.title=ok?'Alles in Ordnung':'Leyla ist gerade nicht erreichbar';}
async function load(){if(editing||dragging)return;try{const r=CODE?await post('/api/lists',{}):await fetch('/api/lists');if(!r.ok)throw 0;const s=await r.text();health(true);if(s!==last){last=s;render(JSON.parse(s));}}catch(e){health(false);}}
document.getElementById('del').onclick=async()=>{if(!sel.size||!confirm(sel.size+(view?' Punkte':' Einträge')+' endgültig löschen?'))return;
 if(view){const rest=[...document.querySelectorAll('.list label')].map(x=>x._t).filter(t=>!sel.has(key(view.kind,t)));
  await saveFields(rest);snd.del();sel=new Set();last='';load();return;}
 const items=[...sel].map(x=>{const i=x.indexOf('\\u0000');return {kind:x.slice(0,i),text:x.slice(i+1)}});
 await post('/api/delete',{items});snd.del();sel=new Set();last='';load();};
document.getElementById('snd').onclick=()=>{soundOn=!soundOn;try{localStorage.setItem('snd',soundOn?'1':'0')}catch(e){}sndLabel();if(soundOn)snd.on();};
let lampOn=false;
const LROWS=[['listen','Zuhören',['listen']],['think','Denken und Suchen',['think']],['speak','Reden',['speak_low','speak_high']]];
function lmsg(t){document.getElementById('lmsg').textContent=t;}
const LTXT={ok:'',busy:'Leyla spricht gerade, bitte danach testen.',off:'Lampenshow ist aus.',failed:'Eine Lampe antwortet nicht, Leyla versucht es weiter.',error:'Hat nicht geklappt.'};
async function lampPost(path,body){try{const r=await fetch(path,{method:'POST',body:JSON.stringify(body||{})});return await r.json();}catch(e){return {result:'error'};}}
async function loadLamps(){let d;try{d=await (await fetch('/api/lamp')).json();}catch(e){return;}
 lampOn=!!d.available;const box=document.getElementById('lamps');box.innerHTML='';if(!lampOn){box.style.display='none';return;}
 box.style.display=view?'none':'block';
 const h=document.createElement('h2');h.textContent='Lampenfarben';box.appendChild(h);
 for(const [mode,name,keys] of LROWS){const c=document.createElement('div');c.className='card';
  const n=document.createElement('div');n.className='n';n.innerHTML=esc(name)+(keys.length>1?'<small>leise und laut, das Licht wechselt mit ihrer Stimme</small>':'');c.appendChild(n);
  for(const k of keys){const i=document.createElement('input');i.type='color';i.value=d.colors[k];i.title=d.labels[k];
   i.onchange=async()=>{const j=await lampPost('/api/lamp/colors',{colors:{[k]:i.value}});if(j.ok){snd.save();lmsg('Gespeichert.');}else lmsg(LTXT.error);};c.appendChild(i);}
  const b=document.createElement('button');b.textContent='Testen';
  b.onclick=async()=>{b.disabled=true;lmsg('Die Lampen zeigen die Farbe kurz und gehen dann zurück.');snd.on();
   const j=await lampPost('/api/lamp/test',{mode});lmsg(LTXT[j.result]||'');b.disabled=false;};
  c.appendChild(b);box.appendChild(c);}
 const row=document.createElement('div');row.className='lb';
 const df=document.createElement('button');df.textContent='Standardfarben';
 df.onclick=async()=>{if(!confirm('Alle Farben auf die Leyla Farben zurückstellen?'))return;
  const j=await lampPost('/api/lamp/colors',{colors:{listen:null,think:null,speak_low:null,speak_high:null}});if(j.ok){snd.save();loadLamps();}};
 const rs=document.createElement('button');rs.textContent='Lampen zurücksetzen';
 rs.onclick=async()=>{rs.disabled=true;lmsg('Lampen werden zurückgestellt …');const j=await lampPost('/api/lamp/reset');
  lmsg(j.result==='ok'?'Lampen sind zurückgestellt.':(LTXT[j.result]||''));rs.disabled=false;};
 row.append(df,rs);box.appendChild(row);
 const m=document.createElement('div');m.id='lmsg';box.appendChild(m);}
(async()=>{let c=null;try{c=localStorage.getItem('lcode')}catch(e){}  // remembered on this phone only
 if(c){try{if((await (await fetch('/api/unlock',{method:'POST',body:JSON.stringify({code:c})})).json()).ok)CODE=c;
  else localStorage.removeItem('lcode');}catch(e){}}
 last='';load();})();
sndLabel();loadLamps();setInterval(load,4000);
(function(){const sp=document.getElementById('splash');let gone=false;
 const hide=()=>{if(gone)return;gone=true;sp.classList.add('out');setTimeout(()=>sp.remove(),600);};
 sp.onclick=hide;setTimeout(hide,2100);})();
</script></body></html>"""

MANIFEST = json.dumps({"name": "Leyla Gedächtnis", "short_name": "Leyla", "start_url": "/",
                       "display": "standalone", "background_color": "#000000",
                       "theme_color": "#000000",
                       "id": "/", "scope": "/",
                       "icons": [{"src": "/icon.png?v=5", "sizes": sz, "type": "image/png",
                                  "purpose": "any"} for sz in ("192x192", "512x512")]
                                + [{"src": "/icon-maskable.png?v=6", "sizes": sz, "type": "image/png",
                                    "purpose": "maskable"} for sz in ("192x192", "512x512")]})


async def _respond(writer, status: str, ctype: str, body: str) -> None:
    raw = body.encode("utf-8")
    writer.write((f"HTTP/1.1 {status}\r\nContent-Type: {ctype}; charset=utf-8\r\n"
                  f"Content-Length: {len(raw)}\r\nCache-Control: no-store\r\n"
                  "Connection: close\r\n\r\n").encode() + raw)
    await writer.drain()


async def _lamp_api(lamp, method: str, path: str, body: bytes):
    """The lamp colour settings in the app. None when the path is not one of them."""
    if method == "GET" and path == "/api/lamp":
        if lamp is None or not lamp.available:
            return {"available": False}
        from app.lamp_show import COLOR_LABELS
        return {"available": True, "colors": lamp.colors_hex(), "labels": COLOR_LABELS}
    if method != "POST" or path not in ("/api/lamp/colors", "/api/lamp/test", "/api/lamp/reset"):
        return None
    if lamp is None or not lamp.available:
        return {"ok": False, "result": "off"}
    d = json.loads(body or b"{}") or {}
    if path == "/api/lamp/colors":
        ok = lamp.set_colors(d.get("colors"))
        if ok:
            logger.info("Memory page: lamp colours changed to %s", lamp.colors_hex())
        return {"ok": ok}
    if path == "/api/lamp/test":
        return {"result": await lamp.preview(str(d.get("mode")))}
    return {"result": await lamp.reset()}


async def _handle(store, sync, reader, writer, lamp=None, code_phrase: str = "", rules=None, chat=None) -> None:
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
        lamp_reply = await _lamp_api(lamp, method, path, body) if path.startswith("/api/lamp") else None
        d = {}
        if method == "POST" and not path.startswith("/api/lamp"):
            d = json.loads(body or b"{}") or {}
            if not isinstance(d, dict):
                d = {}
        unlocked = bool(d.get("code")) and check_code(d.get("code"), code_phrase)
        titles = TITLES + (PRIVATE_TITLE,) if unlocked else TITLES
        if lamp_reply is not None:
            await _respond(writer, "200 OK", "application/json", json.dumps(lamp_reply, ensure_ascii=False))
        elif method == "GET" and path == "/":
            await _respond(writer, "200 OK", "text/html", PAGE)
        elif method == "GET" and path in ("/icon.png", "/icon-maskable.png"):
            with open(ICON_PATH if path == "/icon.png" else MASKABLE_PATH, "rb") as f:
                raw = f.read()
            writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nContent-Length: {len(raw)}\r\n"
                          "Cache-Control: no-cache\r\nConnection: close\r\n\r\n").encode() + raw)
            await writer.drain()
        elif method == "GET" and path == "/leyla.jpg":
            with open(AVATAR_PATH, "rb") as f:
                raw = f.read()
            writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: {len(raw)}\r\n"
                          "Cache-Control: max-age=86400\r\nConnection: close\r\n\r\n").encode() + raw)
            await writer.drain()
        elif method == "GET" and path == "/manifest.json":
            await _respond(writer, "200 OK", "application/manifest+json", MANIFEST)
        elif method == "GET" and path == "/api/lists":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(snapshot(store), ensure_ascii=False))
        elif method == "POST" and path == "/api/lists":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(snapshot(store, titles), ensure_ascii=False))
        elif method == "POST" and path == "/api/rules":
            text = rules() if (unlocked and rules) else ""
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"text": text}, ensure_ascii=False))
        elif method == "POST" and path == "/api/chat":
            out = None
            if unlocked and chat:
                try:
                    out = await chat(d.get("history"), d.get("message"))
                except Exception as e:
                    logger.warning("Chat failed: %s", e)
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(out or {"error": True}, ensure_ascii=False))
        elif method == "POST" and path == "/api/unlock":
            if unlocked:
                logger.info("Memory page: private list opened")
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": unlocked}))
        elif method == "POST" and path == "/api/add":
            ok = add_item(store, d.get("kind"), d.get("text"), titles)
            if ok:
                logger.info("Memory page: new entry in %s", d.get("kind"))
                if sync:
                    sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/edit":
            ok = edit_item(store, d.get("kind"), d.get("old"), d.get("new"), titles)
            if ok and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/folder":
            new = edit_folder(store, d.get("kind"), d.get("old"), d.get("fields"), titles)
            if new is not None and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"ok": new is not None, "text": new}, ensure_ascii=False))
        elif method == "POST" and path == "/api/move":
            ok = move_items(store, d.get("lists"), titles)
            if ok and sync:
                sync.kick()
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/delete":
            n = delete_items(store, d.get("items"), titles)
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
                     host: str = "0.0.0.0", port: int = 8082, lamp: Optional[object] = None,
                     code_phrase: str = "", rules=None, chat=None):
    """`rules`: a function that returns Leyla's instructions without memory and without the
    code word; shown read only after the code word."""
    server = await asyncio.start_server(
        lambda r, w: _handle(store, sync, r, w, lamp, code_phrase, rules, chat), host, port)
    logger.info("Memory page on port %d", port)
    return server
