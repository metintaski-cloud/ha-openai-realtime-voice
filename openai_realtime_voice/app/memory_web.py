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
import base64
import collections
import json
import re
import logging
import time
import os
from typing import Optional

from app import day, memory, ticker, voice_stream

logger = logging.getLogger(__name__)

TITLES = ((memory.FAMILY, "Familie und Haushalt"),
          (memory.FRIENDS, "Freunde und Verwandte"),
          (memory.LEYLA, "Leylas eigene Geschichte"))
PRIVATE_TITLE = (memory.PRIVATE, "Privat, nur für dich")
MAX_BODY = 2 * 1024 * 1024  # a voice message from the chat is up to about 1.5 MB
CODE_MAX_FAILS = 5        # wrong code words in a row, then the private list is locked for a while
CODE_LOCK_S = 300
_code_fails = {"n": 0, "until": 0.0}
ICON_PATH = os.path.join(os.path.dirname(__file__), "memory_icon.png")
MASKABLE_PATH = os.path.join(os.path.dirname(__file__), "memory_icon_maskable.png")  # full square, no transparent corners
AVATAR_PATH = os.path.join(os.path.dirname(__file__), "leyla_avatar.jpg")  # her picture in the chat
BODY_PATH = os.path.join(os.path.dirname(__file__), "leyla_body.jpg")  # her full figure on the stage (2.97.0)
BUILTIN_CLIPS = os.path.join(os.path.dirname(__file__), "clips")
MEDIA_CLIPS = "/media/leyla"  # Home Assistant media folder (scene concept 2.0, filled by Metin over Samba)
CLIPS_DIR = os.environ.get("LEYLA_CLIPS_DIR", "")


def clips_dir() -> str:
    """Where the stage clips live: LEYLA_CLIPS_DIR if set, else the media folder as soon as it holds a
    look with clips, else the clips built into the add on. Checked per request, so clips copied into
    the media folder show without a restart."""
    if CLIPS_DIR:
        return CLIPS_DIR
    try:
        for look in os.listdir(MEDIA_CLIPS):
            folder = os.path.join(MEDIA_CLIPS, look)
            if os.path.isdir(folder) and any(f.endswith(".mp4") for f in os.listdir(folder)):
                return MEDIA_CLIPS
    except OSError:
        pass
    return BUILTIN_CLIPS
