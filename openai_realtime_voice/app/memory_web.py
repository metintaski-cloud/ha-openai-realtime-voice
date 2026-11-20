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
import re
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
CLIP_RE = re.compile(r"^/clips/([a-z0-9]{2,20})/([a-z]{2,20}[0-9]{0,2})\.(mp4|jpg|m4a)$")  # look/scene (2.99.4), musik/<mood>.m4a (2.103.0)


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
#rules{position:fixed;inset:0;z-index:20;overflow-y:auto;background:#000;padding-bottom:40px;display:none}
#rules .top{position:sticky;top:0;display:flex;align-items:center;gap:12px;padding:14px 16px;background:#000000ee;backdrop-filter:blur(6px)}
#rules .top button{width:auto;font-size:26px;line-height:1;padding:6px 14px;box-shadow:none;background:#1b2a6b;border:1px solid #3b82f688}
#rules p{margin:0 12px 8px;padding:12px 14px;background:#0d1750cc;border:1px solid #3b82f655;border-radius:12px;white-space:pre-wrap;word-break:break-word}
#rules ul{margin:8px 0 0;padding-left:20px;white-space:normal}#rules li{margin:6px 0}
#rules .dm{display:block;color:#9fb4ff;font-size:13px;margin-bottom:4px}#rules p.dy{position:relative;padding-left:50px;padding-right:52px}#rules .dyk{position:absolute;right:10px;top:8px;width:auto;padding:4px 8px;font-size:18px;background:none;border:1px solid #47556988;box-shadow:none;filter:grayscale(1);opacity:.55}#rules .dyk.on{filter:none;opacity:1;border-color:#fbbf24;background:#3a2a0a}#rules .dyk.err{border-color:#f87171}#rules p.dy.fest{border-color:#fbbf2499}#rules .dyc{position:absolute;left:14px;top:14px;width:24px;height:24px;accent-color:#d946ef}#rules p.dy.sel{border-color:#d946ef;background:#2a0f45cc}#dydel{position:sticky;bottom:12px;display:block;margin:12px auto;width:calc(100% - 24px)}#dydel:disabled{opacity:.5}#rules .lead{background:none;border:0;color:#9fb4ff;padding:4px 16px}
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
#stage::after{content:"";position:absolute;inset:0;pointer-events:none;z-index:2;background:linear-gradient(90deg,#000 1.5%,#0005 7%,#0002 35%,transparent 55%,transparent 93%,#000 98.5%),linear-gradient(#000 3%,transparent 7%,transparent 93%,#000 97%)}
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
#stage.vid .fig{opacity:0;animation:none}
#stage.low .fig{animation-duration:12s}#stage.low img{filter:saturate(.55) brightness(.75)}
#chat.oncall #stage{box-shadow:inset 0 0 40px #22d3ee55}#chat.oncall.speak #stage{box-shadow:inset 0 0 60px #d946efaa}
@keyframes lsway{0%,100%{transform:translateX(-6px) rotate(-.5deg)}50%{transform:translateX(6px) rotate(.5deg)}25%,75%{transform:scale(1.008)}}
#chat .chead{position:absolute;top:0;left:0;right:0;z-index:2;margin:0;padding:10px;display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
#chat .chead .cav,#chat .chead h2{display:none}
#chat .chead>div:nth-child(2){display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;flex:1}
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
#cin{display:grid;grid-template-columns:1fr auto 1fr;align-items:center}#cin #cnew{justify-self:start;margin:0;padding:9px 14px;font-size:14px}#cin #ckey{justify-self:end;width:48px;height:48px;padding:0;border-radius:50%;font-size:22px;background:#0008;backdrop-filter:blur(4px);border:1px solid #22d3ee66}#chat.typing #cin #ckey{border-color:#d946ef;box-shadow:0 0 12px #d946ef88}
#ctype{display:none;position:absolute;z-index:3;left:8px;right:8px;bottom:84px;gap:8px;align-items:stretch}#chat.typing #ctype{display:flex}#chat.typing #clog{bottom:146px}
#ctype textarea{flex:1;min-height:44px;max-height:110px;height:48px;font:inherit;color:#fff;background:#000a;backdrop-filter:blur(4px);border:1px solid var(--bl);border-radius:10px;padding:9px;resize:none}#ctype #csend{width:auto;padding:0 16px}
#cin #cmic{width:64px;height:64px;padding:0;border-radius:50%;font-size:28px;box-shadow:0 0 18px #d946ef88}
#clog{bottom:84px}#stage{top:0;bottom:0}body.chatfull{overflow:hidden;overscroll-behavior:none}body.chatfull #chat{position:fixed;inset:0;z-index:15;margin:0;border-radius:0;height:100vh!important;height:100dvh!important}body.chatfull #menu{position:fixed;top:56px;left:8px;right:8px;z-index:60;max-height:80vh;overflow-y:auto}#chat .chead .cav{display:none}#chat .chead #cmenu{width:auto;padding:7px 11px;font-size:16px;background:#000a;border:1px solid #22d3ee66}#chat #clog{pointer-events:none}#chat #clog>*{pointer-events:auto}#stage,#stage *{-webkit-touch-callout:none;-webkit-user-select:none;user-select:none;-webkit-tap-highlight-color:transparent}
</style></head><body>
<div id="splash"><div class="sp"><img src="/icon.png?v=5" alt=""><svg viewBox="0 0 200 200"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#a855f7"/><stop offset="1" stop-color="#d946ef"/></linearGradient></defs><circle class="trk" cx="100" cy="100" r="90"/><circle class="rg" cx="100" cy="100" r="90" pathLength="100"/></svg></div></div>
<header><button id="back">&#8249;</button><img id="micon" src="/icon.png?v=5" alt="Menü" title="Menü"><h1>Leyla Gedächtnis</h1></header><div id="menu"></div><div id="pulse" class="ok" title="Alles in Ordnung"><div class="tick" id="tick" style="display:none"><span></span></div><i class="spark" style="left:12%;top:30%;animation-delay:0s"></i><i class="spark" style="left:22%;top:68%;animation-delay:0.6s"></i><i class="spark" style="left:31%;top:22%;animation-delay:1.2s"></i><i class="spark" style="left:68%;top:74%;animation-delay:0.3s"></i><i class="spark" style="left:77%;top:28%;animation-delay:0.9s"></i><i class="spark" style="left:88%;top:60%;animation-delay:1.5s"></i><i class="spark" style="left:40%;top:80%;animation-delay:1.8s"></i><i class="spark" style="left:60%;top:18%;animation-delay:2.1s"></i><div class="beam"></div><svg viewBox="0 0 100 90"><defs><linearGradient id="hg" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#f43f5e"/></linearGradient><radialGradient id="hc"><stop offset="0" stop-color="#fff"/><stop offset=".4" stop-color="#7dd3fc"/><stop offset="1" stop-color="#7dd3fc" stop-opacity="0"/></radialGradient></defs><path d="M50 84C20 62 4 46 4 28C4 14 15 4 28 4C38 4 46 10 50 18C54 10 62 4 72 4C85 4 96 14 96 28C96 46 80 62 50 84Z" fill="#0b1650cc" stroke="url(#hg)" stroke-width="3.2" stroke-linejoin="round"/><path d="M14 40H34L40 28L47 54L53 34L58 44H86" fill="none" stroke="#e0f2fe" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/><circle cx="54" cy="38" r="9" fill="url(#hc)"/></svg></div><div id="chat"><div id="stage"><div class="fig"><img src="/leyla_body.jpg" alt=""></div><video id="svid" muted playsinline preload="auto"></video><video id="svid2" muted playsinline preload="auto"></video><div class="fog"><i class="fl"></i><i class="fr"></i><i class="ff"></i></div></div><div class="chead"><button id="cmenu" title="Menü">&#9776;</button><div class="cav"><img src="/leyla.jpg" alt=""><span id="mbadge"></span></div><div><h2>Chat mit Leyla</h2><div id="mlabel"></div><div id="ccount"></div></div><button id="crose" title="Rose schenken, einmal pro Woche">&#127801;</button><button id="cmus" title="Musik an oder aus">&#127925;</button><button id="clive" title="Live mit Leyla reden">&#128222; Live</button><div id="lpill"></div></div><div id="clog"></div><div id="ctype"><textarea id="ctext" placeholder="Schreib Leyla ..."></textarea><button id="csend">Senden</button></div><div id="cin"><button id="cnew" title="Neuen Chat beginnen">Neuer Chat</button><button id="cmic" title="Sprachnachricht">&#127908;</button><button id="ckey" title="Schreiben">&#9000;&#65039;</button></div></div><div id="live"><img src="/leyla.jpg" alt=""><div id="lstat">Verbinde ...</div><button id="lend">Auflegen</button></div><div id="rules"><div class="top"><button id="rback">&#8249;</button><h1>So ist Leyla</h1></div><div id="rtext"></div></div><div id="root"></div><div id="gmail" style="display:none"></div><div id="lamps" style="display:none"></div>
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
const SECICON={family:'👪',friends:'🤝',leyla:'💜',private:'🔒',mail:'✉',lamps:'💡',rules:'📜',diary:'📔',set:'⚙'};
function menuItems(){const it=[];const ls=(LASTD&&LASTD.lists)||[];
 for(const l of ls)it.push([l.kind,l.title,l.items.length]);
 if(CODE&&GM.shown&&GM.needs)it.push(['mail','Google verbinden','']);if(lampOn)it.push(['lamps','Lampenfarben','']);
 if(CODE){it.push(['diary','Tagebuch','']);it.push(['rules','So ist Leyla',''])};it.push(['set','Einstellungen','']);return it;}
