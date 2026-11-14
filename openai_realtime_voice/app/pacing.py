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
# Soft edges: where the audio stops (end of a reply or a pause) the last 15 ms are faded to zero and the
# next audio fades in over 5 ms, so the speaker never jumps from a level to silence (a click). Only
# existing samples are changed, nothing is added, so the timing stays as it was.
FADE_OUT_BYTES = SAMPLE_RATE * 15 // 1000 * 2  # 720 bytes
FADE_IN_BYTES = SAMPLE_RATE * 5 // 1000 * 2    # 240 bytes


def fade_out(buf: bytearray) -> None:
    """Fade the last FADE_OUT_BYTES of 16-bit mono PCM to zero, in place."""
    n = min(len(buf), FADE_OUT_BYTES) // 2
    if n == 0:
        return
    tail = array.array("h")
    tail.frombytes(bytes(buf[len(buf) // 2 * 2 - n * 2: len(buf) // 2 * 2]))
    if sys.byteorder == "big":
        tail.byteswap()
    for i in range(n):
        tail[i] = tail[i] * (n - 1 - i) // n
    if sys.byteorder == "big":
        tail.byteswap()
    end = len(buf) // 2 * 2
    buf[end - n * 2:end] = tail.tobytes()


def fade_in(chunk: bytes) -> bytes:
    """Fade in the first FADE_IN_BYTES of 16-bit mono PCM."""
    n = min(len(chunk), FADE_IN_BYTES) // 2
    if n == 0:
        return chunk
    head = array.array("h")
    head.frombytes(chunk[: n * 2])
    if sys.byteorder == "big":
        head.byteswap()
    for i in range(n):
        head[i] = head[i] * (i + 1) // (n + 1)
    if sys.byteorder == "big":
        head.byteswap()
    return head.tobytes() + chunk[n * 2:]


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
        self.faded = False  # the last audio sent was faded out: fade the next in

    def reset(self) -> None:
        """Forget the pacing clock; the next reply starts fresh."""
        self.bytes_sent = 0
        self.start_time = None
        self.first_chunk_at = None

    def add(self, chunk: bytes) -> None:
        if self.start_time is None and not self.buffer:
            self.first_chunk_at = asyncio.get_event_loop().time()
        if self.faded and chunk:
            chunk = fade_in(chunk)
            self.faded = False
        self.buffer.extend(chunk)

    async def pump(self, flush: bool = False, force: bool = False) -> None:
        """Send what is buffered at playback rate."""
        loop = asyncio.get_event_loop()
        if not self.buffer:
            return
        if self.start_time is None:
            waited = loop.time() - (self.first_chunk_at or loop.time())
            # the last 15 ms stay back for the fade, so the reserve that goes out is still PREBUFFER_S
            if not force and len(self.buffer) < PREBUFFER_BYTES + FADE_OUT_BYTES and waited < PREBUFFER_MAX_WAIT_S:
                return
            self.start_time = loop.time()
        if flush:  # the audio stops here: fade out its end
            fade_out(self.buffer)
            self.faded = True
        # Keep the last 15 ms back until more audio comes or the flush, so there is something left to fade
        hold = 0 if flush else FADE_OUT_BYTES
        while len(self.buffer) - hold >= SEND_CHUNK_SIZE or (flush and self.buffer):
            n = min(SEND_CHUNK_SIZE, len(self.buffer))
            to_send = bytes(self.buffer[:n])
            del self.buffer[:n]
            self.bytes_sent += n
            target_time = self.start_time + self.bytes_sent / BYTES_PER_SEC - OUTPUT_LEAD_S
            now = loop.time()
            if target_time > now:
                await asyncio.sleep(target_time - now)
            await self.client_ws.send(to_send)