CLIP_RE = re.compile(r"^/clips/([a-z0-9]{2,20})/([a-z]{2,30}[0-9]{0,2})\.(mp4|jpg|m4a|webm)$")  # 30 since 2.133.9: freizeiteifersuechtig has 21 letters and was invisible to the server, so the jealousy loop never played in Freizeit (Metin, 22.11.2026)  # look/scene (2.99.4), musik/<mood>.m4a (2.103.0)


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
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
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
#pulse svg path:first-of-type{transition:fill 1.2s}#pulse[data-mood=good] svg path:first-of-type{fill:#dc2626e6}#pulse[data-mood=good] svg path{filter:drop-shadow(0 0 6px #ef4444) drop-shadow(0 0 12px #f43f5e88)}
#pulse[data-mood=low] svg path:first-of-type{fill:#000}#pulse[data-mood=low] svg path{filter:drop-shadow(0 0 4px #64748b)}#pulse[data-mood=low] svg{animation-duration:3.2s}
#pulse .tick{position:absolute;left:0;right:0;top:118px;height:22px;overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent,#000 8%,#000 88%,transparent);mask-image:linear-gradient(90deg,transparent,#000 8%,#000 88%,transparent)}
#pulse .tick span{position:absolute;left:100%;white-space:nowrap;font-size:14px;line-height:22px;color:#e0f2fe;text-shadow:0 0 8px #22d3ee;animation:crawl linear infinite}
#pulse.bad .tick{display:none}
@keyframes crawl{from{transform:translateX(0)}to{transform:translateX(calc(-100% - 100vw))}}
@keyframes beat{0%,100%{transform:scale(1)}12%{transform:scale(1.12)}24%{transform:scale(.98)}36%{transform:scale(1.07)}50%{transform:scale(1)}}
@keyframes tw{0%,100%{opacity:.1;transform:scale(.6)}50%{opacity:1;transform:scale(1.2)}}
#chat{margin:0 12px 14px;padding:10px;border:1px solid #3b82f655;border-radius:14px;background:#050a24;display:none}
#chat h2{margin:2px 4px 8px}
#chat .chead{display:flex;align-items:center;gap:14px;margin:4px 4px 12px}#chat .chead h2{margin:0;font-size:20px;letter-spacing:.06em}
#chat .cav{position:relative;flex:none}#mbadge{position:absolute;right:-2px;bottom:-2px;width:28px;height:28px;border-radius:50%;display:none;align-items:center;justify-content:center;font-size:16px;background:#060c33;border:2px solid #ef4444}
#ccount{font-size:13px;margin-top:3px;color:#9fb4ff}#ccount.warn{color:#fbbf24}#ccount.over{color:#f87171;font-weight:600}#cnew{width:auto;margin-top:6px;padding:4px 10px;font-size:13px;background:#000;border:1px solid #22d3ee55}
#mlabel{font-size:14px;margin-top:4px;color:#fca5a5}#chat.low #mlabel{color:#cbd5e1}#chat.low #mbadge{border-color:#475569}
#chat.good .chead img{border-color:#ef4444;box-shadow:0 0 14px #ef4444aa,0 0 20px #f43f5e44}#chat.low .chead img{border-color:#111;box-shadow:0 0 14px #000,0 0 18px #64748b66;filter:saturate(.6)}
#chat .chead #clive{margin-left:8px;width:auto;padding:8px 14px;font-size:15px}
#gmail{margin:14px 12px;padding:12px;border:1px solid #3b82f688;border-radius:14px;background:#060c33}
#gmail h3{margin:0 0 8px;font-size:15px;letter-spacing:.08em;color:var(--cy)}
#gmail input[type=text]{width:100%;box-sizing:border-box;font:inherit;color:#fff;background:#000;border:1px solid var(--bl);border-radius:10px;padding:9px;margin:6px 0}
#gmail .gb{display:flex;gap:10px;margin-top:8px}#gmail .gb button{flex:1;width:auto;font-size:15px;padding:10px;box-shadow:none;background:#1b2a6b;border:1px solid var(--cy)}
#gmail .hint{color:#9fb4ff;font-size:14px;margin:4px 0}
.mc .web{color:#fbbf24;font-weight:600;margin:4px 0}.mc.tr{border-color:#f43f5e88}.mc.rm{border-color:#fbbf2499}.mc.tr li{margin:3px 0}.mc.tr ul{margin:6px 0 8px;padding-left:18px}
.mc{margin:8px 0;padding:10px 12px;border:1px solid #d946ef88;border-radius:12px;background:#140a2e}.mc b{color:#e9d5ff}.mc .meta{color:#9fb4ff;font-size:14px;margin:4px 0}.mc pre{white-space:pre-wrap;font:inherit;margin:6px 0 8px}.mc .row{display:flex;gap:8px}.mc .row button{flex:1}
#live{display:none;position:fixed;inset:0;z-index:50;background:#000;flex-direction:column;align-items:center;justify-content:center;gap:22px}
#live img{width:180px;height:180px;border-radius:50%;object-fit:cover;border:3px solid #22d3ee;box-shadow:0 0 24px #22d3ee99,0 0 40px #d946ef66;transition:transform .15s}
#live.speak img{transform:scale(1.06);border-color:#d946ef}#live #lstat{font-size:20px;color:#9fb4ff}
#live #lend{width:auto;padding:14px 34px;background:linear-gradient(90deg,#ef4444,#f97316);font-size:18px}
#chat .chead img{width:76px;height:76px;border-radius:50%;object-fit:cover;border:2px solid #22d3ee;box-shadow:0 0 12px #22d3ee88,0 0 18px #d946ef55}
#clog .lr{display:flex;gap:8px;align-items:flex-end;align-self:flex-start;max-width:92%}#clog .lr img{width:28px;height:28px;border-radius:50%;object-fit:cover;flex:none;border:1px solid #d946ef88}
#clog .lr .m{max-width:none}
#clog{max-height:26vh;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding:2px}
#clog .m{max-width:85%;padding:9px 12px;border-radius:14px;white-space:pre-wrap;word-break:break-word;font-size:16px}
#clog .u{align-self:flex-end;background:#000;border:1px solid #22d3ee55}
#clog .l{align-self:flex-start;background:#3a1457;border:1px solid #d946ef66}
#clog .noted{display:flex;gap:8px;align-items:center;pointer-events:auto;opacity:.8}
#clog .noted button{background:none;border:0;color:#9aa;font-size:13px;padding:2px 6px;cursor:pointer;pointer-events:auto}
#clog .p{align-self:flex-start;max-width:90%;padding:9px 12px;border-radius:12px;background:#0a2a22;border:1px dashed #22c55e;font-size:15px;white-space:pre-line}
#clog .p b{color:#86efac}#clog .p .row{display:flex;gap:8px;margin-top:8px}#clog .p button{flex:1;padding:8px}
#clog .wait{align-self:flex-start;color:#9fb4ff;font-size:14px;padding:2px 6px}
#cin{display:flex;gap:8px;margin-top:10px}#cin textarea{flex:1;min-height:44px;max-height:120px;font:inherit;color:#fff;background:#000;border:1px solid var(--bl);border-radius:10px;padding:9px;resize:vertical}
#cin button{width:auto;padding:0 16px}
#cmic{padding:0 14px!important;font-size:20px}#cmic.rec{background:linear-gradient(90deg,#ef4444,#f97316);animation:recp 1s infinite}
@keyframes recp{50%{opacity:.6}}
.m .play{display:inline-block;margin-left:8px;width:auto;padding:2px 10px;font-size:14px}a.play{color:#fff;text-decoration:none;border:1px solid #d946ef88;border-radius:8px}
header{display:flex;align-items:center;justify-content:center;gap:12px;padding:18px 16px 6px;position:relative}
header img{width:44px;height:44px;border-radius:11px;box-shadow:0 0 14px #3b82f688}
h1{font-size:21px;margin:0;background:linear-gradient(90deg,var(--cy),var(--vi),var(--mg));-webkit-background-clip:text;background-clip:text;color:transparent}
header h1{font-size:26px;letter-spacing:.01em}header img{width:46px;height:46px;margin-left:-58px}
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
#micon{cursor:pointer;transition:transform .15s}#micon:active{transform:scale(.92)}#micon.open{box-shadow:0 0 0 2px var(--cy),0 0 18px #22d3eeaa}
#menu{display:none;margin:8px 12px 4px;padding:6px;border:1px solid #22d3ee66;border-radius:16px;background:#060c33ee;box-shadow:0 8px 30px #000a}
#menu .mi{display:flex;align-items:center;gap:12px;width:100%;margin:4px 0;padding:13px 14px;font-size:17px;text-align:left;background:#0b1650;border:1px solid #1b2a6b;border-radius:12px;box-shadow:none}
#menu .mi i{font-style:normal;width:26px;text-align:center}#menu .mi span{flex:1}#menu .mi small{color:#9fb4ff;font-size:14px}#menu .mi b{color:var(--cy);font-size:20px;font-weight:400}
#back{display:none;position:absolute;left:16px;width:auto;font-size:26px;line-height:1;padding:6px 14px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
.fold .t{position:relative;padding-right:26px}.fold .t::after{content:'\\203A';position:absolute;right:2px;top:50%;margin-top:-18px;font-size:34px;color:var(--cy)}
.add{margin:4px 12px;width:calc(100% - 24px);display:block;background:#1b2a6b;border:1px solid var(--cy);box-shadow:none;font-size:16px;padding:12px}
.addbox{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid var(--cy);border-radius:12px}
#snd{box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
#bar{position:fixed;left:0;right:0;bottom:0;padding:12px 16px;background:#000000e6;border-top:1px solid #3b82f655;backdrop-filter:blur(6px)}
button{width:100%;font-size:18px;padding:14px;border:0;border-radius:12px;background:linear-gradient(90deg,var(--vi),var(--mg));color:#fff;box-shadow:0 0 16px #a855f777}
button:disabled{background:#1b2152;color:#6c79b8;box-shadow:none}
.card{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.card .n{flex:1;min-width:110px}.card small{display:block;color:#9fb4ff;font-size:13px}
.card input[type=color]{width:52px;height:40px;border:1px solid #3b82f688;border-radius:10px;background:none;padding:2px}
.card button,.lb button{width:auto;font-size:15px;padding:10px 14px;box-shadow:none;background:#1b2a6b;border:1px solid var(--cy)}
.lb{display:flex;gap:10px;margin:4px 12px 8px}.lb button{flex:1}
#lmsg{margin:0 16px 8px;min-height:20px;color:#9fb4ff;font-size:14px}
#lamps h3{margin:16px 16px 8px;font-size:15px;font-weight:600;color:#9fb4ff}
.card .lv{flex-basis:100%;display:flex;align-items:center;gap:10px}
.card .lv input{flex:1;min-width:0;accent-color:#22d3ee}
.card .lv span{min-width:52px;text-align:right;color:#9fb4ff;font-size:14px}
#rules{position:fixed;inset:0;z-index:20;overflow-y:auto;background:#000;padding-bottom:40px;display:none}
#rules .top{position:sticky;top:0;display:flex;align-items:center;gap:12px;padding:14px 16px;background:#000000ee;backdrop-filter:blur(6px)}
#rules .top button{width:auto;font-size:26px;line-height:1;padding:6px 14px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
#rules p{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;white-space:pre-wrap;word-break:break-word}
#rules ul{margin:8px 0 0;padding-left:20px;white-space:normal}#rules li{margin:6px 0}
#rules .dm{display:block;color:#9fb4ff;font-size:13px;margin-bottom:4px}#rules p.dy.th{border-left:3px solid #7c3aed}#rules p.dy{position:relative;padding-left:50px;padding-right:52px}#rules .dyk{position:absolute;right:10px;top:8px;width:auto;padding:4px 8px;font-size:18px;background:none;border:1px solid #47556988;box-shadow:none;filter:grayscale(1);opacity:.55}#rules .dyk.on{filter:none;opacity:1;border-color:#fbbf24;background:#3a2a0a}#rules .dyk.err{border-color:#f87171}#rules p.dy.fest{border-color:#fbbf2499}#rules .dyc{position:absolute;left:14px;top:14px;width:24px;height:24px;accent-color:#d946ef}#rules p.dy.sel{border-color:#d946ef;background:#2a0f45cc}#dydel{position:sticky;bottom:12px;display:block;margin:12px auto;width:calc(100% - 24px)}#dydel:disabled{opacity:.5}#rules .lead{background:none;border:0;color:#9fb4ff;padding:4px 16px}
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
#chat{position:relative;margin:0 6px 8px;padding:0;border:none;border-radius:16px;background:#000;overflow:hidden;height:calc(100vh - 16px);font-size:15px}
#stage{display:none;position:absolute;left:0;right:0;top:60px;bottom:66px;z-index:0;overflow:hidden}
#stage::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:2;background:linear-gradient(90deg,#000 1.5%,#0005 7%,#0002 35%,transparent 55%,transparent 93%,#000 98.5%)}
#stage .fig{position:absolute;inset:0;transform-origin:50% 100%;animation:lsway 8s ease-in-out infinite}
#stage img,#stage video{position:absolute;inset:0;height:100%;width:100%;object-fit:cover;object-position:50% 50%;display:block}
#stage video{opacity:0;transition:opacity .8s}
#stage .fog{position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen;z-index:1}
#stage .fog i{position:absolute;border-radius:50%;filter:blur(26px);opacity:.6}
#stage .fl{left:-14%;top:10%;width:58%;height:52%;background:radial-gradient(closest-side,#22b8ffaa,#0e7fd466 45%,transparent 75%);animation:fogl 13s ease-in-out infinite alternate}
#stage .fr{right:-14%;top:12%;width:58%;height:52%;background:radial-gradient(closest-side,#c03cffaa,#8b2fd466 45%,transparent 75%);animation:fogr 15s ease-in-out infinite alternate}
#stage .ff{left:0;right:0;bottom:4%;height:22%;border-radius:0;filter:blur(18px);background:linear-gradient(90deg,transparent 4%,#22b8ff55 14%,transparent 30%,transparent 70%,#c03cff55 86%,transparent 96%);animation:fogf 6s ease-in-out infinite alternate}
@keyframes fogl{0%{transform:translate(0,0) scale(1);opacity:.4}50%{opacity:.8}100%{transform:translate(9%,6%) scale(1.15);opacity:.45}}
@keyframes fogr{0%{transform:translate(0,4%) scale(1.1);opacity:.5}50%{opacity:.85}100%{transform:translate(-9%,-3%) scale(.95);opacity:.35}}
@keyframes fogf{0%{opacity:.35;transform:scaleY(1)}100%{opacity:.75;transform:scaleY(1.15)}}
#stage.low .fog{opacity:.6}#stage video.on{opacity:1}
#stage video.pet{z-index:2;pointer-events:none;transition:opacity 1.2s}
#stage.vid .fig{opacity:0;animation:none}
#stage.low .fig{animation-duration:12s}#stage.low img{filter:saturate(.55) brightness(.75)}
#chat.oncall #stage{box-shadow:inset 0 0 40px #22d3ee55}#chat.oncall.speak #stage{box-shadow:inset 0 0 60px #d946efaa}
@keyframes lsway{0%,100%{transform:translateX(-6px) rotate(-.5deg)}50%{transform:translateX(6px) rotate(.5deg)}25%,75%{transform:scale(1.008)}}
#chat .chead{position:absolute;top:0;left:0;right:0;z-index:2;margin:0;padding:10px;display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
#chat .chead .cav,#chat .chead h2{display:none}
#chat .chead>div:nth-child(3){display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;flex:1}
#mlabel,#ccount{font-size:13px;padding:4px 9px;border-radius:12px;background:#0007;backdrop-filter:blur(4px)}
#chat #cnew{padding:5px 10px;font-size:13px;background:#0008;backdrop-filter:blur(4px)}
#chat .chead #clive{margin-left:8px;padding:7px 12px;font-size:14px}
#chat .chead #crose{margin-left:auto;width:auto;padding:7px 11px;font-size:16px;background:#000a;border:1px solid #f43f5e66}#chat .chead #crose.off{opacity:.4;filter:grayscale(1)}#chat .chead #cmus{margin-left:6px;width:auto;padding:7px 11px;font-size:16px;background:#000a;border:1px solid #22d3ee66}#chat .chead #cmus.off{opacity:.55;border-color:#64748b66}
#chat.oncall #clive{background:linear-gradient(90deg,#ef4444,#f97316)}
#lpill{display:none;width:100%;text-align:right;font-size:13px;color:#9fb4ff}#chat.oncall #lpill{display:block}
#clog{position:absolute;z-index:1;left:8px;top:92px;bottom:76px;width:56%;max-height:none;overflow-y:auto;justify-content:flex-end;-webkit-mask-image:linear-gradient(transparent,#000 8%);mask-image:linear-gradient(transparent,#000 8%)}
#clog .lr img{display:none}#clog .lr{max-width:100%}
#clog .m{font-size:15px;max-width:100%;backdrop-filter:blur(3px)}
#clog .u{background:#0009;border-color:#22d3ee44}#clog .l{background:#3a145799;border-color:#d946ef55}
#cin{position:absolute;z-index:2;left:8px;right:8px;bottom:8px;margin:0}
#cin{display:grid;grid-template-columns:1fr auto 1fr;align-items:center}#cin #cnew{justify-self:start;margin:0;padding:9px 14px;font-size:14px}
#ctype{display:flex;position:absolute;z-index:3;left:8px;right:auto;width:58%;bottom:8px;gap:6px;align-items:stretch}#chat #clog{bottom:70px}#ctype #cnew{width:auto;margin:0;padding:0 10px;font-size:13px;white-space:nowrap}#cin{display:none!important}
#ctype #ckb{position:absolute;right:-2px;top:-30px;width:auto;padding:3px 9px;font-size:12px;border-radius:999px;background:#000a;border:1px solid #22d3ee66}#ctype #ckb.on{background:linear-gradient(90deg,#22d3ee,#8b5cf6);color:#04121e}
#ctype textarea.hoert{border-color:#ef4444;box-shadow:0 0 14px #ef444488;animation:recp 1s infinite}
#ctype textarea{flex:1;min-height:44px;max-height:110px;height:48px;font:inherit;color:#fff;background:#000a;backdrop-filter:blur(4px);border:1px solid var(--bl);border-radius:10px;padding:9px;resize:none}#ctype #csend{width:auto;padding:0 12px;font-size:15px}
#cin #cmic{width:64px;height:64px;padding:0;border-radius:50%;font-size:28px;box-shadow:0 0 18px #d946ef88}
#clog{bottom:84px}body.chatfull #chat #clog{bottom:calc(70px + var(--kb,0px))}body.chatfull #chat #ctype{bottom:calc(8px + var(--kb,0px))}#stage{top:0;bottom:0}body.chatfull{overflow:hidden;overscroll-behavior:none}body.chatfull #chat{position:fixed;inset:0;z-index:15;margin:0;border-radius:0;height:100vh!important;height:100dvh!important}body.chatfull #menu{position:fixed;top:56px;left:8px;right:8px;z-index:60;max-height:80vh;overflow-y:auto}#chat .chead .cav,#chat #mlabel,#chat .chead>div:nth-child(3){display:none!important}#chat .chead #clive,#chat .chead #crose,#chat .chead #cmus{position:absolute;right:10px;margin:0;z-index:3;min-width:52px;text-align:center}#chat .chead #cmic{position:absolute;right:10px;top:10px;margin:0;z-index:3;min-width:52px;width:auto;height:auto;padding:7px 12px!important;font-size:14px;line-height:normal;border-radius:999px;box-shadow:none;text-align:center}#chat .chead #clive{top:58px}#chat .chead #crose{top:106px}#chat .chead #cmus{top:154px}#chat .chead #csend,#chat .chead #cnew{position:absolute;margin:0;z-index:3;min-width:52px;width:auto;height:auto;padding:7px 12px;font-size:14px;line-height:normal;border-radius:999px;text-align:center;white-space:nowrap}#chat .chead #csend{left:10px;top:106px}#chat .chead #cnew{left:10px;top:154px}#chat .chead #cmenu{width:auto;padding:7px 11px;font-size:16px;background:#000a;border:1px solid #22d3ee66}#chat #clog{pointer-events:none}#chat #clog>*{pointer-events:auto}#clog .m,#clog .lr,#clog .wait{pointer-events:none}#clog .play{pointer-events:auto}#ztimer{display:none;position:absolute;z-index:4;left:14px;top:64px;width:30px;height:30px;cursor:pointer}#zname{display:none;position:absolute;z-index:4;left:8px;top:200px;max-width:60%;padding:3px 7px;border-radius:7px;background:#000a;color:#9fe8ff;font-size:12px;pointer-events:auto}body.chatfull #ztimer{display:block}#ztimer circle{fill:none;stroke-width:4}#ztimer .bg{stroke:#ffffff26}#ztimer .fg{stroke:#ef4444;stroke-linecap:round;transform:rotate(-90deg);transform-origin:50% 50%;transition:stroke .2s}#ztimer.go .fg{stroke:#22c55e}#ztimer .dot{fill:#fff;stroke:none;opacity:0;transition:opacity .2s}#ztimer.hit .dot{opacity:.9}#ztimer.gold .dot{fill:#facc15;opacity:1}#stage .zring{position:absolute;z-index:6;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;border:2px solid #fffb;background:#ffffff1f;pointer-events:none;animation:zring .9s ease-out forwards}@keyframes zring{from{transform:scale(.5);opacity:1}to{transform:scale(1.4);opacity:0}}body.chatfull #chat{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}body.chatfull #chat textarea{-webkit-user-select:text;user-select:text}body.chatfull #clog{width:46%}body.chatfull #clog .m{font-size:13px;line-height:1.3;padding:6px 9px;border-radius:11px}body.chatfull #clog .wait{font-size:12px}#stage,#stage *{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}
/* 2.146.0 (Metin: the buttons looked untidy): every button of the stage is a symbol in one column at the right edge, from the top down: menu, microphone, live, rose, music, new chat, then the clip timer. Send sits alone at the right edge at the height of her calves. Same size and look for all, like rose and music before */
#chat .chead{padding:0;display:block;bottom:0;pointer-events:none}#chat .chead>*{pointer-events:auto}
#chat .chead #cmenu,#chat .chead #cmic,#chat .chead #clive,#chat .chead #crose,#chat .chead #cmus,#chat .chead #cnew,#chat .chead #csend{position:absolute;left:auto;right:10px;margin:0;z-index:3;width:50px;min-width:0;height:44px;padding:0!important;font-size:20px;line-height:1;border-radius:14px;background:#000a;border:1px solid #22d3ee66;box-shadow:none;display:flex;align-items:center;justify-content:center;white-space:nowrap;backdrop-filter:blur(4px)}
#chat .chead #cmenu{top:10px}
#chat .chead #cmic{top:62px;border-color:#d946ef88}
#chat .chead #clive{top:114px;border-color:#8b5cf688}
#chat .chead #crose{top:166px;border-color:#f43f5e66}
#chat .chead #cmus{top:218px}
#chat .chead #cnew{top:270px}
#chat .chead #csend{top:74%;border-color:#d946ef;background:linear-gradient(135deg,#8b5cf6cc,#d946efcc)}
#chat .chead #cmic.rec,#chat.oncall .chead #clive{background:linear-gradient(90deg,#ef4444,#f97316);border-color:#ef4444}
#ztimer{left:auto;right:20px;top:326px}
#zname{left:auto;right:10px;top:364px;max-width:70%}
#lpill{position:absolute;right:68px;top:126px;width:auto}
/* 2.144.2 (Metin: the black above her head must go completely): the installed app runs fullscreen, and without viewport-fit=cover Android keeps the strip beside the camera hole black. Now the stage fills that strip too; buttons, chat and lists stay below it */
body{padding-top:env(safe-area-inset-top,0px)}#rules{padding-top:env(safe-area-inset-top,0px)}
body.chatfull #chat{top:env(safe-area-inset-top,0px);bottom:env(safe-area-inset-bottom,0px);height:auto!important;overflow:visible}
body.chatfull #stage{top:calc(0px - env(safe-area-inset-top,0px));bottom:calc(0px - env(safe-area-inset-bottom,0px))}
body.chatfull #menu{top:calc(56px + env(safe-area-inset-top,0px))}
</style></head><body>
<div id="splash"><div class="sp"><img src="/icon.png?v=5" alt=""><svg viewBox="0 0 200 200"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#a855f7"/><stop offset="1" stop-color="#d946ef"/></linearGradient></defs><circle class="trk" cx="100" cy="100" r="90"/><circle class="rg" cx="100" cy="100" r="90" pathLength="100"/></svg></div></div>
<header><button id="back">&#8249;</button><img id="micon" src="/icon.png?v=5" alt="Menü" title="Menü"><h1>Leyla Gedächtnis</h1></header><div id="menu"></div><div id="pulse" class="ok" title="Alles in Ordnung"><div class="tick" id="tick" style="display:none"><span></span></div><i class="spark" style="left:12%;top:30%;animation-delay:0s"></i><i class="spark" style="left:22%;top:68%;animation-delay:0.6s"></i><i class="spark" style="left:31%;top:22%;animation-delay:1.2s"></i><i class="spark" style="left:68%;top:74%;animation-delay:0.3s"></i><i class="spark" style="left:77%;top:28%;animation-delay:0.9s"></i><i class="spark" style="left:88%;top:60%;animation-delay:1.5s"></i><i class="spark" style="left:40%;top:80%;animation-delay:1.8s"></i><i class="spark" style="left:60%;top:18%;animation-delay:2.1s"></i><div class="beam"></div><svg viewBox="0 0 100 90"><defs><linearGradient id="hg" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#f43f5e"/></linearGradient><radialGradient id="hc"><stop offset="0" stop-color="#fff"/><stop offset=".4" stop-color="#7dd3fc"/><stop offset="1" stop-color="#7dd3fc" stop-opacity="0"/></radialGradient></defs><path d="M50 84C20 62 4 46 4 28C4 14 15 4 28 4C38 4 46 10 50 18C54 10 62 4 72 4C85 4 96 14 96 28C96 46 80 62 50 84Z" fill="#0b1650cc" stroke="url(#hg)" stroke-width="3.2" stroke-linejoin="round"/><path d="M14 40H34L40 28L47 54L53 34L58 44H86" fill="none" stroke="#e0f2fe" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/><circle cx="54" cy="38" r="9" fill="url(#hc)"/></svg></div><div id="chat"><div id="stage"><div class="fig"><img src="/leyla_body.jpg" alt=""></div><video id="svid" muted playsinline preload="auto"></video><video id="svid2" muted playsinline preload="auto"></video><video id="spet" class="pet" muted playsinline preload="auto"></video><div class="fog"><i class="fl"></i><i class="fr"></i><i class="ff"></i></div></div><div class="chead"><button id="cmenu" title="Menü">&#9776;</button><div class="cav"><img src="/leyla.jpg" alt=""><span id="mbadge"></span></div><div><h2>Chat mit Leyla</h2><div id="mlabel"></div><div id="ccount"></div></div><button id="crose" title="Rose schenken, einmal pro Woche">&#127801;</button><button id="cmus" title="Musik an oder aus">&#127925;</button><button id="clive" title="Live mit Leyla reden">&#128222;</button><div id="lpill"></div></div><div id="clog"></div><div id="ctype"><textarea id="ctext" readonly inputmode="none" placeholder="Tippen und sprechen ..."></textarea><button id="ckb" title="Tastatur statt Diktat">abc</button><button id="csend" title="Senden">&#10148;</button></div><div id="cin"><button id="cnew" title="Neuen Chat beginnen">&#128172;&#8314;</button><button id="cmic" title="Sprachnachricht">&#127908;</button></div></div><div id="live"><img src="/leyla.jpg" alt=""><div id="lstat">Verbinde ...</div><button id="lend">Auflegen</button></div><div id="rules"><div class="top"><button id="rback">&#8249;</button><h1>So ist Leyla</h1></div><div id="rtext"></div></div><div id="root"></div><div id="gmail" style="display:none"></div><div id="lamps" style="display:none"></div>
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
function sndLabel(){const b=document.getElementById('snd');if(b)b.textContent=soundOn?'Ton an':'Ton aus';}
function sndBtn(){const t=document.createElement('button');t.id='snd';t.onclick=()=>{soundOn=!soundOn;try{localStorage.setItem('snd',soundOn?'1':'0')}catch(e){}sndLabel();if(soundOn)snd.on();};t.textContent=soundOn?'Ton an':'Ton aus';return t;}
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
let sec=null,menuOpen=false,LASTD=null;
const SECNAME={family:'Familie und Haushalt',friends:'Freunde und Verwandte',leyla:'Leylas Geschichte',private:'Privat',mail:'Google verbinden',lamps:'Lampenfarben',set:'Einstellungen'};
const SECICON={family:'👪',friends:'🤝',leyla:'💜',private:'🔒',mail:'✉',lamps:'💡',rules:'📜',diary:'📔',full:'⛶',set:'⚙'};
let LOOKS=[];  /* her dresses, filled by clipsLoad */
function menuItems(){const it=[];const ls=(LASTD&&LASTD.lists)||[];
 for(const l of ls)it.push([l.kind,l.title,l.items.length]);
 if(CODE&&GM.shown&&GM.needs)it.push(['mail','Google verbinden','']);if(lampOn)it.push(['lamps','Lampenfarben','']);
 if(CODE){it.push(['diary','Tagebuch',LASTD&&LASTD.diary_n!=null?LASTD.diary_n:'']);it.push(['rules','So ist Leyla',''])};if(LOOKS.length>1)it.push(['look','Kleid wechseln','']);it.push(['full','Vollbild','']);it.push(['set','Einstellungen','']);return it;}
function drawMenu(){const m=document.getElementById('menu');m.innerHTML='';m.style.display=menuOpen?'block':'none';document.getElementById('micon').classList.toggle('open',menuOpen);if(!menuOpen)return;
 for(const [k,t,n] of menuItems()){const b=document.createElement('button');b.className='mi';const i=document.createElement('i');i.textContent=SECICON[k]||'•';
  const sp=document.createElement('span');sp.textContent=t;const sm=document.createElement('small');sm.textContent=n===''?'':String(n);const ch=document.createElement('b');ch.textContent='›';
  b.append(i,sp,sm,ch);b.onclick=()=>openSec(k);m.appendChild(b);}}
document.getElementById('micon').onclick=()=>{menuOpen=!menuOpen;snd[menuOpen?'on':'off']();drawMenu();};
document.getElementById('cmenu').onclick=e=>{e.stopPropagation();document.getElementById('micon').onclick();};
function openSec(k){menuOpen=false;drawMenu();if(k==='rules'){openRules();return;}if(k==='diary'){openDiary();return;}
 if(k==='look'){  /* 2.146.3 (Metin wants to look at the clips of the other dress): the next look, kept for today like the one picked at random */
  const i=LOOKS.indexOf(OUTFIT),nx=LOOKS[(i+1)%LOOKS.length];
  try{localStorage.setItem('loutfit',nx);localStorage.setItem('loutfitday',dressDay());localStorage.setItem('lseen',String(Date.now()));}catch(e){}
  location.reload();return;}
 if(k==='full'){  /* 2.134.2 (Metin): the stage over the whole phone, without the address bar */
  const on=!document.fullscreenElement;
  try{localStorage.setItem('lfull',on?'1':'0');}catch(e){}  /* 2.134.4: remembered, so the next visit goes full screen at his first touch; a browser never allows it without one */
  if(on)goFull();else document.exitFullscreen().catch(()=>{});
  return;}
 const was=sec;sec=k;view=null;sel=new Set();last='';if(!was)history.pushState({s:1},'');else history.replaceState({s:1},'');window.scrollTo(0,0);snd.on();
 if(k==='mail')gmailLoad();if(k==='lamps')loadLamps();load();}
function openFolder(kind,head){view={kind,head,text:''};sel=new Set();last='';history.pushState({f:1},'');window.scrollTo(0,0);snd.on();load();}
function closeFolder(){view=null;sel=new Set();last='';load();}
window.addEventListener('popstate',()=>{if(view)closeFolder();else if(sec&&!rulesOpen){sec=null;sel=new Set();last='';if(menuOpen){menuOpen=false;drawMenu();}load();}});
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
let CDROP=0;try{CDROP=+localStorage.getItem('lcdrop')||0}catch(e){}
const isTalk=m=>m.role==='user'||m.role==='leyla';
function chatSave(){let k=0,cut=0;for(let i=CHAT.length-1;i>=0;i--){if(isTalk(CHAT[i])&&++k===20){cut=i;break;}}if(cut>0){CDROP+=CHAT.slice(0,cut).filter(isTalk).length;CHAT=CHAT.slice(cut);}try{localStorage.setItem('lchat',JSON.stringify(CHAT));localStorage.setItem('lcdrop',String(CDROP))}catch(e){}}
function chatNew(){CHAT=[];CDROP=0;chatSave();chatDraw();post('/api/chat_new',{}).catch(()=>{});}
function chatDraw(wait){const log=document.getElementById('clog');log.innerHTML='';{const n=CDROP+CHAT.filter(isTalk).length,c=document.getElementById('ccount');const r=Math.max(0,20-n);c.textContent='Noch '+r+' von 20';c.className=r===0?'over':r<=3?'warn':'';}
 CHAT.forEach((m,i)=>{if(m.role==='prop'){if(m.done==='Gespeichert'||m.done==='Verworfen')return;return log.appendChild(propCard(m,i));}
  if(m.role==='info'){const n=document.createElement('div');n.className='wait';n.textContent=m.text;return log.appendChild(n);}
  if(m.role==='noted')return log.appendChild(notedLine(m,i));
  if(m.role==='mail')return log.appendChild(mailCard(m,i));
  if(m.role==='trash')return log.appendChild(trashCard(m,i));
  if(m.role==='remind')return log.appendChild(remindCard(m,i));
  const d=document.createElement('div');d.className='m '+(m.role==='user'?'u':'l');d.textContent=m.text;
  /* 2.143.1 (Metin): her voice replies show no text, only the play button; while the voice is still coming a speaker sign. Without audio (after a reload, or when the voice failed) the text shows as before */
  if(m.aid&&AUDIO.has(m.aid)){d.textContent='';const b=document.createElement('button');b.className='play';b.style.marginLeft='0';b.textContent='\u25B6';b.onclick=()=>playAudio(m.aid);d.appendChild(b);}
  else if(m.aid&&VSTREAM.has(m.aid))d.textContent='🔊';
  if(m.rid&&m.voice){const b=document.createElement('button');b.className='play';b.textContent='\u25B6';b.onclick=()=>reachPlay(m.rid);d.appendChild(b);}
  if(m.role==='user')return log.appendChild(d);const r=document.createElement('div');r.className='lr';const im=document.createElement('img');im.src='/leyla.jpg';im.alt='';r.append(im,d);log.appendChild(r);});
 if(wait){const w=document.createElement('div');w.className='wait';w.textContent='Leyla schreibt ...';log.appendChild(w);}
 {const kids=[...log.children],talk=[];kids.forEach((e,i)=>{if(e.classList.contains('u')||e.classList.contains('lr'))talk.push(i);});const k=talk.length>2?talk[talk.length-2]:0;kids.slice(0,k).forEach(e=>e.style.display='none');}
 log.scrollTop=log.scrollHeight;}
function diffText(o,n){if(o.indexOf(' | ')<0&&n.indexOf(' | ')<0)return o+'  \u2192  '+n;const a=o.split(' | '),b=n.split(' | ');
 const kv=l=>{const m=new Map();l.slice(1).forEach(x=>{const i=x.indexOf(':');m.set(i>0?x.slice(0,i).trim():x,i>0?x.slice(i+1).trim():'');});return m;};
 const A=kv(a),B=kv(b),out=[];
 B.forEach((v,k)=>{if(!A.has(k))out.push('neu '+k+': '+v);else if(A.get(k)!==v){const nv=v.split('; davor:')[0].trim();out.push(k+': '+nv);}});
 A.forEach((v,k)=>{if(!B.has(k))out.push('weg: '+k);});
 return title(b[0])+'\\n'+(out.join('\\n')||'(nur Kleinigkeiten)');}
/* 2.149.0 (Metin: the Ja/Nein card does not feel alive): what she kept by herself is one small line; the cross strikes it again (an added entry is deleted, a profile gets its old text back) */
function notedLine(m,i){const p=m.p,n=document.createElement('div');n.className='wait noted';
 const t=document.createElement('span');t.textContent='💭 '+(p.action==='add'?p.new:diffText(p.old,p.new).replace(/\\n/g,', '));n.appendChild(t);
 const x=document.createElement('button');x.textContent='\u2715';x.title='Streichen';
 x.onclick=async()=>{x.disabled=true;let ok=false;
  try{ok=p.action==='add'?(await (await post('/api/delete',{items:[{kind:p.kind,text:p.new}]})).json()).removed>0:(await (await post('/api/edit',{kind:p.kind,old:p.new,new:p.old})).json()).ok;}catch(e){}
  if(ok){CHAT.splice(i,1);snd.off();}else{CHAT[i]={role:'info',text:'Ging nicht, der Eintrag hat sich inzwischen geändert'};}chatSave();chatDraw();last='';load();};
 n.appendChild(x);return n;}
function propCard(m,i){const c=document.createElement('div');c.className='p';const p=m.p;
 const what=p.action==='add'?'Merken':p.action==='edit'?'Ändern':p.action==='move'?'Verschieben nach '+(KNAME[p.to]||p.to)+' von':'Streichen';
 const h=document.createElement('b');h.textContent=what+' ('+(KNAME[p.kind]||p.kind)+')';c.appendChild(h);
 const t=document.createElement('div');t.textContent=p.action==='add'?p.new:p.action==='edit'?diffText(p.old,p.new):p.old;c.appendChild(t);
 if(m.done){const s=document.createElement('div');s.textContent=m.done;s.style.marginTop='6px';s.style.color='#9fb4ff';c.appendChild(s);return c;}
 const row=document.createElement('div');row.className='row';const y=document.createElement('button');y.textContent='Ja';const n=document.createElement('button');n.textContent='Nein';n.className='no';
 y.onclick=async()=>{y.disabled=n.disabled=true;let ok=false;
  try{if(p.action==='add')ok=(await (await post('/api/add',{kind:p.kind,text:p.new})).json()).ok;
   else if(p.action==='edit')ok=(await (await post('/api/edit',{kind:p.kind,old:p.old,new:p.new})).json()).ok;
   else if(p.action==='move'){ok=(await (await post('/api/add',{kind:p.to,text:p.old})).json()).ok;
    if(ok)ok=(await (await post('/api/delete',{items:[{kind:p.kind,text:p.old}]})).json()).removed>0;}
   else ok=(await (await post('/api/delete',{items:[{kind:p.kind,text:p.old}]})).json()).removed>0;}catch(e){}
  if(ok){CHAT.splice(i,1);snd.save();}else CHAT[i].done='Ging nicht, der Eintrag hat sich inzwischen geändert';chatSave();chatDraw();last='';load();};
 n.onclick=()=>{CHAT.splice(i,1);snd.off();chatSave();chatDraw();};
 row.append(y,n);c.appendChild(row);return c;}
let CRTT=null;  /* 2.141.6: round trip of the last chat answer, sent with the next one */
async function chatSend(){const ta=document.getElementById('ctext'),msg=ta.value.trim();if(!msg)return;
 const history=CHAT.filter(m=>m.role==='user'||m.role==='leyla').map(m=>({role:m.role,text:m.text}));
 CHAT.push({role:'user',text:msg});ta.value='';DIKQ=false;bgmTick();chatSave();chatDraw(true);snd.on();  /* music back on when he sends (2.140.1, Metin) */
 if(!ta.readOnly){const kb=document.getElementById('ckb');if(kb)kb.onclick();}  /* back to dictation after sending (2.140.0) */
 let j=null;const t0=performance.now();try{j=await (await post('/api/chat',{history,message:msg,rtt:CRTT,light:lightNow()})).json();}catch(e){}
 CRTT=Math.round(performance.now()-t0);chatAnswer(j);chatSave();chatDraw();snd.drop();}
const AUDIO=new Map(),VSTREAM=new Set();let REC=null,RECT=null,DIK=null,DIKT=null,DIKQ=false;  /* DIK: dictation, DIKQ: music stays off until he sends */
let VOUT=null;function voiceOut(){if(!VOUT){VCTX=VCTX||new (window.AudioContext||window.webkitAudioContext)();const g=VCTX.createGain(),l=VCTX.createDynamicsCompressor();
 g.gain.value=1.05;l.threshold.value=-1;l.knee.value=0;l.ratio.value=20;l.attack.value=.003;l.release.value=.1;g.connect(l);l.connect(VCTX.destination);VOUT=g;}return VOUT;}  /* 2.142.5: her voice 5 % louder (Metin), a limiter keeps it from clipping */
function playAudio(id){try{const a=new Audio(AUDIO.get(id));try{VCTX=VCTX||new (window.AudioContext||window.webkitAudioContext)();VCTX.resume();VCTX.createMediaElementSource(a).connect(voiceOut());}catch(e){}let v=false;const off=()=>{stageTalk(false);if(v){v=false;voiceOn(false);}};a.onplay=()=>{stageTalk(true);if(!v){v=true;voiceOn(true);}};a.onended=a.onpause=off;a.play().catch(off);}catch(e){}}
let TALKING=false,DANCING=false;
const DANCE_N=4;
function zeigenChain(){if(!STM||STM.outfit!=='nacht')return null;const T=['ruhig','mittel','schnell'].filter(t=>clipVars('zeigen'+t).length);if(clipVars('zeigenlang').length&&(!T.length||Math.random()<.5))return ['zeigenlang'];if(!T.length)return null;const t=T[Math.floor(Math.random()*T.length)],f='zeigen'+t,o=[];
 if(clipVars('hinten').length&&clipVars(f+'hf').length){o.push([f,'hinten',f+'hf']);if(clipVars(f+'hh').length)o.push(['hinten',f+'hh',f+'hf']);}
 if(!o.length)o.push([f,f,f]);return o[Math.floor(Math.random()*o.length)];}  /* night show (2.119.1, Metin): three clips of one tempo, front poses, turning away, posing from behind, turning back; fast ones three front poses */
function stageScene(n){if(!CLIPS||!STM)return;ZCOLNOW='';if(n==='komm'&&!clipVars('komm').length)n='liebe';const ok=n==='zeigen'&&zeigenChain()?1:n==='bettvonarbeit'?(clipVars(n).length||clipVars('umziehen').length):clipVars(n).length;if(!ok)return;
 ZBUSY=Date.now()+300000;ZPEND=null;SWAP=0;CONT=false;document.querySelectorAll('#stage video:not(.pet)').forEach(x=>{x.style.transition='opacity .35s';setTimeout(()=>{x.style.transition='';},1500);});
 stageSceneNow(n);}
function stageSceneNow(n){if(n==='bettvonarbeit'&&!clipVars(n).length&&clipVars('umziehen').length)return stagePlay(['umziehen','bettvonfreizeit'],clipFor(STM));
 const zc=n==='zeigen'?zeigenChain():null;if(zc)return stagePlay(zc,clipFor(STM));  /* 2.133.7: the night show was dead because no night clip is called zeigen (they are zeigenlang, zeigenruhig ...) and the check below asked for exactly that; it also rolled the chain twice, once for the check and once for playing */
 if(!clipVars(n).length)return;if(n.startsWith('tanz'))stageDance(n);else stagePlay([n],clipFor(STM));}
const DNEXT={"hinten":["tanzhh2","tanzhh3","tanzhh5","tanzhf","tanzhf2","tanzhf3","tanzhf4","tanzhf5","tanzhf6","tanzhf7"],"hinten2":["tanzhf4"],"hinten3":["tanzhh5","tanzhf","tanzhf4","tanzhf6","tanzhf7"],"hinten4":["tanzhh","tanzhh2","tanzhh3","tanzhh5","tanzhf","tanzhf2","tanzhf3","tanzhf4","tanzhf5","tanzhf6","tanzhf7"],"tanzhh":["tanzhh5","tanzhf2","tanzhf3"],"tanzhh2":["tanzhh5","tanzhf","tanzhf4","tanzhf6","tanzhf7"],"tanzhh3":["tanzhh2","tanzhh5","tanzhf","tanzhf2","tanzhf3","tanzhf4","tanzhf5","tanzhf6","tanzhf7"],"tanzhh4":["tanzhh5","tanzhf","tanzhf4","tanzhf6","tanzhf7"],"tanzhh5":["tanzhf","tanzhf3","tanzhf4","tanzhf6","tanzhf7"],"tanz":["tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz2":["tanz","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz3":["tanz","tanz2","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz4":["tanz","tanz2","tanz3","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz5":["tanz","tanz2","tanz3","tanz4","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz6":["tanz2","tanz3","tanz5","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz7":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz10","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz8":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz9","tanz10","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz9":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz10","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz10":["tanz2","tanz6","tanz7","tanz8","tanz9","hinten","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf2":["tanz2","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf3":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf4":["hinten4"],"tanzhf5":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf6":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanzhf7":["tanz","tanz2","tanz3","tanz4","tanz5","tanz6","tanz7","tanz8","tanz9","tanz10","hinten","hinten2","hinten3","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz11":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz12":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz13":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz14":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz15":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz16":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz17":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz18":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz19":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz20":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz21":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz22":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz23":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz24","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz24":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz25","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz25":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz26","tanz27","tanz28","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz26":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz28","tanz29"],"tanz27":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz28","tanz29"],"tanz28":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz29","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz29":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz26","tanz27","tanz28","tanz30","tanz31","tanz32","tanz33","tanz34","tanz35","tanz36","tanz37"],"tanz30":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz31":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz32":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz33":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz34":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz35":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz36":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"],"tanz37":["tanz","tanz2","tanz3","tanz4","tanz5","hinten","hinten2","hinten4","tanz11","tanz12","tanz13","tanz14","tanz15","tanz16","tanz17","tanz18","tanz19","tanz20","tanz21","tanz22","tanz23","tanz24","tanz25","tanz29","tanz28"]};  // measured: end pose of a clip against the start pose of the next (night dances, 20 Nov 2026); tanz12 and tanz13 belly dances mirror tanz11 (2.131.2), tanz14 R&B dance too (2.131.3), tanz15 to tanz22 back view dances (2.131.4 to 2.131.7), tanz23 to tanz25 belly dances (2.131.8), tanz26 and tanz27 20 s solos that never follow each other (2.131.9), tanz28 and tanz29 (2.132.0)
const DFIRST_BAD=['hinten3','hinten4'],DLAST_BAD=['tanzhf4'];let DUSED={};try{DUSED=JSON.parse(localStorage.getItem('ldused')||'{}');}catch(e){}
const DNEXTW={"kurz":{"tanz":["tanz5","tanz8","tanz4","tanz9"],"tanz4":["tanz5","tanz8","tanz9"],"tanz5":["tanz8","tanz9","tanz4","tanz"],"tanz8":["tanz4","tanz5"],"tanz9":["tanz5","tanz8","tanz4"]}};  // work dresses, measured like the night table (kurz threshold 6, its poses vary more), 2.116.3
function workChain(){const T=DNEXTW[OUTFIT];if(!T)return [];const have=n=>CLIPS.includes(n);const lru=c=>{c=c.filter(have);if(!c.length)return null;c.sort((a,b)=>((DUSED[OUTFIT+a]||0)-(DUSED[OUTFIT+b]||0))||(Math.random()-.5));return c[Math.floor(Math.random()*Math.min(2,c.length))];};
 let cur=lru(Object.keys(T));if(!cur)return [];const q=[cur];while(q.length<DANCE_N){const n=lru((T[cur]||[]).filter(x=>!q.includes(x)));if(!n)break;q.push(n);cur=n;}
 const t=Date.now();q.forEach((n,k)=>DUSED[OUTFIT+n]=t+k);try{localStorage.setItem('ldused',JSON.stringify(DUSED));}catch(e){}return q;}
function danceChain(){const have=n=>NIGHT.includes(n),isBack=n=>/^(hinten|tanzhh)/.test(n);  // night: chain by facing, only transitions whose poses match, least used first (2.116.2)
 const lru=c=>{c=c.filter(have);if(!c.length)return null;c.sort((a,b)=>((DUSED[a]||0)-(DUSED[b]||0))||(Math.random()-.5));return c[Math.floor(Math.random()*Math.min(2,c.length))];};
 for(let tries=0;tries<20;tries++){const q=[];let cur=lru(Object.keys(DNEXT).filter(n=>/^(tanz[0-9]*|hinten[0-9]*)$/.test(n)&&!DFIRST_BAD.includes(n)&&(Math.random()<.5||!isBack(n))));if(!cur)return [];q.push(cur);
  while(q.length<DANCE_N+2){const left=DANCE_N-q.length;let c=(DNEXT[cur]||[]).filter(n=>!q.includes(n));
   if(left<=0){if(!isBack(cur)&&!DLAST_BAD.includes(cur))break;c=c.filter(n=>/^tanzhf/.test(n)&&!DLAST_BAD.includes(n));}
   else if(left===1)c=c.filter(n=>!isBack(n)&&!DLAST_BAD.includes(n)&&(isBack(cur)?/^tanzhf/.test(n):/^tanz[0-9]*$/.test(n)));
   const n=lru(c);if(!n)break;q.push(n);cur=n;}
  if(!isBack(cur)&&!DLAST_BAD.includes(cur)){const t=Date.now();q.forEach((n,k)=>DUSED[n]=t+k);try{localStorage.setItem('ldused',JSON.stringify(DUSED));}catch(e){}return q.map(n=>'nacht/'+n);}}
 return [];}
function stageDance(name){const v=clipVars(name);if(!CLIPS||!STM||!v.length)return;const q=[];let pool=[];
 for(let i=0;i<DANCE_N&&(q.length<v.length||name==='tanz');i++){if(!pool.length)pool=v.filter(n=>n!==q[q.length-1]).sort(()=>Math.random()-0.5);q.push(pool.shift());}
 if(STM&&STM.outfit==='nacht'&&name==='tanz'&&clipVars('tanzhf').length){const c=danceChain();if(c.length){q.length=0;q.push(...c);}}
 else if(name==='tanz'&&(!STM||!STM.outfit||STM.outfit==='arbeit')&&DNEXTW[OUTFIT]){const c=workChain();if(c.length){q.length=0;q.push(...c);}}
 DANCING=true;const next=()=>{const n=q.shift();if(n)stageShow(n,false,next,true);else{DANCING=false;stageLoop(clipFor(STM));}};next();}
function stageTalk(on){on=!!on;if(on===TALKING||CLIPS===null||!STM)return;TALKING=on;
 const t=STM.low&&clipVars('sprichttraurig').length?'sprichttraurig':'spricht';
 if(!clipVars(t).length||DANCING)return;if(on)stageLoop(t);else stagePlay([],clipFor(STM));}
function moodShow(st){if(!st||!st.mood)return;const c=document.getElementById('chat'),b=document.getElementById('mbadge');
 c.classList.toggle('low',!!st.low);c.classList.toggle('good',!st.low);document.getElementById('pulse').dataset.mood=st.low?'low':'good';b.style.display='flex';b.textContent=st.low?'🖤':'❤️';
 document.getElementById('mlabel').textContent=(st.low?'🖤 ':'❤️ ')+st.label;LASTST=st;const rb=document.getElementById('crose');if(rb)rb.classList.toggle('off',st.rose!=='ready');stageMood(st);}
let CLIPS=null,LASTST=null,STM=null;
let CVER={},MUSV={},PET=[],PETON=false,PETCAME=false;let OUTFIT='',NIGHT=[],NIGHTBODY=false,LOOKBODY='';const CHANGE=['umziehen','bettvonarbeit','bettvonfreizeit'];
/* Mokka, Leyla's cat (2.127.0, Metin's gift, name and look chosen by Leyla): a see through
   layer over the stage, same size and fit as the clips, only while Leyla wears her Freizeit
   clothes. She walks in from the right once (kommt), then plays her sitting loops (sitzt...). */
function petUrl(n){return '/clips/mokka/'+n+'.webm?v='+(CVER.mokka||0);}
const PETSIT=6.0;  /* 2.131.0: second of kommt.webm where Mokka sits like the first keyframe of the surprise clip */
function petFreude(v,clip){try{localStorage.setItem('lmokka','1');}catch(e){}post('/api/pet',{}).catch(()=>{});ZBUSY=Date.now()+20000;  /* the first time: Leyla discovers Mokka, cuddles her and puts her down (clip carries the cat) */
 v.style.transition='opacity .35s';v.classList.remove('on');setTimeout(()=>{v.pause();v.style.transition='';},400);
 stageShow(clip,false,()=>{const a=document.getElementById(SV?'svid2':'svid'),left=a&&a.duration?Math.max(0,(endOf(a)-a.currentTime)*1000/(a.playbackRate||1)-350):3000;
  setTimeout(()=>{if(PETON){petNext();v.classList.add('on');}},left);stageLoop(clipFor(STM));},true);}
function petIdle(){const l=PET.filter(n=>n.startsWith('liegt'));return l.length?l:PET.filter(n=>n.startsWith('sitzt'));}  /* 2.130.0: after the walk in she sleeps (liegt), sitzt only as a fallback */
function petNext(){const v=document.getElementById('spet');if(!v||!PETON)return;const idle=petIdle();if(!idle.length)return;
 const n=idle[Math.floor(Math.random()*idle.length)];v.loop=idle.length===1;v.src=petUrl(n);v.playbackRate=rateOf('mokka/'+n);v.play().catch(()=>{});}
function petTick(){const v=document.getElementById('spet');if(!v)return;const want=!!(STM&&STM.outfit==='freizeit'&&PET.length&&document.body.classList.contains('chatfull'));
 if(want&&!PETON){PETON=true;v.onended=petNext;v.ontimeupdate=null;v.classList.add('on');if(PET.includes('kommt')&&!PETCAME){PETCAME=true;v.loop=false;v.src=petUrl('kommt');v.play().catch(()=>{});let first=false;try{first=!localStorage.getItem('lmokka');}catch(e){}const fr=clipVars('mokka');if(first&&fr.length)v.ontimeupdate=()=>{if(v.currentTime<PETSIT)return;v.ontimeupdate=null;petFreude(v,fr[0]);};}else petNext();}
 else if(!want&&PETON){PETON=false;v.classList.remove('on');setTimeout(()=>{if(!PETON){v.pause();v.removeAttribute('src');v.load();}},1300);}}
setInterval(petTick,2000);
const AWAY_MS=4*3600*1000;  /* she chooses her dress at 5 in the morning and keeps it; only after the app has been closed for hours can she have changed (docs/SZENEN_KONZEPT.md, Kleiderwechsel; until 2.133.2 every reload rolled a new dress, Metin 22.11.2026) */
function dressDay(){const d=new Date(Date.now()-5*3600*1000);return d.getFullYear()+'-'+(d.getMonth()+1)+'-'+d.getDate();}
function seenTick(){try{localStorage.setItem('lseen',String(Date.now()));}catch(e){}}
setInterval(seenTick,60000);document.addEventListener('visibilitychange',seenTick);
function goFull(){const d=document.documentElement;if(document.fullscreenElement)return;(d.requestFullscreen?d.requestFullscreen({navigationUI:'hide'}):Promise.reject()).catch(()=>{});}
/* 2.134.5: at every touch, not only the first one after loading; leaving full screen with the system gesture otherwise kept it off until he used the menu again (Metin).
   2.144.2 (Metin: full screen at once, not by hand through the menu): a finger only counts as a user action for the browser when it lifts (pointerup, click), not when it goes down, so on the phone the old pointerdown never switched; and on a phone full screen is now the default until he turns it off in the menu */
function fullWant(){if(runMode()!=='browser')return false;  /* 2.146.4: the installed app already is full screen; asking again only made Chrome show its notice "zum Beenden des Vollbildmodus ..." at the first tap (Metin: it takes the immersion away) */
 let v=null;try{v=localStorage.getItem('lfull');}catch(e){}return v==='1'||(v!=='0'&&PHONE);}
for(const ev of ['pointerup','click','keydown'])document.addEventListener(ev,()=>{if(fullWant()&&!document.fullscreenElement)goFull();},true);
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});
/* 2.144.3 (Metin: full screen at once when he opens the app, without any tap): the page reports how it runs (tab or app), so the cause can be read from the server. 2.144.4: the install button of 2.144.3 is gone again. Metin's icon already is an installed app; Chrome opens an app whose address only exists in the home network as a tab with its bars anyway (known behaviour, see STATUS.md), so installing again changes nothing */
let INST=null;
function runMode(){for(const m of ['fullscreen','standalone','minimal-ui'])if(matchMedia('(display-mode: '+m+')').matches)return m;return 'browser';}
function diag(ev){try{fetch('/api/diag',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ev,mode:runMode(),secure:!!window.isSecureContext,sw:!!(navigator.serviceWorker&&navigator.serviceWorker.controller),inst:!!INST,ua:(navigator.userAgent.match(/Chrome.[0-9]+/)||[''])[0]+(/Android/.test(navigator.userAgent)?' Android':'')})}).catch(()=>{});}catch(e){}}
window.addEventListener('beforeinstallprompt',e=>{INST=e;diag('installable');});
window.addEventListener('appinstalled',()=>{INST=null;diag('installed');});
setTimeout(()=>diag('open'),4000);  /* 2.134.3: only with a service worker does Chrome install the page as an app, and only then does the manifest's fullscreen apply */
async function clipsLoad(){let outs={};try{outs=(await (await fetch('/clips.json')).json()).outfits||{};}catch(e){}
 for(const k in outs){CVER[k]=outs[k].v||0;const r=outs[k].r||{};for(const c in r)RATE[k+'/'+c]=r[c];const q=outs[k].k||{};for(const c in q)KURVE[k+'/'+c]=q[c];const sc=outs[k].s||{};for(const c in sc)SCHNITT[k+'/'+c]=sc[c];}  /* 2.136.0 (Metin): his tempo from the tester, the clip files stay untouched */
NIGHT=outs.nacht?outs.nacht.clips:[];NIGHTBODY=!!(outs.nacht&&outs.nacht.body);delete outs.nacht;PET=outs.mokka&&outs.mokka.alpha||[];delete outs.mokka;const names=Object.keys(outs);LOOKS=names.slice().sort();
 let last='',lday='',seen=0;try{last=localStorage.getItem('loutfit')||'';lday=localStorage.getItem('loutfitday')||'';seen=Number(localStorage.getItem('lseen')||0);}catch(e){}
 let mokpend=false;try{mokpend=!localStorage.getItem('lmokka');}catch(e){}
 const mok=PET.length&&mokpend?names.filter(n=>(outs[n].clips||[]).includes('freizeitmokka')):[];  /* until Metin's surprise has played she wears the dress that has the discovery clip (2.133.6) */
 const keep=!mok.length&&last&&names.includes(last)&&lday===dressDay()&&(Date.now()-seen)<AWAY_MS;
 if(mok.length)OUTFIT=mok[0];else if(keep)OUTFIT=last;else{const cand=names.length>1?names.filter(n=>n!==last):names;OUTFIT=cand.length?cand[Math.floor(Math.random()*cand.length)]:'';}
 try{if(OUTFIT){localStorage.setItem('loutfit',OUTFIT);localStorage.setItem('loutfitday',dressDay());}}catch(e){}
 seenTick();
 CLIPS=OUTFIT?outs[OUTFIT].clips:[];if(OUTFIT&&outs[OUTFIT].body){LOOKBODY='/clips/'+OUTFIT+'/body.jpg?v='+(CVER[OUTFIT]||0);document.querySelector('#stage .fig img').src=LOOKBODY;}
 if(LASTST)stageMood(LASTST);}
function clipVars(b){const o=STM&&!CHANGE.includes(b)?STM.outfit:'';if(o==='nacht')return NIGHT.filter(n=>n.replace(/[0-9]+$/,'')===b).map(n=>'nacht/'+n);
 const k=o==='freizeit'?'freizeit'+b:b;return CLIPS.filter(n=>n.replace(/[0-9]+$/,'')===k);}  // Freizeit: freizeit<name> clips (2.113.0), night: folder nacht (2.114.0)
function clipFor(st){const lv=st.low&&st.level&&st.mood!=='eifersuechtig'?'traurig'+st.level:'';if(lv&&clipVars(lv).length)return lv;if(clipVars(st.mood).length)return st.mood;
 const g=(st.low?['traurigleicht','traurig','eifersuechtig'].concat(st.outfit&&st.outfit!=='arbeit'?['gluecklich']:[]):['gluecklich']).filter(n=>clipVars(n).length);return g.length?g[0]:null;}
/* light copies on the go (2.141.0, Metin: the 4K clips stall on mobile data). Automatic:
   on mobile data, or after a clip has stalled twice within a minute. */
let LIGHT=false,STALLS=[];
/* 2.143.0: a phone always gets the copy at phone size (1440 px wide); its screen cannot show more and decoding 4K made it warm (Metin) */
const PHONE=Math.min(screen.width,screen.height)*(window.devicePixelRatio||1)<=1600;
function lightNow(){try{const o=localStorage.getItem('llight');if(o==='an')return true;if(o==='aus')return false;}catch(e){}
 const c=navigator.connection;return LIGHT||PHONE||!!(c&&(c.type==='cellular'||c.saveData));}
function stallSeen(){if(lightNow())return;const t=Date.now();STALLS=STALLS.filter(x=>t-x<60000);STALLS.push(t);if(STALLS.length>=2)LIGHT=true;}
let RATE={},KURVE={},SCHNITT={};
/* 2.144.0 (Metin sets where a clip begins and ends, in the tester): the stage starts a clip at its mark, hands over at its end mark and holds the last picture there; the file stays whole */
function cutStart(pth){const c=SCHNITT[pth];return c&&c[0]>0?c[0]:0;}
function endOf(v){const d=v.duration||0,c=SCHNITT[v.dataset.pth||''];return c&&c[1]>0&&c[1]<d?c[1]:d;}
function rateOf(pth){return RATE[pth]||1;}
/* a clip can have its own speed for a stretch inside it (2.139.0, Metin: the whole clip is
   not too fast, one second in the middle is). The browser takes a new speed mid play, so
   this costs no re-encoding and no quality. */
function rateAt(pth,t){const k=KURVE[pth];if(k)for(const s of k)if(t>=s[0]&&t<s[1])return s[2];
 return rateOf(pth);}
function rateFollow(v,pth){if(!KURVE[pth])return null;return()=>{const r=rateAt(pth,v.currentTime);
 if(Math.abs((v.playbackRate||1)-r)>0.001)v.playbackRate=r;};}
let SV=0,STOK=0,CONT=false,SWAP=0;const PRELOAD_S=3,PRELOAD_LIGHT_S=9;  /* 2.141.5: on the go a 7 Mbit copy needs about 7 s over an 11 Mbit line, so the next clip starts loading 9 s ahead, once the running one is fully loaded */
let TIGHT=false;  /* a loop that replays the same clip blends only at the very end (2.133.5): nacht/eifersuechtig does not come all the way back to its start pose, and the wide blend showed both poses at once */
function stageShow(name,loop,done,snd){snd=snd&&SND_RE.test(name);const tight=TIGHT;TIGHT=false;const PRE=tight?0.25:0.8,OFF=tight?300:850;const s=document.getElementById('stage'),vs=[document.getElementById('svid'),document.getElementById('svid2')],a=vs[SV],b=vs[1-SV],tok=++STOK,cont=CONT;CONT=false;
 if(!name){s.classList.remove('vid');vs.forEach(v=>{v.classList.remove('on');setTimeout(()=>{if(tok===STOK){v.pause();v.removeAttribute('src');v.load();}},600);});return;}
 if(loop&&a.loop&&a.classList.contains('on')&&a.src.split('?')[0].endsWith('/'+name+'.mp4'))return;
 b.onended=null;b.ontimeupdate=null;b.loop=!!loop;b.muted=!snd||document.getElementById('chat').classList.contains('oncall');b.volume=.7;let rdy=false;const ready=()=>{if(rdy)return;rdy=true;b.oncanplaythrough=null;if(tok!==STOK)return;
  if(cont&&a.classList.contains('on')&&a.duration&&!a.ended){const w=(endOf(a)-PRE-a.currentTime)*1000/(a.playbackRate||1);if(w>30){SWAP=tok;setTimeout(()=>{if(tok===STOK)go();},w);return;}}go();};
 /* 2.141.5 (Metin on the go: each clip stalled on its first pass and ran smoothly on the second): start a clip only when the browser expects to play it through, not at the first frame; after 8 s it starts anyway */
 b.oncanplaythrough=ready;b.oncanplay=null;
 /* 2.141.8: Chrome does not always say it is on mobile data (through Tailscale it did not), so a clip that cannot play through after 2.5 s switches to the light copy; it starts once it shows a frame */
 setTimeout(()=>{if(rdy||tok!==STOK)return;if(!lightNow()&&!b.src.includes('&m=1')){LIGHT=true;b.src+='&m=1';b.load();}
  setTimeout(()=>{if(rdy||tok!==STOK)return;if(b.readyState>=3)ready();else b.oncanplay=()=>{b.oncanplay=null;ready();};},6000);},2500);
 const go=()=>{const cs=cutStart(b.dataset.pth||'');if(Math.abs(b.currentTime-cs)>0.04)b.currentTime=cs;b.play().catch(()=>{b.muted=true;b.play().catch(()=>{});});b.style.zIndex=1;a.style.zIndex=0;b.classList.add('on');s.classList.add('vid');SV=1-SV;
  setTimeout(()=>{if(tok===STOK)a.classList.remove('on');},OFF);setTimeout(()=>{if(!a.classList.contains('on'))a.pause();},OFF+150);let fired=false;const fire=()=>{if(fired||tok!==STOK||!done)return;fired=true;CONT=true;done();CONT=false;};
  const fol=rateFollow(b,b.dataset.pth||'');
  const pre=lightNow()?PRELOAD_LIGHT_S:PRELOAD_S,full=()=>{const r=b.buffered;return r.length&&r.end(r.length-1)>=endOf(b)-0.2;};
  /* 2.143.2 (Metin: the ends of the clips flicker): the early preload on the phone began about 1 s into a 10 s clip and loaded the next clip into the old video while it was still fading out (it stays visible up to 1.65 s). The early preload now waits 2.5 s after the swap */
  const t0=performance.now();
  const src0=b.src;let hold=0;
  b.ontimeupdate=()=>{if(fol)fol();if(!b.duration)return;const e=endOf(b);
   if(e<b.duration-0.05&&!hold&&b.currentTime>e-0.6)hold=setTimeout(()=>{if(b.src===src0&&!b.paused){b.pause();fire();}},Math.max(0,(e-b.currentTime)*1000/(b.playbackRate||1)));  /* hold the last picture at the end mark */
   if(b.currentTime>e-PRELOAD_S||(b.currentTime>e-pre&&full()&&performance.now()-t0>2500))fire();};b.onended=fire;};
 {const pth=name.includes('/')?name:OUTFIT+'/'+name;b.dataset.pth=pth;const rt=rateAt(pth,0);b.src='/clips/'+pth+'.mp4?v='+(CVER[pth.split('/')[0]]||0)+(lightNow()?'&m=1':'');if(!b.dataset.st){b.dataset.st='1';b.addEventListener('waiting',()=>{if(b.classList.contains('on')&&b.currentTime>0.3)stallSeen();});}b.playbackRate=rt;b.onratechange=null;b.onloadedmetadata=()=>{b.playbackRate=rateAt(pth,0);const cs=cutStart(pth);if(cs)b.currentTime=cs;};}b.load();}
function stageLoop(b){if(ZPEND){const f=ZPEND;ZPEND=null;return f();}ZBUSY=0;DANCING=false;if(!b)return stageShow(null);const v=clipVars(b),nx=()=>stageNext(b);if(v.length<2){TIGHT=true;return stageShow(v[0],false,nx);}
 const cur=document.getElementById(SV?'svid2':'svid').src.split('?')[0].split('/').pop().replace('.mp4','');const o=v.filter(n=>n.split('/').pop()!==cur);
 /* 2.141.2 (Metin: shadow artifacts at the end of the loops): each variant closes well on itself (0.4 to 0.6) but
    starts in another pose than the others end (1.5 to 2.0), so the wide 0.85 s blend showed two Leylas at once */
 TIGHT=true;stageShow(o[Math.floor(Math.random()*o.length)],false,nx);}
const SPECIAL=[],SPECIAL_P=0;  // since 2.111.2 no dance by herself, only when Metin asks (Metin)
const KNIET_P=0.12,EXTRA_P=0.25;const SND_RE=/(^|[/])(kuss|rose|komm|liebe|freizeitmokka|(freizeit)?(gesicht|brust|bauch|po|mix|hinten))/;  /* 2.130.2 laugh on belly and chest, 2.131.0 cat surprise, 2.131.1 sound on every touch clip in every outfit, never on loops or dances (Metin; the older touch clips carry no audio track) */
function stageNext(b){if(ZPEND){const f=ZPEND;ZPEND=null;return f();}const sp=STM&&!STM.low?SPECIAL.filter(n=>clipVars(n).length):[];if(sp.length&&Math.random()<SPECIAL_P)stagePlay([sp[Math.floor(Math.random()*sp.length)]],b);
 else if(STM&&!STM.low&&clipVars('gluecklichextra').length&&Math.random()<EXTRA_P)stagePlay(['gluecklichextra'],b);
 else if(STM&&STM.low&&STM.level==='schwer'&&clipVars('setzen').length&&Math.random()<KNIET_P)stagePlay(['setzen'],b);else stageLoop(b);}
var SLAST={};function stagePlay(once,loop){DANCING=false;const q=once.map(n=>{let v=clipVars(n);if(v.length>1&&SLAST[n])v=v.filter(x=>x!==SLAST[n]);const c=v.length?v[Math.floor(Math.random()*v.length)]:null;if(c)SLAST[n]=c;return c;}).filter(Boolean);/* never the same variant twice in a row (2.116.4) */const next=()=>{const n=q.shift();if(n)stageShow(n,false,next,true);else stageLoop(loop);};next();}
function stageMood(st){if(CLIPS===null)return;document.getElementById('stage').classList.toggle('low',!!st.low);let once=[];const o=STM;
 if(!o)once=['begruessung'];if(o){if(o.low&&!st.low)once=['uebergang','kuss'];else if(st.low&&o.low&&(st.cheer||0)>(o.cheer||0))once=['trost'];}
 const changed=!o||once.length||o.mood!==st.mood||o.level!==st.level;/* an outfit change waits for its change scene or the next hand over (2.116.0) */STM=st;if(!o||o.outfit!==st.outfit){const im=document.querySelector('#stage .fig img'),nb=st.outfit==='nacht'&&NIGHTBODY?'/clips/nacht/body.jpg?v='+(CVER.nacht||0):LOOKBODY;if(nb&&!im.src.endsWith(nb))im.src=nb;}if(changed&&(!o||!(Date.now()<ZBUSY||ZPEND||DANCING)))stagePlay(once,clipFor(st));}
clipsLoad();
function stageHello(){if(CLIPS&&STM&&!DANCING)stagePlay(['begruessung'],clipFor(STM));}  // hallo on every open (2.113.1, Metin)
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&document.getElementById('chat').style.display==='block')stageHello();});
let MUSIC=[],BGMN='',MUSON=true,BGCTX=null,BGSRC=null,BGGAIN=null,BGLOAD='',BGEL=null;const BGBUF={},BGLONG={};try{MUSON=localStorage.getItem('lmusic')!=='0';}catch(e){}
function musDraw(){const b=document.getElementById('cmus');b.innerHTML=MUSON?'&#127925;':'&#128263;';b.classList.toggle('off',!MUSON);}
musDraw();document.getElementById('cmus').onclick=e=>{e.stopPropagation();MUSON=!MUSON;try{localStorage.setItem('lmusic',MUSON?'1':'0');}catch(e){}musDraw();bgmTick();};
async function bgmIsLong(n){if(n in BGLONG)return BGLONG[n];let L=false;try{const r=await fetch('/clips/musik/'+n+'.m4a?v='+(MUSV[n]||0),{headers:{Range:'bytes=0-0'}});const m=(r.headers.get('Content-Range')||'').match(/[/]([0-9]+)/);L=m?+m[1]>4e6:false;}catch(e){}BGLONG[n]=L;return L;}  /* a long track (over 4 MB) streams through an audio element; a short loop is decoded for a gapless loop (2.117.6) */
async function bgmBuf(n){if(BGBUF[n])return BGBUF[n];const b=await BGCTX.decodeAudioData(await (await fetch('/clips/musik/'+n+'.m4a?v='+(MUSV[n]||0))).arrayBuffer());
 const d=b.getChannelData(0);let a=0,e=d.length-1;while(a<e&&Math.abs(d[a])<1e-4)a++;while(e>a&&Math.abs(d[e])<1e-4)e--;b.ls=a/b.sampleRate;b.le=(e+1)/b.sampleRate;BGBUF[n]=b;return b;}
let VOICE=0;function voiceOn(on){VOICE=Math.max(0,VOICE+(on?1:-1));bgmTick();}  /* 2.142.1: her voice lowers the music at once and on its own, not through the talking clip (Metin could not understand her) */
function bgVol(){if(TALKING||VOICE)return .22*.02;const v=document.getElementById(SV?'svid2':'svid');return v&&!v.muted&&!v.paused?.22*.96:.22;}  /* 2.130.1: a clip with sound (her laugh) lowers the music from 100 to 96 % (Metin) */
function bgmTick(){const c=document.getElementById('chat');let n='';if(STM&&MUSIC.length){n=MUSIC.includes(STM.mood)?STM.mood:(STM.low?'traurig':'gut');if(!MUSIC.includes(n))n='';}  /* gapless loop through Web Audio, the audio element paused at its loop point (2.117.5, Metin) */
 const on=n&&MUSON&&soundOn&&CODE&&!REC&&!DIK&&!DIKQ&&!c.classList.contains('oncall')&&!document.hidden;  /* keeps playing in the menu and list pages, silent while he records or dictates (2.140.1, Metin) */
 if(!on){if(BGCTX&&BGCTX.state==='running')BGCTX.suspend().catch(()=>{});if(BGEL)BGEL.pause();return;}
 if(BGEL&&BGMN===n){BGEL.volume=bgVol();if(BGEL.paused)BGEL.play().catch(()=>{});return;}
 if(!BGCTX){try{BGCTX=new (window.AudioContext||window.webkitAudioContext)();BGGAIN=BGCTX.createGain();BGGAIN.connect(BGCTX.destination);}catch(e){return;}}
 if(BGCTX.state==='suspended')BGCTX.resume().catch(()=>{});
 BGGAIN.gain.setTargetAtTime(bgVol(),BGCTX.currentTime,.3);
 if(n!==BGMN&&BGLOAD!==n){BGLOAD=n;bgmIsLong(n).then(L=>{if(L){BGLOAD='';if(BGSRC){try{BGSRC.stop();}catch(e){}BGSRC=null;}if(BGEL)BGEL.pause();BGEL=new Audio('/clips/musik/'+n+'.m4a?v='+(MUSV[n]||0));BGEL.loop=true;BGEL.volume=bgVol();BGEL.play().catch(()=>{});BGMN=n;return;}
 bgmBuf(n).then(b=>{BGLOAD='';if(BGEL){BGEL.pause();BGEL=null;}if(BGSRC){try{BGSRC.stop();}catch(e){}}const s=BGCTX.createBufferSource();s.buffer=b;s.loop=true;s.loopStart=b.ls;s.loopEnd=b.le;s.connect(BGGAIN);s.start(0,b.ls);BGSRC=s;BGMN=n;}).catch(()=>{BGLOAD='';});});}}
fetch('/clips.json').then(r=>r.json()).then(o=>{MUSIC=o.music||[];MUSV=o.music_v||{};bgmTick();}).catch(()=>{});
setInterval(bgmTick,1000);document.addEventListener('pointerdown',bgmTick);document.addEventListener('visibilitychange',bgmTick);
function stageFit(){const ch=document.getElementById('chat');if(ch.style.display!=='block')return;const vh=(window.visualViewport?visualViewport.height:innerHeight);ch.style.height=Math.max(420,vh-12)+'px';}
function stageView(){stageFit();const ch=document.getElementById('chat');if(ch.style.display==='block')window.scrollTo({top:ch.getBoundingClientRect().top+scrollY-6,behavior:'smooth'});}
window.addEventListener('resize',stageFit);if(window.visualViewport)visualViewport.addEventListener('resize',stageView);
/* 2.150.6 (Metin: with the keyboard open he could not see what he typed): in the full screen stage the keyboard lies over the page instead of making it smaller, so the text field and the messages are lifted by the height the keyboard covers (--kb); the stage itself stays as it is */
/* 2.150.7: on Metin's phone the field still stood behind the keyboard by about its own height: in the installed full screen app the bar with the three system buttons comes back together with the keyboard and Chrome does not count it. KBPLUS lifts the field by that bar; the real numbers are reported once a minute to /api/diag (sizes only), so the lift can be made exact */
const KBPLUS=56;let KBREP=0;
function kbFit(){const vv=window.visualViewport;if(!vv)return;const kb=Math.round(window.innerHeight-vv.height-vv.offsetTop),open=kb>80;
 document.documentElement.style.setProperty('--kb',(open?kb+(runMode()==='browser'?0:KBPLUS):0)+'px');
 if(open&&Date.now()-KBREP>60000){KBREP=Date.now();try{const p=document.createElement('div');p.style.cssText='position:fixed;visibility:hidden;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)';document.body.appendChild(p);const cs=getComputedStyle(p);
  diag('kb '+[innerHeight,Math.round(vv.height),Math.round(vv.offsetTop),screen.height,document.getElementById('chat').offsetHeight,parseInt(cs.paddingTop)||0,parseInt(cs.paddingBottom)||0,devicePixelRatio].join(' '));p.remove();}catch(e){}}}
if(window.visualViewport){visualViewport.addEventListener('resize',kbFit);visualViewport.addEventListener('scroll',kbFit);}
document.getElementById('ctext').addEventListener('focus',()=>setTimeout(stageView,300));
document.getElementById('stage').addEventListener('contextmenu',e=>e.preventDefault());
const ZONES=[['gesicht',.02,.16,.37,.63],['brust',.16,.31,.30,.70],['bauch',.31,.42,.32,.68],['po',.42,.57,.29,.71]],ZLAST={},ZPRE={po:'hinten'},ZEXTRA={po:['povorne','mix'],bauch:['mix']};  // night po clips start from behind: she turns away first (2.114.2)
function zoneAt(ev){const st=document.getElementById('stage').getBoundingClientRect(),ar=1176/1764;let w=st.width,h=w/ar;if(h<st.height){h=st.height;w=h*ar;}
 const x=(ev.clientX-st.left-(st.width-w)/2)/w,y=(ev.clientY-st.top-(st.height-h)/2)/h;const z=ZONES.find(z=>y>=z[1]&&y<z[2]&&x>=z[3]&&x<=z[4]);return z?z[0]:null;}
var ZT=0,ZBUSY=0;  // one touch at a time: no other spot reacts until her clip is through (2.114.6, Metin)
var ZKISS=false,ZCOLNOW='';const ZCOL={gesicht:'#c084fc',brust:'#ef4444',bauch:'#fb923c',po:'#3b82f6'};/* dot colour per touched zone, only Metin knows the meaning (2.119.0) */const zDone=()=>{ZBUSY=0;ZCOLNOW='';if(ZKISS&&clipVars('kuss').length){ZKISS=false;return stagePlay(['kuss'],clipFor(STM));}ZKISS=false;stageLoop(clipFor(STM));};
var ZPEND=null,ZT_GREEN=()=>false,ZGOLD=0;
const ZNAME={gesicht:'Gesicht',brust:'Brust',bauch:'Bauch',po:'Po'};
async function zGame(z,miss){if(!miss)ZGOLD=Date.now()+1500;let j=null;try{j=await (await post('/api/game',{zone:z,miss:!!miss})).json();}catch(e){}if(!j||!j.ok)return;
 if(miss){if(j.mood)moodShow(j.mood);CHAT.push({role:'info',text:'❌ Daneben, deine Treffer sind weg.'});chatDraw();return;}  // touch game: hit while the timer is green (2.115.0, Metin)
 if(j.bonus){if(Date.now()<ZBUSY)ZKISS=true;else if(!ZPEND)ZPEND=()=>stagePlay(['kuss'],clipFor(STM));}  // won: a kiss, a random variant, at the next clean hand over (2.115.2)
 if(j.mood)moodShow(j.mood);const n=(j.hits||[]).length;CHAT.push({role:'info',text:j.bonus?'🌹 Alle vier Stellen getroffen! Der Rosenknopf ist noch einmal frei.':'🎯 Treffer: '+ZNAME[z]+' ('+n+' von 4)'});chatDraw();}
(function(){const c=document.getElementById('chat'),d=document.createElement('div');d.id='ztimer';  // clip timer: red ring = how far the running clip is, green = a touch starts now (2.114.8, Metin)
 d.innerHTML='<svg viewBox="0 0 30 30"><circle class="bg" cx="15" cy="15" r="12"/><circle class="fg" cx="15" cy="15" r="12" stroke-dasharray="75.4" stroke-dashoffset="75.4"/><circle class="dot" cx="15" cy="15" r="4"/></svg>';c.appendChild(d);
 const fg=d.querySelector('.fg'),dot=d.querySelector('.dot');let last='',flash=0;ZT_GREEN=()=>Date.now()<flash;
 const nm=document.createElement('div');nm.id='zname';c.appendChild(nm);  /* 2.134.1 (Metin): a tap on the clip timer shows the name of the running clip, so he can say which one to replace */
 let show=false;try{show=localStorage.getItem('lzname')==='1';}catch(e){}
 nm.style.display=show?'block':'none';
 nm.onclick=()=>{if(nm.textContent)location.href='/tempo?clip='+encodeURIComponent(nm.textContent);};  /* 2.144.0: a tap on the name opens this clip in the tester (tempo, begin and end) */
 d.onclick=()=>{show=!show;nm.style.display=show?'block':'none';try{localStorage.setItem('lzname',show?'1':'0');}catch(e){}};
 setInterval(()=>{if(c.style.display!=='block')return;const v=document.getElementById(SV?'svid2':'svid'),on=document.getElementById('stage').classList.contains('vid')&&v.classList.contains('on');
  const src=on?v.getAttribute('src')||'':'';if(src!==last){if(last)flash=Date.now()+1000;last=src;}
  if(show)nm.textContent=src?decodeURIComponent(src.split('?')[0].split('/clips/')[1]||'').replace('.mp4',''):'';
  const free=!on||Date.now()<flash;let p=1;if(!free&&v.duration)p=Math.min(1,v.currentTime/Math.max(.1,endOf(v)-.8));
  d.classList.toggle('go',free);d.classList.toggle('hit',!!ZPEND||Date.now()<ZBUSY);d.classList.toggle('gold',Date.now()<ZGOLD);dot.style.fill=Date.now()<ZGOLD?'':ZCOLNOW;fg.setAttribute('stroke-dashoffset',(75.4*(1-(free?1:p))).toFixed(1));},100);})();  // the touch is noted at once and plays when the running clip hands over, so the poses match (2.114.7, Metin)
let TOUCHT=0;function touchAsk(z){if(!CODE||Date.now()-TOUCHT<TOUCH_GAP)return null;TOUCHT=Date.now();return post('/api/chat_touch',{zone:z,history:CHAT.filter(m=>m.role==='user'||m.role==='leyla').slice(-20).map(m=>({role:m.role,text:m.text}))}).then(r=>r.json()).catch(()=>null);}
const TOUCH_GAP=25000;/* she answers a touch at most every 25 s, so touches do not push the real chat out of her thread */
function touchShow(j){if(!j||j.error||!j.reply)return;const m={role:'leyla',text:j.reply};if(j.audio){m.aid='a'+Date.now();AUDIO.set(m.aid,'data:audio/wav;base64,'+j.audio);}CHAT.push(m);if(j.mood)moodShow(j.mood);chatSave();chatDraw();if(m.aid)playAudio(m.aid);}  /* her written reaction to a touch appears when the touch clip starts (2.119.0, Metin) */
function zRing(ev){const st=document.getElementById('stage'),r=st.getBoundingClientRect(),d=document.createElement('div');d.className='zring';d.style.left=(ev.clientX-r.left)+'px';d.style.top=(ev.clientY-r.top)+'px';st.appendChild(d);setTimeout(()=>d.remove(),900);}
document.getElementById('stage').onpointerdown=ev=>{if(ev.button>0||Date.now()-ZT<700||ZPEND||Date.now()<ZBUSY)return;ZT=Date.now();if(!CLIPS||!STM||(STM.low&&!STM.touch_ok))return;const z=zoneAt(ev);if(!z)return;const v=clipVars(z).concat(...(ZEXTRA[z]||[]).map(clipVars));if(!v.length)return;ZBUSY=Date.now()+60000;zRing(ev);ZCOLNOW=ZCOL[z]||'';const tr=touchAsk(z);
 {const g=(STM&&STM.game)||{};if(!g.done){if(ZT_GREEN()){if(!(g.hits||[]).includes(z))zGame(z);}else if((g.hits||[]).length)zGame(z,true);}}
 const o=v.length>1?v.filter(n=>n!==ZLAST[z]):v,n=o[Math.floor(Math.random()*o.length)];ZLAST[z]=n;
 const pre=ZPRE[z]&&!/povorne|mix/.test(n)&&clipVars(ZPRE[z]),h=pre&&pre.length?pre[Math.floor(Math.random()*pre.length)]:'';  /* povorne clips start facing him, no turn first (2.117.3) */
 const go=()=>{DANCING=false;ZBUSY=Date.now()+40000;if(tr)tr.then(touchShow);document.querySelectorAll('#stage video:not(.pet)').forEach(x=>{x.style.transition='opacity .35s';setTimeout(()=>{x.style.transition='';},1500);});if(h)return stageShow(h,false,()=>stageShow(n,false,zDone,true),true);stageShow(n,false,zDone,true);};
 ZPEND=null;SWAP=0;go();};  /* 2.130.3: the reaction starts at the touch (crossfade), no more waiting for the clip end (Metin: must be in sync) */

document.getElementById('crose').onclick=async()=>{const st=LASTST||{};
 if(st.rose==='used'){CHAT.push({role:'info',text:'🌹 Diese Woche hast du ihr schon eine Rose geschenkt.'});chatDraw();return;}
 if(st.rose==='blocked'){CHAT.push({role:'info',text:'🌹 Sie nimmt gerade keine Rose an.'});chatDraw();return;}
 let j=null;try{j=await (await post('/api/rose',{})).json();}catch(e){}
 if(!j||!j.ok){if(j&&j.mood)moodShow(j.mood);CHAT.push({role:'info',text:j&&j.rose==='blocked'?'🌹 Sie nimmt gerade keine Rose an.':'🌹 Gerade nicht möglich.'});chatDraw();return;}
 moodShow(j.mood);const sc=clipVars(j.scene).length?j.scene:(j.scene==='rosefroh'?'kuss':'');if(sc)stageScene(sc);
 const ta=document.getElementById('ctext');ta.value='🌹 Ich schenke dir eine Rose.';chatSend();};
async function moodLoad(){try{moodShow(await (await post('/api/mood',{})).json());}catch(e){}}
setInterval(()=>{if(CODE&&document.getElementById('chat').style.display==='block'){moodLoad();remindPending();reachPending();}},60000);
function chatAnswer(j){if(j&&j.silent){CHAT.push({role:'info',text:'🤐 Leyla antwortet gerade nicht.'});if(j.mood)moodShow(j.mood);return null;}
 if(!j||j.error||!j.reply){CHAT.push({role:'leyla',text:'Hmm, gerade komme ich nicht durch. Versuch es gleich nochmal.'});return null;}
 const m={role:'leyla',text:j.reply};if(j.audio||j.voice_id){m.aid='a'+Date.now();if(j.audio)AUDIO.set(m.aid,'data:audio/wav;base64,'+j.audio);else VSTREAM.add(m.aid);}CHAT.push(m);
 (j.lights||[]).forEach(t=>CHAT.push({role:'info',text:(/^(✉|📣|🧹)/.test(t)?'':'💡 ')+t}));if(j.scene)stageScene(j.scene);if(j.mood)moodShow(j.mood);if(j.email)CHAT.push({role:'mail',e:j.email});if(j.trash)CHAT.push({role:'trash',t:j.trash});(j.noted||[]).forEach(p=>CHAT.push({role:'noted',p}));(j.proposals||[]).forEach(p=>CHAT.push({role:'prop',p}));return m.aid||null;}
function blobB64(b){return new Promise(r=>{const f=new FileReader();f.onload=()=>r(String(f.result).split(',')[1]||'');f.readAsDataURL(b);});}
let VRTT=null;  /* 2.141.7: round trip of the last voice message */
async function voiceSend(blob,mime){const history=CHAT.filter(m=>m.role==='user'||m.role==='leyla').map(m=>({role:m.role,text:m.text}));
 const u={role:'user',text:'🎤 ...'};CHAT.push(u);chatSave();chatDraw(true);snd.on();
 let j=null;const t0=performance.now();try{j=await (await post('/api/chat_voice',{history,audio:await blobB64(blob),mime,rtt:VRTT,light:lightNow(),stream:true})).json();}catch(e){}VRTT=Math.round(performance.now()-t0);
 if(j&&j.heard){u.text='🎤 '+j.heard;}else{u.text='🎤 (nicht verstanden)';}
 const aid=(j&&j.heard)?chatAnswer(j):null;chatSave();chatDraw();snd.drop();if(aid&&j.voice_id)playStream(j.voice_id,aid);else if(aid)playAudio(aid);}
/* 2.142.0 (Metin on the go: a voice reply took 20 to 30 s, of which 15 to 24 s the server waited for the whole voice):
   the text comes at once and her voice plays while it is still being spoken, 24 kHz PCM from /api/voice/<id> through
   Web Audio; at the end the whole reply is kept as a WAV for the play button and the download */
let VCTX=null;
function wavUrl(parts,n){const h=new DataView(new ArrayBuffer(44)),w=(o,t)=>{for(let i=0;i<4;i++)h.setUint8(o+i,t.charCodeAt(i));};
 w(0,'RIFF');h.setUint32(4,36+n,true);w(8,'WAVE');w(12,'fmt ');h.setUint32(16,16,true);h.setUint16(20,1,true);h.setUint16(22,1,true);
 h.setUint32(24,24000,true);h.setUint32(28,48000,true);h.setUint16(32,2,true);h.setUint16(34,16,true);w(36,'data');h.setUint32(40,n,true);
 return URL.createObjectURL(new Blob([h.buffer,...parts],{type:'audio/wav'}));}
async function playStream(id,aid){let r;try{VCTX=VCTX||new (window.AudioContext||window.webkitAudioContext)();await VCTX.resume();r=await fetch('/api/voice/'+id);}catch(e){VSTREAM.delete(aid);chatDraw();return;}
 if(!r.ok||!r.body){VSTREAM.delete(aid);chatDraw();return;}const rd=r.body.getReader(),parts=[];let rest=null,t=0,on=false,n=0;
 try{for(;;){const x=await rd.read();if(x.done)break;let u=x.value;if(rest){const m=new Uint8Array(rest.length+u.length);m.set(rest);m.set(u,rest.length);u=m;rest=null;}
  const k=u.length-(u.length%2);if(k<u.length)rest=u.slice(k);if(!k)continue;const p=u.slice(0,k);parts.push(p);n+=k;
  const s16=new Int16Array(p.buffer,0,k/2),f=new Float32Array(k/2);for(let i=0;i<f.length;i++)f[i]=s16[i]/32768;
  const b=VCTX.createBuffer(1,f.length,24000);b.copyToChannel(f,0);const src=VCTX.createBufferSource();src.buffer=b;src.connect(voiceOut());
  const now=VCTX.currentTime;if(!on){on=true;stageTalk(true);voiceOn(true);t=now+0.4;}else if(t<now+0.05)t=now+0.3;  /* a gap in the line: wait a little instead of stuttering */
  src.start(t);t+=b.duration;}}catch(e){}
 if(on)setTimeout(()=>{stageTalk(false);voiceOn(false);},Math.max(0,(t-VCTX.currentTime)*1000));
 if(n)AUDIO.set(aid,wavUrl(parts,n));VSTREAM.delete(aid);chatDraw();}
document.querySelector('#chat .chead').appendChild(document.getElementById('cmic'));  // mic as a pill top right above Live (2.114.9, Metin)
document.getElementById('cmic').onclick=async()=>{const b=document.getElementById('cmic');
 if(REC){REC.stop();return;}
 if(!navigator.mediaDevices||!window.MediaRecorder){CHAT.push({role:'info',text:'Das Mikrofon ist auf dieser Seite nicht frei (Chrome Einstellung fehlt).'});chatSave();chatDraw();return;}
 let st;try{st=await navigator.mediaDevices.getUserMedia({audio:true});}catch(e){CHAT.push({role:'info',text:'Kein Zugriff aufs Mikrofon.'});chatSave();chatDraw();return;}
 const parts=[];REC=new MediaRecorder(st);REC.ondataavailable=e=>{if(e.data.size)parts.push(e.data);};
 REC.onstop=()=>{st.getTracks().forEach(t=>t.stop());clearTimeout(RECT);const mime=REC.mimeType||'audio/webm';REC=null;bgmTick();b.classList.remove('rec');b.innerHTML='&#127908;';
  const blob=new Blob(parts,{type:mime});if(blob.size>2000)voiceSend(blob,mime);};
 REC.start();bgmTick();b.classList.add('rec');b.innerHTML='&#9632;';snd.on();RECT=setTimeout(()=>{if(REC)REC.stop();},60000);};
/* Dictation instead of the keyboard (2.140.0, Metin: "wenn ich unten auf chat zum
   schreiben druecke die Tastatur nicht mehr erscheint aber dafuer mikro was Sprache zu
   text umwandelt was ich dann nur noch senden muss"). The field is readonly, so Android
   keeps the keyboard shut; a tap records, a second tap stops, the text lands in the field
   and he presses Senden. The abc pill gives him the keyboard back when he wants it. */
(function(){const ta=document.getElementById('ctext'),kb=document.getElementById('ckb');
 const say=t=>{ta.placeholder=t;};
 async function stopDik(){if(!DIK)return;const r=DIK;DIK=null;try{r.stop();}catch(e){}}
 async function startDik(){
  if(!navigator.mediaDevices||!window.MediaRecorder){say('Mikrofon ist hier nicht frei');return;}
  let st;try{st=await navigator.mediaDevices.getUserMedia({audio:true});}catch(e){say('Kein Zugriff aufs Mikrofon');return;}
  const parts=[];DIK=new MediaRecorder(st);DIK.ondataavailable=e=>{if(e.data.size)parts.push(e.data);};
  DIK.onstop=async()=>{st.getTracks().forEach(t=>t.stop());clearTimeout(DIKT);const mime=DIK?DIK.mimeType:'audio/webm';DIK=null;
   ta.classList.remove('hoert');say('Tippen und sprechen ...');bgmTick();
   const blob=new Blob(parts,{type:mime||'audio/webm'});if(blob.size<2000)return;
   say('schreibe mit ...');
   let j=null;try{j=await (await post('/api/hoeren',{audio:await blobB64(blob),mime:mime||'audio/webm'})).json();}catch(e){}
   say('Tippen und sprechen ...');
   if(j&&j.heard){const old=ta.value.trim();ta.value=(old?old+' ':'')+j.heard;ta.scrollTop=ta.scrollHeight;}
   else say('nicht verstanden, nochmal tippen');};
  DIKQ=true;DIK.start();bgmTick();ta.classList.add('hoert');say('hoert zu, zum Beenden nochmal tippen');
  DIKT=setTimeout(()=>{if(DIK)stopDik();},60000);}
 ta.addEventListener('click',e=>{if(!ta.readOnly)return;e.preventDefault();if(DIK)stopDik();else startDik();});
 kb.onclick=()=>{if(DIK)stopDik();DIKQ=false;bgmTick();ta.readOnly=!ta.readOnly;
  if(ta.readOnly){ta.setAttribute('inputmode','none');kb.classList.remove('on');ta.placeholder='Tippen und sprechen ...';ta.blur();}
  else{ta.removeAttribute('inputmode');kb.classList.add('on');ta.placeholder='Schreib Leyla ...';ta.focus();}};
})();
function mailCard(m,i){const c=document.createElement('div');c.className='mc';const e=m.e;
 const h=document.createElement('b');h.textContent='✉ E-Mail an '+e.to;c.appendChild(h);
 const a=document.createElement('div');a.className='meta';a.textContent=e.addr+'  ·  Betreff: '+e.subject;c.appendChild(a);
 if(e.web){const w=document.createElement('div');w.className='web';w.textContent='⚠ Adresse aus dem Web gefunden, bitte prüfen';c.appendChild(w);}
 const t=document.createElement('pre');t.textContent=e.body;c.appendChild(t);
 if(m.done){const s=document.createElement('div');s.className='meta';s.textContent=m.done;c.appendChild(s);return c;}
 const row=document.createElement('div');row.className='row';const y=document.createElement('button');y.textContent='Senden';const n=document.createElement('button');n.textContent='Nein';n.className='no';
 y.onclick=async()=>{y.disabled=n.disabled=true;let r={ok:false};try{r=await (await post('/api/mail/send',{id:e.id})).json();}catch(_){}
  CHAT[i].done=r.ok?'Gesendet':(r.error||'Senden ging nicht');if(r.ok)snd.save();chatSave();chatDraw();};
 n.onclick=async()=>{try{await post('/api/mail/discard',{id:e.id});}catch(_){}CHAT[i].done='Nicht gesendet';snd.off();chatSave();chatDraw();};
 row.append(y,n);c.appendChild(row);return c;}
const GM={shown:false,list:[],needs:false};
async function gpost(p,b){try{return await (await post('/api/google/'+p,b||{})).json();}catch(e){return {};}}
function gmailDraw(st){const box=document.getElementById('gmail');box.innerHTML='';
 const h=document.createElement('h3');box.appendChild(h);
 if(!st.connected||(st.missing&&st.missing.length)){h.textContent='GOOGLE KONTAKTE';
  const p=document.createElement('div');p.className='hint';p.textContent=(st.connected?'Für neue Funktionen (Kalender, Mails lesen) bitte einmal neu verbinden, dabei alle Häkchen setzen. ':'')+'1. Auf "Mit Google anmelden" tippen und anmelden. 2. Die Seite danach lädt nicht, das ist richtig: ihre ganze Adresse oben kopieren, hier einfügen und auf "Verbinden" tippen.';box.appendChild(p);
  const i=document.createElement('input');i.type='text';i.placeholder='http://127.0.0.1/?code=...';i.autocomplete='off';box.appendChild(i);
  const row=document.createElement('div');row.className='gb';const a=document.createElement('button');a.textContent='Mit Google anmelden';
  a.onclick=async()=>{const w=window.open('about:blank','_blank');const j=await gpost('auth');if(j.url&&w)w.location.href=j.url;else if(j.url)location.href=j.url;else if(w)w.close();};
  const c=document.createElement('button');c.textContent='Verbinden';c.onclick=async()=>{c.disabled=true;const j=await gpost('connect',{url:i.value});c.disabled=false;
   if(j.ok){snd.save();gmailLoad();}else{p.textContent=j.error||'Hat nicht geklappt.';}};row.append(a,c);box.appendChild(row);return;}
 h.textContent='E-MAIL';const p=document.createElement('div');p.className='hint';p.textContent='Mit Google verbunden.';box.appendChild(p);}
async function gmailLoad(force){const st=await gpost('status');const box=document.getElementById('gmail');
 if(!st.configured){GM.shown=false;box.style.display='none';return;}
 GM.needs=!st.connected||!!(st.missing&&st.missing.length);
 if(st.connected){const j=await gpost('contacts',{force:!!force});GM.list=j.contacts||[];}
 GM.shown=true;box.style.display=(sec==='mail'&&!view)?'block':'none';gmailDraw(st);}
function trashCard(m,i){const c=document.createElement('div');c.className='mc tr';const t=m.t;
 const h=document.createElement('b');h.textContent='🗑 '+t.items.length+(t.items.length===1?' Mail':' Mails')+' in den Papierkorb?';c.appendChild(h);
 const ul=document.createElement('ul');t.items.forEach(x=>{const li=document.createElement('li');li.textContent=x.betreff+'  ·  '+x.von;ul.appendChild(li);});c.appendChild(ul);
 if(m.done){const s=document.createElement('div');s.className='meta';s.textContent=m.done;c.appendChild(s);return c;}
 const row=document.createElement('div');row.className='row';const y=document.createElement('button');y.textContent='In den Papierkorb';const n=document.createElement('button');n.textContent='Nein';n.className='no';
 y.onclick=async()=>{y.disabled=n.disabled=true;let r={ok:false};try{r=await (await post('/api/mail/trash',{id:t.id})).json();}catch(_){}
  CHAT[i].done=r.ok?(r.anzahl+' im Papierkorb (30 Tage wiederherstellbar)'):(r.error||'Ging nicht');if(r.ok)snd.del();chatSave();chatDraw();};
 n.onclick=async()=>{try{await post('/api/mail/trash_discard',{id:t.id});}catch(_){}CHAT[i].done='Bleibt im Posteingang';snd.off();chatSave();chatDraw();};
 row.append(y,n);c.appendChild(row);return c;}
function remindCard(m,i){const c=document.createElement('div');c.className='mc rm';
 const h=document.createElement('b');h.textContent='⏰ Erinnerung';c.appendChild(h);
 const p=document.createElement('div');p.className='meta';p.textContent=m.r.text;c.appendChild(p);
 if(m.done){const s=document.createElement('div');s.className='meta';s.textContent=m.done;c.appendChild(s);return c;}
 const row=document.createElement('div');row.className='row';const y=document.createElement('button');y.textContent='OK, nicht mehr erinnern';
 y.onclick=async()=>{y.disabled=true;let r={ok:false};try{r=await (await post('/api/remind/ok',{id:m.r.id})).json();}catch(_){}
  CHAT[i].done=r.ok?'Erinnerung beendet':'Ging nicht';chatSave();chatDraw();};
 row.append(y);c.appendChild(row);return c;}
async function remindPending(){let j=null;try{j=await (await post('/api/remind/pending',{})).json();}catch(_){}
 if(!j||!j.ok)return;let added=false;(j.items||[]).forEach(r=>{if(!CHAT.some(m=>m.role==='remind'&&m.r.id===r.id)){CHAT.push({role:'remind',r});added=true;}});
 if(added){chatSave();chatDraw();}}
async function reachPending(){let j=null;try{j=await (await post('/api/reach/pending',{})).json();}catch(_){}
 if(!j||!j.ok||!(j.items||[]).length)return;const ids=[];
 j.items.forEach(r=>{if(!CHAT.some(m=>m.rid===r.id))CHAT.push({role:r.role==='user'?'user':'leyla',text:r.text,rid:r.id,voice:!!r.voice});ids.push(r.id);});
 chatSave();chatDraw();try{await post('/api/reach/seen',{ids});}catch(_){}}
async function reachPlay(id){let j=null;try{j=await (await post('/api/reach/audio',{id})).json();}catch(_){}
 if(!j||!j.ok)return;if(!AUDIO.has('r'+id)){const bin=atob(j.audio),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);AUDIO.set('r'+id,URL.createObjectURL(new Blob([u],{type:'audio/wav'})));}playAudio('r'+id);}
async function mailPending(){remindPending();reachPending();let j=null;try{j=await (await post('/api/mail/pending',{})).json();}catch(_){}
 if(!j||!j.ok)return;let added=false;(j.drafts||[]).forEach(e=>{if(!CHAT.some(m=>m.role==='mail'&&m.e.id===e.id)){CHAT.push({role:'mail',e});added=true;}});
 (j.trash||[]).forEach(t=>{if(!CHAT.some(m=>m.role==='trash'&&m.t.id===t.id)){CHAT.push({role:'trash',t});added=true;}});
 if(added){chatSave();chatDraw();}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&CODE)mailPending();});
let LIVE=null;
function liveStat(t,sp){document.getElementById('lpill').textContent=t;document.getElementById('chat').classList.toggle('speak',!!sp);stageTalk(sp);}
function liveStop(){const L=LIVE;LIVE=null;const c=document.getElementById('chat');c.classList.remove('oncall','speak');stageTalk(false);if(!L)return;
 try{L.ws.close();}catch(e){}try{L.proc.disconnect();L.src.disconnect();}catch(e){}try{L.st.getTracks().forEach(t=>t.stop());}catch(e){}try{L.ctx.close();}catch(e){}}
async function liveStart(){if(LIVE)return;const box=document.getElementById('live');
 if(!navigator.mediaDevices){CHAT.push({role:'info',text:'Das Mikrofon ist auf dieser Seite nicht frei (Chrome Einstellung fehlt).'});chatSave();chatDraw();return;}
 let st;try{st=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});}catch(e){CHAT.push({role:'info',text:'Kein Zugriff aufs Mikrofon.'});chatSave();chatDraw();return;}
 document.getElementById('chat').classList.add('oncall');stageView();liveStat('Verbinde ...');
 const ctx=new (window.AudioContext||window.webkitAudioContext)();const ratio=ctx.sampleRate/24000;
 const ws=new WebSocket((location.protocol==='https:'?'wss://'+location.hostname+':8443':'ws://'+location.hostname+':8080')+'/app');  /* 2.145.0: over HTTPS live talk needs wss, served on 8443 */ws.binaryType='arraybuffer';
 const L={ws,ctx,st,ready:false,playT:0,srcs:[],last:0};LIVE=L;
 const src=ctx.createMediaStreamSource(st),proc=ctx.createScriptProcessor(2048,1,1);L.src=src;L.proc=proc;
 proc.onaudioprocess=e=>{if(!L.ready||ws.readyState!==1)return;const inp=e.inputBuffer.getChannelData(0);const n=Math.floor(inp.length/ratio);const out=new Int16Array(n);
  for(let i=0;i<n;i++){const a=Math.floor(i*ratio),b=Math.min(inp.length,Math.floor((i+1)*ratio));let sum=0;for(let k=a;k<b;k++)sum+=inp[k];const v=Math.max(-1,Math.min(1,sum/Math.max(1,b-a)));out[i]=v<0?v*32768:v*32767;}
  ws.send(out.buffer);};
 src.connect(proc);proc.connect(ctx.destination);
 ws.onopen=()=>ws.send(JSON.stringify({type:'hello',code:CODE}));
 ws.onmessage=e=>{if(typeof e.data==='string'){let m={};try{m=JSON.parse(e.data);}catch(_){}
   if(m.type==='ready'){L.ready=true;liveStat('Leyla hört zu');}
   else if(m.type==='phase'){liveStat(m.phase==='replying'?'Leyla spricht':m.phase==='searching'?'Leyla sucht ...':'Leyla denkt ...',m.phase==='replying');}
   else if(m.type==='interrupt'){L.srcs.forEach(s=>{try{s.stop();}catch(_){}});L.srcs=[];L.playT=ctx.currentTime;liveStat('Leyla hört zu');}
   else if(m.type==='disconnect'||m.type==='error'){liveStop();}
   return;}
  const pcm=new Int16Array(e.data);if(!pcm.length)return;const buf=ctx.createBuffer(1,pcm.length,24000);const ch=buf.getChannelData(0);
  for(let i=0;i<pcm.length;i++)ch[i]=pcm[i]/32768;const s=ctx.createBufferSource();s.buffer=buf;s.connect(ctx.destination);
  const at=Math.max(L.playT,ctx.currentTime+0.05);s.start(at);L.playT=at+buf.duration;L.srcs.push(s);s.onended=()=>{L.srcs=L.srcs.filter(x=>x!==s);if(!L.srcs.length&&L.ready)liveStat('Leyla hört zu');};
  liveStat('Leyla spricht',true);};
 ws.onclose=()=>{if(LIVE===L)liveStop();};ws.onerror=()=>{if(LIVE===L){liveStop();CHAT.push({role:'info',text:'Live Verbindung ging nicht.'});chatSave();chatDraw();}};}
document.getElementById('clive').onclick=()=>{if(document.getElementById('chat').classList.contains('oncall'))liveStop();else liveStart();};document.getElementById('lend').onclick=liveStop;
document.getElementById('csend').onclick=chatSend;
{const ch=document.querySelector('#chat .chead');ch.appendChild(document.getElementById('csend'));ch.appendChild(document.getElementById('cnew'));}  /* Senden and Neuer Chat in the right column, the field alone and narrow at the bottom, so Mokka stays visible (2.133.3, Metin) */
document.getElementById('cnew').onclick=chatNew;
let FRESH=new Set(),TICK='';
function ticker(list){const t=(list||[]).join('   \u2726   ');if(t===TICK)return;TICK=t;const box=document.getElementById('tick'),sp=box.firstChild;
 box.style.display=t?'block':'none';sp.textContent=t;sp.style.animationDuration=Math.max(10,t.length*0.16)+'s';}
function render(d){FRESH=new Set(d.fresh||[]);ticker(d.ticker);const root=document.getElementById('root');root.innerHTML='';const all=new Set();
 const back=document.getElementById('back'),h1=document.querySelector('h1');
 let found=null;
 if(view){const l=d.lists.find(x=>x.kind===view.kind);const t=l&&l.items.find(x=>parts(x).head===view.head);if(t){found={l,t};}else view=null;}
 LASTD=d;const kinds=d.lists.map(l=>l.kind);if(sec&&!SECNAME[sec])sec=null;if(sec==='private'&&!kinds.includes('private'))sec=null;if((sec==='mail'||sec==='private')&&!CODE)sec=null;
 const home=!view&&!sec,isList=!!view||kinds.includes(sec);
 back.style.display=home?'none':'block';document.getElementById('micon').style.display=home?'':'none';document.getElementById('pulse').style.display=home?'block':'none';const ch=document.getElementById('chat'),showChat=!!CODE&&home;document.body.classList.toggle('chatfull',showChat);if(showChat&&ch.style.display!=='block'){ch.style.display='block';chatDraw();mailPending();gmailLoad();moodLoad();stageHello();}else if(!showChat)ch.style.display='none';document.getElementById('stage').style.display=showChat?'block':'none';if(showChat){setTimeout(stageFit,0);setTimeout(stageView,2600);}document.getElementById('gmail').style.display=(sec==='mail'&&GM.shown&&!view)?'block':'none';document.getElementById('lamps').style.display=(sec==='lamps'&&lampOn&&!view)?'block':'none';document.getElementById('bar').style.display=isList?'':'none';h1.textContent=view?title(view.head):sec?SECNAME[sec]:'Leyla Gedächtnis';if(menuOpen)drawMenu();
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
 if(home&&!CODE)root.appendChild(privBox());
 if(sec==='set')root.appendChild(privBox());
 for(const l of d.lists.filter(x=>x.kind===sec)){const box=document.createElement('div');box.className='list';box.dataset.kind=l.kind;
  const h=document.createElement('h2');h.textContent=l.title+' ('+l.items.length+')';box.appendChild(h);
  const e=document.createElement('div');e.className='empty';e.textContent='leer';box.appendChild(e);
  for(const t of l.items){all.add(key(l.kind,t));box.appendChild(makeRow(l.kind,t));}
  root.appendChild(box);
  const add=document.createElement('button');add.className='add';add.textContent='+ Neuer Eintrag';
  add.onclick=()=>{if(editing)return;const bx=document.createElement('div');bx.className='addbox';const sp=document.createElement('span');bx.appendChild(sp);
   root.insertBefore(bx,add);add.style.display='none';
   startEdit(sp,l.kind,'',async v=>{const r=await post('/api/add',{kind:l.kind,text:v});return (await r.json()).ok;});};
  root.appendChild(add);}}
 sel=new Set([...sel].filter(x=>all.has(x)));upd();}
function privBox(){const b=document.createElement('div');b.className='lb';
 if(CODE){const r=document.createElement('button');r.textContent='So ist Leyla';r.onclick=openRules;
  const x=document.createElement('button');x.textContent='Private Liste schließen';x.onclick=()=>{CODE=null;try{localStorage.removeItem('lcode')}catch(e){}last='';snd.off();load();};b.append(r,x,sndBtn());return b;}
 const i=document.createElement('input');i.type='password';i.placeholder='Codewort';i.autocomplete='off';
 i.style.cssText='flex:2;font:inherit;color:#fff;background:#060c33;border:1px solid var(--bl);border-radius:10px;padding:10px;min-width:0';
 const o=document.createElement('button');o.textContent='Privat öffnen';
 const go=async()=>{if(!i.value.trim())return;o.disabled=true;let ok=false;
  try{ok=(await (await fetch('/api/unlock',{method:'POST',body:JSON.stringify({code:i.value})})).json()).ok;}catch(e){}
  o.disabled=false;if(ok){CODE=i.value;try{localStorage.setItem('lcode',CODE)}catch(e){}snd.save();last='';load();}else{i.value='';i.placeholder='Falsch, nochmal';snd.del();}};
 o.onclick=go;i.onkeydown=e=>{if(e.key==='Enter')go();};
 i.onfocus=()=>{editing=true;};i.onblur=()=>{setTimeout(()=>{editing=false;},300);};
 b.append(i,o,sndBtn());return b;}
let rulesOpen=false;
async function openRules(){let t='';try{const j=await (await post('/api/rules',{})).json();t=j.text||'';}catch(e){}
 if(!t)return;document.querySelector('#rules .top h1').textContent='So ist Leyla';const box=document.getElementById('rtext');box.innerHTML='';
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
async function openDiary(){let j=null;try{j=await (await post('/api/diary',{})).json();}catch(e){}
 if(!j||!j.ok)return;document.querySelector('#rules .top h1').textContent='Tagebuch';const box=document.getElementById('rtext');box.innerHTML='';
 const lead=document.createElement('p');lead.className='lead';lead.textContent='Was Leyla im Chat und zu Hause erlebt hat, die letzten 30 Tage. Sie selbst erinnert sich an Älteres nur noch ungefähr. Mit 🔑 hältst du einen Eintrag für immer fest ('+j.items.filter(x=>x.fest).length+' von 20).';box.appendChild(lead);
 /* 2.150.0: what she thought over at night (app/nachdenken.py), each part with a cross to strike it; a struck day is thought over again from the entries that are left */
 if(j.think){const T=j.think;const sec=(title,text,what)=>{if(!text)return;const p=document.createElement('p');p.className='dy th';const m=document.createElement('span');m.className='dm';m.textContent=title;const x=document.createElement('button');x.className='dyk';x.textContent='✕';x.title='Streichen';x.onclick=async()=>{let r={ok:false};try{r=await (await post('/api/kopf/nachdenken',{forget:what})).json();}catch(_){}if(r.ok){snd.del();openDiary();}};p.append(x,m,document.createTextNode(text));box.appendChild(p);};
  sec('🌙 Unsere Geschichte  ·  🔒',T.story.privat,'story');sec('🌙 Ihre Geschichte mit der Familie',T.story.offen,'story');sec('💭 Ihr Gedanke aus der Nacht  ·  🔒',T.thought,'thought');sec('🧵 Was ihr noch nachgeht  ·  🔒',(T.threads||[]).join('  ·  '),'threads');
  for(const d of T.days)sec('🌙 '+new Date(d.day+'T12:00:00').toLocaleDateString('de-DE',{weekday:'short',day:'2-digit',month:'2-digit'})+'  ·  nachts durchdacht  ·  🔒',d.privat,d.day);}
 if(!j.items.length){const e=document.createElement('p');e.textContent='Noch keine Einträge.';box.appendChild(e);}
 const dsel=new Set();const db=document.createElement('button');db.id='dydel';db.disabled=true;db.textContent='Markierte löschen';
 const dup=()=>{db.disabled=!dsel.size;db.textContent=dsel.size?dsel.size+' markierte löschen':'Markierte löschen';};
 db.onclick=async()=>{if(!dsel.size)return;let r={ok:false};try{r=await (await post('/api/diary/delete',{ids:[...dsel]})).json();}catch(_){}if(r.ok){snd.del();openDiaryRefresh();}};
 for(const x of j.items){const p=document.createElement('p');p.className='dy';const cb=document.createElement('input');cb.type='checkbox';cb.className='dyc';
  cb.onchange=()=>{if(cb.checked)dsel.add(x.t);else dsel.delete(x.t);p.classList.toggle('sel',cb.checked);snd[cb.checked?'on':'off']();dup();};p.appendChild(cb);
  const k=document.createElement('button');k.className='dyk'+(x.fest?' on':'');k.textContent='🔑';k.title=x.fest?'Festgehalten, tippen zum Lösen':'Für immer festhalten';
  k.onclick=async()=>{let r={ok:false};try{r=await (await post('/api/diary/pin',{id:x.t})).json();}catch(_){}if(r.ok){snd[r.fest?'on':'off']();openDiary();}else if(r.error){k.title=r.error;k.classList.add('err');}};p.appendChild(k);if(x.fest)p.classList.add('fest');const m=document.createElement('span');m.className='dm';
  const d=new Date(x.t*1000);m.textContent=d.toLocaleDateString('de-DE',{weekday:'short',day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'})+'  ·  '+(x.src==='chat'?'💬 Chat':'🏠 Zuhause')+'  ·  '+(x.who||'unbekannt')+(x.privat?'  ·  🔒':'')+(x.blass?'  ·  verblasst':'');if(x.blass)p.style.opacity='.55';
  p.append(m,document.createTextNode(x.text));box.appendChild(p);}
 if(j.items.length)box.appendChild(db);
 const el=document.getElementById('rules');if(el.style.display!=='block'){el.style.display='block';el.scrollTop=0;rulesOpen=true;editing=true;history.pushState({r:1},'');snd.on();}}
function openDiaryRefresh(){openDiary();}
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
 const lists={};((LASTD&&LASTD.lists)||[]).forEach(l=>{lists[l.kind]=l.items.slice();});document.querySelectorAll('.list').forEach(b=>{lists[b.dataset.kind]=[...b.querySelectorAll('label')].map(x=>x._t);});
 try{if(view)await saveFields(lists[view.kind]);else await post('/api/move',{lists});}catch(e){}
 last='';load();}
function health(ok){const p=document.getElementById('pulse');p.className=ok?'ok':'bad';p.title=ok?'Alles in Ordnung':'Leyla ist gerade nicht erreichbar';}
async function load(){if(editing||dragging)return;try{const r=CODE?await post('/api/lists',{}):await fetch('/api/lists');if(!r.ok)throw 0;const s=await r.text();health(true);if(s!==last){last=s;render(JSON.parse(s));}}catch(e){health(false);}}
document.getElementById('del').onclick=async()=>{if(!sel.size)return;
 if(view){const rest=[...document.querySelectorAll('.list label')].map(x=>x._t).filter(t=>!sel.has(key(view.kind,t)));
  await saveFields(rest);snd.del();sel=new Set();last='';load();return;}
 const items=[...sel].map(x=>{const i=x.indexOf('\\u0000');return {kind:x.slice(0,i),text:x.slice(i+1)}});
 await post('/api/delete',{items});snd.del();sel=new Set();last='';load();};

let lampOn=false;
const LROWS=[['listen','Zuhören',['listen']],['think','Denken und Suchen',['think']],['speak','Reden',['speak_low','speak_high']]];
const LSETS=[['','Wenn Leyla glücklich ist'],['sad_','Wenn Leyla traurig oder eifersüchtig ist']];
function lmsg(t){document.getElementById('lmsg').textContent=t;}
const LTXT={ok:'',busy:'Leyla spricht gerade, bitte danach testen.',off:'Lampenshow ist aus.',failed:'Eine Lampe antwortet nicht, Leyla versucht es weiter.',error:'Hat nicht geklappt.'};
async function lampPost(path,body){try{const r=await fetch(path,{method:'POST',body:JSON.stringify(body||{})});return await r.json();}catch(e){return {result:'error'};}}
async function lampSave(body){const j=await lampPost('/api/lamp/colors',body);if(j.ok){snd.save();lmsg('Gespeichert.');}else lmsg(LTXT.error);}
async function loadLamps(){let d;try{d=await (await fetch('/api/lamp')).json();}catch(e){return;}
 lampOn=!!d.available;const box=document.getElementById('lamps');box.innerHTML='';if(!lampOn){box.style.display='none';return;}
 box.style.display=(sec==='lamps'&&!view)?'block':'none';
 const h=document.createElement('h2');h.textContent='Lampenfarben';box.appendChild(h);
 for(const [pre,title] of LSETS){const t=document.createElement('h3');t.textContent=title;box.appendChild(t);
 for(const [m0,name,k0] of LROWS){const mode=pre+m0,keys=k0.map(k=>pre+k);const c=document.createElement('div');c.className='card';
  const n=document.createElement('div');n.className='n';n.innerHTML=esc(name)+(keys.length>1?'<small>leise und laut, das Licht wechselt mit ihrer Stimme</small>':'');c.appendChild(n);
  for(const k of keys){const i=document.createElement('input');i.type='color';i.value=d.colors[k];i.title=d.labels[k];
   i.onchange=()=>lampSave({colors:{[k]:i.value}});c.appendChild(i);}
  const b=document.createElement('button');b.textContent='Testen';
  b.onclick=async()=>{b.disabled=true;lmsg('Die Lampen zeigen das Licht kurz und gehen dann zurück.');snd.on();
   const j=await lampPost('/api/lamp/test',{mode});lmsg(LTXT[j.result]||'');b.disabled=false;};
  c.appendChild(b);
  const lv=document.createElement('div');lv.className='lv';const r=document.createElement('input');r.type='range';r.min=5;r.max=100;r.step=5;r.value=d.levels[mode];r.title='Helligkeit';
  const p=document.createElement('span');p.textContent=r.value+' %';r.oninput=()=>{p.textContent=r.value+' %';};
  r.onchange=()=>lampSave({levels:{[mode]:+r.value}});lv.append(r,p);c.appendChild(lv);box.appendChild(c);}}
 const row=document.createElement('div');row.className='lb';
 const df=document.createElement('button');df.textContent='Standardwerte';
 df.onclick=async()=>{if(!confirm('Alle Farben und Helligkeiten auf die Leyla Werte zurückstellen?'))return;
  const nul=o=>Object.fromEntries(Object.keys(o).map(k=>[k,null]));
  const j=await lampPost('/api/lamp/colors',{colors:nul(d.colors),levels:nul(d.levels)});if(j.ok){snd.save();loadLamps();}};
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
                       "display": "fullscreen", "background_color": "#000000",
                       "theme_color": "#000000",
                       "id": "/", "scope": "/",
                       "icons": [{"src": "/icon.png?v=5", "sizes": sz, "type": "image/png",
                                  "purpose": "any"} for sz in ("192x192", "512x512")]
                                + [{"src": "/icon-maskable.png?v=6", "sizes": sz, "type": "image/png",
                                    "purpose": "maskable"} for sz in ("192x192", "512x512")]})


def list_outfits() -> dict:
    """Leyla's looks (2.99.4, Metin's idea: another dress each time the app opens): one folder
    per look in clips_dir() with its scenes (traurig.mp4, kuss.mp4, ...) and its still body.jpg."""
    out = {}
    base = clips_dir()
    try:
        looks = sorted(os.listdir(base))
    except OSError:
        return out
    for look in looks:
        folder = os.path.join(base, look)
        if not os.path.isdir(folder):
            continue
        files = os.listdir(folder)
        clips = sorted(f[:-4] for f in files
                       if f.endswith(".mp4") and CLIP_RE.match(f"/clips/{look}/{f}"))
        body = "body.jpg" in files
        # clips with a see through background (WebM with alpha), Mokka the cat (2.127.0)
        alpha = sorted(f[:-5] for f in files
                       if f.endswith(".webm") and CLIP_RE.match(f"/clips/{look}/{f}"))
        if clips or body or alpha:
            # v: newest change in the folder, the page adds it to every clip address so a phone
            # never plays a cached old version after a clip was replaced (2.117.8)
            try:
                v = int(max(os.path.getmtime(os.path.join(folder, f)) for f in files))
            except (OSError, ValueError):
                v = 0
            out[look] = {"clips": clips, "body": body, "v": v}
            # t: the date of each clip file, so a check can tell an old clip from a new one
            # (2.133.8, Metin wants to replace the clips that are still in the old size)
            out[look]["t"] = {c: int(os.path.getmtime(os.path.join(folder, c + ".mp4")))
                              for c in clips if os.path.exists(os.path.join(folder, c + ".mp4"))}
            if alpha:
                out[look]["alpha"] = alpha
    # r: the play speed Metin set in the tempo tester (2.136.0). The files stay untouched, the
    # page plays them faster or slower, so nothing is re-encoded and a value can change anytime
    rates = {}
    for item in _tempo_read():
        name, rate = str(item.get("name") or ""), item.get("rate")
        if "/" not in name or not isinstance(rate, (int, float)):
            continue
        if 0.2 <= float(rate) <= 3 and round(float(rate), 2) != 1.0:
            rates[name] = round(float(rate), 2)
    for name, rate in rates.items():
        look, clip = name.split("/", 1)
        if look in out and (clip in out[look]["clips"] or clip in out[look].get("alpha", ())):
            out[look].setdefault("r", {})[clip] = rate
    # k: the tempo curve, a own speed for a stretch inside a clip (2.139.0)
    for name, segs in _kurve_read().items():
        if "/" not in name:
            continue
        look, clip = name.split("/", 1)
        if look in out and clip in out[look]["clips"]:
            out[look].setdefault("k", {})[clip] = segs
    for name, cut in _schnitt_read().items():
        if "/" not in name:
            continue
        look, clip = name.split("/", 1)
        if look in out and clip in out[look]["clips"]:
            out[look].setdefault("s", {})[clip] = cut
    return out


def music_versions() -> dict:
    folder = os.path.join(clips_dir(), "musik")
    out = {}
    for name in list_music():
        try:
            out[name] = int(os.path.getmtime(os.path.join(folder, name + ".m4a")))
        except OSError:
            out[name] = 0
    return out


def list_music() -> list:
    """Background music of the stage (2.103.0): clips/musik/<mood>.m4a, or gut.m4a and traurig.m4a for
    every good or low mood."""
    try:
        return sorted(f[:-4] for f in os.listdir(os.path.join(clips_dir(), "musik"))
                      if f.endswith(".m4a") and CLIP_RE.match(f"/clips/musik/{f}"))
    except OSError:
        return []


async def _send_clip(writer, look: str, name: str, ext: str, lines: list, light: bool = False) -> None:
    """One clip or still of a look, with byte ranges, because Chrome asks for parts of a video.
    `light`: the page is on mobile data, send the light copy if there is one (2.141.0)."""
    fn = os.path.join(clips_dir(), look, f"{name}.{ext}")
    if light and ext == "mp4":
        fn = mobil_runner().copy_for(f"{look}/{name}", fn) or fn
    try:
        size = os.path.getsize(fn)
    except OSError:
        return await _respond(writer, "404 Not Found", "text/plain", "not found")
    start, end, status = 0, size - 1, "200 OK"
    for ln in lines[1:]:
        m = re.match(r"(?i)range:\s*bytes=(\d*)-(\d*)", ln)
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            status = "206 Partial Content"
    if start > end:
        return await _respond(writer, "416 Range Not Satisfiable", "text/plain", "")
    with open(fn, "rb") as f:
        f.seek(start)
        raw = f.read(end - start + 1)
    extra = f"Content-Range: bytes {start}-{end}/{size}\r\n" if status.startswith("206") else ""
    ctype = {"mp4": "video/mp4", "m4a": "audio/mp4", "webm": "video/webm"}.get(ext, "image/jpeg")
    writer.write((f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(raw)}\r\n"
                  f"Accept-Ranges: bytes\r\n{extra}Cache-Control: max-age=86400\r\n"
                  "Connection: close\r\n\r\n").encode() + raw)
    await writer.drain()


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
        return {"available": True, "colors": lamp.colors_hex(), "labels": COLOR_LABELS,
                "levels": dict(lamp.levels)}
    if method != "POST" or path not in ("/api/lamp/colors", "/api/lamp/test", "/api/lamp/reset"):
        return None
    if lamp is None or not lamp.available:
        return {"ok": False, "result": "off"}
    d = json.loads(body or b"{}") or {}
    if path == "/api/lamp/colors":
        ok = lamp.set_colors(d.get("colors"), d.get("levels"))
        if ok:
            logger.info("Memory page: lamp looks changed to %s, strengths %s", lamp.colors_hex(), lamp.levels)
        return {"ok": ok}
    if path == "/api/lamp/test":
        return {"result": await lamp.preview(str(d.get("mode")))}
    return {"result": await lamp.reset()}


TEMPO_PATH = "/data/tempo_wunsch.json"  # what Metin set in the tempo tester (2.135.2)


def _tempo_read() -> list:
    try:
        with open(os.environ.get("LEYLA_TEMPO", TEMPO_PATH), encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _tempo_add(name: str, rate: float) -> None:
    path = os.environ.get("LEYLA_TEMPO", TEMPO_PATH)
    items = [i for i in _tempo_read() if i.get("name") != name]
    items.append({"name": name, "rate": rate, "t": int(time.time())})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-2000:], f, ensure_ascii=False)  # 2.135.7: 60 was too few, his run of 300 clips got cut
    os.replace(tmp, path)


KURVE_PATH = "/data/tempo_kurve.json"


def _kurve_read() -> dict:
    """Tempo curves: a clip can have its own speed for a stretch inside it (2.139.0,
    Metin: "Ich muesste mit einem Skalpell die ms hoeher oder tiefer stellen an Sekunde
    4-5 von 10"). Shape: {"nacht/tanz4": [[3.5, 5.0, 1.3], ...]} with seconds and speed."""
    try:
        with open(os.environ.get("LEYLA_KURVE", KURVE_PATH), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


SCHNITT_PATH = "/data/schnitt.json"


def _schnitt_read() -> dict:
    """Cut marks (2.144.0, Metin: "dass ich die Endungen selber einstellen und schneiden kann"):
    where a clip begins and ends on the stage. Shape: {"schwarz/freizeitpo": [0.0, 8.5]} in
    seconds, end 0 means up to the real end. The clip files stay untouched."""
    try:
        with open(os.environ.get("LEYLA_SCHNITT", SCHNITT_PATH), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _schnitt_set(name: str, start, end) -> bool:
    """Store the marks of one clip; start 0 and end 0 removes them. False when they make no sense."""
    try:
        a_, b_ = round(max(0.0, float(start or 0)), 2), round(max(0.0, float(end or 0)), 2)
    except (TypeError, ValueError):
        return False
    if b_ and b_ - a_ < 0.5:      # at least half a second must remain
        return False
    path = os.environ.get("LEYLA_SCHNITT", SCHNITT_PATH)
    d = _schnitt_read()
    if a_ or b_:
        d[name] = [a_, b_]
    else:
        d.pop(name, None)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)
    return True


def _kurve_set(name: str, segs: list) -> None:
    path = os.environ.get("LEYLA_KURVE", KURVE_PATH)
    d = _kurve_read()
    clean = []
    for seg in segs if isinstance(segs, list) else []:
        try:
            a_, b_, r_ = float(seg[0]), float(seg[1]), round(float(seg[2]), 2)
        except (TypeError, ValueError, IndexError):
            continue
        if b_ > a_ >= 0 and 0.2 <= r_ <= 3:
            clean.append([round(a_, 2), round(b_, 2), r_])
    clean.sort()
    if clean:
        d[name] = clean[:40]
    else:
        d.pop(name, None)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def _tempo_clear() -> None:
    """His run by feel is replaced by the measurement (2.137.0, he said 'Kannst loeschen';
    the old values stay readable in docs/TEMPO_WUNSCH.md)."""
    path = os.environ.get("LEYLA_TEMPO", TEMPO_PATH)
    try:
        os.remove(path)
    except OSError:
        pass


def clip_paths() -> dict:
    """Every clip with its file, as "look/clip" -> path (for the motion measurement)."""
    base = clips_dir()
    out = {}
    for look, info in list_outfits().items():
        for clip in info.get("clips", ()):
            out[f"{look}/{clip}"] = os.path.join(base, look, clip + ".mp4")
    return out


MOTION = None
MOBIL = None


DIAG = collections.deque(maxlen=30)
TIMING = collections.deque(maxlen=50)  # 2.141.6: chat times, server part against what the phone saw


def _timing_add(server_ms, prev_rtt, light) -> None:
    """Server time of this chat answer and the round trip the phone measured for the previous one."""
    rtt = prev_rtt if isinstance(prev_rtt, int) and 0 < prev_rtt < 600000 else None
    TIMING.append({"at": time.strftime("%H:%M:%S"), "server_ms": server_ms,
                   "prev_rtt_ms": rtt, "light": bool(light)})
    logger.info("Chat timing: server %d ms, phone saw %s ms for the previous one", server_ms, rtt)


def mobil_runner():
    """Light copies of the heavy 4K clips for the phone on the go (app/mobil.py, 2.141.0)."""
    global MOBIL
    if MOBIL is None:
        from . import mobil
        MOBIL = mobil.Mobil(clip_paths, os.environ.get("LEYLA_MOBIL_DIR", "/data/mobil"))
    return MOBIL


def motion_runner():
    global MOTION
    if MOTION is None:
        from . import motion
        MOTION = motion.Runner(clip_paths, _tempo_add)
    return MOTION


TEMPO_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip Tester</title><style>
body{margin:0;background:#000;color:#eee;font:15px system-ui}
h1{font-size:17px;margin:8px 10px}
.wrap{display:flex;gap:10px;margin:0 10px;align-items:flex-start}
.p{flex:1;padding:8px;border:1px solid #334;border-radius:10px;min-width:0}
.p.ref{border-color:#2a6}
video{width:100%;max-height:52vh;background:#000;margin-top:6px;border-radius:8px}
input[type=range]{width:100%}
.v{font-size:19px;font-weight:600;color:#9fe8ff}
.row{display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap}
button{padding:6px 10px;border-radius:8px;background:#222;color:#eee;border:1px solid #445}
.t{font-size:13px;color:#8aa}
.t.g{color:#5c9}
#liste{margin:10px;padding:8px;border:1px solid #334;border-radius:10px;font-size:13px;color:#9ab}
@media (max-width:720px){.wrap{flex-direction:column}video{max-height:34vh}}
</style></head><body><h1>Clip Tester: Tempo, Anfang und Ende</h1><div class="wrap" id="w"></div>
<script>
/* 2.138.0 (Metin: "Ich brauche Referenz vor Augen"): judging a clip on its own does not
   work, so the left side keeps playing one clip he picked as the reference and the right
   side is the clip under test. He steps with the mouse wheel or the arrows, sets the
   speed until the two match and presses merken, which takes the clip out of the list. */
let NAMES=[],ALL=[],REF='',RATES={},KURVE={},SCHNITT={};
const med=a=>{a=a.slice().sort((x,y)=>x-y);return a.length?a[Math.floor(a.length/2)]:1;};
function save(k,v){try{localStorage.setItem(k,v);}catch(e){}}
function load(k){try{return localStorage.getItem(k)||'';}catch(e){return '';}}
async function build(){
 const j=await (await fetch('/clips.json')).json(),o=j.outfits||{};
 const order=['kurz','schwarz','nacht','mokka'];
 const looks=Object.keys(o).sort((a,b)=>(order.indexOf(a)+99)%100-(order.indexOf(b)+99)%100||a.localeCompare(b));
 for(const look of looks){const r=o[look].r||{};for(const c in r)RATES[look+'/'+c]=r[c];
  const q=o[look].k||{};for(const c in q)KURVE[look+'/'+c]=q[c];
  const sc=o[look].s||{};for(const c in sc)SCHNITT[look+'/'+c]=sc[c];
  for(const c of (o[look].clips||[]).slice().sort())NAMES.push(look+'/'+c);}
 ALL=NAMES.slice();
 let done=[];try{done=((await (await fetch('/api/tempo?t='+Date.now())).json()).items||[]).map(x=>x.name);}catch(e){}
 for(const n of done){const i=NAMES.indexOf(n);if(i>=0&&NAMES.length>2)NAMES.splice(i,1);}
 const want=new URLSearchParams(location.search).get('clip')||'';if(ALL.includes(want)&&!NAMES.includes(want))NAMES.unshift(want);
 REF=load('lref');if(!NAMES.length)return;if(!REF)REF=NAMES[0];
 const w=document.getElementById('w');
 /* left: the reference, always running */
 const rd=document.createElement('div');rd.className='p ref';
 const rt=document.createElement('div');rt.className='t g';
 const rv=document.createElement('video');rv.loop=true;rv.muted=true;rv.playsInline=true;
 const rrow=document.createElement('div');rrow.className='row';
 const rprev=document.createElement('button');rprev.textContent='◀';
 const rnext=document.createElement('button');rnext.textContent='▶';
 rrow.append(rprev,rnext);
 rd.append(rt,rv,rrow);
 const refShow=()=>{rt.textContent='Referenz: '+REF+'   (Tempo '+(RATES[REF]||1).toFixed(2)+')';
  rv.src='/clips/'+REF+'.mp4?t='+Date.now();rv.playbackRate=RATES[REF]||1;rv.play().catch(()=>{});save('lref',REF);};
 rv.onloadedmetadata=()=>{rv.playbackRate=RATES[REF]||1;};
 const refStep=k=>{const i=NAMES.indexOf(REF);REF=NAMES[((i<0?0:i)+k+NAMES.length)%NAMES.length];refShow();};
 rprev.onclick=()=>refStep(-1);rnext.onclick=()=>refStep(1);
 rv.addEventListener('wheel',e=>{e.preventDefault();refStep(e.deltaY>0?1:-1);},{passive:false});
 /* right: the clip under test */
 const d=document.createElement('div');d.className='p';
 const pos=document.createElement('div');pos.className='t';
 const v=document.createElement('video');v.loop=true;v.muted=true;v.playsInline=true;
 const nav=document.createElement('div');nav.className='row';
 const prev=document.createElement('button');prev.textContent='◀';
 const next=document.createElement('button');next.textContent='▶';
 const asref=document.createElement('button');asref.textContent='als Referenz';
 const pick=document.createElement('select');pick.style.cssText='max-width:100%;padding:6px;border-radius:8px;background:#222;color:#eee;border:1px solid #445';
 for(const n of ALL){const op=document.createElement('option');op.value=n;op.textContent=n;pick.appendChild(op);}
 nav.append(prev,next,asref,pick);
 const r=document.createElement('input');r.type='range';r.min='0.4';r.max='2';r.step='0.05';r.value='1';
 const lab=document.createElement('span');lab.className='v';lab.textContent='1.00';
 const row=document.createElement('div');row.className='row';
 const back=document.createElement('button');back.textContent='zurueck auf 1';
 const mk=document.createElement('button');mk.textContent='merken';
 const skip=document.createElement('button');skip.textContent='passt schon';
 row.append(lab,back,mk,skip);
 /* the scalpel (2.139.0, Metin): a stretch inside the clip gets its own tempo */
 const seg=document.createElement('div');seg.className='row';
 const sfrom=document.createElement('input');sfrom.type='range';sfrom.min='0';sfrom.max='10';sfrom.step='0.05';sfrom.value='0';
 const slen=document.createElement('input');slen.type='range';slen.min='0.2';slen.max='4';slen.step='0.05';slen.value='1';
 const srate=document.createElement('input');srate.type='range';srate.min='0.4';srate.max='2';srate.step='0.05';srate.value='1';
 const slab=document.createElement('div');slab.className='t';
 const only=document.createElement('button');only.textContent='nur Stueck';
 const sadd=document.createElement('button');sadd.textContent='Stueck merken';
 const sclr=document.createElement('button');sclr.textContent='Kurve loeschen';
 const slist=document.createElement('div');slist.className='t';
 seg.append(only,sadd,sclr);
 /* begin and end (2.144.0, Metin: "dass ich die Endungen selber einstellen und schneiden kann"): two marks per clip,
    stored by the server; the stage starts at the first and hands over at the second, the file stays whole */
 const clab=document.createElement('div');clab.className='v';clab.style.fontSize='15px';clab.style.marginTop='10px';
 const cfrom=document.createElement('input');cfrom.type='range';cfrom.min='0';cfrom.max='10';cfrom.step='0.01';cfrom.value='0';
 const cto=document.createElement('input');cto.type='range';cto.min='0';cto.max='10';cto.step='0.01';cto.value='10';
 const crow=document.createElement('div');crow.className='row';
 const mkb=(txt)=>{const x=document.createElement('button');x.textContent=txt;return x;};
 const am=mkb('Anfang -'),ap=mkb('Anfang +'),em=mkb('Ende -'),ep=mkb('Ende +');
 const crow2=document.createElement('div');crow2.className='row';
 const seam=mkb('Ende ansehen'),csave=mkb('Schnitt merken'),cclr=mkb('Schnitt weg');
 crow.append(am,ap,em,ep);crow2.append(seam,csave,cclr);
 d.append(pos,v,nav,r,row,clab,cfrom,cto,crow,crow2,slab,sfrom,slen,srate,seg,slist);
 let cur=(ALL.includes(want)&&want)||NAMES.find(n=>n!==REF)||NAMES[0];
 const show=()=>{pos.textContent=cur+'   '+(NAMES.indexOf(cur)+1)+' von '+NAMES.length+' offen';pick.value=cur;};
 const play=()=>{v.src='/clips/'+cur+'.mp4?t='+Date.now();v.playbackRate=Number(r.value);v.play().catch(()=>{});show();};
 v.onloadedmetadata=()=>{v.playbackRate=Number(r.value);};
 const step=k=>{const i=NAMES.indexOf(cur);cur=NAMES[((i<0?0:i)+k+NAMES.length)%NAMES.length];
  r.value=String(RATES[cur]||1);lab.textContent=Number(r.value).toFixed(2);play();segShow();};
 prev.onclick=()=>step(-1);next.onclick=()=>step(1);
 pick.onchange=()=>{cur=pick.value;if(!NAMES.includes(cur))NAMES.push(cur);r.value=String(RATES[cur]||1);lab.textContent=Number(r.value).toFixed(2);play();segShow();};
 /* --- begin and end --- */
 let SEAM=false,DUR=10;const FR=1/24;
 const cutA=()=>Number(cfrom.value),cutB=()=>Number(cto.value);
 const cutShow=()=>{const c=SCHNITT[cur],sv=c&&Math.abs(c[0]-cutA())<0.011&&Math.abs((c[1]||DUR)-cutB())<0.011;
  clab.textContent='Anfang '+cutA().toFixed(2)+' s   Ende '+cutB().toFixed(2)+' s von '+DUR.toFixed(2)+' s'+(sv?'   (gemerkt)':(cutA()>0||cutB()<DUR-0.03?'   (noch nicht gemerkt)':''))+(SEAM?'   Ansicht: Ende, dann Anfang':'');};
 const cutLoad=()=>{DUR=v.duration||10;cfrom.max=cto.max=String(DUR);const c=SCHNITT[cur]||[0,0];cfrom.value=String(c[0]||0);cto.value=String(c[1]&&c[1]<DUR?c[1]:DUR);cutShow();};
 const clampA=()=>{if(cutA()>cutB()-0.5)cfrom.value=String(Math.max(0,cutB()-0.5));};
 const clampB=()=>{if(cutB()<cutA()+0.5)cto.value=String(Math.min(DUR,cutA()+0.5));};
 cfrom.oninput=()=>{clampA();cutShow();v.currentTime=cutA();};
 cto.oninput=()=>{clampB();cutShow();v.currentTime=Math.max(cutA(),cutB()-1.2);};
 am.onclick=()=>{cfrom.value=String(Math.max(0,cutA()-FR));cfrom.oninput();};
 ap.onclick=()=>{cfrom.value=String(cutA()+FR);cfrom.oninput();};
 em.onclick=()=>{cto.value=String(cutB()-FR);cto.oninput();};
 ep.onclick=()=>{cto.value=String(Math.min(DUR,cutB()+FR));cto.oninput();};
 seam.onclick=()=>{SEAM=!SEAM;seam.style.borderColor=SEAM?'#2a6':'';if(SEAM)v.currentTime=Math.max(cutA(),cutB()-2);cutShow();};
 const cutSave=async(a,b)=>{let ok=false;try{ok=(await (await fetch('/api/schnitt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,start:a,end:b})})).json()).ok;}catch(e){}
  if(ok){if(a||b)SCHNITT[cur]=[a,b];else delete SCHNITT[cur];}return ok;};
 csave.onclick=async()=>{const a=Number(cutA().toFixed(2)),b=cutB()>=DUR-0.03?0:Number(cutB().toFixed(2));const ok=await cutSave(a,b);
  csave.textContent=ok?'gemerkt':'ging nicht';setTimeout(()=>{csave.textContent='Schnitt merken';},1200);cutShow();};
 cclr.onclick=async()=>{if(await cutSave(0,0)){cfrom.value='0';cto.value=String(DUR);}cutShow();};
 /* the preview follows the marks picture by picture (timeupdate only comes every quarter second) */
 const cutTick=()=>{if(!ONLY&&v.duration&&!v.paused){const A=cutA(),B=cutB(),t=v.currentTime;
   if(t>=B-0.01||t<A-0.15)v.currentTime=A;else if(SEAM&&t>A+1.5&&t<B-2.05)v.currentTime=B-2;}
  requestAnimationFrame(cutTick);};
 v.addEventListener('wheel',e=>{e.preventDefault();step(e.deltaY>0?1:-1);},{passive:false});
 r.oninput=()=>{v.playbackRate=Number(r.value);lab.textContent=Number(r.value).toFixed(2);};
 back.onclick=()=>{r.value='1';r.oninput();};
 asref.onclick=()=>{REF=cur;refShow();step(1);};
 const drop=()=>{const i=NAMES.indexOf(cur);if(i>=0&&NAMES.length>2)NAMES.splice(i,1);
  cur=NAMES[Math.min(i<0?0:i,NAMES.length-1)];r.value=String(RATES[cur]||1);lab.textContent=Number(r.value).toFixed(2);play();segShow();};
 const remember=async rate=>{try{await fetch('/api/tempo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,rate:rate})});
   RATES[cur]=rate;mk.textContent='gemerkt';drop();}catch(e){mk.textContent='ging nicht';}
  setTimeout(()=>{mk.textContent='merken';},1200);liste();};
 mk.onclick=()=>remember(Number(r.value));
 skip.onclick=()=>remember(1);
 /* --- the piece inside the clip --- */
 let ONLY=false;
 const segFrom=()=>Number(sfrom.value),segTo=()=>Number(sfrom.value)+Number(slen.value);
 const segShow=()=>{slab.textContent='Stueck '+segFrom().toFixed(2)+' bis '+segTo().toFixed(2)+' s   Tempo '+Number(srate.value).toFixed(2)+(ONLY?'   (Schleife nur ueber dem Stueck)':'');
  slist.innerHTML=(KURVE[cur]||[]).map((x,i)=>'Kurve: '+x[0].toFixed(2)+'-'+x[1].toFixed(2)+' s  '+Number(x[2]).toFixed(2)+' <a href="#" data-i="'+i+'">weg</a>').join('<br>')||'keine Kurve';
  slist.querySelectorAll('a').forEach(a2=>{a2.onclick=e=>{e.preventDefault();const k=(KURVE[cur]||[]).slice();k.splice(Number(a2.dataset.i),1);kurveSave(k);};});};
 sfrom.oninput=slen.oninput=()=>{segShow();if(ONLY)v.currentTime=segFrom();};
 srate.oninput=()=>{segShow();if(ONLY)v.playbackRate=Number(srate.value);};
 only.onclick=()=>{ONLY=!ONLY;only.style.borderColor=ONLY?'#2a6':'';v.currentTime=ONLY?segFrom():0;segShow();};
 v.addEventListener('timeupdate',()=>{
  if(ONLY){if(v.currentTime>=segTo()||v.currentTime<segFrom()-0.1)v.currentTime=segFrom();
   v.playbackRate=Number(srate.value);return;}
  const k=KURVE[cur];if(!k)return;let rr=Number(r.value);
  for(const sg of k)if(v.currentTime>=sg[0]&&v.currentTime<sg[1])rr=sg[2];
  if(Math.abs(v.playbackRate-rr)>0.001)v.playbackRate=rr;});
 async function kurveSave(k){try{await fetch('/api/kurve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:cur,segs:k})});
   if(k.length)KURVE[cur]=k;else delete KURVE[cur];}catch(e){}
  segShow();}
 sadd.onclick=()=>{const k=(KURVE[cur]||[]).filter(x=>x[1]<=segFrom()||x[0]>=segTo());
  k.push([Number(segFrom().toFixed(2)),Number(segTo().toFixed(2)),Number(srate.value)]);k.sort((a2,b2)=>a2[0]-b2[0]);kurveSave(k);};
 sclr.onclick=()=>kurveSave([]);
 v.addEventListener('loadedmetadata',()=>{sfrom.max=String(Math.max(1,(v.duration||10)-0.2));segShow();cutLoad();});
 w.append(rd,d);refShow();play();segShow();requestAnimationFrame(cutTick);
}
async function liste(){let j={items:[]};try{j=await (await fetch('/api/tempo?t='+Date.now())).json();}catch(e){}
 let d=document.getElementById('liste');if(!d){d=document.createElement('div');d.id='liste';document.body.appendChild(d);}
 const it=(j.items||[]).filter(x=>Number(x.rate)!==1);
 d.innerHTML='<b>Gemerkt</b> ('+(j.items||[]).length+' durch, '+it.length+' mit anderem Tempo)<br>'+
  (it.slice(-30).map(x=>x.name+'  '+Number(x.rate).toFixed(2)).join('<br>')||'noch nichts');}
build();liste();
</script></body></html>"""


async def _reach_api(reach, method: str, path: str, d: dict, unlocked: bool) -> dict:
    """Her own messages (app/reach.py): the app asks for new ones, marks them seen, plays a
    voice message. GET /api/reachstats (no code word) gives counts and states only."""
    if reach is None:
        return {"ok": False}
    if method == "GET" and path == "/api/reachstats":
        return reach.stats()
    if method != "POST" or not unlocked:
        return {"ok": False}
    if path == "/api/reach/pending":
        return {"ok": True, "items": reach.pending()}
    if path == "/api/reach/seen":
        ids = d.get("ids")
        return {"ok": True, "seen": reach.seen(ids if isinstance(ids, list) else [])}
    if path == "/api/reach/audio":
        wav = reach.audio(str(d.get("id") or "")[:20])
        return {"ok": bool(wav), "audio": base64.b64encode(wav).decode("ascii") if wav else ""}
    return {"ok": False}


async def _handle(store, sync, reader, writer, lamp=None, code_phrase: str = "", rules=None,
                  chat=None, voice=None, mailer=None, google=None, inbox=None,
                  mood=None, reminders=None, diary=None, chat_new=None, reach=None,
                  touch=None, hear=None, kopf=None) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        lines = head.decode("latin-1").split("\r\n")
        method, path = (lines[0].split(" ") + ["", ""])[:2]
        query = path.split("?", 1)[1] if "?" in path else ""
        path = path.split("?")[0]
        length = 0
        for ln in lines[1:]:
            if ln.lower().startswith("content-length:"):
                length = min(int(ln.split(":", 1)[1].strip() or 0), MAX_BODY)
        body = await asyncio.wait_for(reader.readexactly(length), timeout=10) if length else b""
        lamp_reply = await _lamp_api(lamp, method, path, body) if path.startswith("/api/lamp") else None
        d = {}
        if method == "POST" and not path.startswith("/api/lamp") and path != "/api/weckton":
            d = json.loads(body or b"{}") or {}
            if not isinstance(d, dict):
                d = {}
        unlocked = bool(d.get("code")) and check_code(d.get("code"), code_phrase)
        titles = TITLES + (PRIVATE_TITLE,) if unlocked else TITLES
        if lamp_reply is not None:
            await _respond(writer, "200 OK", "application/json", json.dumps(lamp_reply, ensure_ascii=False))
        elif method == "POST" and path == "/api/weckton":
            # raw samples from the Voice PE: the sound that almost woke her (app/sammler.py)
            from app import sammler
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(sammler.collector().take(body, query)))
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
        elif method == "GET" and path == "/leyla_body.jpg":
            with open(BODY_PATH, "rb") as f:
                raw = f.read()
            writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: {len(raw)}\r\n"
                          "Cache-Control: max-age=86400\r\nConnection: close\r\n\r\n").encode() + raw)
            await writer.drain()
        elif method == "GET" and path == "/clips.json":
            await _respond(writer, "200 OK", "application/json", json.dumps({"outfits": list_outfits(), "music": list_music(), "music_v": music_versions()}))
        elif method == "GET" and CLIP_RE.match(path):
            m = CLIP_RE.match(path)
            await _send_clip(writer, m.group(1), m.group(2), m.group(3), lines,
                             light="m=1" in query.split("&"))
        elif method == "GET" and path == "/manifest.json":
            await _respond(writer, "200 OK", "application/manifest+json", MANIFEST)
        elif method == "GET" and path == "/api/tempo":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"items": _tempo_read()}, ensure_ascii=False))
        elif method == "POST" and path == "/api/tempo":
            n = str(d.get("name") or "")[:60]
            try:
                rate = round(float(d.get("rate") or 0), 2)
            except (TypeError, ValueError):
                rate = 0.0
            ok = bool(n) and 0.2 <= rate <= 3
            if ok:
                _tempo_add(n, rate)
                logger.info("Tempo tester: %s at %.2f", n, rate)
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "GET" and path == "/api/kurve":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(_kurve_read(), ensure_ascii=False))
        elif method == "POST" and path == "/api/kurve":
            n = str(d.get("name") or "")[:60]
            if n:
                _kurve_set(n, d.get("segs") or [])
                logger.info("Tempo curve: %s -> %s", n, d.get("segs"))
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": bool(n)}))
        elif method == "GET" and path == "/api/schnitt":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(_schnitt_read(), ensure_ascii=False))
        elif method == "POST" and path == "/api/schnitt":
            n = str(d.get("name") or "")[:60]
            ok = bool(n) and _schnitt_set(n, d.get("start"), d.get("end"))
            if ok:
                logger.info("Cut marks: %s -> %s to %s", n, d.get("start"), d.get("end"))
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "GET" and path.startswith("/api/voice/"):
            st = voice_stream.get(path.rsplit("/", 1)[1])
            if st is None:
                await _respond(writer, "404 Not Found", "text/plain", "")
            else:  # raw 24 kHz PCM as it is spoken, the end of the body is the end of the voice
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                             b"Cache-Control: no-store\r\nConnection: close\r\n\r\n")
                async for chunk in st.read():
                    writer.write(chunk)
                    await writer.drain()
        elif method == "POST" and path == "/api/diag":
            # 2.144.3: how the page runs on the phone (tab or installed app), to find out why
            # Metin's icon opens with the address bar; only these few flags, nothing personal
            DIAG.append({"at": time.strftime("%H:%M:%S"),
                         **{k: d.get(k) for k in ("mode", "secure", "sw", "inst", "ev", "ua") if k in d}})
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": True}))
        elif method == "GET" and path == "/api/diag":
            await _respond(writer, "200 OK", "application/json", json.dumps(list(DIAG)))
        elif method == "GET" and path == "/api/timing":
            await _respond(writer, "200 OK", "application/json", json.dumps(list(TIMING)))
        elif method == "GET" and path == "/api/mobil":
            await _respond(writer, "200 OK", "application/json", json.dumps(mobil_runner().status()))
        elif method == "GET" and path == "/api/motion":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(motion_runner().status()))
        elif method == "POST" and path == "/api/motion":
            # measure how fast she really moves and set one cadence per group (2.137.0)
            r = motion_runner()
            if d.get("fresh"):
                r.items = {}
                _tempo_clear()
            asyncio.get_running_loop().create_task(r.run())
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"ok": True, "started": True}))
        elif method == "GET" and path == "/api/motion/items":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(motion_runner().items, ensure_ascii=False))
        elif method == "GET" and path == "/tempo":
            # Tempo Tester (2.135.0, Metin): two clips side by side with a speed slider each,
            # so he can find the right factor himself and name it
            await _respond(writer, "200 OK", "text/html; charset=utf-8", TEMPO_PAGE)
        elif method == "GET" and path == "/sw.js":
            # without a service worker Chrome only makes a shortcut that opens with its address
            # bar; with one the page installs as an app and the manifest's fullscreen applies
            # (2.134.3, Metin). It only passes requests through, nothing is cached.
            await _respond(writer, "200 OK", "application/javascript",
                           "self.addEventListener('install',e=>self.skipWaiting());\n"
                           "self.addEventListener('activate',e=>e.waitUntil(clients.claim()));\n"
                           "self.addEventListener('fetch',e=>{});\n")
        elif method == "GET" and path == "/api/lists":
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(snapshot(store), ensure_ascii=False))
        elif method == "POST" and path == "/api/lists":
            snap = snapshot(store, titles)
            if unlocked and diary:  # the menu shows how many diary entries there are (2.150.3)
                snap["diary_n"] = len(diary.entries())
            await _respond(writer, "200 OK", "application/json", json.dumps(snap, ensure_ascii=False))
        elif method == "POST" and path == "/api/rules":
            text = rules() if (unlocked and rules) else ""
            await _respond(writer, "200 OK", "application/json",
                           json.dumps({"text": text}, ensure_ascii=False))
        elif method == "POST" and path == "/api/chat":
            out = None
            t0 = time.monotonic()
            if unlocked and chat:
                try:
                    out = await chat(d.get("history"), d.get("message"))
                except Exception as e:
                    logger.warning("Chat failed: %s", e)
            _timing_add(int((time.monotonic() - t0) * 1000), d.get("rtt"), d.get("light"))
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(out or {"error": True}, ensure_ascii=False))
        elif method == "POST" and path == "/api/chat_touch":
            out = None
            if unlocked and touch:
                try:
                    out = await touch(d.get("history"), str(d.get("zone", "")))
                except Exception as e:
                    logger.warning("Touch reaction failed: %s", e)
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(out or {"error": True}, ensure_ascii=False))
        elif method == "POST" and path == "/api/hoeren":
            # dictation: only turn his speech into text, the sending stays his (2.140.0,
            # Metin wants the keyboard gone and the words in the field before he sends)
            out = None
            if unlocked and hear:
                try:
                    out = await hear(d.get("audio"), d.get("mime"))
                except Exception as e:
                    logger.warning("Dictation failed: %s", e)
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(out or {"error": True}, ensure_ascii=False))
        elif method == "POST" and path == "/api/chat_voice":
            out = None
            if unlocked and voice:
                try:
                    args = (d.get("history"), d.get("audio"), d.get("mime"))
                    out = await (voice(*args, stream=True) if d.get("stream") else voice(*args))
                except Exception as e:
                    logger.warning("Voice message failed: %s", e)
            if isinstance(out, dict):
                t = out.pop("t", {})
                TIMING.append({"at": time.strftime("%H:%M:%S"), "kind": "mikro", **t,
                               "up_kb": len(d.get("audio") or "") * 3 // 4096,
                               "down_kb": len(out.get("audio") or "") * 3 // 4096,
                               "prev_rtt_ms": d.get("rtt"), "light": bool(d.get("light"))})
            await _respond(writer, "200 OK", "application/json",
                           json.dumps(out or {"error": True}, ensure_ascii=False))
        elif method == "POST" and path.startswith("/api/google/"):
            out = {"ok": False}
            if unlocked and google:
                if path == "/api/google/status":
                    out = {"ok": True, "configured": google.configured,
                           "connected": google.connected,
                           "missing": google.missing if google.connected else []}
                elif path == "/api/google/auth" and google.configured:
                    out = {"ok": True, "url": google.auth_url()}
                elif path == "/api/google/connect":
                    out = await google.connect(str(d.get("url", "")))
                elif path == "/api/google/contacts":
                    out = {"ok": True, "contacts": await google.contacts(force=bool(d.get("force")))}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path.startswith("/api/mail/"):
            out = {"ok": False}
            if unlocked and mailer:
                if path == "/api/mail/pending":
                    out = {"ok": True, "drafts": mailer.pending(),
                           "trash": inbox.pending() if inbox else []}
                elif path == "/api/mail/send":
                    out = await mailer.send(str(d.get("id", "")))
                elif path == "/api/mail/discard":
                    out = {"ok": mailer.discard(str(d.get("id", "")))}
                elif path == "/api/mail/trash" and inbox:
                    out = await inbox.confirm(str(d.get("id", "")))
                elif path == "/api/mail/trash_discard" and inbox:
                    out = {"ok": inbox.discard(str(d.get("id", "")))}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "GET" and path == "/api/wakestats":
            # only counts, no content: false wakes per day and the kept recordings
            from app import metrics
            folder = os.environ.get("FALSE_WAKE_DIR", "/data/false_wakes")
            try:
                files = len([f for f in os.listdir(folder) if f.endswith(".wav")])
            except OSError:
                files = 0
            from app import sammler
            out = {"tage": metrics.wake_stats(metrics.load()), "aufnahmen": files,
                   "beinahe": sammler.collector().stats()}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/game_reset":
            out = mood.game_reset() if (mood and hasattr(mood, "game_reset")) else {"ok": False}
            logger.info("Memory page: touch game reset")
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "GET" and path == "/api/moodstats":
            # mood names and roll times only, no texts (2.96.1, to check that the moods run)
            out = mood.stats() if mood else {}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/chat_new":
            ok = False
            if unlocked and chat_new:
                try:
                    await chat_new()
                    ok = True
                except Exception as e:
                    logger.warning("New chat: %s", e)
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path.startswith("/api/kopf/"):
            # her memory by meaning: status, tuning and measuring (app/recall.py), code word only
            out = {"ok": False}
            if unlocked and kopf:
                try:
                    out = await kopf.api(path, d)
                except Exception as e:
                    logger.warning("Kopf: %s", type(e).__name__)
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/diary/pin":
            out = diary.pin(d.get("id")) if (unlocked and diary) else {"ok": False}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/diary/delete":
            n = diary.delete(d.get("ids") or []) if (unlocked and diary) else 0
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": n > 0, "deleted": n}))
        elif method == "POST" and path == "/api/diary":
            out = {"ok": False}
            if unlocked and diary:
                out = {"ok": True, "items": [
                    {"t": e.get("t", 0), "who": (e.get("who") or "").split(" ")[0], "src": e.get("src", ""),
                     "privat": bool(e.get("privat")), "text": e.get("lang", ""),
                     "fest": bool(e.get("fest")), "blass": bool(e.get("blass"))}
                    for e in sorted(diary.entries(), key=lambda x: -x.get("t", 0))]}
                if kopf and getattr(kopf, "reflect", None) and kopf.settings.get("nachdenken"):
                    out["think"] = kopf.reflect.listing()  # what she thought over at night
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path.startswith("/api/remind/"):
            out = {"ok": False}
            if unlocked and reminders and reminders.available:
                if path == "/api/remind/pending":
                    out = {"ok": True, "items": await reminders.pending()}
                elif path == "/api/remind/ok":
                    out = {"ok": reminders.ack(str(d.get("id", ""))[:300]) > 0}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif path.startswith("/api/reach"):
            out = await _reach_api(reach, method, path, d, unlocked)
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/pet":
            # the stage has played the surprise: only now does Leyla know Mokka (2.133.1, Metin)
            ok = bool(unlocked) and day.pet_meet()
            if ok:
                logger.info("Memory page: Leyla has discovered Mokka")
            await _respond(writer, "200 OK", "application/json", json.dumps({"ok": ok}))
        elif method == "POST" and path == "/api/rose":
            out = mood.give_rose() if (unlocked and mood and hasattr(mood, "give_rose")) else {"ok": False}
            if out.get("ok") or out.get("rose") == "blocked":
                logger.info("Memory page: rose %s", "given" if out.get("ok") else "not taken")
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/game":
            out = (mood.game_hit(str(d.get("zone", ""))[:20], miss=bool(d.get("miss")))
                   if (unlocked and mood and hasattr(mood, "game_hit")) else {"ok": False})
            if out.get("bonus"):
                logger.info("Memory page: touch game won, bonus rose")
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/mood":
            out = mood.status() if (unlocked and mood) else {}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
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
                     code_phrase: str = "", rules=None, chat=None, voice=None,
                     mailer=None, google=None, inbox=None, mood=None, reminders=None,
                     diary=None, chat_new=None, reach=None, touch=None, hear=None, tls=None,
                     kopf=None):
    """`rules`: a function that returns Leyla's instructions without memory and without the
    code word; shown read only after the code word. `tls`: an ssl context; then this is the
    HTTPS copy of the page (app/tls.py) and the background jobs are not started a second time."""
    server = await asyncio.start_server(
        lambda r, w: _handle(store, sync, r, w, lamp, code_phrase, rules, chat, voice, mailer, google,
                          inbox, mood, reminders, diary, chat_new, reach, touch, hear, kopf),
        host, port, ssl=tls)
    logger.info("Memory page on port %d%s", port, " (HTTPS)" if tls else "")
    if tls is None and os.environ.get("LEYLA_MOBIL", "1") == "1":
        asyncio.get_running_loop().create_task(mobil_runner().run())
    return server
