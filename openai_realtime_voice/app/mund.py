"""Her mouth on the living room TV, live (2.199.0).

Metin's PC runs the mouth service (tools/mundprobe/munddienst.py): it plays her clip as one video stream to the
TV and, while her voice comes in, computes mouth and chin for every picture. Her voice still comes from the Voice
PE (if it came from the TV, the Voice PE would hear it and she would interrupt herself). So two things happen here:

- MundLink: one TCP connection to the PC. Every piece of reply audio goes there the moment GPT Live sends it,
  framed as 1 byte kind + 4 bytes length + payload (S start with {"in_ms"}, A audio, E end, X abort). The PC
  answers once a second with a JSON line {"bereit", "zuschauer", "strom_ms"}.
- Ausgang: the output queue of a talk. While the mouth is active it holds everything of a reply back for
  delay_s, so the PC has time to compute; then it lets the reply through at once, and the paced sender plays it
  as before, only later. With the mouth off (no host set, PC off, nobody watching the stream, talk from the app)
  it behaves like a plain queue: nothing changes.

The promise to the PC is "the first sound of this reply plays at the Voice PE in in_ms from now"; the PC shows
the matching picture at that moment.
"""
import asyncio
import collections
import json
import logging
import os
import struct
import time
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

TON_PORT = 8091
SEITE_PORT = 8090
BYTES_PER_SEC = 48000          # 24 kHz, 16 bit, mono
GAP_S = 0.3                    # no audio for this long: the reply is over (the paced sender resets after the same time)
STALE_S = 4.0                  # a status line older than this does not count
RETRY_S = 5.0
MAX_BACKLOG = 2_000_000        # bytes waiting in the socket: the PC does not read, drop the connection


class MundLink:
    """The connection to the mouth service on the PC. All senders are plain calls that never wait."""

    def __init__(self, host: str, delay_s: float = 1.2, fein_ms: float = 100.0, back_url: str = "",
                 port: int = TON_PORT, page_port: int = SEITE_PORT) -> None:
        self.host = host.strip()
        self.port, self.page_port = port, page_port
        self.delay_s = max(0.0, delay_s)
        self.fein_ms = fein_ms          # how long the Voice PE needs from the frame to the sound, to tune by eye
        self.back_url = back_url
        self._writer: Optional[asyncio.StreamWriter] = None
        self._stand: dict = {}
        self._stand_at = 0.0
        self.sent = {"S": 0, "A": 0, "E": 0, "X": 0}

    @classmethod
    def from_env(cls, back_url: str = "") -> Optional["MundLink"]:
        host = (os.environ.get("MUND_HOST") or "").strip()
        if not host or host == "null":
            return None

        def num(name: str, default: float) -> float:
            try:
                return float(os.environ.get(name) or default)
            except ValueError:
                return default

        return cls(host, delay_s=num("MUND_DELAY_MS", 1200) / 1000.0, fein_ms=num("MUND_FEIN_MS", 100), back_url=back_url)

    # ------------------------------------------------------------------ state
    def _fresh(self) -> bool:
        return self._writer is not None and time.monotonic() - self._stand_at < STALE_S

    def ready(self) -> bool:
        """The service runs and has its models loaded: the TV may open its page."""
        return self._fresh() and bool(self._stand.get("bereit"))

    def active(self) -> bool:
        """Somebody watches the stream right now: only then is a reply held back for the mouth."""
        return self.ready() and bool(self._stand.get("zuschauer"))

    def page(self) -> str:
        """The page on the PC for the TV; it goes back to back_url when the stream breaks."""
        url = f"http://{self.host}:{self.page_port}/"
        if self.back_url:
            back = self.back_url + ("&" if "?" in self.back_url else "?") + "mundaus=1"
            url += "?zurueck=" + quote(back, safe="")
        return url

    # ------------------------------------------------------------------ sending
    def _send(self, kind: str, payload: bytes = b"") -> None:
        w = self._writer
        if w is None:
            return
        try:
            if w.transport.get_write_buffer_size() > MAX_BACKLOG:
                raise ConnectionError("the mouth service does not read")
            w.write(struct.pack(">cI", kind.encode(), len(payload)) + payload)
            self.sent[kind] += 1
        except Exception as e:
            logger.warning("Mouth: sending failed (%s), connection dropped", e)
            self._drop()

    def start(self, in_ms: float) -> None:
        self._send("S", json.dumps({"in_ms": round(in_ms)}).encode())

    def audio(self, pcm: bytes) -> None:
        self._send("A", bytes(pcm))

    def end(self) -> None:
        self._send("E")

    def abort(self) -> None:
        self._send("X")

    def _drop(self) -> None:
        w, self._writer = self._writer, None
        if w is not None:
            try:
                w.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ the connection
    async def run(self) -> None:
        """Keep the connection up for as long as the add on runs. The PC may be off for days: quiet retries."""
        told = False
        while True:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=3)
            except (OSError, asyncio.TimeoutError):
                if not told:
                    logger.info("Mouth: the service on %s:%s is not there (PC off?), trying again every %d s",
                                self.host, self.port, int(RETRY_S))
                    told = True
                await asyncio.sleep(RETRY_S)
                continue
            told = False
            self._writer = writer
            logger.info("Mouth: connected to the service on %s:%s", self.host, self.port)
            try:
                was = None
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout=STALE_S * 2)
                    if not line:
                        break
                    try:
                        self._stand = json.loads(line)
                    except ValueError:
                        continue
                    self._stand_at = time.monotonic()
                    now = (bool(self._stand.get("bereit")), bool(self._stand.get("zuschauer")))
                    if now != was:
                        was = now
                        logger.info("Mouth: service ready=%s, TV watching=%s, stream delay %s ms",
                                    now[0], now[1], self._stand.get("strom_ms"))
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                pass
            finally:
                self._drop()
                self._stand = {}
                logger.info("Mouth: connection to the service lost")
            await asyncio.sleep(RETRY_S)