function drawMenu(){const m=document.getElementById('menu');m.innerHTML='';m.style.display=menuOpen?'block':'none';document.getElementById('micon').classList.toggle('open',menuOpen);if(!menuOpen)return;
 for(const [k,t,n] of menuItems()){const b=document.createElement('button');b.className='mi';const i=document.createElement('i');i.textContent=SECICON[k]||'•';
  const sp=document.createElement('span');sp.textContent=t;const sm=document.createElement('small');sm.textContent=n===''?'':String(n);const ch=document.createElement('b');ch.textContent='›';
  b.append(i,sp,sm,ch);b.onclick=()=>openSec(k);m.appendChild(b);}}
document.getElementById('micon').onclick=()=>{menuOpen=!menuOpen;snd[menuOpen?'on':'off']();drawMenu();};
document.getElementById('cmenu').onclick=e=>{e.stopPropagation();document.getElementById('micon').onclick();};
function openSec(k){menuOpen=false;drawMenu();if(k==='rules'){openRules();return;}if(k==='diary'){openDiary();return;}
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
  if(m.role==='mail')return log.appendChild(mailCard(m,i));
  if(m.role==='trash')return log.appendChild(trashCard(m,i));
  if(m.role==='remind')return log.appendChild(remindCard(m,i));
  const d=document.createElement('div');d.className='m '+(m.role==='user'?'u':'l');d.textContent=m.text;
  if(m.aid&&AUDIO.has(m.aid)){const b=document.createElement('button');b.className='play';b.textContent='\u25B6';b.onclick=()=>playAudio(m.aid);d.appendChild(b);const sv=document.createElement('a');sv.className='play';sv.textContent='\u2B07';sv.title='Als Datei speichern';sv.href=AUDIO.get(m.aid);sv.download='leyla_'+m.aid+'.wav';d.appendChild(sv);}
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
async function chatSend(){const ta=document.getElementById('ctext'),msg=ta.value.trim();if(!msg)return;
 const history=CHAT.filter(m=>m.role==='user'||m.role==='leyla').map(m=>({role:m.role,text:m.text}));
 CHAT.push({role:'user',text:msg});ta.value='';chatSave();chatDraw(true);snd.on();
 let j=null;try{j=await (await post('/api/chat',{history,message:msg})).json();}catch(e){}
 chatAnswer(j);chatSave();chatDraw();snd.drop();}
const AUDIO=new Map();let REC=null,RECT=null;
function playAudio(id){try{const a=new Audio(AUDIO.get(id));a.onplay=()=>stageTalk(true);a.onended=a.onpause=()=>stageTalk(false);a.play().catch(()=>stageTalk(false));}catch(e){}}
let TALKING=false,DANCING=false;
const DANCE_N=4;
function stageScene(n){if(!CLIPS||!STM||!clipVars(n).length)return;if(n.startsWith('tanz'))stageDance(n);else stagePlay([n],clipFor(STM));}
function stageDance(name){const v=clipVars(name);if(!CLIPS||!STM||!v.length)return;const q=[];let pool=[];
 for(let i=0;i<DANCE_N&&(q.length<v.length||name==='tanz');i++){if(!pool.length)pool=v.filter(n=>n!==q[q.length-1]).sort(()=>Math.random()-0.5);q.push(pool.shift());}
 DANCING=true;const next=()=>{const n=q.shift();if(n)stageShow(n,false,next,true);else{DANCING=false;stageLoop(clipFor(STM));}};next();}
function stageTalk(on){on=!!on;if(on===TALKING||CLIPS===null||!STM)return;TALKING=on;
 const t=STM.low&&clipVars('sprichttraurig').length?'sprichttraurig':'spricht';
 if(!clipVars(t).length||DANCING)return;if(on)stageLoop(t);else stagePlay([],clipFor(STM));}
function moodShow(st){if(!st||!st.mood)return;const c=document.getElementById('chat'),b=document.getElementById('mbadge');
 c.classList.toggle('low',!!st.low);c.classList.toggle('good',!st.low);document.getElementById('pulse').dataset.mood=st.low?'low':'good';b.style.display='flex';b.textContent=st.low?'🖤':'❤️';
 document.getElementById('mlabel').textContent=(st.low?'🖤 ':'❤️ ')+st.label;LASTST=st;const rb=document.getElementById('crose');if(rb)rb.classList.toggle('off',st.rose!=='ready');stageMood(st);}
let CLIPS=null,LASTST=null,STM=null;
let OUTFIT='';
async function clipsLoad(){let outs={};try{outs=(await (await fetch('/clips.json')).json()).outfits||{};}catch(e){}
 const names=Object.keys(outs);let last='';try{last=localStorage.getItem('loutfit')||'';}catch(e){}
 const cand=names.length>1?names.filter(n=>n!==last):names;OUTFIT=cand.length?cand[Math.floor(Math.random()*cand.length)]:'';
 try{if(OUTFIT)localStorage.setItem('loutfit',OUTFIT);}catch(e){}
 CLIPS=OUTFIT?outs[OUTFIT].clips:[];if(OUTFIT&&outs[OUTFIT].body)document.querySelector('#stage .fig img').src='/clips/'+OUTFIT+'/body.jpg';
 if(LASTST)stageMood(LASTST);}
function clipVars(b){return CLIPS.filter(n=>n.replace(/[0-9]+$/,'')===b);}
function clipFor(st){const lv=st.low&&st.level&&st.mood!=='eifersuechtig'?'traurig'+st.level:'';if(lv&&clipVars(lv).length)return lv;if(clipVars(st.mood).length)return st.mood;
 const g=(st.low?['traurigleicht','traurig']:['gluecklich']).filter(n=>clipVars(n).length);return g.length?g[0]:null;}
let SV=0,STOK=0,CONT=false;const PRELOAD_S=3;
function stageShow(name,loop,done,snd){const s=document.getElementById('stage'),vs=[document.getElementById('svid'),document.getElementById('svid2')],a=vs[SV],b=vs[1-SV],tok=++STOK,cont=CONT;CONT=false;
 if(!name){s.classList.remove('vid');vs.forEach(v=>{v.classList.remove('on');setTimeout(()=>{if(tok===STOK){v.pause();v.removeAttribute('src');v.load();}},600);});return;}
 if(loop&&a.loop&&a.classList.contains('on')&&a.src.endsWith('/'+name+'.mp4'))return;
 b.onended=null;b.ontimeupdate=null;b.loop=!!loop;b.muted=!snd||document.getElementById('chat').classList.contains('oncall');b.volume=.7;b.oncanplay=()=>{b.oncanplay=null;if(tok!==STOK)return;
  if(cont&&a.classList.contains('on')&&a.duration&&!a.ended){const w=(a.duration-0.8-a.currentTime)*1000;if(w>30){setTimeout(()=>{if(tok===STOK)go();},w);return;}}go();};
 const go=()=>{b.currentTime=0;b.play().catch(()=>{b.muted=true;b.play().catch(()=>{});});b.style.zIndex=1;a.style.zIndex=0;b.classList.add('on');s.classList.add('vid');SV=1-SV;
  setTimeout(()=>{if(tok===STOK)a.classList.remove('on');},850);setTimeout(()=>{if(!a.classList.contains('on'))a.pause();},1000);let fired=false;const fire=()=>{if(fired||tok!==STOK||!done)return;fired=true;CONT=true;done();CONT=false;};
  b.ontimeupdate=()=>{if(b.duration&&b.currentTime>b.duration-PRELOAD_S)fire();};b.onended=fire;};
 b.src='/clips/'+OUTFIT+'/'+name+'.mp4';b.load();}
function stageLoop(b){DANCING=false;if(!b)return stageShow(null);const v=clipVars(b),nx=()=>stageNext(b);if(v.length<2)return stageShow(v[0],false,nx);
 const cur=document.getElementById(SV?'svid2':'svid').src.split('/').pop().replace('.mp4','');const o=v.filter(n=>n!==cur);stageShow(o[Math.floor(Math.random()*o.length)],false,nx);}
const SPECIAL=[],SPECIAL_P=0;  // since 2.111.2 no dance by herself, only when Metin asks (Metin)
const KNIET_P=0.12,EXTRA_P=0.25;
function stageNext(b){const sp=STM&&!STM.low?SPECIAL.filter(n=>clipVars(n).length):[];if(sp.length&&Math.random()<SPECIAL_P)stagePlay([sp[Math.floor(Math.random()*sp.length)]],b);
 else if(STM&&!STM.low&&clipVars('gluecklichextra').length&&Math.random()<EXTRA_P)stagePlay(['gluecklichextra'],b);
 else if(STM&&STM.low&&STM.level==='schwer'&&clipVars('setzen').length&&Math.random()<KNIET_P)stagePlay(['setzen'],b);else stageLoop(b);}
function stagePlay(once,loop){DANCING=false;const q=once.map(n=>{const v=clipVars(n);return v.length?v[Math.floor(Math.random()*v.length)]:null;}).filter(Boolean);const next=()=>{const n=q.shift();if(n)stageShow(n,false,next,true);else stageLoop(loop);};next();}
function stageMood(st){if(CLIPS===null)return;document.getElementById('stage').classList.toggle('low',!!st.low);let once=[];const o=STM;
 if(!o)once=['begruessung'];if(o){if(o.low&&!st.low)once=['uebergang','kuss'];else if(st.low&&o.low&&(st.cheer||0)>(o.cheer||0))once=['trost'];}
 const changed=!o||once.length||o.mood!==st.mood||o.level!==st.level;STM=st;if(changed)stagePlay(once,clipFor(st));}
clipsLoad();
let MUSIC=[],BGM=null,BGMN='',MUSON=true;try{MUSON=localStorage.getItem('lmusic')!=='0';}catch(e){}
function musDraw(){const b=document.getElementById('cmus');b.innerHTML=MUSON?'&#127925;':'&#128263;';b.classList.toggle('off',!MUSON);}
musDraw();document.getElementById('cmus').onclick=e=>{e.stopPropagation();MUSON=!MUSON;try{localStorage.setItem('lmusic',MUSON?'1':'0');}catch(e){}musDraw();bgmTick();};
function bgmTick(){const c=document.getElementById('chat');let n='';if(STM&&MUSIC.length){n=MUSIC.includes(STM.mood)?STM.mood:(STM.low?'traurig':'gut');if(!MUSIC.includes(n))n='';}
 const on=n&&MUSON&&soundOn&&c.style.display==='block'&&!c.classList.contains('oncall')&&!document.hidden;
 if(!on){if(BGM)BGM.pause();return;}
 if(n!==BGMN){if(BGM)BGM.pause();BGM=new Audio('/clips/musik/'+n+'.m4a');BGM.loop=true;BGMN=n;}
 BGM.volume=TALKING?.05:.22;if(BGM.paused)BGM.play().catch(()=>{});}
fetch('/clips.json').then(r=>r.json()).then(o=>{MUSIC=o.music||[];bgmTick();}).catch(()=>{});
setInterval(bgmTick,1000);document.addEventListener('pointerdown',bgmTick);document.addEventListener('visibilitychange',bgmTick);
function stageFit(){const ch=document.getElementById('chat');if(ch.style.display!=='block')return;const vh=(window.visualViewport?visualViewport.height:innerHeight);ch.style.height=Math.max(420,vh-12)+'px';}
function stageView(){stageFit();const ch=document.getElementById('chat');if(ch.style.display==='block')window.scrollTo({top:ch.getBoundingClientRect().top+scrollY-6,behavior:'smooth'});}
window.addEventListener('resize',stageFit);if(window.visualViewport)visualViewport.addEventListener('resize',stageView);
document.getElementById('ctext').addEventListener('focus',()=>setTimeout(stageView,300));
document.getElementById('stage').addEventListener('contextmenu',e=>e.preventDefault());
const ZONES=[['gesicht',.02,.17],['brust',.17,.32],['bauch',.32,.44],['po',.44,.58]],ZX=[.30,.72],ZLAST={};
function zoneAt(ev){const st=document.getElementById('stage').getBoundingClientRect(),ar=1176/1764;let w=st.width,h=w/ar;if(h<st.height){h=st.height;w=h*ar;}
 const x=(ev.clientX-st.left-(st.width-w)/2)/w,y=(ev.clientY-st.top-(st.height-h)/2)/h;if(x<ZX[0]||x>ZX[1])return null;const z=ZONES.find(z=>y>=z[1]&&y<z[2]);return z?z[0]:null;}
document.getElementById('stage').onclick=ev=>{if(!CLIPS||!STM||STM.low)return;const z=zoneAt(ev);if(!z)return;const v=clipVars(z);if(!v.length)return;
 const o=v.length>1?v.filter(n=>n!==ZLAST[z]):v,n=o[Math.floor(Math.random()*o.length)];ZLAST[z]=n;DANCING=false;stageShow(n,false,()=>stageLoop(clipFor(STM)),true);};

document.getElementById('crose').onclick=async()=>{const st=LASTST||{};
 if(st.rose==='used'){CHAT.push({role:'info',text:'🌹 Diese Woche hast du ihr schon eine Rose geschenkt.'});chatDraw();return;}
 if(st.rose==='blocked'){CHAT.push({role:'info',text:'🌹 Sie nimmt gerade keine Rose an.'});chatDraw();return;}
 let j=null;try{j=await (await post('/api/rose',{})).json();}catch(e){}
 if(!j||!j.ok){if(j&&j.mood)moodShow(j.mood);CHAT.push({role:'info',text:j&&j.rose==='blocked'?'🌹 Sie nimmt gerade keine Rose an.':'🌹 Gerade nicht möglich.'});chatDraw();return;}
 moodShow(j.mood);const sc=clipVars(j.scene).length?j.scene:(j.scene==='rosefroh'?'kuss':'');if(sc)stageScene(sc);
 const ta=document.getElementById('ctext');ta.value='🌹 Ich schenke dir eine Rose.';chatSend();};
async function moodLoad(){try{moodShow(await (await post('/api/mood',{})).json());}catch(e){}}
setInterval(()=>{if(CODE&&document.getElementById('chat').style.display==='block'){moodLoad();remindPending();}},60000);
function chatAnswer(j){if(j&&j.silent){CHAT.push({role:'info',text:'🤐 Leyla antwortet gerade nicht.'});if(j.mood)moodShow(j.mood);return null;}
 if(!j||j.error||!j.reply){CHAT.push({role:'leyla',text:'Hmm, gerade komme ich nicht durch. Versuch es gleich nochmal.'});return null;}
 const m={role:'leyla',text:j.reply};if(j.audio){m.aid='a'+Date.now();AUDIO.set(m.aid,'data:audio/wav;base64,'+j.audio);}CHAT.push(m);
 (j.lights||[]).forEach(t=>CHAT.push({role:'info',text:(/^(✉|📣)/.test(t)?'':'💡 ')+t}));if(j.mood)moodShow(j.mood);if(j.scene)stageScene(j.scene);if(j.email)CHAT.push({role:'mail',e:j.email});if(j.trash)CHAT.push({role:'trash',t:j.trash});(j.proposals||[]).forEach(p=>CHAT.push({role:'prop',p}));return m.aid||null;}
function blobB64(b){return new Promise(r=>{const f=new FileReader();f.onload=()=>r(String(f.result).split(',')[1]||'');f.readAsDataURL(b);});}
async function voiceSend(blob,mime){const history=CHAT.filter(m=>m.role==='user'||m.role==='leyla').map(m=>({role:m.role,text:m.text}));
 const u={role:'user',text:'🎤 ...'};CHAT.push(u);chatSave();chatDraw(true);snd.on();
 let j=null;try{j=await (await post('/api/chat_voice',{history,audio:await blobB64(blob),mime})).json();}catch(e){}
 if(j&&j.heard){u.text='🎤 '+j.heard;}else{u.text='🎤 (nicht verstanden)';}
 const aid=(j&&j.heard)?chatAnswer(j):null;chatSave();chatDraw();snd.drop();if(aid)playAudio(aid);}
document.getElementById('cmic').onclick=async()=>{const b=document.getElementById('cmic');
 if(REC){REC.stop();return;}
 if(!navigator.mediaDevices||!window.MediaRecorder){CHAT.push({role:'info',text:'Das Mikrofon ist auf dieser Seite nicht frei (Chrome Einstellung fehlt).'});chatSave();chatDraw();return;}
 let st;try{st=await navigator.mediaDevices.getUserMedia({audio:true});}catch(e){CHAT.push({role:'info',text:'Kein Zugriff aufs Mikrofon.'});chatSave();chatDraw();return;}
 const parts=[];REC=new MediaRecorder(st);REC.ondataavailable=e=>{if(e.data.size)parts.push(e.data);};
 REC.onstop=()=>{st.getTracks().forEach(t=>t.stop());clearTimeout(RECT);const mime=REC.mimeType||'audio/webm';REC=null;b.classList.remove('rec');b.innerHTML='&#127908;';
  const blob=new Blob(parts,{type:mime});if(blob.size>2000)voiceSend(blob,mime);};
 REC.start();b.classList.add('rec');b.innerHTML='&#9632;';snd.on();RECT=setTimeout(()=>{if(REC)REC.stop();},60000);};
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
async function mailPending(){remindPending();let j=null;try{j=await (await post('/api/mail/pending',{})).json();}catch(_){}
 if(!j||!j.ok)return;let added=false;(j.drafts||[]).forEach(e=>{if(!CHAT.some(m=>m.role==='mail'&&m.e.id===e.id)){CHAT.push({role:'mail',e});added=true;}});
 (j.trash||[]).forEach(t=>{if(!CHAT.some(m=>m.role==='trash'&&m.t.id===t.id)){CHAT.push({role:'trash',t});added=true;}});
 if(added){chatSave();chatDraw();}}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&CODE)mailPending();});
