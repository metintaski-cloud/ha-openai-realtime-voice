"""
Announcements spoken by GPT Live without a listener (HA event leyla_announce, messages from
Metin): one short session that only speaks the given text, collected as 24 kHz PCM, plus the
TV volume around a played announcement. Mixed into the bridge; needs self.live_model,
self.backend_model, self.voice, self.tv, self._active_sessions and self._take_live from it.
"""
import asyncio
import base64
import json
import logging
import uuid

from app.live_link import END_CONVERSATION_TOOL
from app.pacing import BYTES_PER_SEC, OUTPUT_SILENCE_PEAK, SAMPLE_RATE, pcm_level

logger = logging.getLogger(__name__)

SPEAK_INSTRUCTIONS = (
    "Du bist Leyla, eine warme, fröhliche und lebendige Sprachassistentin der Familie. "
    "Du sprichst mit viel Gefühl, natürlicher Betonung und einem Lächeln in der Stimme, nie "
    "monoton, aber ohne Kosewörter wie „canım“. Du machst nur die verlangte kurze Ansage "
    "und redest danach nicht weiter.")
# A soft breath in before the first word is far quieter than speech (below OUTPUT_SILENCE_PEAK), but the
# idle frames GPT Live streams are exactly 0, so a low threshold keeps the breath and drops nothing else.
ANNOUNCE_START_PEAK = 30
SPEECH_END_GAP_S = 1.2  # GPT Live keeps sending silence after the speech: stop after this
# 24 Nov 2026: three of eight voice replies in the app came back empty, and the retry of
# 2.150.7 did not help at 05:21 (twice 0.0 s). Measured with /api/kopf/stimme (2.150.8, 7 runs,
# 2 silent, with and without mood and closeness in the instructions): in a silent session GPT
# Live confirms the note (session.commentary.appended) and then sends only zero audio and not
# one word of transcript, it simply does not take its turn; when she speaks, the first word
# comes within a second. So: no word NUDGE_AFTER_S after the note sends it once more in the
# same session, no speech within FIRST_AUDIO_S gives up, a blip shorter than MIN_SPEECH_S is
# not the end of her speech, and _speak_once takes up to SPEAK_TRIES fresh sessions.
# 2.151.0: a voice reply she only said from a text sounded read to Metin ("klingt wie Roboter",
# "nicht die voice ai von gpt"). Measured with /api/kopf/stimme (2.150.12): when she hears a
# recording herself and the note with the content comes after it, she answers 0.5 s later in
# her own words. With the note before the recording she talks into it (first word after 5.8 s
# of a 9.9 s recording, or only "Mmm."), and a recording fed faster than real time is an error.
# So: first a note to listen in silence, the recording in real time, then the note.
LISTEN_NOTE = ("Interne Notiz, nicht vorlesen: Metin schickt dir jetzt eine Sprachnachricht. "
               "Hör sie dir still bis zum Ende an und sag nichts dazu, auch kein „Mhm“, bis "
               "gleich die nächste Notiz kommt.")
NUDGE_AFTER_S = 3.0
FIRST_AUDIO_S = 8.0
MIN_SPEECH_S = 0.3
SPEAK_TRIES = 3
# Events not worth keeping when a session stayed silent (the audio itself, counters).
QUIET_EVENTS = ("session.output_audio.delta", "session.usage.updated", "session.started")


