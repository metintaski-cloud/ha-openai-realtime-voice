"""
Near wakes: the sound that almost woke her, collected for training the wake word (2.158.0).

Why (docs/WECKWORT.md, research of 24 Nov 2026): the wake word model on the device was trained
with artificial voices and stock background sound. Its folder for real false wakes was empty, so
it never learned what to ignore in this living room, and a threshold cannot teach it. What is
proven to help is training with the sound that really fooled it, taken through the same
microphone path. At about five false wakes a day that would take weeks to collect.

So the device runs a second, silent copy of the model with a low cutoff. When that copy fires,
nothing starts; the device only sends the last seconds of the microphone here (POST
/api/weckton, raw 16 bit mono samples, the channel and gain the model listens with). Most of
these are the television nearly waking her: exactly the hard examples the training needs. Some
are real calls the strict model missed, and those must never be trained as "not her name". So
every clip is settled before it is filed:

- a talk that the wake word started within WAKE_NEAR_S: dropped, that talk's own history
  (main._keep_preroll) already holds the same sound;
- another near wake or a wake within SETTLE_S before or after: marked f1 (somebody may have
  called again), else f0;
- a speech recogniser with her name as a keyword hears her name: n1, else n0 (nx: no answer).

File name: beinahe_<day>_<time>_n0_f0.wav. Only n0_f0 clips are meant to go into training as
they are; the others wait for a person to listen. What the recogniser heard is never stored or
logged: the clips can hold the family talking.
"""
import asyncio
import collections
import logging
import os
import time
from urllib.parse import parse_qs

import httpx

from app import metrics, wakecheck

logger = logging.getLogger(__name__)

FOLDER = os.environ.get("NEAR_WAKE_DIR", "/data/near_wakes")
MAX_FILES = 800          # 4 s each, 128 KB: about 100 MB at most
MIN_S, MAX_S = 0.5, 4.5
GAP_S = 1.0              # at most one clip in this time, whoever sends
MAX_PENDING = 12
SETTLE_S = 15.0          # how long a clip waits for what happens around it
WAKE_NEAR_S = 3.0        # a wake word talk this close is the same sound
HEAR_TIMEOUT_S = 20.0


class Collector:
    def __init__(self, folder: str = FOLDER):
        self.folder = folder
        self.api_key = ""
        self.pending: list = []
        self.wakes: collections.deque = collections.deque(maxlen=40)   # monotonic times
        self.nears: collections.deque = collections.deque(maxlen=200)
        self.last = 0.0
        self.covered = 0     # dropped since the start because a talk began
        self.refused = 0

    # ---- from the device ----

    def take(self, body: bytes, query: str = "") -> dict:
        """One clip from the device. Answers at once; the clip is filed SETTLE_S later."""
        now = time.monotonic()
        try:
            rate = int((parse_qs(query or "").get("rate") or ["16000"])[0])
        except ValueError:
            rate = 0
        seconds = len(body) / (rate * 2) if 8000 <= rate <= 48000 else 0.0
        if not (MIN_S <= seconds <= MAX_S) or now - self.last < GAP_S \
                or len(self.pending) >= MAX_PENDING:
            self.refused += 1
            return {"ok": False}
        self.last = now
        item = {"t": now, "at": time.time(), "pcm": bytes(body[:len(body) // 2 * 2]), "rate": rate}
        self.pending.append(item)
        self.nears.append(now)
        try:
            asyncio.get_running_loop().create_task(self._later(item))
        except RuntimeError:   # no loop (a test calls settle itself)
            pass
        return {"ok": True}

    def wake(self) -> None:
        """A talk was started by the wake word just now."""
        self.wakes.append(time.monotonic())

    # ---- filing ----

    async def _later(self, item: dict) -> None:
        try:
            await asyncio.sleep(SETTLE_S)
            await self.settle(item)
        except Exception as e:
            logger.warning("Near wake not filed: %s", e or type(e).__name__)
        finally:
            if item in self.pending:
                self.pending.remove(item)

    async def hears_her_name(self, item: dict):
        """True, False, or None when the recogniser did not answer."""
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=HEAR_TIMEOUT_S) as client:
                text = await asyncio.wait_for(wakecheck.transcribe(
                    wakecheck.wav(item["pcm"], item["rate"]), self.api_key, client,
                    wakecheck.KEYWORDS), HEAR_TIMEOUT_S)
        except Exception:
            return None
        return None if text is None else wakecheck.named(text)

    async def settle(self, item: dict):
        """File one clip (or drop it). Returns the file name, or None when it was dropped."""
        t = item["t"]
        if any(abs(w - t) <= WAKE_NEAR_S for w in self.wakes):
            self.covered += 1
            metrics.record("near_wake", covered=True)
            return None
        followed = (any(WAKE_NEAR_S < abs(w - t) <= SETTLE_S for w in self.wakes)
                    or any(0 < abs(n - t) <= SETTLE_S for n in self.nears))
        named = await self.hears_her_name(item)
        name = "beinahe_%s_n%s_f%d.wav" % (
            time.strftime("%Y%m%d_%H%M%S", time.localtime(item["at"])),
            {True: "1", False: "0", None: "x"}[named], int(followed))
        await asyncio.to_thread(self._write, name, wakecheck.wav(item["pcm"], item["rate"]))
        metrics.record("near_wake", named=named, followed=followed,
                       s=round(len(item["pcm"]) / (item["rate"] * 2), 1))
        logger.info("Near wake kept: %s", name)
        return name

    def _write(self, name: str, data: bytes) -> None:
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, name), "wb") as f:
            f.write(data)
        for old in sorted(n for n in os.listdir(self.folder) if n.endswith(".wav"))[:-MAX_FILES]:
            os.remove(os.path.join(self.folder, old))

    # ---- counts ----

    def stats(self) -> dict:
        """Counts only: how many clips are there, how many may go into training as they are,
        how many a person has to listen to first, per day."""
        try:
            names = sorted(n for n in os.listdir(self.folder) if n.startswith("beinahe_"))
        except OSError:
            names = []
        days: dict = {}
        for n in names:
            day = "%s-%s-%s" % (n[8:12], n[12:14], n[14:16])
            d = days.setdefault(day, {"tag": day, "sauber": 0, "pruefen": 0})
            d["sauber" if n.endswith("_n0_f0.wav") else "pruefen"] += 1
        clean = sum(d["sauber"] for d in days.values())
        return {"gesammelt": len(names), "sauber": clean, "pruefen": len(names) - clean,
                "wartend": len(self.pending), "gespraech_statt_clip": self.covered,
                "abgelehnt": self.refused,
                "tage": [days[k] for k in sorted(days, reverse=True)[:14]]}


_COLLECTOR = None


def collector() -> Collector:
    global _COLLECTOR
    if _COLLECTOR is None:
        _COLLECTOR = Collector()
    return _COLLECTOR
