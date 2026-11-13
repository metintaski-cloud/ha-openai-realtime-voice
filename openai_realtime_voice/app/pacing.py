"""
Pacing of reply audio to the Voice PE: GPT Live streams at about real time, the ESP only
queues a few chunks, so audio is held until a small buffer is full and then sent at playback
rate, a little ahead (see AGENTS.md, session learnings).
"""
import array
import asyncio
import sys
from typing import Optional

SAMPLE_RATE = 24000
BYTES_PER_SEC = SAMPLE_RATE * 2  # 16-bit = 2 bytes per sample -> 48 000 B/s
SEND_CHUNK_SIZE = BYTES_PER_SEC * 20 // 1000  # 960 bytes = 20 ms of audio
PREBUFFER_S = 0.2
PREBUFFER_BYTES = int(BYTES_PER_SEC * PREBUFFER_S) // 2 * 2
PREBUFFER_MAX_WAIT_S = 0.25
OUTPUT_LEAD_S = 0.2
# GPT Live may stream quiet frames while it is not talking: frames below this peak are silence.
OUTPUT_SILENCE_PEAK = 300


def pcm_level(pcm: bytes) -> tuple[int, int]:
    """Return (rms, peak) of 16-bit little-endian mono PCM. Used for diagnostics."""
    if len(pcm) < 2:
        return 0, 0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(abs(x) for x in samples)
    rms = int((sum(x * x for x in samples) / len(samples)) ** 0.5)
    return rms, peak


class PacedSender:
    """Buffers reply audio and sends it to the client at playback rate, OUTPUT_LEAD_S ahead.
    A reply starts only once PREBUFFER_S is buffered or PREBUFFER_MAX_WAIT_S has passed."""

    def __init__(self, client_ws) -> None:
        self.client_ws = client_ws
        self.buffer = bytearray()
        self.bytes_sent = 0
        self.start_time: Optional[float] = None
        self.first_chunk_at: Optional[float] = None

    def reset(self) -> None:
        """Forget the pacing clock; the next reply starts fresh."""
        self.bytes_sent = 0
        self.start_time = None
        self.first_chunk_at = None

    def add(self, chunk: bytes) -> None:
        if self.start_time is None and not self.buffer:
            self.first_chunk_at = asyncio.get_event_loop().time()
        self.buffer.extend(chunk)

    async def pump(self, flush: bool = False, force: bool = False) -> None:
        """Send what is buffered at playback rate."""
        loop = asyncio.get_event_loop()
        if not self.buffer:
            return
        if self.start_time is None:
            waited = loop.time() - (self.first_chunk_at or loop.time())
            if not force and len(self.buffer) < PREBUFFER_BYTES and waited < PREBUFFER_MAX_WAIT_S:
                return
            self.start_time = loop.time()
        while len(self.buffer) >= SEND_CHUNK_SIZE or (flush and self.buffer):
            n = min(SEND_CHUNK_SIZE, len(self.buffer))
            to_send = bytes(self.buffer[:n])
            del self.buffer[:n]
            self.bytes_sent += n
            target_time = self.start_time + self.bytes_sent / BYTES_PER_SEC - OUTPUT_LEAD_S
            now = loop.time()
            if target_time > now:
                await asyncio.sleep(target_time - now)
            await self.client_ws.send(to_send)
