"""
Radio remote (433 MHz) for the ceiling fan, through the Broadlink RM4 Pro.

Home Assistant's Broadlink integration only learns RF codes after a frequency
sweep, and the codes it captured did not move this fan. The Broadlink app, which
does work, captures at the exact frequency of the remote (433.87 MHz). This module
does the same with python-broadlink: listen directly at a fixed frequency, store
the captured packet, replay it later.

A tiny HTTP endpoint on the add-on (port 8081 by default) is used to learn and test
codes from a browser:
  GET /rf/learn?name=licht   listen up to 60 s, press the button once meanwhile
  GET /rf/send?name=licht    send a learned code
  GET /rf/list               list learned codes
"""
import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

DEFAULT_FREQUENCY = 433.87
LEARN_TIMEOUT_S = 60.0


class RfRemote:
    def __init__(self, host: str, frequency: float = DEFAULT_FREQUENCY,
                 path: str = "/data/rf_codes.json", device_factory=None) -> None:
        self.host = host
        self.frequency = frequency
        self.path = path
        self._device = None
        self._device_factory = device_factory
        self._lock = asyncio.Lock()
        self.learning: Optional[str] = None
        base, _ = os.path.splitext(path)
        self.state_path = base + "_state.json"

    @property
    def available(self) -> bool:
        return bool(self.host)

    # storage -----------------------------------------------------------------
    def load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f).get("codes", {})
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.warning("Could not read RF codes: %s", e)
            return {}

    def save_code(self, name: str, packet: bytes) -> None:
        codes = self.load()
        codes[name] = base64.b64encode(packet).decode()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"frequency": self.frequency, "codes": codes}, f, indent=2)
        os.replace(tmp, self.path)

    def _load_state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _record_sent(self, name: str) -> None:
        """Remember which capture of a button was sent last (name like licht_2)."""
        key, _, idx = name.rpartition("_")
        if not key or not idx.isdigit():
            return
        state = self._load_state()
        state.setdefault("last_index", {})[key] = int(idx)
        state["last_sent"] = name
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, self.state_path)
        except Exception as e:
            logger.warning("Could not save RF state: %s", e)

    def captures(self, key: str) -> list[int]:
        """Indexes of the learned captures of a button, e.g. [1, 2, 3] for licht_1..3."""
        out = []
        for name in self.load():
            k, _, idx = name.rpartition("_")
            if k == key and idx.isdigit():
                out.append(int(idx))
        return sorted(out)

    def next_capture(self, key: str) -> str:
        """The capture to send next: never the same one as last time for this button."""
        idxs = self.captures(key)
        if not idxs:
            if key in self.load():
                return key
            raise KeyError(f"Taste '{key}' ist nicht angelernt")
        last = self._load_state().get("last_index", {}).get(key)
        if last is None:
            # Nothing recorded yet; start with the second capture, because the first one
            # was used for testing right after learning.
            nxt = idxs[1] if len(idxs) > 1 else idxs[0]
        else:
            later = [i for i in idxs if i > last]
            nxt = later[0] if later else idxs[0]
        return f"{key}_{nxt}"

    async def send_rotating(self, key: str) -> dict:
        return await self.send(self.next_capture(key))

    # device ------------------------------------------------------------------
    def _connect(self):
        if self._device is None:
            if self._device_factory:
                dev = self._device_factory(self.host)
            else:
                import broadlink
                dev = broadlink.hello(self.host, timeout=5)
            dev.auth()
            self._device = dev
        return self._device

    def _learn_blocking(self, timeout: float) -> bytes:
        dev = self._connect()
        dev.find_rf_packet(self.frequency)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(1.0)
            try:
                data = dev.check_data()
            except Exception:  # ReadError / StorageError while nothing captured yet
                continue
            if data:
                try:
                    dev.cancel_sweep_frequency()
                except Exception:
                    pass
                return bytes(data)
        try:
            dev.cancel_sweep_frequency()
        except Exception:
            pass
        raise TimeoutError("Kein Funksignal empfangen")

    def _send_blocking(self, packet: bytes) -> None:
        dev = self._connect()
        dev.send_data(packet)

    async def learn(self, name: str, timeout: float = LEARN_TIMEOUT_S) -> dict:
        async with self._lock:
            self.learning = name
            try:
                packet = await asyncio.to_thread(self._learn_blocking, timeout)
            except Exception:
                self._device = None
                raise
            finally:
                self.learning = None
            self.save_code(name, packet)
            logger.info("RF code '%s' learned (%d bytes)", name, len(packet))
            return {"learned": name, "bytes": len(packet)}

    async def send(self, name: str, repeats: int = 1) -> dict:
        code = self.load().get(name)
        if not code:
            raise KeyError(f"Taste '{name}' ist nicht angelernt")
        packet = base64.b64decode(code)
        async with self._lock:
            for i in range(max(1, repeats)):
                try:
                    await asyncio.to_thread(self._send_blocking, packet)
                except Exception:
                    self._device = None  # reconnect once, then give up
                    await asyncio.to_thread(self._send_blocking, packet)
                if i + 1 < repeats:
                    await asyncio.sleep(0.15)
        self._record_sent(name)
        logger.info("RF code '%s' sent", name)
        return {"sent": name}


def remote_from_env() -> RfRemote:
    host = (os.environ.get("RF_HOST") or "").strip()
    if host.lower() == "null":
        host = ""
    try:
        freq = float((os.environ.get("RF_FREQUENCY") or "").replace(",", ".") or DEFAULT_FREQUENCY)
    except ValueError:
        freq = DEFAULT_FREQUENCY
    return RfRemote(host, freq, os.environ.get("RF_CODES_PATH", "/data/rf_codes.json"))


# tiny HTTP endpoint ------------------------------------------------------------
async def _handle_http(remote: RfRemote, reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> None:
    status, body = 200, {}
    try:
        line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
        while True:  # skip headers
            h = await asyncio.wait_for(reader.readline(), 5)
            if h in (b"\r\n", b"\n", b""):
                break
        parts = line.split()
        url = urlparse(parts[1] if len(parts) > 1 else "/")
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        name = (q.get("name") or "").strip().lower()
        if url.path == "/rf/list":
            body = {"frequency": remote.frequency, "codes": sorted(remote.load()),
                    "learning": remote.learning}
        elif url.path == "/rf/learn" and name:
            body = await remote.learn(name)
        elif url.path == "/rf/send" and name:
            body = await remote.send(name, int(q.get("repeats", "1") or 1))
        else:
            status, body = 404, {"error": "unknown path"}
    except KeyError as e:
        status, body = 404, {"error": str(e).strip("'\"")}
    except TimeoutError as e:
        status, body = 408, {"error": str(e)}
    except Exception as e:
        logger.warning("RF HTTP request failed: %s", e)
        status, body = 500, {"error": str(e)}
    data = json.dumps(body, ensure_ascii=False).encode()
    head = (f"HTTP/1.1 {status} OK\r\nContent-Type: application/json; charset=utf-8\r\n"
            f"Access-Control-Allow-Origin: *\r\nContent-Length: {len(data)}\r\n"
            "Connection: close\r\n\r\n").encode()
    try:
        writer.write(head + data)
        await writer.drain()
    finally:
        writer.close()


async def start_http(remote: RfRemote, host: str = "0.0.0.0", port: int = 8081):
    server = await asyncio.start_server(lambda r, w: _handle_http(remote, r, w), host, port)
    logger.info("RF remote HTTP on port %d (Broadlink %s, %.2f MHz)", port, remote.host,
                remote.frequency)
    return server
