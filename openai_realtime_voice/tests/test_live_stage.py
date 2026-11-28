"""2.194.0. Metin, 28 Nov 2026, 00:48, after his first live talk in which she answered a touch with her live
voice: "wenn ich ja Tanz sage, sie normalerweise getanzt hat. Und das ist jetzt leider nicht mehr der Fall. Können
wir das noch irgendwie mit einpflegen?" In the chat the model writes a szene field; a live talk had no way to the
stage. Now a live talk from the app has the function buehne: her heart decides, the app plays the scene."""
import asyncio
import json

from app import heart, memory_web


def _bridge(monkeypatch, tmp_path):
    from app import main as m
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("CODE_PHRASE", "Leyla habibi")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("LEYLA_HEART_PATH", str(tmp_path / "heart.json"))
    return m, m.LiveVoiceBridge()


def test_only_a_live_talk_from_the_app_gets_the_stage(tmp_path, monkeypatch):
    m, bridge = _bridge(monkeypatch, tmp_path)
    plain = bridge._session_start()["session"]
    stage = bridge._session_start(stage=True)["session"]
    names = lambda s: [t.get("name") for t in s["delegation"]["responses"]["tools"]]
    assert "buehne" in names(stage) and "buehne" not in names(plain)
    assert heart.STAGE_BACKEND_HINT in stage["delegation"]["responses"]["instructions"]
    assert heart.STAGE_BACKEND_HINT not in plain["delegation"]["responses"]["instructions"]
    assert heart.STAGE_LIVE_HINT in stage["instructions"] and heart.STAGE_LIVE_HINT not in plain["instructions"]
    assert "Sag nie, dass du tanzt" in heart.STAGE_LIVE_HINT
    assert set(heart.STAGE_TOOL["parameters"]["properties"]["szene"]["enum"]) <= set(heart.SCENES)


async def test_her_heart_decides_and_the_app_is_told(tmp_path, monkeypatch):
    m, bridge = _bridge(monkeypatch, tmp_path)
    spec = bridge._tools["buehne"]
    asked = []
    bridge.mood.scene = lambda wanted: (asked.append(wanted), {"tanz": "tanz", "kuss": ""}.get(wanted, ""))[1]
    queue = asyncio.Queue()
    state = {"from_app": True, "output_queue": queue}
    args = {"szene": "tanz"}
    assert spec["gate"](args, state) is None
    assert await spec["run"](args) == {"szene": "tanz", "hinweis": "Sie tut es jetzt auf der Bühne."}
    assert queue.get_nowait() == ("scene", "tanz") and "_queue" not in args
    assert spec["log"](args, {"szene": "tanz"}) == "tanz -> tanz"
    args = {"szene": "kuss"}                                   # not in the mood: nothing on the stage
    assert spec["gate"](args, state) is None
    assert (await spec["run"](args))["szene"] == "" and queue.empty()
    assert spec["log"](args, {"szene": ""}) == "kuss -> not in the mood"
    args = {"szene": "bett"}                                   # nothing that changes what she wears
    assert spec["gate"](args, state) is None
    assert (await spec["run"](args))["szene"] == "" and queue.empty() and asked == ["tanz", "kuss"]
    blocked = spec["gate"]({"szene": "tanz"}, {"from_app": False})     # the living room has no stage
    assert blocked["szene"] == "" and "App" in blocked["hinweis"]


async def test_the_scene_goes_to_the_app_and_the_app_plays_it(tmp_path, monkeypatch):
    m, bridge = _bridge(monkeypatch, tmp_path)

    class Client:
        leyla_app = True

        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)
    client, queue = Client(), asyncio.Queue()
    task = asyncio.create_task(bridge._output_sender(client, queue, [False], {}))
    await queue.put(("scene", "tanz"))
    for _ in range(40):
        await asyncio.sleep(0.05)
        if client.sent:
            break
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    assert [json.loads(x) for x in client.sent if isinstance(x, str)] == [{"type": "scene", "scene": "tanz"}]
    page = open(memory_web.__file__, encoding="utf-8").read()
    assert "else if(m.type==='scene'){if(m.scene)stageScene(String(m.scene));}" in page
