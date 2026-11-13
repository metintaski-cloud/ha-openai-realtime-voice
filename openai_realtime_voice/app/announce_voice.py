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
SPEECH_END_GAP_S = 1.2  # GPT Live keeps sending silence after the speech: stop after this


class AnnounceVoiceMixin:
    def _announce_session_start(self) -> dict:
        return {
            "type": "session.start",
            "event_id": "event_announce",
            "session": {
                "model": self.live_model,
                "instructions": SPEAK_INSTRUCTIONS,
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

    async def _collect_speech(self, ws, prompt: str, max_s: float) -> bytes:
        """Start the speaking session on ws, send the prompt and collect the speech (PCM)."""
        pcm = bytearray()
        feeder = None
        try:
            await ws.send(json.dumps(self._announce_session_start()))
            loop = asyncio.get_event_loop()
            end = loop.time() + max_s
            started = False
            last_audio = None
            loud_end = 0
            while loop.time() < end:
                wait = SPEECH_END_GAP_S if last_audio else end - loop.time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, wait))
                except asyncio.TimeoutError:
                    if last_audio:
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
                    if peak >= OUTPUT_SILENCE_PEAK:
                        last_audio = loop.time()
                        pcm += chunk_pcm
                        loud_end = len(pcm)
                    elif last_audio:
                        pcm += chunk_pcm  # pauses inside the speech
                    if last_audio and loop.time() - last_audio > SPEECH_END_GAP_S:
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

    async def _speak_once(self, prompt: str, max_s: float = 40.0) -> bytes:
        """Let GPT Live speak one announcement without a listener; return 24 kHz PCM."""
        ws, _ = await self._take_live()
        try:
            pcm = await self._collect_speech(ws, prompt, max_s)
        finally:
            await ws.close()
        logger.info("Announcement audio: %.1f s", len(pcm) / BYTES_PER_SEC)
        return pcm

    async def _tv_down_for_announcement(self) -> None:
        """Turn the TV down before an announcement, unless a conversation already did."""
        if self.tv.available and not self._active_sessions:
            await self.tv.duck()

    async def _tv_up_after_announcement(self) -> None:
        if self.tv.available and not self._active_sessions:
            await self.tv.unduck()

