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

HEAVY = 12_000_000        # bit/s; clips below play smoothly on the go already
MAX_RATE = "8M"           # 2.141.1: with 10M the copies still peaked at 13 Mbit/s in single seconds,
BUF = "8M"                # above Metin's limit of about 11; a tight buffer keeps the peaks under 10
PROBE_TIMEOUT = 30.0
ENCODE_TIMEOUT = 1800.0
RESCAN_S = 1800


class Mobil:
    def __init__(self, folder_of, out_dir: str = "/data/mobil"):
        self.folder_of = folder_of        # () -> {"look/clip": path of the original}
        self.out_dir = out_dir
        self.index_path = os.path.join(out_dir, "index.json")
        self.index = {}                   # "look/clip" -> {"stamp": mtime, "rate": bit/s}
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

    def status(self) -> dict:
        paths = self.folder_of()
        heavy = [n for n, m in self.index.items() if m.get("rate", 0) > HEAVY and n in paths]
        ready = [n for n in heavy if self.copy_for(n, paths[n])]
        return {"heavy": len(heavy), "ready": len(ready), "busy": self.busy,
                "failed": self.failed[-10:], "max_rate": MAX_RATE}

    # --- work -------------------------------------------------------------------
    async def _probe(self, path: str) -> int:
        try:
            p = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=bit_rate:format=bit_rate", "-of", "csv=p=0", path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), timeout=PROBE_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            return 0
        nums = [int(x) for x in out.decode().replace("\n", ",").split(",") if x.strip().isdigit()]
        return max(nums) if nums else 0

    async def _encode(self, src: str, dst: str) -> bool:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".part.mp4"
        cmd = ("nice", "-n", "19", "ffmpeg", "-v", "error", "-y", "-i", src, "-an",
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
            if not m or m.get("stamp") != stamp:
                self.index[name] = {"stamp": stamp, "rate": await self._probe(path)}
        for name in [n for n in self.index if n not in paths]:
            self.index.pop(name, None)
            try:
                os.remove(self.copy_path(name))
            except OSError:
                pass
        self._save()
        for name, m in sorted(self.index.items()):
            if m.get("rate", 0) <= HEAVY:
                continue
            if self.copy_for(name, paths[name]) and m.get("cap") == MAX_RATE:
                continue           # an older copy stays served until the new one is ready
            self.busy = name
            ok = await self._encode(paths[name], self.copy_path(name))
            self.busy = ""
            if ok:
                m["cap"] = MAX_RATE
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