class Ausgang:
    """The output queue of one talk (what asyncio.Queue was), with the hold for the mouth.

    Order is never changed. Every item gets a release time; get() gives the oldest item once its time has come.
    Without a mouth (or while it is not active) every release time is "now": a plain queue."""

    def __init__(self, mund: Optional[MundLink] = None) -> None:
        self.mund = mund
        self._items: collections.deque = collections.deque()   # [release time, item]
        self._wake = asyncio.Event()
        self._gate = 0.0            # release time of the running reply
        self._last_audio = -1e9     # when the last piece of audio came in
        self._play_end = 0.0        # when the Voice PE will have played everything let through so far
        self._hold = False          # the running reply is held for the mouth

    # ------------------------------------------------------------------ in
    def put_nowait(self, item) -> None:
        now = time.monotonic()
        if isinstance(item, (bytes, bytearray)):
            if now - self._last_audio > GAP_S:                 # a new reply (or the next part after a pause)
                self._close(now)
                self._hold = bool(self.mund and self.mund.active())
                delay = self.mund.delay_s if self._hold else 0.0
                self._gate = now + delay
                start = max(self._gate, self._play_end)        # the Voice PE may still be playing the part before
                self._play_end = start
                if self._hold:
                    self.mund.start((start - now) * 1000.0 + self.mund.fein_ms)
            self._last_audio = now
            self._play_end += len(item) / BYTES_PER_SEC
            if self._hold:
                self.mund.audio(item)
            release = max(self._gate, now)
        elif isinstance(item, tuple) and item and item[0] == "interrupt":
            # she was interrupted: nothing waits, and her mouth on the TV stops with her voice
            if self._hold and self.mund:
                self.mund.abort()
            self._hold = False
            self._last_audio = -1e9
            self._gate = self._play_end = now
            release = now
        else:
            # phases, scenes, errors travel with the audio around them: late by the same hold
            running = now - self._last_audio <= GAP_S
            delay = self.mund.delay_s if (self.mund and (self._hold if running else self.mund.active())) else 0.0
            release = max(self._gate, now) if running else now + delay
        self._items.append([release, item])
        self._wake.set()

    async def put(self, item) -> None:
        self.put_nowait(item)

    def _close(self, now: float) -> None:
        """The reply before is over: tell the PC, so it finishes the last pictures."""
        if self._hold and self.mund:
            self.mund.end()
        self._hold = False

    # ------------------------------------------------------------------ out
    async def get(self):
        """The oldest item, once its release time has come. Safe to cancel (wait_for): nothing is taken before."""
        while True:
            now = time.monotonic()
            if self._hold and now - self._last_audio > GAP_S:
                self._close(now)
            if self._items:
                wait = self._items[0][0] - now
                if wait <= 0:
                    return self._items.popleft()[1]
            else:
                wait = GAP_S if self._hold else None
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    def get_nowait(self):
        """The oldest item whether its time has come or not (used to drop everything on an interrupt)."""
        if not self._items:
            raise asyncio.QueueEmpty
        return self._items.popleft()[1]

    def empty(self) -> bool:
        return not self._items

    def qsize(self) -> int:
        return len(self._items)
