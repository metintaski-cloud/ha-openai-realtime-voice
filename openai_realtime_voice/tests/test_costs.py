"""Tests for the OpenAI spending report."""
import asyncio
import json
import os
import sys
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import costs  # noqa: E402
from tests.test_live_bridge import FakeLive, CHUNK, _run, _collect  # noqa: E402

TODAY = date(2026, 11, 2)


def _ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


DAYS = {date(2026, 10, 5): 1.00, date(2026, 10, 31): 0.50,
        date(2026, 11, 1): 0.25, date(2026, 11, 2): 0.10}


class _Handler(BaseHTTPRequestHandler):
    requests: list = []

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        _Handler.requests.append((self.headers.get("Authorization"), q))
        start = int(q["start_time"][0])
        days = sorted(d for d in DAYS if _ts(d) >= start)
        page = q.get("page", ["0"])[0]
        half = len(days) // 2
        chunk, more = (days[:half], True) if page == "0" else (days[half:], False)
        data = [{"object": "bucket", "start_time": _ts(d), "end_time": _ts(d) + 86400,
                 "results": [{"object": "organization.costs.result",
                              "amount": {"value": DAYS[d] / 2, "currency": "usd"}},
                             {"object": "organization.costs.result",
                              "amount": {"value": DAYS[d] / 2, "currency": "usd"}}]}
                for d in chunk]
        body = json.dumps({"object": "page", "data": data, "has_more": more,
                           "next_page": "1" if more else None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_summarize_and_budget():
    totals = dict(DAYS)
    r = costs.summarize(totals, TODAY, 20.0)
    assert r["today"] == 0.10 and r["yesterday"] == 0.25
    assert r["this_month"] == 0.35 and r["last_month"] == 1.50
    assert r["last_7_days"] == 0.85
    assert r["monthly_budget"] == 20.0 and r["budget_left_this_month"] == 19.65
    assert r["budget_used_percent"] == 2
    r2 = costs.summarize(totals, TODAY)
    assert "monthly_budget" not in r2


async def test_cost_report_paginates():
    server = HTTPServer(("127.0.0.1", 19994), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        r = await costs.cost_report("adm", 20.0,
                                    url="http://127.0.0.1:19994/v1/organization/costs",
                                    today=TODAY)
        assert r["this_month"] == 0.35 and r["last_month"] == 1.50
        assert r["budget_left_this_month"] == 19.65
        assert _Handler.requests[0][0] == "Bearer adm"
        assert len(_Handler.requests) == 2
    finally:
        server.shutdown()


async def test_bridge_answers_cost_tool_call():
    server = HTTPServer(("127.0.0.1", 19995), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["OPENAI_ADMIN_KEY"] = "adm"
    os.environ["MONTHLY_BUDGET_USD"] = "20"
    os.environ["OPENAI_COSTS_URL"] = "http://127.0.0.1:19995/v1/organization/costs"
    try:
        class CostLive(FakeLive):
            outputs: list = []

            async def __call__(self, ws):
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg["type"] == "response.item.create":
                            CostLive.outputs.append(msg["item"])
                            continue
                        if msg["type"] == "session.start":
                            self.start_msg = msg
                            await ws.send(json.dumps({"type": "session.started",
                                                      "session": {"id": "s1"}}))
                        elif msg["type"] == "session.input_audio.append" and not self.responded:
                            self.responded = True
                            await ws.send(json.dumps({"type": "response.event", "event": {
                                "type": "response.output_item.done",
                                "item": {"type": "function_call", "name": "openai_kosten",
                                         "call_id": "c9", "arguments": "{}"}}}))
                            for _ in range(3):
                                await ws.send(json.dumps({"type": "session.output_audio.delta",
                                                          "delta": CHUNK}))
                except Exception:
                    pass

        fake = CostLive()

        async def scenario(client):
            assert json.loads(await client.recv())["type"] == "ready"
            for _ in range(3):
                await client.send(b"\x00\x00" * 480)
            await _collect(client, timeout=2.0)
            return True

        await _run(fake, scenario)
        tools = fake.start_msg["session"]["delegation"]["responses"]["tools"]
        assert any(t.get("name") == "openai_kosten" for t in tools)
        assert CostLive.outputs and CostLive.outputs[0]["call_id"] == "c9"
        out = json.loads(CostLive.outputs[0]["output"])
        assert out["currency"] == "USD" and "this_month" in out
        assert out["monthly_budget"] == 20.0 and "budget_left_this_month" in out
    finally:
        server.shutdown()
        for k in ("OPENAI_ADMIN_KEY", "MONTHLY_BUDGET_USD", "OPENAI_COSTS_URL"):
            os.environ.pop(k, None)


async def test_no_admin_key_no_tool():
    os.environ.pop("OPENAI_ADMIN_KEY", None)
    fake = FakeLive(respond_after=10**6)

    async def scenario(client):
        assert json.loads(await client.recv())["type"] == "ready"
        return True

    await _run(fake, scenario)
    tools = fake.start_msg["session"]["delegation"]["responses"]["tools"]
    assert not any(t.get("name") == "openai_kosten" for t in tools)