class AnnounceVoiceMixin:
    def _announce_session_start(self, instructions: str = SPEAK_INSTRUCTIONS) -> dict:
        return {
            "type": "session.start",
            "event_id": "event_announce",
            "session": {
                "model": self.live_model,
                "instructions": instructions,
                "audio": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                          "output": {"voice": self.voice}},
                "delegation": {"type": "responses", "responses": {
                    "model": self.backend_model, "instructions": "Do nothing.",
                    "tools": [END_CONVERSATION_TOOL], "tool_choice": "auto",
                    "parallel_tool_calls": False}},
            },
        }

    @staticmethod
    async def _feed_silence(ws, heard: bytes = b"", fed=None) -> None:
        # GPT Live runs on the input audio clock: without input it never
        # finishes injecting the commentary, so feed real-time silence.
        # `heard`: a recording she hears first (24 kHz PCM), in real time; `fed` is set after it.
        step = BYTES_PER_SEC // 10
        for i in range(0, len(heard), step):
            part = base64.standard_b64encode(heard[i:i + step]).decode("ascii")
            await ws.send(json.dumps({"type": "session.input_audio.append", "audio": part}))
            await asyncio.sleep(0.1)
        if fed is not None:
            fed.set()
        chunk = base64.standard_b64encode(b"\x00" * step).decode("ascii")
        while True:
            await ws.send(json.dumps({"type": "session.input_audio.append", "audio": chunk}))
            await asyncio.sleep(0.1)

    async def _collect_speech(self, ws, prompt, max_s: float,
                              instructions: str = SPEAK_INSTRUCTIONS, on_chunk=None,
                              heard: bytes = b"") -> bytes:
        """Start the speaking session on ws, send the prompt and collect the speech (PCM).
        `prompt`: the note that makes her speak, a text or a future of one ("" = say nothing).
        `heard`: a recording (24 kHz PCM) she hears herself before the note, so she answers a
        voice and not a text; what she says before the note is dropped."""
        pcm = bytearray()
        feeder = None
        seen: dict = {}   # event type -> count: what GPT Live sent, for a silent session
        other: list = []  # the first events besides audio and words, shortened (errors)
        said: list = []   # her words as GPT Live reports them
        understood: list = []  # what GPT Live understood of the recording
        self._speak_seen = info = {"events": seen, "other": other, "nudged": False}
        fed = asyncio.Event()  # the recording is through
        later = asyncio.isfuture(prompt)
        text = "" if later else prompt
        try:
            await ws.send(json.dumps(self._announce_session_start(instructions)))
            loop = asyncio.get_event_loop()
            t_start = loop.time()
            end = t_start + max_s
            started = False
            armed = False     # the note went out: from now on it is her answer
            last_audio = None
            loud_end = 0
            early = 0         # bytes she spoke before the note (dropped)
            give_up = end
            nudge_at = None

            async def note(content: str, kind: str = "announce") -> None:
                await ws.send(json.dumps({
                    "type": "session.commentary.append",
                    "event_id": f"{kind}_{uuid.uuid4().hex[:8]}",
                    "delegation_id": None, "content": content}))

            async def arm() -> None:
                nonlocal armed, nudge_at, give_up
                armed = True
                info["note_s"] = round(loop.time() - t_start, 1)
                await note(text)
                nudge_at = loop.time() + NUDGE_AFTER_S
                give_up = loop.time() + FIRST_AUDIO_S

            def spoken() -> bool:  # more than a blip: the gap after it is the end of her speech
                return loud_end >= MIN_SPEECH_S * BYTES_PER_SEC

            while loop.time() < end:
                if started and not armed and (fed.is_set() or not heard) and (
                        not later or prompt.done()):
                    if later:
                        text = "" if prompt.cancelled() or prompt.exception() else prompt.result()
                    if not text:
                        break  # nothing to say
                    await arm()
                if not started and loop.time() > t_start + FIRST_AUDIO_S:
                    break  # the session did not even start
                if armed and not spoken() and loop.time() > give_up:
                    break  # she did not start to speak: the caller tries again
                if nudge_at and not last_audio and not said and loop.time() > nudge_at:
                    nudge_at = None  # she let her turn pass: the same note once more
                    info["nudged"] = True
                    await note(text)
                wait = SPEECH_END_GAP_S if last_audio else (
                    min(end, give_up, nudge_at or end) - loop.time())
                if not armed:
                    wait = min(wait, 0.2)  # look often for the recording's end and the note
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, wait))
                except asyncio.TimeoutError:
                    if last_audio and spoken():
                        break
                    continue
                if not isinstance(raw, str):
                    continue
                ev = json.loads(raw)
                t = ev.get("type")
                seen[t] = seen.get(t, 0) + 1
                if t == "session.output_transcript.delta":
                    if armed:
                        said.append(ev.get("delta") or "")
                elif t == "session.input_transcript.delta":
                    understood.append(ev.get("delta") or "")
                elif t not in QUIET_EVENTS and len(other) < 12:
                    other.append(raw[:300])
                if t == "session.started" and not started:
                    started = True
                    if heard:  # her turn comes when the recording is through and the note is there
                        await note(LISTEN_NOTE, "listen")
                        feeder = asyncio.create_task(self._feed_silence(ws, heard, fed))
                        info["heard_s"] = round(len(heard) / BYTES_PER_SEC, 1)
                    else:
                        feeder = asyncio.create_task(self._feed_silence(ws))
                elif t == "session.output_audio.delta" and ev.get("delta"):
                    chunk_pcm = base64.standard_b64decode(ev["delta"])
                    _, peak = pcm_level(chunk_pcm)
                    if not armed:
                        if peak >= OUTPUT_SILENCE_PEAK:
                            early += len(chunk_pcm)
                        continue
                    if peak >= (OUTPUT_SILENCE_PEAK if last_audio else ANNOUNCE_START_PEAK):
                        if last_audio is None:
                            info["first_s"] = round(loop.time() - t_start, 1)
                        last_audio = loop.time()
                        pcm += chunk_pcm
                        loud_end = len(pcm)
                        if on_chunk:
                            on_chunk(chunk_pcm)  # 2.142.0: the app plays it while she speaks
                    elif last_audio:
                        pcm += chunk_pcm  # pauses inside the speech
                        if on_chunk:
                            on_chunk(chunk_pcm)
                    if last_audio and spoken() and loop.time() - last_audio > SPEECH_END_GAP_S:
                        break
                elif t == "error":
                    raise RuntimeError(f"GPT Live: {ev.get('error')}")
            try:
                await ws.send(json.dumps({"type": "session.close"}))
            except Exception:
                pass
        finally:
            if feeder and not feeder.done():
                feeder.cancel()
            info["said"] = "".join(said).strip()
            info["understood"] = "".join(understood).strip()
            info["early_s"] = round(early / BYTES_PER_SEC, 1)
        return bytes(pcm[:loud_end + BYTES_PER_SEC // 4])  # drop trailing silence

    async def _speak_once(self, prompt, max_s: float = 40.0,
                          instructions: str = SPEAK_INSTRUCTIONS, on_chunk=None,
                          heard: bytes = b"", heard_prompt=None) -> bytes:
        """Let GPT Live speak one announcement without a listener; return 24 kHz PCM.
        `instructions`: who speaks; the default is the announcement voice, a voice reply in
        the app chat passes Leyla talking to Metin (2.98.7). `prompt` may be a future.
        `heard` and `heard_prompt`: the first try lets her hear this recording and answer it
        (2.151.0); a silent first try falls back to the plain prompt without the recording."""
        pcm = b""
        for attempt in range(1, SPEAK_TRIES + 1):
            listen = bool(heard) and heard_prompt is not None and attempt == 1
            note = heard_prompt if listen else prompt
            ws, _ = await self._take_live()
            try:
                pcm = await self._collect_speech(ws, note, max_s, instructions, on_chunk,
                                                 heard=heard if listen else b"")
            finally:
                await ws.close()
            logger.info("Announcement audio: %.1f s%s", len(pcm) / BYTES_PER_SEC,
                        " (she heard %.1f s first)" % (len(heard) / BYTES_PER_SEC) if listen else "")
            if len(pcm) >= MIN_SPEECH_S * BYTES_PER_SEC:
                break
            if asyncio.isfuture(note) and note.done() and (
                    note.cancelled() or note.exception() or not note.result()):
                break  # there was nothing to say
            logger.warning("GPT Live did not speak (try %d of %d): events %s", attempt,
                           SPEAK_TRIES, json.dumps(self._speak_seen["events"], ensure_ascii=False))
        return pcm

    async def _speak_test(self, text: str, instructions: str, prompt, heard: bytes = b"") -> dict:
        """One spoken sentence without a listener and without any trace, for /api/kopf/stimme:
        how long she spoke and what GPT Live sent (to find out why she sometimes stays silent)."""
        loop = asyncio.get_event_loop()
        t0 = loop.time()
        ws, warm = await self._take_live()
        try:
            pcm = await self._collect_speech(ws, prompt, 40.0, instructions, heard=heard)
        except RuntimeError as e:
            return {"ok": False, "why": str(e)[:300], **self._speak_seen}
        finally:
            await ws.close()
        self._last_test_pcm = pcm
        return {"ok": True, "audio_s": round(len(pcm) / BYTES_PER_SEC, 1), "warm": warm,
                "took_s": round(loop.time() - t0, 1), **self._speak_seen}

    async def _tv_down_for_announcement(self) -> None:
        """Turn the TV down before an announcement, unless a conversation already did."""
        if self.tv.available and not self._active_sessions:
            await self.tv.duck()

    async def _tv_up_after_announcement(self) -> None:
        if self.tv.available and not self._active_sessions:
            await self.tv.unduck()

