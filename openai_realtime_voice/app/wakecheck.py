"""
Was she really called? (2.157.0)

The wake word model on the Voice PE also fires on the television: of the 31 false wakes of the
week before 24 Nov 2026, 29 came while the TV was running, and the kept recordings were Turkish
television from their first second. Each false wake made her greet aloud, light her lamps and
turn the TV down for a quarter of a minute.

With firmware that has `preroll` (leyla_voice 2.157.0), the device sends the last seconds of
the microphone from before the wake word when the socket opens: a text frame
{"type":"preroll","rate":16000,"bytes":N}, then N bytes of 16 bit mono PCM, before any audio of
the talk. While the GPT Live session is being opened anyway (about 1.3 s), the server
transcribes that history when the TV is running and looks for her name in it.

Server setting `weckpruefung`: 0 = the history is only taken off the line; 1 = watch (default):
the verdict is logged and counted, nothing changes; 2 = act: when the TV runs and her name was
not heard, the talk ends before it began, without greeting, lamps or a quieter TV. In doubt (no
history, the check too slow, an error) she is taken as called. The history of a false wake is
kept next to the other recordings, as the real trigger sound for training.

2.157.1: acting was switched on for three minutes on 24 Nov 2026 and turned away two of three
real calls by Metin (TV at volume 23): the recogniser wrote down the television, or nothing,
and not his "Hallo Leyla" at the very end. So there are now four ways of listening (WAYS): the
whole history or only its end, where the wake word must be, each plain or with her name given
to the recogniser as a keyword (gpt-transcribe `keywords`, hints that may also make a word
appear that was not said: to be measured, not assumed). All four run on every wake with the TV
on and are logged next to how the talk ended; server setting `weckart` names the ones that
count ("ganz+ende_kw": called when any of them heard her name). `falsewakes.probe` runs them
over the kept recordings.
"""
import asyncio
import io
import json
import logging
import re
import time
import unicodedata
import wave

import httpx

from app import chat

logger = logging.getLogger(__name__)

HEADER_WAIT_S = 0.6     # old firmware sends nothing before ready: do not wait longer for it
BODY_WAIT_S = 1.5
CHECK_TIMEOUT_S = 2.0   # the transcription; later than this she is taken as called
MAX_BYTES = 4 * 48000 * 2
# Her name as a speech recogniser may write it: Leyla, Leila, Layla, Laila, Leylâ, Leyla'yı
NAME_RE = re.compile(r"\bl[ae][iy]+l+a")
TAIL_S = 1.5            # the wake word ends right before the device froze the history
KEYWORDS = ("Hallo Leyla", "Leyla")
# way of listening: (seconds from the end, 0 = all of it; her name as a keyword)
WAYS = {"ganz": (0.0, False), "ende": (TAIL_S, False),
        "ganz_kw": (0.0, True), "ende_kw": (TAIL_S, True)}


class FalseWake(Exception):
    """The talk ends before it began: nobody called her."""


def header(message) -> int:
    """The number of history bytes a text frame announces, 0 when it is something else."""
    if not isinstance(message, str) or '"preroll"' not in message:
        return 0
    try:
        d = json.loads(message)
    except ValueError:
        return 0
    if not isinstance(d, dict) or d.get("type") != "preroll":
        return 0
    try:
        return max(0, min(int(d.get("bytes") or 0), MAX_BYTES))
    except (TypeError, ValueError):
        return 0


def rate_of(message: str) -> int:
    try:
        rate = int(json.loads(message).get("rate") or 16000)
    except Exception:
        rate = 16000
    return rate if 8000 <= rate <= 48000 else 16000


async def read(ws, state: dict) -> tuple:
    """(pcm, rate) of the history the device sends right after connecting, (b"", 0) when it
    sends none. What is still missing when the time is up is left in state["pre_left"], so the
    talk's own loop drops it instead of taking it for audio of the talk."""
    try:
        first = await asyncio.wait_for(ws.recv(), HEADER_WAIT_S)
    except Exception:
        return b"", 0
    total = header(first)
    if not total:
        state.setdefault("early", []).append(first)  # not ours: the talk's loop gets it first
        return b"", 0
    rate, pcm = rate_of(first), bytearray()
    end = time.monotonic() + BODY_WAIT_S
    try:
        while len(pcm) < total:
            part = await asyncio.wait_for(ws.recv(), max(0.05, end - time.monotonic()))
            if isinstance(part, bytes):
                pcm += part
            else:
                state.setdefault("early", []).append(part)
    except Exception:
        pass
    state["pre_left"] = max(0, total - len(pcm))
    return bytes(pcm[:total]), rate