let LIVE=null;
function liveStat(t,sp){document.getElementById('lpill').textContent=t;document.getElementById('chat').classList.toggle('speak',!!sp);stageTalk(sp);}
function liveStop(){const L=LIVE;LIVE=null;const c=document.getElementById('chat');c.classList.remove('oncall','speak');stageTalk(false);document.getElementById('clive').innerHTML='&#128222; Live';if(!L)return;
 try{L.ws.close();}catch(e){}try{L.proc.disconnect();L.src.disconnect();}catch(e){}try{L.st.getTracks().forEach(t=>t.stop());}catch(e){}try{L.ctx.close();}catch(e){}}
async function liveStart(){if(LIVE)return;const box=document.getElementById('live');
 if(!navigator.mediaDevices){CHAT.push({role:'info',text:'Das Mikrofon ist auf dieser Seite nicht frei (Chrome Einstellung fehlt).'});chatSave();chatDraw();return;}
 let st;try{st=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});}catch(e){CHAT.push({role:'info',text:'Kein Zugriff aufs Mikrofon.'});chatSave();chatDraw();return;}
 document.getElementById('chat').classList.add('oncall');document.getElementById('clive').textContent='Auflegen';stageView();liveStat('Verbinde ...');
 const ctx=new (window.AudioContext||window.webkitAudioContext)();const ratio=ctx.sampleRate/24000;
 const ws=new WebSocket('ws://'+location.hostname+':8080/app');ws.binaryType='arraybuffer';
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
document.getElementById('cnew').onclick=chatNew;
document.getElementById('ckey').onclick=()=>{const c=document.getElementById('chat'),on=c.classList.toggle('typing');if(on)setTimeout(()=>document.getElementById('ctext').focus(),50);};
let FRESH=new Set(),TICK='';
function ticker(list){const t=(list||[]).join('   \u2726   ');if(t===TICK)return;TICK=t;const box=document.getElementById('tick'),sp=box.firstChild;
 box.style.display=t?'block':'none';sp.textContent=t;sp.style.animationDuration=Math.max(10,t.length*0.16)+'s';}
