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
# 24 Nov 2026: three of eight voice replies in the app came back empty (0.0 s after waiting the
# whole 60 s, or 0.2 s: one loud chunk, then the 1.2 s gap ended it before she spoke), and the
# app showed a speaker sign without any sound. So: no audio within FIRST_AUDIO_S gives up early,
# a blip shorter than MIN_SPEECH_S does not count as the end, and _speak_once tries once more.
FIRST_AUDIO_S = 12.0
MIN_SPEECH_S = 0.3


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
    async def _feed_silence(ws) -> None:
        # GPT Live runs on the input audio clock: without input it never
        # finishes injecting the commentary, so feed real-time silence.
        chunk = base64.standard_b64encode(b"\x00" * (BYTES_PER_SEC // 10)).decode("ascii")
        while True:
            await ws.send(json.dumps({"type": "session.input_audio.append", "audio": chunk}))
            await asyncio.sleep(0.1)

    async def _collect_speech(self, ws, prompt: str, max_s: float,
                              instructions: str = SPEAK_INSTRUCTIONS, on_chunk=None) -> bytes:
        """Start the speaking session on ws, send the prompt and collect the speech (PCM)."""
        pcm = bytearray()
        feeder = None
        try:
            await ws.send(json.dumps(self._announce_session_start(instructions)))
            loop = asyncio.get_event_loop()
            end = loop.time() + max_s
            started = False
            last_audio = None
            loud_end = 0
            give_up = loop.time() + FIRST_AUDIO_S

            def spoken() -> bool:  # more than a blip: the gap after it is the end of her speech
                return loud_end >= MIN_SPEECH_S * BYTES_PER_SEC

            while loop.time() < end:
                if not spoken() and loop.time() > give_up:
                    break  # she did not start to speak: the caller tries again
                wait = SPEECH_END_GAP_S if last_audio else min(end, give_up) - loop.time()
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
                if t == "session.started" and not started:
                    started = True
                    feeder = asyncio.create_task(self._feed_silence(ws))
                    await ws.send(json.dumps({
                        "type": "session.commentary.append",
                        "event_id": f"announce_{uuid.uuid4().hex[:8]}",
                        "delegation_id": None, "content": prompt}))
                elif t == "session.output_audio.delta" and ev.get("delta"):
                    chunk_pcm = base64.standard_b64decode(ev["delta"])
                    _, peak = pcm_level(chunk_pcm)
                    if peak >= (OUTPUT_SILENCE_PEAK if last_audio else ANNOUNCE_START_PEAK):
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
        return bytes(pcm[:loud_end + BYTES_PER_SEC // 4])  # drop trailing silence

    async def _speak_once(self, prompt: str, max_s: float = 40.0,
                          instructions: str = SPEAK_INSTRUCTIONS, on_chunk=None) -> bytes:
        """Let GPT Live speak one announcement without a listener; return 24 kHz PCM.
        `instructions`: who speaks; the default is the announcement voice, a voice reply in
        the app chat passes Leyla talking to Metin (2.98.7)."""
        pcm = b""
        for attempt in (1, 2):
            ws, _ = await self._take_live()
            try:
                pcm = await self._collect_speech(ws, prompt, max_s, instructions, on_chunk)
            finally:
                await ws.close()
            logger.info("Announcement audio: %.1f s", len(pcm) / BYTES_PER_SEC)
            if len(pcm) >= MIN_SPEECH_S * BYTES_PER_SEC:
                break
            if attempt == 1:
                logger.warning("GPT Live did not speak, trying once more")
        return pcm

    async def _tv_down_for_announcement(self) -> None:
        """Turn the TV down before an announcement, unless a conversation already did."""
        if self.tv.available and not self._active_sessions:
            await self.tv.duck()

    async def _tv_up_after_announcement(self) -> None:
        if self.tv.available and not self._active_sessions:
            await self.tv.unduck()

