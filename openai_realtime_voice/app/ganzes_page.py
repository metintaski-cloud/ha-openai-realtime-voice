"""The page /ganzes: one outfit as a whole (2.163.0).

Metin, 24 Nov 2026 (23:58): in the clip tester he sees one clip at a time; he wants to see
the loops of an outfit one after the other (clip + clip + clip) and the matching touch clips
for face, chest and bottom in between, the way the app plays them. This page does that with
the same hand over as the stage of the app (memory_web.stageShow): the next loop clip is
loaded PRELOAD_S before the end and fades in 0.25 s before it, a touch clip starts at once
with a 0.35 s fade and with its sound, and stored tempo, tempo curve and cut marks apply.
The loop buttons do not jump to a loop: a tap takes a loop out of the round or back in
(Metin, 00:41: he wants to let loop 1 and loop 2 run, not pick one), one always stays.
The page is grouped (Metin, 00:10: "alles übersichtlich und zugeordnet"): Kleid, Schleifen,
Berührung, then everything that can be set for the running clip (tempo in steps of one
hundredth, begin and end, sound off) and the reset for all clips. The clip never leaves the
view (Metin, 00:29: scrolling down to the settings he lost sight of it, all of it must lie on
the left in the clip): the stage fills the screen like in the app, the groups are a see
through column on its left that scrolls by itself, ☰ hides it, and the picture of the sound
is a strip over the full width at the bottom. Above it, always there (Metin, 00:34): pause,
one picture back or on, and a slider to drag through the clip; using one of them keeps only
this clip on the stage (`solo`) until "weiter mit den Schleifen". Nothing here changes a
clip file: tempo, cut and "sound off" are values the app reads from /clips.json.

The script is a raw string: keep it free of backslashes and check it with node --check
(tests/test_ganzes.py does) before every commit.

The reset point (Metin, 25 Nov 2026, 00:02: "und für alle ein Reset Knopf, wie sie jetzt
sind"): the tempo, the tempo curve and the cut marks of every clip as they were at one moment,
kept in /data/tempo_stand.json. It is taken when this version first starts, so it holds what
he had before he began to try things out. "Reset" puts all three back for all clips at once;
"Stand neu merken" makes the present values the new reset point. Clip files are never touched.

Sound (Metin, 00:09: "wo ich Ton löschen oder schneiden kann", 00:13: a piece that is cut
out of the sound must be replaced by no sound of the same length, the time line stays): in
/data/clip_ton.json, `aus` lists the clips whose whole sound is off and `stumm` holds, per
clip, the stretches [from, to] in seconds that are silent. Nothing is cut out and nothing
moves: the stage of the app plays the clip as it is and turns the volume to zero for those
stretches (`m` and `ms` per look in /clips.json, `MUTE` and `STUMM` in the page). The file
keeps its sound, so everything can be undone. Both are part of the reset point.
Quieter or louder (Metin, 00:39): `laut` holds a factor per clip, 1 is the normal loudness of
the stage (volume 0.7), from 0.1 up to LAUT_MAX (1.4, which is the full volume of the phone);
`mv` per look in /clips.json, `VOL` in the page.

The picture of the sound (Metin, 00:16: "ich muss Ton visuell lang ziehen und schneiden
können"): `wave(path)` lets ffmpeg decode only the sound track of a clip (mono, 4000 Hz) and
returns its loudness in WAVE_BUCKETS steps (GET /api/wave?clip=look/name). The page draws it,
he drags a finger over the stretch that shall be silent, the silent stretches show in red and
a line shows where the clip is. The phone never has to load the 20 MB file for that."""
import array
import asyncio
import json
import math
import os
import re
import time
from typing import Optional

WAVE_BUCKETS = 400
WAVE_RATE = 4000
_WAVES: dict = {}  # (path, file time) -> result, a clip is decoded once


async def wave(path: str) -> dict:
    """{"ok", "dauer": seconds of sound, "peaks": loudness 0 to 1 per step} of a clip's sound track;
    no peaks when the clip has no sound."""
    try:
        key = (path, int(os.path.getmtime(path)))
    except OSError:
        return {"ok": False}
    if key in _WAVES:
        return _WAVES[key]
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-i", path, "-vn", "-map", "0:a:0?", "-ac", "1", "-ar", str(WAVE_RATE),
            "-f", "s16le", "-", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        raw, _ = await asyncio.wait_for(proc.communicate(), 40)
    except Exception:
        return {"ok": False}
    count = len(raw) // 2
    out = {"ok": True, "dauer": round(count / WAVE_RATE, 2), "peaks": []}
    if count:
        samples = array.array("h", raw[:count * 2])
        size = max(1, math.ceil(count / WAVE_BUCKETS))
        peaks = [max(abs(x) for x in samples[i:i + size]) for i in range(0, count, size)]
        top = max(max(peaks), 3000)  # a nearly silent track shall look nearly silent
        out["peaks"] = [round(p / top, 3) for p in peaks]
    if len(_WAVES) > 200:
        _WAVES.clear()
    _WAVES[key] = out
    return out

STAND_PATH = "/data/tempo_stand.json"
TON_PATH = "/data/clip_ton.json"
NAME_RE = re.compile(r"^[a-z0-9]{2,20}/[a-z]{2,30}[0-9]{0,2}$")  # look/clip, as memory_web.CLIP_RE


MAX_STUMM = 20  # silent stretches of one clip
LAUT_MIN, LAUT_MAX = 0.1, 1.4  # loudness factor of a clip: 1 = as always, 1.4 = all the phone gives


def _stretches(segs) -> list:
    """Clean silent stretches: [from, to] in seconds, sorted, overlapping ones joined."""
    clean = []
    for seg in segs if isinstance(segs, list) else []:
        try:
            a, b = round(float(seg[0]), 2), round(float(seg[1]), 2)
        except (TypeError, ValueError, IndexError):
            continue
        if b - a >= 0.02 and a >= 0 and b <= 600:
            clean.append([a, b])
    clean.sort()
    out = []
    for a, b in clean:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out[:MAX_STUMM]