function render(d){FRESH=new Set(d.fresh||[]);ticker(d.ticker);const root=document.getElementById('root');root.innerHTML='';const all=new Set();
 const back=document.getElementById('back'),h1=document.querySelector('h1');
 let found=null;
 if(view){const l=d.lists.find(x=>x.kind===view.kind);const t=l&&l.items.find(x=>parts(x).head===view.head);if(t){found={l,t};}else view=null;}
 LASTD=d;const kinds=d.lists.map(l=>l.kind);if(sec&&!SECNAME[sec])sec=null;if(sec==='private'&&!kinds.includes('private'))sec=null;if((sec==='mail'||sec==='private')&&!CODE)sec=null;
 const home=!view&&!sec,isList=!!view||kinds.includes(sec);
 back.style.display=home?'none':'block';document.getElementById('micon').style.display=home?'':'none';document.getElementById('pulse').style.display=home?'block':'none';const ch=document.getElementById('chat'),showChat=!!CODE&&home;document.body.classList.toggle('chatfull',showChat);if(showChat&&ch.style.display!=='block'){ch.style.display='block';chatDraw();mailPending();gmailLoad();moodLoad();}else if(!showChat)ch.style.display='none';document.getElementById('stage').style.display=showChat?'block':'none';if(showChat){setTimeout(stageFit,0);setTimeout(stageView,2600);}document.getElementById('gmail').style.display=(sec==='mail'&&GM.shown&&!view)?'block':'none';document.getElementById('lamps').style.display=(sec==='lamps'&&lampOn&&!view)?'block':'none';document.getElementById('bar').style.display=isList?'':'none';h1.textContent=view?title(view.head):sec?SECNAME[sec]:'Leyla Gedächtnis';if(menuOpen)drawMenu();
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
 if(!j.items.length){const e=document.createElement('p');e.textContent='Noch keine Einträge.';box.appendChild(e);}
 const dsel=new Set();const db=document.createElement('button');db.id='dydel';db.disabled=true;db.textContent='Markierte löschen';
 const dup=()=>{db.disabled=!dsel.size;db.textContent=dsel.size?dsel.size+' markierte löschen':'Markierte löschen';};
 db.onclick=async()=>{if(!dsel.size)return;let r={ok:false};try{r=await (await post('/api/diary/delete',{ids:[...dsel]})).json();}catch(_){}if(r.ok){snd.del();openDiaryRefresh();}};
 for(const x of j.items){const p=document.createElement('p');p.className='dy';const cb=document.createElement('input');cb.type='checkbox';cb.className='dyc';
  cb.onchange=()=>{if(cb.checked)dsel.add(x.t);else dsel.delete(x.t);p.classList.toggle('sel',cb.checked);snd[cb.checked?'on':'off']();dup();};p.appendChild(cb);
  const k=document.createElement('button');k.className='dyk'+(x.fest?' on':'');k.textContent='🔑';k.title=x.fest?'Festgehalten, tippen zum Lösen':'Für immer festhalten';
  k.onclick=async()=>{let r={ok:false};try{r=await (await post('/api/diary/pin',{id:x.t})).json();}catch(_){}if(r.ok){snd[r.fest?'on':'off']();openDiary();}else if(r.error){k.title=r.error;k.classList.add('err');}};p.appendChild(k);if(x.fest)p.classList.add('fest');const m=document.createElement('span');m.className='dm';
  const d=new Date(x.t*1000);m.textContent=d.toLocaleDateString('de-DE',{weekday:'short',day:'2-digit',month:'2-digit'})+' '+d.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'})+'  ·  '+(x.src==='chat'?'💬 Chat':'🏠 Zuhause')+'  ·  '+(x.who||'unbekannt')+(x.privat?'  ·  🔒':'');
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
function lmsg(t){document.getElementById('lmsg').textContent=t;}
const LTXT={ok:'',busy:'Leyla spricht gerade, bitte danach testen.',off:'Lampenshow ist aus.',failed:'Eine Lampe antwortet nicht, Leyla versucht es weiter.',error:'Hat nicht geklappt.'};
async function lampPost(path,body){try{const r=await fetch(path,{method:'POST',body:JSON.stringify(body||{})});return await r.json();}catch(e){return {result:'error'};}}
async function loadLamps(){let d;try{d=await (await fetch('/api/lamp')).json();}catch(e){return;}
 lampOn=!!d.available;const box=document.getElementById('lamps');box.innerHTML='';if(!lampOn){box.style.display='none';return;}
 box.style.display=(sec==='lamps'&&!view)?'block':'none';
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
        if clips or body:
            out[look] = {"clips": clips, "body": body}
    return out


def list_music() -> list:
    """Background music of the stage (2.103.0): clips/musik/<mood>.m4a, or gut.m4a and traurig.m4a for
    every good or low mood."""
    try:
        return sorted(f[:-4] for f in os.listdir(os.path.join(clips_dir(), "musik"))
                      if f.endswith(".m4a") and CLIP_RE.match(f"/clips/musik/{f}"))
    except OSError:
        return []


async def _send_clip(writer, look: str, name: str, ext: str, lines: list) -> None:
    """One clip or still of a look, with byte ranges, because Chrome asks for parts of a video."""
    fn = os.path.join(clips_dir(), look, f"{name}.{ext}")
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
    ctype = {"mp4": "video/mp4", "m4a": "audio/mp4"}.get(ext, "image/jpeg")
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


async def _handle(store, sync, reader, writer, lamp=None, code_phrase: str = "", rules=None,
                  chat=None, voice=None, mailer=None, google=None, inbox=None,
                  mood=None, reminders=None, diary=None, chat_new=None) -> None:
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
        elif method == "GET" and path == "/leyla_body.jpg":
            with open(BODY_PATH, "rb") as f:
                raw = f.read()
            writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: {len(raw)}\r\n"
                          "Cache-Control: max-age=86400\r\nConnection: close\r\n\r\n").encode() + raw)
            await writer.drain()
        elif method == "GET" and path == "/clips.json":
            await _respond(writer, "200 OK", "application/json", json.dumps({"outfits": list_outfits(), "music": list_music()}))
        elif method == "GET" and CLIP_RE.match(path):
            m = CLIP_RE.match(path)
            await _send_clip(writer, m.group(1), m.group(2), m.group(3), lines)
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
        elif method == "POST" and path == "/api/chat_voice":
            out = None
            if unlocked and voice:
                try:
                    out = await voice(d.get("history"), d.get("audio"), d.get("mime"))
                except Exception as e:
                    logger.warning("Voice message failed: %s", e)
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
            out = {"tage": metrics.wake_stats(metrics.load()), "aufnahmen": files}
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
                     "fest": bool(e.get("fest"))}
                    for e in sorted(diary.entries(), key=lambda x: -x.get("t", 0))]}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path.startswith("/api/remind/"):
            out = {"ok": False}
            if unlocked and reminders and reminders.available:
                if path == "/api/remind/pending":
                    out = {"ok": True, "items": await reminders.pending()}
                elif path == "/api/remind/ok":
                    out = {"ok": reminders.ack(str(d.get("id", ""))[:300]) > 0}
            await _respond(writer, "200 OK", "application/json", json.dumps(out, ensure_ascii=False))
        elif method == "POST" and path == "/api/rose":
            out = mood.give_rose() if (unlocked and mood and hasattr(mood, "give_rose")) else {"ok": False}
            if out.get("ok") or out.get("rose") == "blocked":
                logger.info("Memory page: rose %s", "given" if out.get("ok") else "not taken")
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
                     diary=None, chat_new=None):
    """`rules`: a function that returns Leyla's instructions without memory and without the
    code word; shown read only after the code word."""
    server = await asyncio.start_server(
        lambda r, w: _handle(store, sync, r, w, lamp, code_phrase, rules, chat, voice, mailer, google,
                          inbox, mood, reminders, diary, chat_new), host, port)
    logger.info("Memory page on port %d", port)
    return server