def wav(pcm: bytes, rate: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm[:len(pcm) // 2 * 2])
    return out.getvalue()


def named(text: str) -> bool:
    """Is her name in what was heard?"""
    folded = unicodedata.normalize("NFKD", (text or "").replace("ı", "i")).encode(
        "ascii", "ignore").decode().lower()
    return bool(NAME_RE.search(folded))


def tail(pcm: bytes, rate: int, seconds: float) -> bytes:
    """The last `seconds` of it (all of it for 0 or when it is shorter)."""
    keep = int(rate * seconds) * 2
    return pcm[-keep:] if 0 < keep < len(pcm) else pcm


def ways(setting) -> tuple:
    """The ways that count, from the server setting ("ganz+ende_kw"); unknown names are
    dropped, nothing left means the whole history, plain."""
    names = tuple(n for n in str(setting or "").replace(",", "+").replace(" ", "").split("+")
                  if n in WAYS)
    return names or ("ganz",)


async def transcribe(audio: bytes, api_key: str, client: httpx.AsyncClient,
                     keywords: tuple = ()):
    """What a speech recogniser hears in a wav ("" for nothing, None when nobody answered).
    `keywords`: hints for gpt-transcribe; the older model gets them as a prompt."""
    for model in chat.TRANSCRIBE_MODELS:
        data = {"model": model}
        if keywords and model == "gpt-transcribe":
            data["keywords[]"] = list(keywords)
        elif keywords:
            data["prompt"] = keywords[0]
        try:
            resp = await client.post(chat.TRANSCRIBE_URL,
                                     headers={"Authorization": f"Bearer {api_key}"},
                                     data=data,
                                     files={"file": ("wake.wav", audio, "audio/wav")})
        except Exception as e:
            logger.warning("Wake check: not transcribed (%s): %s", model, e or type(e).__name__)
            continue
        if resp.status_code == 200:
            return (resp.json().get("text") or "").strip()
        logger.info("Wake check: %s answered %s: %s", model, resp.status_code, resp.text[:160])
    return None


async def hear(pcm: bytes, rate: int, api_key: str, client: httpx.AsyncClient,
               names=tuple(WAYS), timeout: float = CHECK_TIMEOUT_S) -> dict:
    """What each way of listening hears, at the same time: {way: text, or None when it did not
    answer in time}."""
    async def one(name: str):
        seconds, kw = WAYS[name]
        try:
            return await asyncio.wait_for(
                transcribe(wav(tail(pcm, rate, seconds), rate), api_key, client,
                           KEYWORDS if kw else ()), timeout)
        except Exception:
            return None
    return dict(zip(names, await asyncio.gather(*(one(n) for n in names))))


def verdict(texts: dict, use: tuple):
    """Was she called, by the ways that count? True when one of them heard her name, False when
    all of them answered and none did, None (taken as called) when one is missing."""
    seen = [None if texts.get(n) is None else named(texts[n]) for n in use]
    if any(v is True for v in seen):
        return True
    return None if any(v is None for v in seen) or not seen else False


async def check(ws, state: dict, mode: int, tv_playing, api_key: str, use="ganz") -> dict:
    """Take the history off the line and, with the TV running, look for her name in it.
    {"pre": seconds, "tv": bool, "named": bool or None, "reject": bool, "s": seconds, "v": {way:
    bool or None}}; never raises. `tv_playing`: async function, True when the TV is on and not
    muted. `use`: the ways that count (setting `weckart`); all ways are heard and reported."""
    started = time.monotonic()
    out = {"pre": 0.0, "tv": False, "named": None, "reject": False}
    try:
        pcm, rate = await read(ws, state)
        if pcm:
            state["preroll"] = (pcm, rate)
            out["pre"] = round(len(pcm) / (rate * 2), 1)
        if pcm and mode >= 1 and api_key:
            out["tv"] = bool(await tv_playing())
            if out["tv"]:
                use = ways(use)
                async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
                    texts = await hear(pcm, rate, api_key, client)
                out["v"] = {n: (None if t is None else named(t)) for n, t in texts.items()}
                out["named"] = verdict(texts, use)
                out["heard"] = " | ".join((texts.get(n) or "")[:80] for n in use)
                out["reject"] = mode >= 2 and out["named"] is False
    except Exception as e:
        logger.info("Wake check not finished (%s): she is taken as called", e or type(e).__name__)
        out["named"], out["reject"] = None, False
    out["s"] = round(time.monotonic() - started, 2)
    return out
