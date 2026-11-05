"""Tests for the fixed-frequency RF remote."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import rf  # noqa: E402


class FakeDevice:
    def __init__(self, host):
        self.host = host
        self.calls = []
        self.polls = 0
        self.sent = []

    def auth(self):
        self.calls.append("auth")

    def find_rf_packet(self, frequency=None):
        self.calls.append(("find", frequency))

    def check_data(self):
        self.polls += 1
        if self.polls < 2:
            raise RuntimeError("no data yet")
        return b"\xb2\x00\x10\x00ABCD"

    def cancel_sweep_frequency(self):
        self.calls.append("cancel")

    def send_data(self, data):
        self.sent.append(data)


async def test_learn_and_send(tmp_path, monkeypatch):
    monkeypatch.setattr(rf.time, "sleep", lambda s: None)
    dev = FakeDevice("1.2.3.4")
    remote = rf.RfRemote("1.2.3.4", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    r = await remote.learn("licht", timeout=5)
    assert r["learned"] == "licht" and ("find", 433.87) in dev.calls
    assert json.load(open(tmp_path / "c.json"))["codes"]["licht"]
    await remote.send("licht", repeats=2)
    assert dev.sent == [b"\xb2\x00\x10\x00ABCD"] * 2


async def test_http_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(rf.time, "sleep", lambda s: None)
    dev = FakeDevice("1.2.3.4")
    remote = rf.RfRemote("1.2.3.4", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    server = await rf.start_http(remote, "127.0.0.1", 18081)

    async def get(path):
        reader, writer = await asyncio.open_connection("127.0.0.1", 18081)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await writer.drain()
        raw = await reader.read()
        writer.close()
        head, body = raw.split(b"\r\n\r\n", 1)
        return int(head.split()[1]), json.loads(body)

    try:
        assert (await get("/rf/send?name=licht"))[0] == 404
        status, body = await get("/rf/learn?name=Licht")
        assert status == 200 and body["learned"] == "licht"
        status, body = await get("/rf/list")
        assert body["codes"] == ["licht"]
        status, body = await get("/rf/send?name=licht")
        assert status == 200 and dev.sent
    finally:
        server.close()


async def test_rotation_never_repeats_capture(tmp_path, monkeypatch):
    dev = FakeDevice("1.2.3.4")
    remote = rf.RfRemote("1.2.3.4", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    for i in (1, 2, 3):
        remote.save_code(f"licht_{i}", bytes([i]))
    remote.save_code("stufe1_1", b"\x09")
    sent = [(await remote.send_rotating("licht"))["sent"] for _ in range(4)]
    assert sent == ["licht_2", "licht_3", "licht_1", "licht_2"]
    assert dev.sent == [b"\x02", b"\x03", b"\x01", b"\x02"]
    # a manual send through the HTTP test endpoint is remembered as well
    await remote.send("licht_3")
    assert remote.next_capture("licht") == "licht_1"
    # survives a restart
    again = rf.RfRemote("1.2.3.4", 433.87, str(tmp_path / "c.json"), device_factory=lambda h: dev)
    assert again.next_capture("licht") == "licht_1"
    assert again.next_capture("stufe1") == "stufe1_1"
    try:
        again.next_capture("power")
        assert False
    except KeyError:
        pass
