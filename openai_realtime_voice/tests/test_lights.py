"""Tests for the living room light control."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import lights  # noqa: E402
from tests.test_live_bridge import FakeLive, CHUNK, _run, _collect  # noqa: E402

ENTS = ["light.l1", "light.l2", "light.l3", "light.l4"]


class _HA(BaseHTTPRequestHandler):
    calls: list = []
    states: dict = {}

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        service = self.path.rsplit("/", 1)[-1]
        _HA.calls.append((self.headers.get("Authorization"), service, body))
        for eid in body.get("entity_id", []):
            st = _HA.states.setdefault(eid, {"entity_id": eid, "state": "off", "attributes": {}})
            if service == "turn_off":
                st["state"] = "off"
            else:
                st["state"] = "on"
                if "brightness_pct" in body:
                    st["attributes"]["brightness"] = round(body["brightness_pct"] * 255 / 100)
                if "color_temp_kelvin" in body:
                    st["attributes"].update(color_mode="color_temp",
                                            color_temp_kelvin=body["color_temp_kelvin"])
        self._send(200, [])

    def do_GET(self):
        eid = self.path.rsplit("/", 1)[-1]
        self._send(200, _HA.states.get(eid, {"entity_id": eid, "state": "unavailable",
                                             "attributes": {}}))

    def log_message(self, *args):
        pass


def _server(port):
    server = HTTPServer(("127.0.0.1", port), _HA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_parse_and_select():
    assert lights.parse_entities(None)[0] == "light.wohnzimmer_lamba_1"
    assert lights.parse_entities("light.a; light.b") == ["light.a", "light.b"]
    assert lights.select_entities(ENTS, []) == (ENTS, [])
    assert lights.select_entities(ENTS, [2, 2, 7]) == (["light.l2"], [7])


def test_service_data():
    assert lights.build_service_data({"action": "off"}) == ("turn_off", {})
    assert lights.build_service_data({"action": "on", "brightness_percent": 150, "white": "warm",
                                      "color": None}) == (
        "turn_on", {"brightness_pct": 100, "color_temp_kelvin": 2700})
    svc, data = lights.build_service_data({"action": "on", "color": "blau", "white": "kalt"})
    assert data == {"rgb_color": [0, 0, 255]}


async def test_controller_switches_single_and_all():
    _HA.calls.clear()
    _HA.states.clear()
    server = _server(19996)
    try:
        ctl = lights.LightController(ENTS, api_url="http://127.0.0.1:19996/api", token="tok")
        r = await ctl.run({"lamps": [3], "action": "on", "brightness_percent": 40,
                           "white": "warm", "color": None})
        assert _HA.calls[-1] == ("Bearer tok", "turn_on", {"brightness_pct": 40,
                                 "color_temp_kelvin": 2700, "entity_id": ["light.l3"]})
        assert r["lamps"] == [{"lamp": 3, "state": "on", "brightness_percent": 40,
                               "white": "warm", "kelvin": 2700}]
        r = await ctl.run({"lamps": [], "action": "off", "brightness_percent": None,
                           "white": None, "color": None})
        assert _HA.calls[-1][1] == "turn_off" and _HA.calls[-1][2]["entity_id"] == ENTS
        assert all(d["state"] == "off" for d in r["lamps"])
        r = await ctl.run({"lamps": [9], "action": "on"})
        assert "error" in r and r["unknown_lamps"] == [9]
    finally:
        server.shutdown()


async def test_bridge_answers_light_tool_call():
    _HA.calls.clear()
    _HA.states.clear()
    server = _server(19997)
    os.environ["SUPERVISOR_TOKEN"] = "tok"
    os.environ["HA_API_URL"] = "http://127.0.0.1:19997/api"
    os.environ["LIGHT_ENTITIES"] = ", ".join(ENTS)
    os.environ["ENABLE_CONTEXT"] = "false"
    try:
        class LightLive(FakeLive):
            outputs: list = []

            async def __call__(self, ws):
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg["type"] == "response.item.create":
                            LightLive.outputs.append(msg["item"])
                            continue
                        if msg["type"] == "session.start":
                            self.start_msg = msg
                            await ws.send(json.dumps({"type": "session.started",
                                                      "session": {"id": "s1"}}))
                        elif msg["type"] == "session.input_audio.append" and not self.responded:
                            self.responded = True
                            args = {"lamps": [1, 2], "action": "on", "brightness_percent": 60,
                                    "white": "kalt", "color": None}
                            await ws.send(json.dumps({"type": "response.event", "event": {
                                "type": "response.output_item.done",
                                "item": {"type": "function_call", "name": "licht_steuern",
                                         "call_id": "c7", "arguments": json.dumps(args)}}}))
                            for _ in range(3):
                                await ws.send(json.dumps({"type": "session.output_audio.delta",
                                                          "delta": CHUNK}))
                except Exception:
                    pass

        fake = LightLive()

        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            for _ in range(3):
                await client.send(b"\x00\x00" * 480)
            await _collect(client, timeout=2.5)
            return True

        await _run(fake, scenario)
        responses = fake.start_msg["session"]["delegation"]["responses"]
        assert any(t.get("name") == "licht_steuern" for t in responses["tools"])
        assert "Lampe 1 to Lampe 4" in responses["instructions"]
        assert _HA.calls and _HA.calls[0][2] == {"brightness_pct": 60, "color_temp_kelvin": 6500,
                                                 "entity_id": ["light.l1", "light.l2"]}
        assert LightLive.outputs and LightLive.outputs[0]["call_id"] == "c7"
        out = json.loads(LightLive.outputs[0]["output"])
        assert [d["lamp"] for d in out["lamps"]] == [1, 2]
        assert out["lamps"][0]["white"] == "kalt"
    finally:
        server.shutdown()
        for k in ("SUPERVISOR_TOKEN", "HA_API_URL", "LIGHT_ENTITIES", "ENABLE_CONTEXT"):
            os.environ.pop(k, None)


async def test_no_token_no_light_tool():
    os.environ.pop("SUPERVISOR_TOKEN", None)
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        return True

    await _run(fake, scenario)
    tools = fake.start_msg["session"]["delegation"]["responses"]["tools"]
    assert not any(t.get("name") == "licht_steuern" for t in tools)
