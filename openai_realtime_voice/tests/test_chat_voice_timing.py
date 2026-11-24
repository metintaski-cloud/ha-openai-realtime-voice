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


def test_streamed_voice_reply_comes_back_at_once_and_arrives_piece_by_piece(monkeypatch, tmp_path):
    """2.142.0: the text returns before the voice is spoken; /api/voice/<id> hands out the PCM as it comes."""
    from app import memory_web, voice_stream

    async def transcribe(key, audio, mime):
        return "Hallo Leyla"

    async def fake_chat(history, message):
        return {"reply": "Hallo Metin", "proposals": [], "lights": []}

    gate = asyncio.Event()

    async def speak(prompt, max_s, instructions, on_chunk=None):
        on_chunk(b"\x01\x00" * 100)
        await gate.wait()
        on_chunk(b"\x02\x00" * 100)
        return b"x" * 400

    monkeypatch.setattr(main.chat, "transcribe", transcribe)

    async def go():
        bridge = types.SimpleNamespace(openai_api_key="k", _chat=fake_chat, _speak_once=speak,
                                       mood=types.SimpleNamespace(feeling=lambda: ""))
        bridge._voice_reply = lambda *a, **k: main.LiveVoiceBridge._voice_reply(bridge, *a, **k)
        out = await main.LiveVoiceBridge._chat_voice(bridge, [], "YWJj", "audio/webm", stream=True)
        assert out["reply"] == "Hallo Metin" and "audio" not in out and out["voice_id"]
        server = await memory_web.start_http(memory_web.memory.MemoryStore(str(tmp_path / "m.json")),
                                             None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"GET /api/voice/{out['voice_id']} HTTP/1.1\r\n\r\n".encode())
        await w.drain()
        head = await r.readuntil(b"\r\n\r\n")
        first = await r.readexactly(200)  # the first piece is there before the voice is finished
        gate.set()
        rest = await r.read()
        w.close()
        server.close()
        await bridge._voice_task
        return head, first, rest

    head, first, rest = asyncio.run(go())
    assert b"200 OK" in head
    assert first == b"\x01\x00" * 100 and rest == b"\x02\x00" * 100


def test_unknown_voice_id_is_404(tmp_path):
    from app import memory_web

    async def go():
        server = await memory_web.start_http(memory_web.memory.MemoryStore(str(tmp_path / "m.json")),
                                             None, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"GET /api/voice/nichtda HTTP/1.1\r\n\r\n")
        await w.drain()
        data = await r.read()
        server.close()
        return data

    assert b"404" in asyncio.run(go()).split(b"\r\n")[0]


def test_with_the_setting_she_hears_the_recording_while_the_answer_is_written(monkeypatch):
    """2.151.0: the listening session starts before the text is there and gets the note later."""
    from app import voice_stream
    order = []

    async def to_pcm(audio):
        return b"\x03\x00" * 12000

    async def transcribe(key, audio, mime):
        order.append("transcribe")
        await asyncio.sleep(0.05)
        return "Hallo Leyla"

    async def fake_chat(history, message):
        order.append("chat")
        return {"reply": "Hallo Metin", "proposals": [], "lights": []}

    got = {}

    async def speak(prompt, max_s, instructions, on_chunk=None, heard=b"", heard_prompt=None):
        order.append("listen")
        got["heard"] = len(heard)
        got["after"] = await heard_prompt
        got["plain"] = await prompt
        on_chunk(b"\x01\x00" * 100)
        return b"x" * 400

    monkeypatch.setattr(main.chat, "transcribe", transcribe)
    monkeypatch.setattr(main.voice_in, "to_pcm", to_pcm)

    async def go(setting, said="Hallo Leyla"):
        order.clear()
        got.clear()
        bridge = types.SimpleNamespace(openai_api_key="k", _chat=fake_chat, _speak_once=speak,
                                       mood=types.SimpleNamespace(feeling=lambda: ""),
                                       recall=types.SimpleNamespace(settings={"hoeren": setting}))
        bridge._voice_reply = lambda *a, **k: main.LiveVoiceBridge._voice_reply(bridge, *a, **k)
        out = await main.LiveVoiceBridge._chat_voice(bridge, [], "YWJj", "audio/webm", stream=True)
        await bridge._voice_task
        chunks = [c async for c in voice_stream.get(out["voice_id"]).read(1.0)]
        return out, chunks

    out, chunks = asyncio.run(go(1))
    assert order == ["transcribe", "listen", "chat"] and got["heard"] == 24000
    assert "Hallo Metin" in got["after"] and got["after"] == main.chat.hear_prompt("Hallo Metin")
    assert got["plain"] == main.chat.speak_prompt("Hallo Metin") and chunks == [b"\x01\x00" * 100]

    async def old_speak(prompt, max_s, instructions, on_chunk=None):  # setting off: the old way
        order.append("speak")
        got["plain"] = prompt
        return b"x" * 400

    async def go_off():
        order.clear()
        bridge = types.SimpleNamespace(openai_api_key="k", _chat=fake_chat, _speak_once=old_speak,
                                       mood=types.SimpleNamespace(feeling=lambda: ""),
                                       recall=types.SimpleNamespace(settings={"hoeren": 0}))
        bridge._voice_reply = lambda *a, **k: main.LiveVoiceBridge._voice_reply(bridge, *a, **k)
        out = await main.LiveVoiceBridge._chat_voice(bridge, [], "YWJj", "audio/webm", stream=True)
        await bridge._voice_task
        return out
    asyncio.run(go_off())
    assert order == ["transcribe", "chat", "speak"] and got["plain"] == main.chat.speak_prompt("Hallo Metin")


def test_nothing_understood_ends_the_listening_session_without_a_voice(monkeypatch):
    async def to_pcm(audio):
        return b"\x03\x00" * 12000

    async def transcribe(key, audio, mime):
        await asyncio.sleep(0.02)
        return ""

    got = {}

    async def speak(prompt, max_s, instructions, on_chunk=None, heard=b"", heard_prompt=None):
        got["after"] = await heard_prompt
        return b""

    monkeypatch.setattr(main.chat, "transcribe", transcribe)
    monkeypatch.setattr(main.voice_in, "to_pcm", to_pcm)

    async def go():
        bridge = types.SimpleNamespace(openai_api_key="k", _chat=None, _speak_once=speak,
                                       mood=types.SimpleNamespace(feeling=lambda: ""),
                                       recall=types.SimpleNamespace(settings={"hoeren": 1}))
        bridge._voice_reply = lambda *a, **k: main.LiveVoiceBridge._voice_reply(bridge, *a, **k)
        out = await main.LiveVoiceBridge._chat_voice(bridge, [], "YWJj", "audio/webm", stream=True)
        await asyncio.wait_for(bridge._voice_task, 2)
        return out
    assert asyncio.run(go()) == {"heard": ""} and got["after"] == ""
