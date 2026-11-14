import asyncio
import json

import httpx

from app import deep_think


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_asks_with_high_effort_and_returns_text():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Nimm die zweite Option."}]}]})

    out = _run(deep_think.think("k", "m1", {"frage": "Was ist besser?"},
                                transport=httpx.MockTransport(handler)))
    assert out["antwort"] == "Nimm die zweite Option."
    assert seen["reasoning"] == {"effort": "high"} and seen["model"] == "m1"
    assert seen["input"] == "Was ist besser?"


def test_errors_are_reported_not_raised():
    bad = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    assert "error" in _run(deep_think.think("k", "m", {"frage": "x"}, transport=bad))
    assert "error" in _run(deep_think.think("k", "m", {"frage": " "}))
    empty = httpx.MockTransport(lambda r: httpx.Response(200, json={"output": []}))
    assert "error" in _run(deep_think.think("k", "m", {"frage": "x"}, transport=empty))
