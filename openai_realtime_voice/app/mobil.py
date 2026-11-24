"""A lighter copy of every heavy clip for the phone on the go (2.141.0, Metin).

Kling's 4K clips come with up to 29 Mbit/s. At home over the WLAN that is no problem, but on
the go through mobile data and Tailscale the phone stalls: Metin's test on 23 Nov 2026 with
schwarz/freizeitgluecklich2 played the original (29 Mbit) and a 15 Mbit copy with stutter,
an 11 Mbit copy smoothly. So every clip above HEAVY gets a copy in full 4K resolution with
at most MAX_RATE, made once in the background and kept in /data/mobil. Measured on that
clip: 99.3 % SSIM against the original at 11 Mbit, no visible difference in the face.
The original in the media folder is never touched.

Like YouTube, but simple: the page asks for the copy with ?m=1 when the phone is on mobile
data or a clip has stalled; the server sends the copy if there is one, else the original.
"""
import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

HEAVY = 9_000_000         # bit/s in the strongest second (2.141.4: the average hid peaks; nacht/tanz36
                          # averages 16 but peaks at 23, tanz14 averages 10 and peaks at 16, both stalled)
MAX_RATE = "7M"           # 2.141.3: 8M still gave a mini stutter now and then; 7M averages 7.4 and peaks at
BUF = "10M"               # 8.7 Mbit/s (2.141.1: 10M had peaked at 13, above Metin's limit of about 11)
MAX_W = 1440              # 2.143.0: the copies are made at phone size; a 1080 px wide screen showed the 2352 px
                          # wide 4K clip at less than half its pixels and the phone got warm decoding it (Metin)
# what a copy was made with; a change makes every copy once more. "ton" since 2.146.2: the copies
# were made without sound, and since the phone always gets the copy (2.143.0) every clip with sound
# (kiss, rose, touch reactions) was silent on the phone. The sound track is now copied unchanged.
CAP = f"{MAX_RATE}/{MAX_W}/ton"
PROBE_TIMEOUT = 30.0
ENCODE_TIMEOUT = 1800.0
RESCAN_S = 120            # 2.146.1: was 30 min; a clip Metin has just swapped in then played as the 4K original on
                          # the phone for up to half an hour. A scan only looks at file times, so it is cheap


def peak_of(packets: str) -> int:
    """ffprobe "pts_time,size" lines -> bit/s of the fullest one second window."""
    per = {}
    for line in packets.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            sec, size = int(float(parts[0])), int(parts[1])
        except ValueError:
            continue
        per[sec] = per.get(sec, 0) + size
    return max(per.values()) * 8 if per else 0


class Mobil:
    def __init__(self, folder_of, out_dir: str = "/data/mobil"):
        self.folder_of = folder_of        # () -> {"look/clip": path of the original}
        self.out_dir = out_dir
        self.index_path = os.path.join(out_dir, "index.json")
        self.index = {}                   # "look/clip" -> {"stamp": mtime, "peak": bit/s, "cap": rate}
        self.busy = ""
        self.done = 0
        self.failed = []
        self._load()

    # --- state ------------------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(self.index_path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.index = d
        except Exception:
            self.index = {}

    def _save(self) -> None:
        try:
            os.makedirs(self.out_dir, exist_ok=True)
            tmp = self.index_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.index, f)
            os.replace(tmp, self.index_path)
        except OSError as e:
            logger.warning("Mobil: cannot save index (%s)", e)

    def copy_path(self, name: str) -> str:
        look, clip = name.split("/", 1)
        return os.path.join(self.out_dir, look, clip + ".mp4")

    def copy_for(self, name: str, original: str) -> str:
        """The light copy if it exists and is newer than the original, else ""."""
        p = self.copy_path(name)
        try:
            if os.path.getmtime(p) >= os.path.getmtime(original):
                return p
        except OSError:
            pass
        return ""

    @staticmethod
    def needs_copy(m: dict) -> bool:
        """Too much for the line in its strongest second, or wider than a phone needs."""
        return m.get("peak", 0) > HEAVY or m.get("w", 0) > MAX_W

    def status(self) -> dict:
        paths = self.folder_of()
        heavy = [n for n, m in self.index.items() if self.needs_copy(m) and n in paths]
        ready = [n for n in heavy if self.copy_for(n, paths[n])]
        return {"heavy": len(heavy), "ready": len(ready), "busy": self.busy,
                "failed": self.failed[-10:], "max_rate": MAX_RATE, "max_w": MAX_W}

    # --- work -------------------------------------------------------------------
    async def _probe(self, path: str) -> int:
        """Bit/s of the strongest second of the picture: that is what has to fit through the line."""
        try:
            p = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "packet=pts_time,size", "-of", "csv=p=0", path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), timeout=PROBE_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            return 0
        return peak_of(out.decode())

    async def _width(self, path: str) -> int:
        try:
            p = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width",
                "-of", "csv=p=0", path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), timeout=PROBE_TIMEOUT)
            return int(out.decode().strip().split(",")[0] or 0)
        except (OSError, asyncio.TimeoutError, ValueError):
            return 0

    async def _encode(self, src: str, dst: str) -> bool:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".part.mp4"
        cmd = ("nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-i", src,
               "-map", "0:v:0", "-map", "0:a:0?", "-c:a", "copy",   # 2.146.2: keep the sound, see CAP
               "-vf", f"scale='min({MAX_W},iw)':-2:flags=lanczos",
               "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high",
               "-level", "5.1", "-pix_fmt", "yuv420p", "-g", "48", "-bf", "3",
               "-maxrate", MAX_RATE, "-bufsize", BUF, "-movflags", "+faststart", tmp)
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(p.communicate(), timeout=ENCODE_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as e:
            logger.warning("Mobil: %s failed (%s)", os.path.basename(src), e)
            return False
        if p.returncode != 0 or not os.path.exists(tmp):
            logger.warning("Mobil: %s failed: %s", os.path.basename(src), err.decode()[-200:])
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        os.replace(tmp, dst)
        return True

    async def scan(self) -> None:
        """Probe new or changed clips, make the missing copies, drop copies of clips that are gone."""
        paths = self.folder_of()
        for name, path in sorted(paths.items()):
            try:
                stamp = int(os.path.getmtime(path))
            except OSError:
                continue
            m = self.index.get(name)
            if not m or m.get("stamp") != stamp or "peak" not in m or "w" not in m:
                cap = m.get("cap") if m and m.get("stamp") == stamp else None
                self.index[name] = {"stamp": stamp, "peak": await self._probe(path),
                                    "w": await self._width(path)}
                if cap:
                    self.index[name]["cap"] = cap
        for name in [n for n in self.index if n not in paths]:
            self.index.pop(name, None)
            try:
                os.remove(self.copy_path(name))
            except OSError:
                pass
        self._save()
        for name, m in sorted(self.index.items()):
            if not self.needs_copy(m):
                continue
            if self.copy_for(name, paths[name]) and m.get("cap") == CAP:
                continue           # an older copy stays served until the new one is ready
            self.busy = name
            ok = await self._encode(paths[name], self.copy_path(name))
            self.busy = ""
            if ok:
                m["cap"] = CAP
                self._save()
                self.done += 1
                logger.info("Mobil: light copy of %s ready (%d so far)", name, self.done)
            else:
                self.failed.append(name)
            await asyncio.sleep(1)

    async def run(self) -> None:
        await asyncio.sleep(60)           # let the add on start in peace first
        while True:
            try:
                await self.scan()
            except Exception as e:        # a broken clip must not stop the loop
                logger.warning("Mobil: scan failed (%s)", e)
            await asyncio.sleep(RESCAN_S)
