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
the verdict is logged and counted, nothing changes. (Until 2.157.2 a value of 2 ended the talk
before it began; that is gone, see below.) The history of a false wake is
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

2.157.2: measured with that probe: with her name as a keyword the recogniser found one of the
two turned away calls and invented her name in none of the 69 kept television recordings; the
plain way found neither. The last 1.5 s found neither as well, and that was my mistake in
thinking: the device freezes the history when the socket opens, not at the wake word, so the
call lies an unknown stretch before the end and can even fall out of 2.5 s. So the firmware
(leyla_voice 2.158.0) now says where it is: `"wake_ms": N` in the header, the time from the
wake word to the end of the history, and only when the wake word started the talk. The ways
"ruf" and "ruf_kw" hear just the two seconds around it.

2.158.0: nine real calls by Metin with the TV on, 12:38 to 12:41 on 24 Nov 2026: the wake word
lies 0.02 to 0.08 s before the end of the history (the socket opens at once, my guess about a
late freeze was wrong too), and her name was heard in 5 of 9 by `ganz_kw`, 2 of 9 by `ruf_kw`,
1 of 9 by `ganz`, 0 of 9 by `ruf`. A recogniser does not tell his call from the television
reliably enough, so TURNING AWAY IS GONE: the code for it was removed, `weckpruefung` 2 is the
same as 1, and what is heard is no longer written to the log. Listening without a greeting was
refused by Metin ("Ich muss schon hören, dass sie da ist"). The check stays as a counter; the
real cure is a wake word model trained with this room's sound (docs/WECKWORT.md, app/sammler.py).
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
CALL_BEFORE_S = 1.9     # the call ends shortly before the wake word fires: this much before it
CALL_AFTER_S = 0.2      # and a little after
KEYWORDS = ("Hallo Leyla", "Leyla")
# way of listening: (only the call, where the device said the wake word was; her name as a keyword)
WAYS = {"ganz": (False, False), "ganz_kw": (False, True),
        "ruf": (True, False), "ruf_kw": (True, True)}


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


def wake_of(message: str):
    """Milliseconds from the wake word to the end of the history, None when the device did not
    say (then the talk was not started by the wake word, or the firmware is older)."""
    try:
        ms = json.loads(message).get("wake_ms")
    except Exception:
        return None
    return int(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and 0 <= ms <= 10000 else None


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
    state["wake_ms"] = wake_of(first)
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


def call(pcm: bytes, rate: int, wake_ms) -> bytes:
    """The part of the history with the call: from CALL_BEFORE_S before the wake word to
    CALL_AFTER_S after it. b"" when the device did not say where the wake word was or the call
    lies before the history."""
    if wake_ms is None:
        return b""
    mark = len(pcm) // 2 - int(rate * wake_ms / 1000)          # sample where the wake word fired
    start, end = max(0, mark - int(rate * CALL_BEFORE_S)), min(len(pcm) // 2, mark + int(rate * CALL_AFTER_S))
    return pcm[start * 2:end * 2] if end - start >= rate // 2 else b""


def ways(setting) -> tuple:
    """The ways that count, from the server setting ("ganz_kw+ruf_kw"); unknown names are
    dropped, nothing left means the whole history with her name as a keyword."""
    names = tuple(n for n in str(setting or "").replace(",", "+").replace(" ", "").split("+")
                  if n in WAYS)
    return names or ("ganz_kw",)


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
               wake_ms=None, timeout: float = CHECK_TIMEOUT_S) -> dict:
    """What each way of listening hears, at the same time: {way: text, or None when it did not
    answer in time}. Without `wake_ms` only the ways that take the whole history."""
    part = call(pcm, rate, wake_ms)
    names = [n for n, (only_call, _) in WAYS.items() if part or not only_call]

    async def one(name: str):
        only_call, kw = WAYS[name]
        try:
            return await asyncio.wait_for(
                transcribe(wav(part if only_call else pcm, rate), api_key, client,
                           KEYWORDS if kw else ()), timeout)
        except Exception:
            return None
    return dict(zip(names, await asyncio.gather(*(one(n) for n in names))))


def verdict(texts: dict, use: tuple):
    """Was she called, by the ways that count? True when one of them heard her name, False when
    all of them answered and none did, None (taken as called) when one is missing. A way that
    could not run (no place of the wake word) does not count."""
    use = [n for n in use if n in texts] or [n for n in ("ganz_kw",) if n in texts]
    seen = [None if texts.get(n) is None else named(texts[n]) for n in use]
    if any(v is True for v in seen):
        return True
    return None if any(v is None for v in seen) or not seen else False


async def check(ws, state: dict, mode: int, tv_playing, api_key: str, use="ganz_kw") -> dict:
    """Take the history off the line and, with the TV running, look for her name in it.
    {"pre": seconds, "tv": bool, "named": bool or None, "s": seconds, "v": {way: bool or None},
    "wake": seconds from the wake word to the end of the history or None}; never raises.
    `tv_playing`: async function, True when the TV is on and not muted. `use`: the ways that
    count for `named` (setting `weckart`); all ways are heard and reported. The result is only
    logged and counted: no talk is turned away and none starts differently because of it."""
    started = time.monotonic()
    out = {"pre": 0.0, "tv": False, "named": None}
    try:
        pcm, rate = await read(ws, state)
        wake_ms = state.get("wake_ms")
        if pcm:
            state["preroll"] = (pcm, rate)
            out["pre"] = round(len(pcm) / (rate * 2), 1)
            out["wake"] = None if wake_ms is None else round(wake_ms / 1000, 2)
        if pcm and mode >= 1 and api_key:
            out["tv"] = bool(await tv_playing())
            if out["tv"]:
                use = ways(use)
                async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
                    texts = await hear(pcm, rate, api_key, client, wake_ms)
                out["v"] = {n: (None if t is None else named(t)) for n, t in texts.items()}
                out["named"] = verdict(texts, use)
    except Exception as e:
        logger.info("Wake check not finished (%s): she is taken as called", e or type(e).__name__)
        out["named"] = None
    out["s"] = round(time.monotonic() - started, 2)
    return out
