"""
What is on the false wake recordings (2.156.0).

The add on keeps the microphone audio of every talk that the wake word started and in which
nobody spoke (main._finish_recording, /data/false_wakes). Before the wake word model is
trained again with them, this tells what they are: when they happened, how loud they were, how
much of them was sound, and what a speech recogniser hears in them (television, a talk in the
room, Turkish, nothing). For POST /api/kopf/fehlwecker (code word); the texts are never stored.
"""
import asyncio
import logging
import os
import re
import wave

import httpx

from app import wakecheck
from app.pacing import pcm_level

logger = logging.getLogger(__name__)

WINDOW_S = 0.1
SOUND_RMS = 300      # a window louder than this counts as sound (voice.py: a voice is 300 to 400)
PARALLEL = 5
# "_vorher": the microphone history from before the wake word (wakecheck.py), else what came after
# "_w840": the wake word fired 840 ms before the end of that history
NAME_RE = re.compile(r"falsewake_(?P<who>.+)_(?P<day>\d{8})_(?P<time>\d{6})"
                     r"(?P<pre>_vorher)?(?:_w(?P<wake>\d+))?\.wav$")


def listing(folder: str) -> list:
    try:
        return sorted(f for f in os.listdir(folder) if f.endswith(".wav"))
    except OSError:
        return []


def measure(path: str) -> dict:
    """Length and loudness of one recording, without its content (16 bit mono, as the add on
    writes it; no audioop, which Python 3.13 no longer has)."""
    with wave.open(path, "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        pcm = w.readframes(w.getnframes())
    if width != 2 or channels != 1:
        raise ValueError(f"not 16 bit mono ({width * 8} bit, {channels} channels)")
    step = max(2, int(rate * WINDOW_S) * 2)
    levels = [pcm_level(pcm[i:i + step]) for i in range(0, len(pcm) - step + 1, step)]
    loud = [r for r, _ in levels if r >= SOUND_RMS]
    first = next((i for i, (r, _) in enumerate(levels) if r >= SOUND_RMS), None)
    return {"sekunden": round(len(pcm) / (rate * 2), 1),
            "rms": int((sum(r * r for r, _ in levels) / len(levels)) ** 0.5) if levels else 0,
            "spitze": max((p for _, p in levels), default=0),
            "ton_anteil": round(len(loud) / len(levels), 2) if levels else 0.0,
            "erster_ton_s": round(first * WINDOW_S, 1) if first is not None else None}


def describe(name: str) -> dict:
    m = NAME_RE.search(name)
    if not m:
        return {"datei": name}
    day, t = m["day"], m["time"]
    return {"tag": f"{day[:4]}-{day[4:6]}-{day[6:]}", "uhrzeit": f"{t[:2]}:{t[2:4]}",
            "app": m["who"].startswith("app_"),  # a live talk from the app is no wake word
            "vorher": bool(m["pre"]), **({"weck_ms": int(m["wake"])} if m["wake"] else {})}


async def heard(path: str, api_key: str, client: httpx.AsyncClient) -> str:
    """What a speech recogniser hears in it ("" for nothing)."""
    with open(path, "rb") as f:
        return await wakecheck.transcribe(f.read(), api_key, client) or ""


PROBE_S = 2.5   # as long as the history the device sends


def levels(pcm: bytes, rate: int, step_s: float = 0.25) -> list:
    """Loudness (rms) of each quarter second, to see where in a history somebody spoke."""
    step = max(2, int(rate * step_s) * 2)
    return [pcm_level(pcm[i:i + step])[0] for i in range(0, len(pcm) - step + 1, step)]


def clip(path: str) -> tuple:
    """(pcm, rate) of what the wake check would have got: a kept history as it is, of any other
    recording its first PROBE_S seconds."""
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("not 16 bit mono")
        pcm = w.readframes(w.getnframes())
    name = os.path.basename(path)   # a near wake (sammler.py) is a history too
    whole = "_vorher" in name or name.startswith("beinahe_")
    return (pcm if whole else pcm[:int(rate * PROBE_S) * 2]), rate


async def probe(folder: str, api_key: str, offset: int = 0, limit: int = 20,
                text: bool = False, pre=None) -> dict:
    """Every way of listening of the wake check over the kept recordings: per file, which way
    heard her name. `pre` True: only kept histories, False: only the others."""
    names = [n for n in listing(folder)
             if pre is None or ("_vorher" in n) == bool(pre)]
    part = names[max(0, offset):max(0, offset) + max(1, min(limit, 30))]
    gate = asyncio.Semaphore(PARALLEL)

    async def one(name: str, client) -> dict:
        item = describe(name)
        try:
            pcm, rate = await asyncio.to_thread(clip, os.path.join(folder, name))
            async with gate:
                texts = await wakecheck.hear(pcm, rate, api_key, client, item.get("weck_ms"),
                                             timeout=20.0)
            item["pegel"] = [int(r) for r in levels(pcm, rate)]
        except Exception as e:
            item["fehler"] = str(e)[:80]
            return item
        item["v"] = {n: (None if t is None else wakecheck.named(t)) for n, t in texts.items()}
        if text:
            item["gehoert"] = {n: (t or "")[:120] for n, t in texts.items()}
        return item

    async with httpx.AsyncClient(timeout=40.0) as client:
        items = await asyncio.gather(*(one(n, client) for n in part))
    counts = {w: sum(1 for i in items if (i.get("v") or {}).get(w)) for w in wakecheck.WAYS}
    return {"ok": True, "anzahl": len(names), "offset": offset, "name_gehoert": counts,
            "items": list(items)}


async def analyse(folder: str, api_key: str = "", offset: int = 0, limit: int = 25,
                  text: bool = True) -> dict:
    names = listing(folder)
    part = names[max(0, offset):max(0, offset) + max(1, min(limit, 40))]
    gate = asyncio.Semaphore(PARALLEL)

    async def one(name: str, client) -> dict:
        path = os.path.join(folder, name)
        item = describe(name)
        try:
            item.update(await asyncio.to_thread(measure, path))
        except Exception as e:
            item["fehler"] = str(e)[:80]
            return item
        if text and api_key and client is not None and item["ton_anteil"] > 0:
            async with gate:
                item["gehoert"] = (await heard(path, api_key, client))[:300]
        return item

    async with httpx.AsyncClient(timeout=40.0) as client:
        items = await asyncio.gather(*(one(n, client) for n in part))
    return {"ok": True, "anzahl": len(names), "offset": offset, "items": list(items)}
