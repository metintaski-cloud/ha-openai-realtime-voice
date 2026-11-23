"""Leyla's voice reply in the app, played while it is still being spoken (2.142.0, Metin).

Measured on 23 Nov 2026 on the go: hearing 1 s, answer 3 to 6 s, voice 15 to 24 s, the line
about 1 s. The server waited until the whole reply was spoken and only then sent it. Now the
text goes out at once, the voice is spoken in the background and each piece of PCM is handed
to the phone as soon as it exists, so she starts talking about a second after the text.
"""
import asyncio
import secrets
import time

KEEP_S = 300          # a finished stream stays this long, for a late or repeated fetch
MAX_STREAMS = 20


class Stream:
    def __init__(self):
        self.chunks = []
        self.done = False
        self.born = time.monotonic()
        self._event = asyncio.Event()

    def push(self, pcm: bytes) -> None:
        if pcm and not self.done:
            self.chunks.append(bytes(pcm))
            self._event.set()

    def finish(self) -> None:
        self.done = True
        self._event.set()

    async def read(self, wait_s: float = 60.0):
        """Every chunk from the start, then the new ones as they come, until done."""
        i = 0
        end = time.monotonic() + wait_s
        while True:
            while i < len(self.chunks):
                yield self.chunks[i]
                i += 1
            if self.done or time.monotonic() > end:
                return
            self._event.clear()
            if i < len(self.chunks) or self.done:
                continue
            try:
                await asyncio.wait_for(self._event.wait(), timeout=max(0.1, end - time.monotonic()))
            except asyncio.TimeoutError:
                return


STREAMS = {}


def new() -> tuple:
    """A new stream and its id (random, so only the phone that asked knows it)."""
    now = time.monotonic()
    for k in [k for k, s in STREAMS.items() if now - s.born > KEEP_S]:
        STREAMS.pop(k, None)
    while len(STREAMS) >= MAX_STREAMS:
        STREAMS.pop(next(iter(STREAMS)))
    sid = secrets.token_hex(12)
    STREAMS[sid] = Stream()
    return sid, STREAMS[sid]


def get(sid: str):
    return STREAMS.get(sid)
