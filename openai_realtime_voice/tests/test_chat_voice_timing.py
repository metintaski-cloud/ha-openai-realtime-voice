"""2.141.9: the timing of voice messages broke them for a few minutes (t1 not defined), so the
whole path runs once here with the outside calls replaced."""
import asyncio
import base64
import types

from app import main


def test_voice_message_runs_through_and_reports_its_steps(monkeypatch):
    async def transcribe(key, audio, mime):
        return "Hallo Leyla"

    async def fake_chat(history, message):
        return {"reply": "Hallo Metin", "proposals": [], "lights": []}

    async def speak(prompt, max_s, instructions):
        return b"\x00\x00" * 2400

    monkeypatch.setattr(main.chat, "transcribe", transcribe)
    bridge = types.SimpleNamespace(openai_api_key="k", _chat=fake_chat, _speak_once=speak,
                                   mood=types.SimpleNamespace(feeling=lambda: ""))
    out = asyncio.run(main.LiveVoiceBridge._chat_voice(
        bridge, [], base64.b64encode(b"abc").decode(), "audio/webm"))
    assert out["heard"] == "Hallo Leyla" and out["audio"]
    assert set(out["t"]) == {"hoeren", "antwort", "stimme"}
