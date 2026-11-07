"""Messages between Metin and his mother."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import messages  # noqa: E402
from tests.test_lights import _HA, _server  # noqa: E402


def _center(tmp_path, port, spoken):
    async def speak(prompt):
        spoken.append(prompt)
        return b"\x01\x00" * 2400

    return messages.MessageCenter(speak, notify_service="notify.mobile_app_handy",
                                  media_player="media_player.voice",
                                  base_url="http://1.2.3.4:8082",
                                  path=str(tmp_path / "m.json"),
                                  api_url=f"http://127.0.0.1:{port}/api", token="tok")


async def test_flow(tmp_path):
    _HA.calls.clear()
    server = _server(19994)
    spoken = []
    mc = _center(tmp_path, 19994, spoken)
    try:
        r = await mc.to_metin({"text": "Metin ekmek al", "text_de": "Metin, kauf Brot",
                               "sender": "Mama"})
        assert r["sent"]
        svc, body = _HA.calls[-1][1], _HA.calls[-1][2]
        assert svc == "mobile_app_handy" and "kauf Brot" in body["message"]
        assert body["data"]["actions"][0]["action"] == "REPLY"

        await mc.from_metin("Ich komme um 8")
        await mc._tick()
        assert spoken and "Ich komme um 8" in spoken[0]
        play = _HA.calls[-1]
        assert play[1] == "play_media" and play[2]["announce"] is True
        key = play[2]["media_content_id"].rsplit("/", 1)[-1][:-4]
        assert mc.audio[key][:4] == b"RIFF"
        await mc._tick()
        assert len(spoken) == 1  # not again before 10 minutes

        p = mc.pending()
        p["last"] = time.time() - 700
        mc._save(p)
        await mc._tick()
        assert len(spoken) == 2 and "Erinnerung" in spoken[1]

        assert messages.is_ack("tamam Leyla")
        assert await mc.acknowledge("tamam")
        assert mc.pending() is None and "bestätigt" in _HA.calls[-1][2]["message"]

        await mc.from_metin("Test")
        p = mc.pending()
        p["created"] = time.time() - 4000
        mc._save(p)
        await mc._tick()
        assert mc.pending() is None and "nicht" in _HA.calls[-1][2]["message"]
    finally:
        server.shutdown()


async def test_say(tmp_path):
    _HA.calls.clear()
    server = _server(19993)
    spoken = []
    mc = _center(tmp_path, 19993, spoken)
    try:
        await mc.say("Saat 16:41, lambaları açıyorum.")
        assert "16:41" in spoken[0] and _HA.calls[-1][1] == "play_media"
    finally:
        server.shutdown()


async def test_message_brought_up_in_a_conversation(tmp_path):
    spoken = []

    async def speak(prompt):
        spoken.append(prompt)
        return b"\x00\x00" * 100

    mc = messages.MessageCenter(speak, notify_service="notify.x", media_player="media_player.x",
                                base_url="http://h:8082", path=str(tmp_path / "m.json"),
                                api_url="http://127.0.0.1:1/api", token="t")

    async def push(*a, **k):
        return None

    mc.push = push
    await mc.to_metin({"text": "Eve gelirken ekmek al", "sender": "Mama"})
    await mc.from_metin("Tamam, ekmek alıyorum, 20 dakikaya evdeyim")
    prompts = []

    async def converse(prompt):
        prompts.append(prompt)
        return True

    mc.converse = converse
    await mc._tick()
    assert len(prompts) == 1 and not spoken  # a conversation, no announcement
    assert "ekmek al" in prompts[0] and "20 dakikaya" in prompts[0]
    assert "antworten möchte" in prompts[0] and "auf Türkisch" in prompts[0]
    assert "Erinnerung" not in prompts[0]
    assert mc.pending()["announced"] == 1
    p = mc.pending()
    p["last"] = 0
    mc._save(p)
    await mc._tick()
    assert "Erinnerung" in prompts[1]