def ton_read() -> dict:
    """{"aus": [clips whose whole sound is off], "stumm": {clip: [[from, to], ...]}} (look/clip names)."""
    try:
        with open(os.environ.get("LEYLA_TON", TON_PATH), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d = d if isinstance(d, dict) else {}
    off = d.get("aus") if isinstance(d.get("aus"), list) else []
    quiet = d.get("stumm") if isinstance(d.get("stumm"), dict) else {}
    out = {"aus": sorted({n for n in off if isinstance(n, str) and NAME_RE.match(n)}), "stumm": {}, "laut": {}}
    for name in sorted(quiet):
        segs = _stretches(quiet[name])
        if isinstance(name, str) and NAME_RE.match(name) and segs:
            out["stumm"][name] = segs
    loud = d.get("laut") if isinstance(d.get("laut"), dict) else {}
    for name in sorted(loud):
        f = loud[name]
        if (isinstance(name, str) and NAME_RE.match(name) and isinstance(f, (int, float))
                and not isinstance(f, bool) and LAUT_MIN <= f <= LAUT_MAX and round(f, 2) != 1.0):
            out["laut"][name] = round(float(f), 2)
    return out


def ton_set(name: str, off: bool) -> bool:
    """Switch the whole sound of one clip off (True) or on again. False for a name that is no clip name."""
    if not NAME_RE.match(name or ""):
        return False
    d = ton_read()
    names = set(d["aus"])
    (names.add if off else names.discard)(name)
    _write(os.environ.get("LEYLA_TON", TON_PATH), dict(d, aus=sorted(names)))
    return True


def ton_laut(name: str, factor) -> bool:
    """Make one clip quieter or louder: a factor from LAUT_MIN to LAUT_MAX, 1 is the normal loudness
    (and removes the entry). False for a name that is no clip name or a factor out of range."""
    if (not NAME_RE.match(name or "") or not isinstance(factor, (int, float)) or isinstance(factor, bool)
            or not LAUT_MIN <= factor <= LAUT_MAX):
        return False
    d = ton_read()
    if round(float(factor), 2) == 1.0:
        d["laut"].pop(name, None)
    else:
        d["laut"][name] = round(float(factor), 2)
    _write(os.environ.get("LEYLA_TON", TON_PATH), d)
    return True


def ton_stumm(name: str, segs) -> bool:
    """Set the silent stretches of one clip ([] removes them). The clip keeps its length:
    the stretch is played without sound, nothing is cut out."""
    if not NAME_RE.match(name or "") or not isinstance(segs, list):
        return False
    d = ton_read()
    clean = _stretches(segs)
    if clean:
        d["stumm"][name] = clean
    else:
        d["stumm"].pop(name, None)
    _write(os.environ.get("LEYLA_TON", TON_PATH), d)
    return True


def _files() -> dict:
    from app import memory_web as mw
    return {"tempo": os.environ.get("LEYLA_TEMPO", mw.TEMPO_PATH),
            "kurve": os.environ.get("LEYLA_KURVE", mw.KURVE_PATH),
            "schnitt": os.environ.get("LEYLA_SCHNITT", mw.SCHNITT_PATH),
            "ton": os.environ.get("LEYLA_TON", TON_PATH),
            "vorlauf": os.environ.get("LEYLA_VORLAUF", mw.VORLAUF_PATH)}


def _now() -> dict:
    from app import memory_web as mw
    return {"tempo": mw._tempo_read(), "kurve": mw._kurve_read(), "schnitt": mw._schnitt_read(),
            "ton": ton_read(), "vorlauf": mw._vorlauf_read()}


def _write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _rates(items) -> dict:
    """The tempo each clip really has: the newest entry counts, 1 is the same as none."""
    out = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("rate"), (int, float)):
            out[str(item.get("name"))] = round(float(item["rate"]), 2)
    return {n: r for n, r in out.items() if r != 1.0}


def _changed(a: dict, b: dict) -> list:
    """Names of the clips whose tempo, curve, cut or sound differs between two states."""
    ta, tb = a.get("ton") or {}, b.get("ton") or {}
    names = set(ta.get("aus") or []) ^ set(tb.get("aus") or [])
    for key in ("stumm", "laut"):
        qa, qb = ta.get(key) or {}, tb.get(key) or {}
        names |= {n for n in set(qa) | set(qb) if qa.get(n) != qb.get(n)}
    for x, y in ((_rates(a.get("tempo")), _rates(b.get("tempo"))),
                 (a.get("kurve") or {}, b.get("kurve") or {}),
                 (a.get("schnitt") or {}, b.get("schnitt") or {}),
                 (a.get("vorlauf") or {}, b.get("vorlauf") or {})):
        names |= {n for n in set(x) | set(y) if x.get(n) != y.get(n)}
    return sorted(names)


