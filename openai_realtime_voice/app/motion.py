"""How fast Leyla really moves in a clip (2.137.0, Metin).

He went through all 300 clips in the tempo tester by feel and lost his reference point
("Bremse verloren"). Judging a clip on its own does not work over 300 of them, so this
measures instead: every clip is decoded small and grey, and from the change between the
frames come two numbers.

- rate:  how much moves per second (mean pixel change). Amplitude.
- beat:  how often the movement swings per second (peaks in that change). Cadence.

For a group of clips that belong together (all nacht/tanz, all zeigenlang, ...) the beat
of the group tells us what "normal" is, and a clip that beats slower than the group gets
a factor above 1. Nothing is re-encoded: the factor only goes into clips.json and the page
plays the clip at that speed (2.136.0).
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

W, H = 48, 72          # small and grey is enough for movement, and it decodes fast
FPS = 12               # 12 samples a second catch a dance step, 24 would only cost time
MIN_FRAMES = 6
TIMEOUT = 120.0


def cadence(series: list, fps: float = 12.0, lo_hz: float = 0.4,
            hi_hz: float = 3.0) -> tuple:
    """How often the movement repeats per second, and how clear that repetition is.

    The same method a tempo detector uses on music: lay the signal over itself, shifted
    by one step at a time, and the shift that fits best is the length of one movement.
    Counting peaks (what the first version did, 2.137.0) was too coarse, a dance keeps the
    change high all the way through and shows almost no peaks (Metin 22.11.2026).
    """
    n = len(series)
    if n < int(fps * 1.5):
        return 0.0, 0.0
    mean = sum(series) / n
    x = [v - mean for v in series]
    zero = sum(v * v for v in x)
    if zero <= 0:
        return 0.0, 0.0
    lo, hi = max(2, int(fps / hi_hz)), min(n - 2, int(fps / lo_hz))
    cs = {}
    for lag in range(lo, hi + 1):
        c = sum(x[i] * x[i + lag] for i in range(n - lag))
        cs[lag] = c / (n - lag)             # per sample, so long lags are not punished
    best = max(cs.values()) if cs else 0.0
    if best <= 0:
        return 0.0, 0.0
    # two steps fit the shift just as well as one, so take the shortest shift that fits:
    # otherwise a cadence of two a second would be read as one a second
    best_lag = min(l for l, c in cs.items() if c >= best * 0.85)
    best = cs[best_lag]
    conf = max(0.0, min(1.0, best * n / zero))
    return round(fps / best_lag, 2), round(conf, 2)


async def measure(path: str) -> dict:
    """Decode the clip small and grey and give back its movement numbers."""
    cmd = ("ffmpeg", "-v", "error", "-i", path,
           "-vf", f"fps={FPS},scale={W}:{H},format=gray",
           "-f", "rawvideo", "-")
    try:
        p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.DEVNULL)
    except OSError as e:
        logger.warning("Motion: ffmpeg missing (%s)", e)
        return {}
    try:
        raw, _ = await asyncio.wait_for(p.communicate(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        p.kill()
        logger.warning("Motion: %s took too long", os.path.basename(path))
        return {}
    size = W * H
    frames = [raw[i:i + size] for i in range(0, len(raw) - size + 1, size)]
    if len(frames) < MIN_FRAMES:
        return {}
    diffs = []
    for a, b in zip(frames, frames[1:]):
        diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / size)
    secs = len(frames) / FPS
    # drift: Kling sometimes runs fast in one half of a clip and slow in the other
    # (Metin 22.11.2026). Half against half tells which clips are uneven, 1.0 is even.
    half = len(diffs) // 2
    a_, b_ = diffs[:half], diffs[half:]
    ma = sum(a_) / max(1, len(a_))
    mb = sum(b_) / max(1, len(b_))
    drift = round(max(ma, mb) / max(0.01, min(ma, mb)), 2) if half else 1.0
    beat, conf = cadence(diffs, FPS)
    # the cadence of each half on its own: far apart means the clip speeds up or slows
    # down inside itself, which no single play speed can fix (Metin 22.11.2026)
    ba, _ = cadence(a_, FPS)
    bb, _ = cadence(b_, FPS)
    wobble = round(max(ba, bb) / max(0.01, min(ba, bb)), 2) if ba and bb else 0.0
    return {"dur": round(secs, 2),
            "rate": round(sum(diffs) / len(diffs) * FPS, 1),
            "beat": beat, "conf": conf, "wobble": wobble,
            "drift": drift}


def factors(items: dict, lo: float = 0.6, hi: float = 1.6) -> dict:
    """One cadence per group: the group's middle beat is the target, each clip gets the
    factor that brings it there. Clips without a beat (she stands still) keep 1."""
    groups = {}
    for name, m in items.items():
        if not m.get("beat") or m.get("conf", 1) < 0.25:
            continue      # no clear repetition, so there is no tempo to correct
        look, clip = name.split("/", 1) if "/" in name else ("", name)
        groups.setdefault(look + "/" + clip.rstrip("0123456789"), []).append((name, m["beat"]))
    out = {}
    for key, members in groups.items():
        beats = sorted(b for _, b in members)
        if len(beats) < 3:          # two clips cannot tell which of them is the odd one
            continue
        target = beats[len(beats) // 2]
        for name, beat in members:
            f = round(min(hi, max(lo, target / beat)) * 20) / 20   # steps of 0.05
            if f != 1.0:
                out[name] = f
    return out


class Runner:
    """Measures every clip once, in the background, and keeps what it found.

    The result lands in the same file the tempo tester writes, so there is one place that
    decides how fast a clip plays: the measurement fills it, and a later "merken" in the
    tester overrules a single clip (2.137.0, Metin: 'Kannst loeschen' about his run by feel).
    """

    def __init__(self, folder_of, write, cache: str = "/data/motion.json"):
        self.folder_of = folder_of      # () -> {"look/clip": path}
        self.write = write             # (name, factor) -> None
        self.cache = cache
        self.items = {}
        self.busy = False
        self.done = 0
        self.total = 0
        self._load()

    def _load(self) -> None:
        import json
        try:
            with open(self.cache, encoding="utf-8") as f:
                items = json.load(f)
            if isinstance(items, dict):
                self.items = items
        except Exception:
            self.items = {}

    def _save(self) -> None:
        import json
        try:
            os.makedirs(os.path.dirname(self.cache) or ".", exist_ok=True)
            tmp = self.cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False)
            os.replace(tmp, self.cache)
        except OSError as e:
            logger.warning("Motion: cannot save (%s)", e)

    def status(self) -> dict:
        return {"busy": self.busy, "done": self.done, "total": self.total,
                "measured": len(self.items)}

    async def run(self) -> dict:
        if self.busy:
            return self.status()
        self.busy = True
        try:
            paths = self.folder_of()
            todo = []
            for name, path in sorted(paths.items()):
                try:
                    stamp = int(os.path.getmtime(path))
                except OSError:
                    continue
                old = self.items.get(name)
                if not old or old.get("stamp") != stamp:
                    todo.append((name, path, stamp))
            self.total, self.done = len(todo), 0
            for name, path, stamp in todo:
                m = await measure(path)
                if m:
                    m["stamp"] = stamp
                    self.items[name] = m
                self.done += 1
                if self.done % 10 == 0:
                    self._save()
                await asyncio.sleep(0)      # let the voice bridge breathe between clips
            self._save()
            # drop clips that are gone, then hand the factors over
            self.items = {k: v for k, v in self.items.items() if k in paths}
            out = factors({k: v for k, v in self.items.items()})
            for name, f in out.items():
                self.write(name, f)
            logger.info("Motion: %d clips measured, %d get another speed",
                        len(self.items), len(out))
            return {"ok": True, "measured": len(self.items), "factors": out}
        finally:
            self.busy = False
