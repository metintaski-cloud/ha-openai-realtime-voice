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
from typing import Optional

from app import memory

logger = logging.getLogger(__name__)

TITLES = ((memory.FAMILY, "Familie und Haushalt"),
          (memory.FRIENDS, "Freunde und Verwandte"),
          (memory.LEYLA, "Leylas eigene Geschichte"))
MAX_BODY = 64 * 1024


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


PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111111">
<meta name="mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">
<title>Leyla Gedächtnis</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#111;color:#eee;font:17px/1.4 system-ui,sans-serif;padding-bottom:90px}
h1{font-size:20px;margin:0;padding:16px}
h2{font-size:15px;margin:18px 16px 6px;color:#9ab;text-transform:uppercase;letter-spacing:.04em}
label{display:flex;gap:14px;align-items:flex-start;padding:12px 16px;border-bottom:1px solid #262626}
label.on{background:#2a1a1a}
input{width:24px;height:24px;flex:none;margin-top:2px}
.t{flex:1;word-break:break-word}.t small{display:block;color:#9ab}
.empty{padding:12px 16px;color:#777}
textarea{width:100%;box-sizing:border-box;min-height:140px;font:inherit;color:#eee;background:#1d1d1d;border:1px solid #567;border-radius:8px;padding:8px}
.row{display:flex;gap:10px;margin-top:8px}.row button{padding:10px;font-size:16px;background:#2d6a4f}.row .no{background:#444}
#bar{position:fixed;left:0;right:0;bottom:0;padding:12px 16px;background:#1b1b1b;border-top:1px solid #333}
button{width:100%;font-size:18px;padding:14px;border:0;border-radius:10px;background:#c0392b;color:#fff}
button:disabled{background:#3a3a3a;color:#888}
</style></head><body>
<h1>Leyla Gedächtnis</h1><div id="root"></div>
<div id="bar"><button id="del" disabled>Markierte löschen</button></div>
<script>
let sel=new Set(),last='',editing=false;
function startEdit(span,kind,text){editing=true;span.onclick=null;span.innerHTML='';
 const ta=document.createElement('textarea');ta.value=text;
 const row=document.createElement('div');row.className='row';
 const ok=document.createElement('button');ok.textContent='Speichern';
 const no=document.createElement('button');no.textContent='Abbrechen';no.className='no';
 no.onclick=()=>{editing=false;last='';load();};
 ok.onclick=async()=>{ok.disabled=true;const r=await fetch('/api/edit',{method:'POST',body:JSON.stringify({kind,old:text,new:ta.value})});
  const j=await r.json();if(!j.ok){alert('Nicht gespeichert: leer, zu lang oder schon vorhanden.');ok.disabled=false;return;}
  editing=false;last='';load();};
 row.append(ok,no);span.append(ta,row);ta.focus();}
const key=(k,t)=>k+'\\u0000'+t;
function fmt(t){const p=t.split(' | ');if(p.length<2||!p[0].startsWith('Person:'))return esc(t);
 return '<b>'+esc(p[0].slice(7).trim())+'</b>'+p.slice(1).map(x=>'<small>'+esc(x)+'</small>').join('');}
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function render(d){const root=document.getElementById('root');root.innerHTML='';
 const all=new Set();
 for(const l of d.lists){const h=document.createElement('h2');h.textContent=l.title+' ('+l.items.length+')';root.appendChild(h);
  if(!l.items.length){const e=document.createElement('div');e.className='empty';e.textContent='leer';root.appendChild(e);}
  for(const t of l.items){const k=key(l.kind,t);all.add(k);
   const lab=document.createElement('label');const cb=document.createElement('input');cb.type='checkbox';cb.checked=sel.has(k);
   lab.className=cb.checked?'on':'';
   cb.onchange=()=>{cb.checked?sel.add(k):sel.delete(k);lab.className=cb.checked?'on':'';upd();};
   const s=document.createElement('span');s.className='t';s.innerHTML=fmt(t);
   s.onclick=e=>{e.preventDefault();startEdit(s,l.kind,t);};lab.append(cb,s);root.appendChild(lab);}}
 sel=new Set([...sel].filter(x=>all.has(x)));upd();}
function upd(){const b=document.getElementById('del');b.disabled=!sel.size;b.textContent=sel.size?sel.size+' markierte löschen':'Markierte löschen';}
async function load(){if(editing)return;try{const r=await fetch('/api/lists');const s=await r.text();if(s!==last){last=s;render(JSON.parse(s));}}catch(e){}}
document.getElementById('del').onclick=async()=>{if(!sel.size||!confirm(sel.size+' Einträge endgültig löschen?'))return;
 const items=[...sel].map(x=>{const i=x.indexOf('\\u0000');return {kind:x.slice(0,i),text:x.slice(i+1)}});
 await fetch('/api/delete',{method:'POST',body:JSON.stringify({items})});sel=new Set();last='';load();};
load();setInterval(load,4000);
</script></body></html>"""

MANIFEST = json.dumps({"name": "Leyla Gedächtnis", "short_name": "Leyla", "start_url": "/",
                       "display": "standalone", "background_color": "#111111",
                       "theme_color": "#111111", "icons": []})


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