def stand_read() -> Optional[dict]:
    try:
        with open(os.environ.get("LEYLA_STAND", STAND_PATH), encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return None
    ok = (isinstance(d, dict) and isinstance(d.get("t"), (int, float)) and isinstance(d.get("tempo"), list)
          and isinstance(d.get("kurve"), dict) and isinstance(d.get("schnitt"), dict)
          and isinstance(d.get("ton", {}), dict))
    lead = d.get("vorlauf") if ok and isinstance(d.get("vorlauf"), dict) else {}  # none before 2.166.0
    return dict(d, ton=d.get("ton") or {"aus": [], "stumm": {}, "laut": {}}, vorlauf=lead) if ok else None


def stand_save() -> dict:
    """Make the values of this moment the reset point."""
    _write(os.environ.get("LEYLA_STAND", STAND_PATH), {"t": int(time.time()), **_now()})
    return stand_info()


def stand_info() -> dict:
    """The reset point in numbers (taken now when there is none yet) and how many clips differ from it."""
    d = stand_read()
    if d is None:
        _write(os.environ.get("LEYLA_STAND", STAND_PATH), {"t": int(time.time()), **_now()})
        d = stand_read()
    return {"ok": True, "t": int(d["t"]), "wann": time.strftime("%d.%m. %H:%M", time.localtime(d["t"])),
            "tempo": len(_rates(d["tempo"])), "kurve": len(d["kurve"]), "schnitt": len(d["schnitt"]),
            "ton": len(set(d["ton"].get("aus") or []) | set(d["ton"].get("stumm") or {})
                       | set(d["ton"].get("laut") or {})),
            "geaendert": _changed(d, _now())}


def stand_restore() -> dict:
    """Put tempo, curve, cut and sound of every clip back to the reset point."""
    d = stand_read()
    if d is None:
        return {"ok": False}
    back = _changed(d, _now())
    files = _files()
    for key in ("tempo", "kurve", "schnitt", "ton", "vorlauf"):
        _write(files[key], d[key])
    return {**stand_info(), "zurueck": back}


PAGE = r"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Outfit als Ganzes</title><style>
html,body{margin:0;height:100%;overflow:hidden;background:#000;color:#eee;font:13px system-ui}
h1{font-size:14px;margin:6px 8px}
h2{font-size:13px;margin:0 0 4px;color:#9fe8ff;font-weight:600}
h3{font-size:12px;margin:8px 0 3px;color:#c9a8ff;font-weight:600}
a{color:#9fe8ff}
/* the clip always stays in view (Metin, 00:29): it fills the screen like in the app, everything to set lies on its left */
#st{position:fixed;top:0;right:0;height:100%;aspect-ratio:2/3;max-width:100vw;overflow:hidden;background:#000}
#st video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .8s}
#st video.on{opacity:1}
#panel{position:fixed;top:0;left:0;bottom:46px;width:min(58vw,360px);overflow-y:auto;background:rgba(0,0,0,.30);padding-bottom:10px;z-index:3}
body.wave #panel{bottom:138px}
/* pause, picture by picture and dragging through the clip (Metin, 00:34), always at the bottom */
#trans{position:fixed;left:0;right:0;bottom:0;height:46px;z-index:4;background:rgba(0,0,0,.6);display:flex;gap:6px;align-items:center;padding:0 6px;box-sizing:border-box}
body.wave #trans{bottom:92px}
#trans button{padding:6px 9px;white-space:nowrap}
#ptime{min-width:74px;text-align:right;font-size:12px;color:#cde}
body.hide #panel{display:none}
@media (min-aspect-ratio:1/1){#panel{width:calc(100vw - 100vh*2/3);max-width:none;background:#000}}
#top{position:fixed;top:6px;right:6px;z-index:4;display:flex;gap:6px;align-items:center;flex-direction:row-reverse;max-width:42vw;flex-wrap:wrap}
#name{font-size:13px;font-weight:600;color:#9fe8ff;background:rgba(0,0,0,.55);padding:4px 7px;border-radius:8px}
#wavebar{position:fixed;left:0;right:0;bottom:0;height:92px;z-index:4;background:rgba(0,0,0,.55);display:none}
body.wave #wavebar{display:block}
#wave{width:100%;height:92px;display:block;touch-action:none}
.card{margin:6px;padding:6px 8px;border:1px solid #334;border-radius:10px;background:rgba(0,0,0,.42)}
.bar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0}
select,button{padding:6px 8px;border-radius:8px;background:rgba(34,34,34,.9);color:#eee;border:1px solid #445;font:inherit}
button.on{border-color:#2a6;color:#9f9}
button:disabled{opacity:.45}
.t{font-size:12px;color:#9ab}
.z{color:#9ab;font-size:12px;min-width:44px}
input[type=range]{flex:1 1 120px;min-width:120px}
label{display:flex;gap:4px;align-items:center}
</style></head><body>
<div id="st"><video id="v0" playsinline muted></video><video id="v1" playsinline muted></video></div>
<div id="top"><button id="tog">☰</button><span id="name">...</span></div>
<div id="panel"><h1>Outfit als Ganzes &nbsp; <a href="/tempo" style="font-size:12px;font-weight:400">Clip Tester</a> &nbsp; <a href="/naht" id="naht" style="font-size:12px;font-weight:400">Naht</a></h1>
<div class="card"><h2>1. Kleid</h2><div class="bar"><select id="look"></select></div><div class="t" id="info"></div>
<div class="bar" id="solobar" style="display:none"><span class="t">Nur dieser Clip läuft, zum Einstellen.</span><button id="weiter">weiter mit den Schleifen</button></div></div>
<div class="card"><h2>2. Schleifen</h2><div id="loops" class="bar"></div>
<div class="bar"><button id="seq">Schleifen: der Reihe nach</button><button id="nxt">nächste Schleife</button></div></div>
<div class="card"><h2>3. Berührung</h2><div id="touch"></div>
<div class="bar"><label><input type="checkbox" id="ton" checked>Ton hier hören</label></div></div>
<div class="card"><h2>4. Einstellen: der Clip, der läuft</h2>
<h3>Tempo</h3>
<div class="bar"><input type="range" id="rate" min="0.4" max="2" step="0.01" value="1"><span id="rlab" style="min-width:34px">1.00</span></div>
<div class="bar"><button id="rm">− 0,01</button><button id="rp">+ 0,01</button><button id="r1">auf 1</button><button id="mk">Tempo merken</button></div>
<h3>Schnitt: Anfang und Ende</h3>
<div class="t" id="clab"></div>
<div class="bar"><span class="z">Anfang</span><input type="range" id="cfrom" min="0" max="10" step="0.01" value="0"><button id="am">− 0,01</button><button id="ap">+ 0,01</button></div>
<div class="bar"><span class="z">Ende</span><input type="range" id="cto" min="0" max="10" step="0.01" value="10"><button id="em">− 0,01</button><button id="ep">+ 0,01</button></div>
<div class="bar"><button id="csave">Schnitt merken</button><button id="cclr">Schnitt weg</button><a id="cut" href="/tempo" class="t">im Clip Tester</a></div>
<h3>Ton</h3>
<div class="bar"><button id="tonb">Ton dieses Clips</button></div><div class="t" id="toninfo"></div>
<div id="tonstk"><div class="t" id="vlab"></div>
<div class="bar"><span class="z">Laut</span><input type="range" id="vol" min="10" max="140" step="1" value="100"></div>
<div class="bar"><button id="vm">leiser</button><button id="vp">lauter</button><button id="v1b">normal</button><button id="vsave">Lautstärke merken</button></div>
<div class="t">Unten am Rand ist das Bild vom Ton: mit dem Finger über das Stück ziehen, das stumm sein soll. Rot ist schon stumm, die weiße Linie zeigt, wo der Clip ist. Einmal tippen springt an die Stelle.</div>
<div class="t" id="slab"></div>
<div class="bar"><span class="z">von</span><input type="range" id="sfrom" min="0" max="10" step="0.01" value="0"><button id="sm1">− 0,01</button><button id="sp1">+ 0,01</button></div>
<div class="bar"><span class="z">bis</span><input type="range" id="sto" min="0" max="10" step="0.01" value="1"><button id="sm2">− 0,01</button><button id="sp2">+ 0,01</button></div>
<div class="bar"><button id="sadd">Stück stumm schalten</button><button id="shear">Stück anhören</button></div><div class="t" id="slist"></div></div></div>
<div class="card"><h2>5. Reset für alle Clips</h2><div class="bar"><button id="rst">Reset</button><button id="rnew" style="font-size:11px;color:#9ab">Stand neu merken</button></div>
<div class="t" id="rinfo"></div></div></div>
<div id="trans"><button id="pp">⏸</button><button id="fb">◀ Bild</button><button id="ff">Bild ▶</button><input type="range" id="pos" min="0" max="10" step="0.01" value="0"><span id="ptime">0.00 s</span></div>
<div id="wavebar"><canvas id="wave"></canvas></div>
<script>
const OUT=[['Kurzes Arbeitskleid','kurz',''],['Kurzes Freizeitkleid','kurz','freizeit'],['Langes Arbeitskleid','schwarz',''],['Langes Freizeitkleid','schwarz','freizeit'],['Nachtkleid','nacht','']];
const ZONES=[['Gesicht',['gesicht']],['Brust',['brust']],['Bauch',['bauch','mix']],['Po',['po','povorne','mix']]];
const PRELOAD_S=3,LOOP_PRE=0.25,LOOP_OFF=300,FAST_OFF=450;
const $=id=>document.getElementById(id);
let LOOK='',PRE='',CL=[],VER={},RATE={},KURVE={},SCHNITT={},SAVED={},MUTE={},STUMM={},VOL={},LEAD={},OFF={},SV=0,TOK=0,CUR='',CURSND=false,LAST='',BUSY=false,SEQ=true,SOLO=false,PAUSED=false,SCRUB=false;
const base=n=>n.replace(/[0-9]+$/,'');
const vars=b=>CL.filter(n=>base(n)===PRE+b);
const pthNow=()=>LOOK+'/'+CUR;
const cutStart=p=>{const c=SCHNITT[p];return c&&c[0]>0?c[0]:0;};
const endOf=v=>{const d=v.duration||0,c=SCHNITT[v.dataset.pth||''];return c&&c[1]>0&&c[1]<d?c[1]:d;};
const rateAt=(p,t)=>{const k=KURVE[p];if(k)for(const s of k)if(t>=s[0]&&t<s[1])return s[2];return RATE[p]||1;};
const vis=()=>$(SV?'v1':'v0');
const quiet=(p,t)=>(STUMM[p]||[]).some(x=>t>=x[0]&&t<x[1]);
/* a silent stretch: the clip plays on, only the volume is zero there, so the time line stays */
const volOf=p=>Math.min(1,.7*(VOL[p]||1));  /* 1 = the normal loudness of the stage, 1.4 = all the phone gives */
function volFollow(v,p){const s0=v.src,f=()=>{if(v.src!==s0)return;v.volume=quiet(p,v.currentTime)?0:volOf(p);if(!v.ended)requestAnimationFrame(f);};f();}
const sameCut=(a,b)=>Math.abs(((a||[])[0]||0)-((b||[])[0]||0))<0.006&&Math.abs(((a||[])[1]||0)-((b||[])[1]||0))<0.006;
function cutShow(){const p=pthNow(),d=vis().duration||0,a=Number($('cfrom').value),b=Number($('cto').value);
 $('clab').textContent='Anfang '+a.toFixed(2)+' s, Ende '+b.toFixed(2)+' s von '+d.toFixed(2)+' s'+(sameCut(SCHNITT[p],SAVED[p])?(SAVED[p]?'  (gemerkt)':''):'  (noch nicht gemerkt)');}
function tonShow(){const p=pthNow(),off=!!MUTE[p];$('tonb').disabled=!CURSND;$('tonb').classList.toggle('on',CURSND&&off);
 $('tonb').textContent=!CURSND?'Schleifen laufen immer ohne Ton':(off?'Ton dieses Clips ist AUS (wieder einschalten)':'Ton dieses Clips ausschalten');
 $('toninfo').textContent=CURSND?(off?'In der App läuft dieser Clip stumm. Die Datei behält ihren Ton.':'In der App läuft dieser Clip mit seinem Ton.'):'';
 $('tonstk').style.display=CURSND&&!off?'block':'none';document.body.classList.toggle('wave',CURSND&&!off);const d=vis().duration||10;$('sfrom').max=$('sto').max=String(d);stkShow();waveLoad();
 $('vol').value=String(Math.round((VOL[p]||1)*100));volShow();}
function volShow(){const n=Number($('vol').value);$('vlab').textContent='Lautstärke dieses Clips: '+n+' % (100 ist normal, 140 ist das Lauteste)';}
/* the picture of the sound: loudness over time from the server, his selection, the silent stretches, the play line */
let WAVE={},WSEL=null;
async function waveLoad(){const p=pthNow();if(!CURSND||WAVE[p])return;WAVE[p]={peaks:[],dauer:0,wait:true};
 try{const j=await (await fetch('/api/wave?clip='+encodeURIComponent(p))).json();if(j&&j.ok)WAVE[p]=j;else WAVE[p]={peaks:[],dauer:0,fail:true};}catch(e){WAVE[p]={peaks:[],dauer:0,fail:true};}}
function waveDur(){const w=WAVE[pthNow()];return (vis().duration||0)||(w&&w.dauer)||10;}
function waveDraw(){const c=$('wave');if(document.body.classList.contains('wave')){const dpr=window.devicePixelRatio||1,W=Math.round(c.clientWidth*dpr),H=Math.round(c.clientHeight*dpr);
  if(c.width!==W||c.height!==H){c.width=W;c.height=H;}
  const g=c.getContext('2d'),p=pthNow(),w=WAVE[p]||{peaks:[]},d=waveDur(),x=t=>t/d*W;g.clearRect(0,0,W,H);
  const n=w.peaks.length;if(n){const span=(w.dauer||d)/n;g.fillStyle='#4fd6ff';for(let i=0;i<n;i++){const h=Math.max(1,w.peaks[i]*(H-6));g.fillRect(x(i*span),(H-h)/2,Math.max(1,x(span)-0.5),h);}}
  else{g.fillStyle='#8aa';g.font=(13*dpr)+'px system-ui';g.fillText(w.wait?'Der Ton wird gelesen ...':(w.fail?'Der Ton konnte nicht gelesen werden.':'Dieser Clip hat keine Tonspur.'),8*dpr,H/2+4*dpr);}
  g.fillStyle='rgba(239,68,68,.45)';for(const s of (STUMM[p]||[]))g.fillRect(x(s[0]),0,x(s[1])-x(s[0]),H);
  const a=Number($('sfrom').value),b=Number($('sto').value);g.fillStyle='rgba(255,255,255,.16)';g.fillRect(x(a),0,x(b)-x(a),H);
  g.strokeStyle='#fff';g.lineWidth=dpr;g.strokeRect(x(a)+0.5,0.5,Math.max(1,x(b)-x(a)-1),H-1);
  g.fillStyle='#fff';g.fillRect(x(vis().currentTime||0),0,Math.max(1,dpr*1.5),H);}
 requestAnimationFrame(waveDraw);}
(function(){const c=$('wave');let x0=0,t0=0,drag=false;const tAt=e=>{const r=c.getBoundingClientRect();return Math.min(waveDur(),Math.max(0,(e.clientX-r.left)/r.width*waveDur()));};
 c.onpointerdown=e=>{c.setPointerCapture(e.pointerId);x0=e.clientX;t0=tAt(e);drag=false;WSEL=true;};
 c.onpointermove=e=>{if(!WSEL)return;if(Math.abs(e.clientX-x0)>5)drag=true;if(!drag)return;const t=tAt(e),a=Math.min(t0,t),b=Math.max(t0,t);
  $('sfrom').value=String(a.toFixed(2));$('sto').value=String(Math.max(a+0.02,b).toFixed(2));stkShow();};
 c.onpointerup=c.onpointercancel=e=>{if(!WSEL)return;WSEL=null;if(!drag){solo();PAUSED=false;const v=vis();v.muted=!!MUTE[pthNow()]||!$('ton').checked;v.currentTime=tAt(e);v.play().catch(()=>{});}};})();
function stkShow(){const p=pthNow(),a=Number($('sfrom').value),b=Number($('sto').value);
 $('slab').textContent='Ein Stück ohne Ton, gleich lang, nichts verschiebt sich: von '+a.toFixed(2)+' bis '+b.toFixed(2)+' s';
 $('slist').innerHTML=(STUMM[p]||[]).map((x,i)=>'stumm: '+x[0].toFixed(2)+' bis '+x[1].toFixed(2)+' s <a href="#" data-i="'+i+'">weg</a>').join('<br>')||'Kein Stück ist stumm.';
 $('slist').querySelectorAll('a').forEach(a2=>{a2.onclick=e=>{e.preventDefault();const k=(STUMM[p]||[]).slice();k.splice(Number(a2.dataset.i),1);stkSave(k);};});}
async function stkSave(k){const p=pthNow(),j=await post('/api/ton',{name:p,stumm:k});
 if(j&&j.ok){const st=(j.stumm||{})[p];if(st)STUMM[p]=st;else delete STUMM[p];}stkShow();standLater();}
function label(){const p=pthNow(),c=SCHNITT[p],v=vis(),d=v.duration||10;$('name').textContent=p;
 $('rate').value=String(RATE[p]||1);$('rlab').textContent=Number(RATE[p]||1).toFixed(2);
 $('cut').href='/tempo?clip='+encodeURIComponent(p);$('naht').href='/naht?a='+encodeURIComponent(p);
 $('cfrom').max=$('cto').max=String(d);$('cfrom').value=String(c&&c[0]||0);$('cto').value=String(c&&c[1]&&c[1]<d?c[1]:d);
 $('info').textContent=(KURVE[p]?'mit Tempo Kurve  ':'')+(v.duration?v.duration.toFixed(1)+' s lang':'');
 cutShow();tonShow();$('solobar').style.display=SOLO?'flex':'none';
 document.querySelectorAll('button[data-n]').forEach(b=>{const run=b.dataset.n===CUR;
  if(b.dataset.loop){b.classList.toggle('on',!OFF[b.dataset.n]);b.style.opacity=OFF[b.dataset.n]?'.5':'1';b.textContent=(run?'▶ ':'')+'Schleife '+b.dataset.loop;}
  else b.classList.toggle('on',run);});}
/* one clip on the stage. opt.cont: it follows the running clip and fades in `pre` seconds before
   that one ends; otherwise it starts as soon as it can play. `done` is called PRELOAD_S before
   its own end, so the next clip can load in time (as on the stage of the app). */
function show(name,opt,done){const vs=[$('v0'),$('v1')],a=vs[SV],b=vs[1-SV],tok=++TOK,pth=LOOK+'/'+name;SOLO=false;PAUSED=false;
 const pre=opt.fast?0:(LEAD[pth]!==undefined?LEAD[pth]:LOOP_PRE),off=opt.fast?FAST_OFF:LOOP_OFF;  /* LEAD: when this clip comes in, set on the page /naht */
 b.onended=null;b.ontimeupdate=null;b.oncanplaythrough=null;b.dataset.pth=pth;b.muted=!(opt.snd&&$('ton').checked&&!MUTE[pth]);b.volume=.7;
 let rdy=false;
 const go=()=>{if(tok!==TOK)return;const cs=cutStart(pth);if(Math.abs(b.currentTime-cs)>0.04)b.currentTime=cs;
  b.play().catch(()=>{b.muted=true;b.play().catch(()=>{});});
  vs.forEach(x=>{x.style.transition='opacity '+(opt.fast?'.35s':'.8s');});
  b.style.zIndex=1;a.style.zIndex=0;b.classList.add('on');SV=1-SV;CUR=name;CURSND=!!opt.snd;label();volFollow(b,pth);
  setTimeout(()=>{if(tok===TOK)a.classList.remove('on');},off);setTimeout(()=>{if(!a.classList.contains('on'))a.pause();},off+150);
  let fired=false,hold=0;const src0=b.src,fire=()=>{if(fired||tok!==TOK)return;fired=true;if(done)done();};
  b.ontimeupdate=()=>{const r=rateAt(pth,b.currentTime);if(Math.abs((b.playbackRate||1)-r)>0.001)b.playbackRate=r;
   if(!b.duration)return;const e=endOf(b);
   if(e<b.duration-0.05&&!hold&&b.currentTime>e-0.6)hold=setTimeout(()=>{if(b.src===src0&&!b.paused&&!SOLO){b.pause();fire();}},Math.max(0,(e-b.currentTime)*1000/(b.playbackRate||1)));
   if(b.currentTime>e-PRELOAD_S)fire();};
  b.onended=fire;};
 const ready=()=>{if(rdy||tok!==TOK)return;rdy=true;b.oncanplaythrough=null;
  if(opt.cont&&a.classList.contains('on')&&a.duration&&!a.ended){const w=(endOf(a)-pre-a.currentTime)*1000/(a.playbackRate||1);if(w>30){setTimeout(go,w);return;}}go();};
 b.oncanplaythrough=ready;setTimeout(()=>{if(!rdy&&tok===TOK&&b.readyState>=3)ready();},4000);setTimeout(()=>{if(!rdy&&tok===TOK)ready();},9000);
 b.onloadedmetadata=()=>{b.playbackRate=rateAt(pth,0);const cs=cutStart(pth);if(cs)b.currentTime=cs;};
 b.src='/clips/'+pth+'.mp4?v='+(VER[LOOK]||0);b.playbackRate=rateAt(pth,0);b.load();}
/* the loop: clip, clip, clip. In order, or like the app a random other one each time */
/* every loop once before one comes again (Metin, 25 Nov 2026, 04:44: 1, 2, 3, then 2, 3, 2 and loop 1 only much later is wrong): a round holds each loop once in random order, and a new round never begins with the loop that just ran */
function roundPick(R,v,cur){let b=(R.b||[]).filter(n=>v.includes(n));
 if(!b.length||(b.length===1&&b[0]===cur&&v.length>1)){b=v.slice();for(let i=b.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1)),t=b[i];b[i]=b[j];b[j]=t;}}
 if(b.length>1&&b[0]===cur)b.push(b.shift());const n=b.shift();R.b=b;return n;}
const RND={};
function loopNext(cont,fast){BUSY=false;const all=vars('gluecklich'),sel=all.filter(n=>!OFF[n]),v=sel.length?sel:all;if(!v.length){$('name').textContent='Dieses Kleid hat noch keine Schleife.';return;}
 let n;if(SEQ){const i=v.indexOf(LAST);n=v[(i+1)%v.length];}else n=roundPick(RND,v,LAST);
 LAST=n;
 show(n,{cont:cont,fast:fast},()=>loopNext(true,false));}
/* a touch clip starts at once, with its sound; a clip from behind first turns her (hinten), as in the app */
function touch(zone,n){if(BUSY&&!SOLO)return;BUSY=true;const turn=zone==='Po'&&!/povorne|mix/.test(n)?vars('hinten'):[];
 const back=()=>loopNext(true,false),play=c=>show(n,{cont:c,fast:!c,snd:true},back);
 if(turn.length)show(turn[Math.floor(Math.random()*turn.length)],{fast:true,snd:true},()=>play(true));else play(false);}
/* while he sets begin and end, only this clip runs, from its begin to its end and again */
function solo(){if(SOLO)return;SOLO=true;++TOK;BUSY=false;const v=vis();v.ontimeupdate=null;v.onended=null;v.loop=false;$('solobar').style.display='flex';
 [$('v0'),$('v1')].forEach(x=>{if(x!==v){x.classList.remove('on');x.pause();}});}
function soloTick(){if(SOLO){const v=vis(),p=v.dataset.pth||'';if(v.duration){const A=cutStart(p),B=endOf(v),t=v.currentTime;
   if(!PAUSED&&!SCRUB){if(t>=B-0.01||t<A-0.15||v.ended)v.currentTime=A;if(v.paused)v.play().catch(()=>{});}
   const r=rateAt(p,t);if(Math.abs((v.playbackRate||1)-r)>0.001)v.playbackRate=r;}}
 requestAnimationFrame(soloTick);}
function draw(){const L=$('loops'),T=$('touch');L.innerHTML='';T.innerHTML='';
 const btn=(txt,n,fn)=>{const b=document.createElement('button');b.textContent=txt;b.dataset.n=n;b.title=LOOK+'/'+n;b.onclick=fn;return b;};
 /* a tap takes a loop out of the round or back in (Metin, 00:41: not pick one, but let loop 1 and 2 run); one always stays */
 vars('gluecklich').forEach((n,i)=>{const b=btn('Schleife '+(i+1),n,()=>{const left=vars('gluecklich').filter(x=>!OFF[x]);
   if(OFF[n])delete OFF[n];else if(left.length>1)OFF[n]=1;label();if(OFF[CUR]&&!SOLO){BUSY=false;loopNext(false,true);}});b.dataset.loop=String(i+1);L.appendChild(b);});
 if(L.children.length>1){const h=document.createElement('div');h.className='t';h.style.flexBasis='100%';h.textContent='Tippen: die Schleife macht mit (grün) oder setzt aus.';L.appendChild(h);}
 for(const [zone,kinds] of ZONES){const names=[].concat(...kinds.map(vars));if(!names.length)continue;
  const row=document.createElement('div');row.className='bar';row.innerHTML='<span class="z">'+zone+'</span>';
  names.forEach((n,i)=>row.appendChild(btn(zone+(names.length>1?' '+(i+1):''),n,()=>touch(zone,n))));T.appendChild(row);}
 if(!T.children.length)T.innerHTML='<div class="t">Dieses Kleid hat noch keine Berührungs Clips.</div>';}
function pick(i){const o=OUT[i];LOOK=o[1];PRE=o[2];CL=(window.J.outfits[LOOK]||{}).clips||[];LAST='';CUR='';OFF={};try{localStorage.setItem('lganz',String(i));}catch(e){}draw();loopNext(false,true);}
async function start(){const j=await (await fetch('/clips.json?t='+Date.now())).json();window.J=j;const o=j.outfits||{};
 for(const look in o){VER[look]=o[look].v||0;for(const c in (o[look].r||{}))RATE[look+'/'+c]=o[look].r[c];
  for(const c in (o[look].k||{}))KURVE[look+'/'+c]=o[look].k[c];for(const c in (o[look].l||{}))LEAD[look+'/'+c]=o[look].l[c];for(const c of (o[look].m||[]))MUTE[look+'/'+c]=1;
  for(const c in (o[look].ms||{}))STUMM[look+'/'+c]=o[look].ms[c];for(const c in (o[look].mv||{}))VOL[look+'/'+c]=o[look].mv[c];
  for(const c in (o[look].s||{})){SCHNITT[look+'/'+c]=o[look].s[c].slice();SAVED[look+'/'+c]=o[look].s[c].slice();}}
 const s=$('look');OUT.forEach((x,i)=>{if(!o[x[1]])return;const op=document.createElement('option');op.value=String(i);op.textContent=x[0];s.appendChild(op);});
 s.onchange=()=>pick(Number(s.value));
 const want=new URLSearchParams(location.search).get('clip')||'';let i=-1;
 if(want.includes('/')){const [lk,c]=want.split('/');i=OUT.findIndex(x=>x[1]===lk&&(x[2]==='freizeit')===c.startsWith('freizeit'));}
 if(i<0){try{i=Number(localStorage.getItem('lganz')||0);}catch(e){i=0;}}
 if(!OUT[i]||!o[OUT[i][1]])i=Number(s.options[0].value);s.value=String(i);pick(i);requestAnimationFrame(soloTick);requestAnimationFrame(waveDraw);}
const post=async(url,body)=>{try{return await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}catch(e){return null;}};
const flash=(b,ok,txt)=>{b.textContent=ok?'gemerkt':'ging nicht';setTimeout(()=>{b.textContent=txt;},1200);};
$('tog').onclick=()=>document.body.classList.toggle('hide');  /* the panel away: the whole clip */
$('nxt').onclick=()=>{BUSY=false;loopNext(false,true);};$('weiter').onclick=()=>{BUSY=false;loopNext(false,true);};
/* pause, one picture back or on, and dragging through the clip; from then on only this clip is on the stage */
const FRAME=1/24;
function posTick(){const v=vis(),d=v.duration||0;if(d){if(!SCRUB){$('pos').max=String(d);$('pos').value=String(v.currentTime);}
  $('ptime').textContent=v.currentTime.toFixed(2)+' / '+d.toFixed(2)+' s';}$('pp').textContent=PAUSED?'▶':'⏸';requestAnimationFrame(posTick);}
const halt=()=>{solo();PAUSED=true;vis().pause();};
$('pp').onclick=()=>{if(!CUR)return;if(PAUSED){PAUSED=false;solo();vis().play().catch(()=>{});}else halt();};
$('fb').onclick=()=>{if(!CUR)return;halt();const v=vis();v.currentTime=Math.max(0,v.currentTime-FRAME);};
$('ff').onclick=()=>{if(!CUR)return;halt();const v=vis();v.currentTime=Math.min((v.duration||0)-0.001,v.currentTime+FRAME);};
$('pos').oninput=()=>{if(!CUR)return;solo();SCRUB=true;vis().currentTime=Number($('pos').value);};
$('pos').onchange=()=>{SCRUB=false;};$('pos').onpointerup=()=>{SCRUB=false;};$('pos').onpointercancel=()=>{SCRUB=false;};
requestAnimationFrame(posTick);
/* the loops in order (clip 1, 2, 3, 1 ...) or at random like the app, where never the same one follows itself */
function seqShow(){$('seq').textContent=SEQ?'Schleifen: der Reihe nach':'Schleifen: zufällig wie in der App';$('seq').classList.toggle('on',!SEQ);}
try{SEQ=localStorage.getItem('lgseq')!=='0';}catch(e){}seqShow();
$('seq').onclick=()=>{SEQ=!SEQ;try{localStorage.setItem('lgseq',SEQ?'1':'0');}catch(e){}seqShow();};
/* tempo, in steps of one hundredth (Metin: buttons with 0,01 steps) */
$('rate').oninput=()=>{if(!CUR)return;const p=pthNow(),r=Number($('rate').value);RATE[p]=r;$('rlab').textContent=r.toFixed(2);if(!KURVE[p])vis().playbackRate=r;};
const nudge=(id,d)=>{const r=$(id);r.value=String(Math.min(Number(r.max),Math.max(Number(r.min),Math.round((Number(r.value)+d)*100)/100)));r.oninput();};
const nudgeBy=(id,d)=>{const r=$(id);r.value=String(Math.min(Number(r.max),Math.max(Number(r.min),Number(r.value)+d)));r.oninput();};
$('rm').onclick=()=>nudge('rate',-0.01);$('rp').onclick=()=>nudge('rate',0.01);$('r1').onclick=()=>{$('rate').value='1';$('rate').oninput();};
$('mk').onclick=async()=>{if(!CUR)return;const j=await post('/api/tempo',{name:pthNow(),rate:Number($('rate').value)});flash($('mk'),j&&j.ok,'Tempo merken');standLater();};
/* begin and end: the marks apply at once on this page, the app gets them with "Schnitt merken" */
const cutSet=()=>{const p=pthNow(),d=vis().duration||0,a=Number($('cfrom').value),b=Number($('cto').value);
 if(a<=0.004&&b>=d-0.03)delete SCHNITT[p];else SCHNITT[p]=[Number(a.toFixed(2)),b>=d-0.03?0:Number(b.toFixed(2))];cutShow();};
$('cfrom').oninput=()=>{if(!CUR)return;solo();const f=$('cfrom'),t=$('cto');if(Number(f.value)>Number(t.value)-0.5)f.value=String(Math.max(0,Number(t.value)-0.5));cutSet();vis().currentTime=Number(f.value);};
$('cto').oninput=()=>{if(!CUR)return;solo();const f=$('cfrom'),t=$('cto');if(Number(t.value)<Number(f.value)+0.5)t.value=String(Math.min(Number(t.max),Number(f.value)+0.5));cutSet();vis().currentTime=Math.max(Number(f.value),Number(t.value)-1.2);};
$('am').onclick=()=>nudge('cfrom',-0.01);$('ap').onclick=()=>nudge('cfrom',0.01);$('em').onclick=()=>nudge('cto',-0.01);$('ep').onclick=()=>nudge('cto',0.01);
$('csave').onclick=async()=>{if(!CUR)return;const p=pthNow(),c=SCHNITT[p]||[0,0],j=await post('/api/schnitt',{name:p,start:c[0],end:c[1]});
 if(j&&j.ok){if(SCHNITT[p])SAVED[p]=SCHNITT[p].slice();else delete SAVED[p];}flash($('csave'),j&&j.ok,'Schnitt merken');cutShow();standLater();};
$('cclr').onclick=async()=>{if(!CUR)return;const p=pthNow(),j=await post('/api/schnitt',{name:p,start:0,end:0});
 if(j&&j.ok){delete SCHNITT[p];delete SAVED[p];label();}standLater();};
/* the sound of this clip in the app: off or on again, the file keeps it */
$('tonb').onclick=async()=>{if(!CUR||!CURSND)return;const p=pthNow(),off=!MUTE[p],j=await post('/api/ton',{name:p,aus:off});
 if(j&&j.ok){if(off)MUTE[p]=1;else delete MUTE[p];vis().muted=off||!$('ton').checked;}tonShow();standLater();};
/* quieter or louder: at once on this page, in the app after "Lautstärke merken" */
$('vol').oninput=()=>{if(!CUR||!CURSND)return;const p=pthNow(),f=Number($('vol').value)/100;if(f===1)delete VOL[p];else VOL[p]=f;volShow();};
$('vm').onclick=()=>nudgeBy('vol',-5);$('vp').onclick=()=>nudgeBy('vol',5);$('v1b').onclick=()=>nudgeBy('vol',100-Number($('vol').value));
$('vsave').onclick=async()=>{if(!CUR||!CURSND)return;const j=await post('/api/ton',{name:pthNow(),laut:Number($('vol').value)/100});flash($('vsave'),j&&j.ok,'Lautstärke merken');standLater();};
/* a stretch of the sound without sound: from, to, in steps of one hundredth */
$('sfrom').oninput=()=>{const f=$('sfrom'),t=$('sto');if(Number(t.value)<Number(f.value)+0.02)t.value=String(Math.min(Number(t.max),Number(f.value)+0.5));stkShow();};
$('sto').oninput=()=>{const f=$('sfrom'),t=$('sto');if(Number(t.value)<Number(f.value)+0.02)f.value=String(Math.max(0,Number(t.value)-0.5));stkShow();};
$('sm1').onclick=()=>nudge('sfrom',-0.01);$('sp1').onclick=()=>nudge('sfrom',0.01);$('sm2').onclick=()=>nudge('sto',-0.01);$('sp2').onclick=()=>nudge('sto',0.01);
$('sadd').onclick=()=>{if(!CUR||!CURSND)return;const k=(STUMM[pthNow()]||[]).slice();k.push([Number($('sfrom').value),Number($('sto').value)]);stkSave(k);};
$('shear').onclick=()=>{if(!CUR)return;solo();PAUSED=false;const v=vis();v.muted=!!MUTE[pthNow()]||!$('ton').checked;v.currentTime=Math.max(0,Number($('sfrom').value)-1);v.play().catch(()=>{});};
/* the reset point: tempo, curve, cut and sound of all clips as they were at one moment */
function standShow(j){if(!j||!j.ok)return;const n=(j.geaendert||[]).length;window.STAND=j;
 $('rst').textContent='Reset: alles wie am '+j.wann+' Uhr';$('rst').disabled=!n;
 $('rinfo').textContent=n?n+(n===1?' Clip ist':' Clips sind')+' seitdem anders: '+j.geaendert.slice(0,6).join(', ')+(n>6?' ...':''):'Nichts ist seitdem anders.';}
async function stand(aktion){if(aktion)return post('/api/stand',{aktion:aktion});try{return await (await fetch('/api/stand?t='+Date.now())).json();}catch(e){return null;}}
function standLater(){setTimeout(async()=>standShow(await stand('')),500);}
$('rst').onclick=async()=>{const s=window.STAND;if(!s||!confirm('Tempo, Kurve, Schnitt und Ton von allen Clips auf den Stand vom '+s.wann+' Uhr zurückstellen? Das betrifft '+s.geaendert.length+' Clip(s). Die Dateien bleiben unberührt.'))return;
 const j=await stand('zurueck');if(j&&j.ok)location.reload();else $('rinfo').textContent='Reset ging nicht.';};
$('rnew').onclick=async()=>{if(!confirm('Den Stand von jetzt als neuen Reset Punkt merken? Der alte Reset Punkt ist dann weg.'))return;standShow(await stand('merken'));};
stand('').then(standShow);
start();
</script></body></html>"""
