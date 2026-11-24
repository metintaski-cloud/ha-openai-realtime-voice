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


async def transcribe(audio: bytes, api_key: str, client: httpx.AsyncClient) -> str:
    """What a speech recogniser hears in a wav ("" for nothing)."""
    for model in chat.TRANSCRIBE_MODELS:
        try:
            resp = await client.post(chat.TRANSCRIBE_URL,
                                     headers={"Authorization": f"Bearer {api_key}"},
                                     data={"model": model},
                                     files={"file": ("wake.wav", audio, "audio/wav")})
        except Exception as e:
            logger.warning("Wake check: not transcribed (%s): %s", model, e or type(e).__name__)
            continue
        if resp.status_code == 200:
            return (resp.json().get("text") or "").strip()
    return ""


async def check(ws, state: dict, mode: int, tv_playing, api_key: str) -> dict:
    """Take the history off the line and, with the TV running, look for her name in it.
    {"pre": seconds, "tv": bool, "named": bool or None, "reject": bool, "s": seconds}; never
    raises. `tv_playing`: async function, True when the TV is on and not muted."""
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
                async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
                    text = await asyncio.wait_for(transcribe(wav(pcm, rate), api_key, client),
                                                  CHECK_TIMEOUT_S)
                out["named"] = named(text)
                out["heard"] = text[:120]
                out["reject"] = mode >= 2 and not out["named"]
    except Exception as e:
        logger.info("Wake check not finished (%s): she is taken as called", e or type(e).__name__)
        out["named"], out["reject"] = None, False
    out["s"] = round(time.monotonic() - started, 2)
    return out
