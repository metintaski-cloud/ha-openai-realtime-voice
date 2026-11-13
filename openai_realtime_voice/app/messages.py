"""
Messages between Metin (phone) and his mother (Leyla in the living room).

Mama -> Metin: Leyla calls the tool nachricht_an_metin; Metin gets a push message on
his phone through the Home Assistant app, with a reply field.

Metin -> Mama: Metin answers that push message, or types into the helper
input_text.leyla_nachricht in the Home Assistant app. Leyla then announces it in
Turkish on the Voice PE speaker, without anyone waking her, and repeats it every
10 minutes until somebody says "Hallo Leyla, tamam". After one hour without an
answer she stops and Metin gets a push message that nobody confirmed it.

Announcements are spoken by GPT Live itself (same voice as Leyla). The audio is
served as a WAV file on a small HTTP port and played with media_player.play_media
(announce) on the Voice PE.
"""
import asyncio
import base64
import io
import json
import logging
import os
import time
import uuid
import wave
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

import httpx
import websockets

logger = logging.getLogger(__name__)

REPEAT_EVERY_S = 600
GIVE_UP_AFTER_S = 3600
ACK_WORDS = ("tamam", "tamamdır", "tamamdir", "anladım", "anladim", "duydum", "olur", "oldu",
             "peki", "verstanden", "gehört", "gehoert")
INPUT_HELPER = "input_text.leyla_nachricht"

TO_METIN_TOOL = {
    "type": "function",
    "name": "nachricht_an_metin",
    "description": (
        "Send a short message to Metin's phone, for example when his mother says "
        "'Metin'e söyle ekmek alsın' or 'sag Metin, er soll Brot kaufen'. Use the words of "
        "the speaker; also give a German version."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The message as said."},
            "text_de": {"type": "string", "description": "The message in German."},
            "sender": {"type": "string", "description": "Who sends it, e.g. Mama."},
        },
        "required": ["text", "text_de", "sender"],
        "additionalProperties": False,
    },
}

TO_METIN_BACKEND_HINT = (
    " When someone asks you to tell Metin something, to send him a message, or to remind "
    "him of something ('Metin'e söyle', 'Metin'e mesaj at', 'sag Metin'), call "
    "nachricht_an_metin with the message and confirm briefly that Metin got it on his phone. "
    "Then always ask whether you should tell him anything else, in the person's language "
    "(Turkish for Mama, e.g. 'Metin'e başka bir şey söylememi ister misin?'). If she adds "
    "something, send it as a new message. The sender is usually Mama (Gülfikar) unless the "
    "person says otherwise."
)

def _env(name: str, default: str = "") -> str:
    v = (os.environ.get(name) or "").strip()
    return default if not v or v.lower() == "null" else v


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def is_ack(text: str) -> bool:
    import re
    words = re.findall(r"\w+", (text or "").lower())
    for i, w in enumerate(words):
        if w in ACK_WORDS:
            if w == "oldu" and i and words[i - 1] in ("ne", "nasıl", "nasil", "kim"):
                continue  # "ne oldu?" is a question, not a confirmation
            return True
    return False


class MessageCenter:
    def __init__(self, speak: Callable[[str], Awaitable[bytes]],
                 notify_service: str = "", media_player: str = "",
                 base_url: str = "", port: int = 8082,
                 path: str = "/data/messages.json",
                 api_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self.speak = speak
        self.notify_service = notify_service
        self.media_player = media_player
        self.base_url = base_url.rstrip("/")
        self.port = port
        self.path = path
        self.api_url = api_url or _env("HA_API_URL", "http://supervisor/core/api")
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.audio: dict[str, bytes] = {}
        self._wake = asyncio.Event()
        self.on_command: Optional[Callable[[dict], Awaitable[dict]]] = None
        # entity_id -> callback(new state string), for state_changed events
        self.state_listeners: dict[str, Callable[[str], None]] = {}
        self.mute_switch = ""
        # Brings a message up in a real conversation (set by the bridge); returns False
        # when that is not possible, then the message is only announced.
        self.converse: Optional[Callable[[str], Awaitable[bool]]] = None

    @property
    def available(self) -> bool:
        return bool(self.token and self.notify_service)

    # storage ---------------------------------------------------------------
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _write(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def pending(self) -> Optional[dict]:
        return self._load().get("pending")

    def _save(self, pending: Optional[dict]) -> None:
        data = self._load()
        data["pending"] = pending
        self._write(data)

    # Home Assistant ----------------------------------------------------------
    async def _service(self, domain: str, service: str, data: dict) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{self.api_url}/services/{domain}/{service}", json=data,
                                     headers={"Authorization": f"Bearer {self.token}"})
        if resp.status_code >= 300:
            raise RuntimeError(f"HA HTTP {resp.status_code}: {resp.text[:200]}")

    async def push(self, title: str, message: str, reply: bool = False) -> None:
        domain, _, service = self.notify_service.partition(".")
        data: dict = {"title": title, "message": message}
        if reply:
            data["data"] = {"actions": [{"action": "REPLY", "title": "Antworten"}]}
        await self._service(domain, service, data)

    # Mama -> Metin -------------------------------------------------------------
    async def to_metin(self, args: dict) -> dict:
        text = (args.get("text") or "").strip()
        if not text:
            return {"error": "Die Nachricht ist leer."}
        de = (args.get("text_de") or "").strip()
        sender = (args.get("sender") or "Mama").strip()
        body = text if not de or de == text else f"{text}\n({de})"
        # Leyla reports on her own, e.g. when someone was rude to her
        title = "Leyla meldet" if sender.lower() == "leyla" else f"Leyla: Nachricht von {sender}"
        try:
            await self.push(title, body, reply=True)
        except Exception as e:
            logger.warning("Push to Metin failed: %s", e)
            return {"error": "Die Nachricht konnte gerade nicht gesendet werden."}
        logger.info("Message to Metin sent: %r", text)
        self._remember_sent(text)
        return {"sent": True, "to": "Metin"}

    def _remember_sent(self, text: str) -> None:
        data = self._load()
        data["last_to_metin"] = {"text": text, "at": time.time()}
        self._write(data)

    def last_to_metin(self, max_age_s: float = 12 * 3600) -> Optional[str]:
        last = self._load().get("last_to_metin") or {}
        if last.get("text") and time.time() - float(last.get("at") or 0) < max_age_s:
            return last["text"]
        return None

    # Metin -> Mama ---------------------------------------------------------------
    async def from_metin(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._save({"id": uuid.uuid4().hex[:8], "text": text, "created": time.time(),
                    "announced": 0, "last": 0.0})
        logger.info("Message from Metin queued: %r", text)
        self._wake.set()

    def live_hint(self) -> str:
        p = self.pending()
        if not p:
            return ""
        return ("\n\nOffene Nachricht von Metin an seine Mutter, die du schon im Raum angesagt "
                f"hast: \"{p['text']}\". Wenn jemand danach fragt, sag sie auf Türkisch. Wenn "
                "jemand sie bestätigt (zum Beispiel 'tamam'), sag kurz und lieb, dass du Metin "
                "Bescheid gibst.")

    async def acknowledge(self, by_text: str = "") -> bool:
        p = self.pending()
        if not p:
            return False
        self._save(None)
        logger.info("Message from Metin confirmed (%r)", by_text.strip())
        try:
            await self.push("Leyla", f"Mama hat deine Nachricht bestätigt: {p['text']}")
        except Exception as e:
            logger.warning("Could not tell Metin about the confirmation: %s", e)
        return True

    async def say(self, text: str, bilingual: bool = False) -> None:
        """One announcement from an automation (HA event leyla_announce), no repeats."""
        text = (text or "").strip()
        if not text:
            return
        language = ("zweisprachig: erst auf Deutsch, dann dasselbe noch einmal auf Türkisch, "
                    "egal in welcher Sprache der Inhalt unten geschrieben ist" if bilingual else
                    "in genau der Sprache, in der der Inhalt unten geschrieben ist; ist er "
                    "Türkisch, dann komplett auf Türkisch, ohne ein deutsches Wort")
        prompt = ("Sag der Familie jetzt etwas im Wohnzimmer, " + language + ". Das ist keine "
                  "Durchsage und nichts zum Vorlesen: Sprich so, wie du es einem lieben "
                  "Familienmitglied sagen würdest, das du sehr magst, warm, zugewandt, mit "
                  "Lächeln und natürlicher Betonung, mit deinen eigenen Worten und nur dem "
                  "Sinn des Inhalts unten. Fasse dich sehr kurz, höchstens zwei kurze Sätze, "
                  "damit es schnell geht, ohne Kosewörter wie „canım“. Alle wichtigen "
                  "Informationen wie Name, Uhrzeit und was du tust müssen drin bleiben. "
                  "Danach sagst du nichts mehr. Inhalt: \"" + text + "\"")
        await self._play(await self.speak(prompt))
        logger.info("Announced: %r", text)

    async def _play(self, pcm: bytes) -> None:
        if not pcm:
            raise RuntimeError("no audio")
        key = uuid.uuid4().hex[:10]
        self.audio = {key: pcm_to_wav(pcm)}
        url = f"{self.base_url}/announce/{key}.wav"
        # Mute the Voice PE microphone while it speaks, so the announcement cannot
        # wake Leyla herself.
        if self.mute_switch:
            try:
                await self._service("switch", "turn_on", {"entity_id": self.mute_switch})
            except Exception as e:
                logger.info("Could not mute during announcement: %s", e)
        await self._service("media_player", "play_media", {
            "entity_id": self.media_player, "media_content_id": url,
            "media_content_type": "music", "announce": True,
        })
        if self.mute_switch:
            seconds = len(pcm) / 48000 + 2.5
            asyncio.get_event_loop().call_later(
                seconds, lambda: asyncio.ensure_future(self._unmute()))

    async def _unmute(self) -> None:
        try:
            await self._service("switch", "turn_off", {"entity_id": self.mute_switch})
        except Exception as e:
            logger.warning("Could not unmute after announcement: %s", e)

    def conversation_prompt(self, p: dict) -> str:
        """How Leyla brings Metin's message up herself and talks about it."""
        context = self.last_to_metin()
        about = (f" Sie hatte ihm vorher geschrieben: „{context}“, seine Nachricht ist die "
                 "Antwort darauf." if context else "")
        again = (" Das ist eine Erinnerung, du hast es vor ein paar Minuten schon gesagt, "
                 "aber niemand hat reagiert." if p.get("announced") else "")
        return (
            "Du meldest dich gerade von selbst im Wohnzimmer, weil eine Nachricht von Metin an "
            f"seine Mutter gekommen ist.{about}{again} Seine Nachricht: „{p['text']}“. Sprich "
            "dabei alles auf Türkisch, auch jede Frage. Sag es ihr warm und natürlich mit deinen "
            "eigenen Worten, nicht vorgelesen, in der dritten Person (zum Beispiel „Metin "
            "ekmeği alacakmış“), und nimm Bezug auf ihre Nachricht, wenn es passt. Frag sie "
            "danach kurz, ob sie ihm etwas antworten möchte, zum Beispiel „Ona bir cevap "
            "yazmamı ister misin?“. Antwortet sie mit einer Nachricht, schick sie mit "
            "nachricht_an_metin an ihn, sag kurz, dass sie unterwegs ist, und frag, ob du ihm "
            "noch etwas mitteilen sollst. Sagt sie nur tamam oder Ähnliches, sag lieb, dass du "
            "Metin Bescheid gibst. Antwortet niemand, sag nichts mehr."
        )

    async def _announce(self, p: dict) -> None:
        if self.converse:
            try:
                if await self.converse(self.conversation_prompt(p)):
                    logger.info("Message from Metin brought up in a conversation (%d. time)",
                                p.get("announced", 0) + 1)
                    return
            except Exception as e:
                logger.warning("Could not start a conversation for the message: %s", e)
        prompt = (
            "Sag jetzt eine kurze Ansage auf Türkisch, lebendig und herzlich als "
            "Teil der Familie, ohne Kosewörter wie „canım“, nicht vorgelesen, und danach nichts mehr. "
            "Inhalt: Es gibt eine Nachricht von Metin. Übersetze seine Nachricht ins Türkische "
            f"und sag sie: \"{p['text']}\". Sag am Ende: Wenn du es gehört hast, sag "
            "'Hallo Leyla, tamam'."
        )
        if p.get("announced"):
            prompt = ("Das ist eine Erinnerung. " + prompt)
        await self._play(await self.speak(prompt))
        logger.info("Announced message from Metin (%d. time)", p.get("announced", 0) + 1)

    async def _tick(self) -> None:
        p = self.pending()
        if not p:
            return
        now = time.time()
        if now - p["created"] >= GIVE_UP_AFTER_S:
            self._save(None)
            logger.info("Message from Metin not confirmed within an hour, giving up")
            try:
                await self.push("Leyla", "Mama hat deine Nachricht nach einer Stunde nicht "
                                         f"bestätigt: {p['text']}")
            except Exception as e:
                logger.warning("Push failed: %s", e)
            return
        if now - p.get("last", 0.0) >= REPEAT_EVERY_S:
            try:
                await self._announce(p)
                p["announced"] = p.get("announced", 0) + 1
            except Exception as e:
                logger.warning("Announcement failed: %s", e)
            p["last"] = now
            if self.pending() and self.pending().get("id") == p["id"]:
                self._save(p)

    async def scheduler(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.warning("Message scheduler error: %s", e)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    # Home Assistant events --------------------------------------------------------
    async def listen(self) -> None:
        u = urlparse(self.api_url)
        ws_url = f"{'wss' if u.scheme == 'https' else 'ws'}://{u.netloc}" + \
            u.path.rsplit("/api", 1)[0] + "/websocket"
        while True:
            try:
                async with websockets.connect(ws_url, max_size=None) as ws:
                    await ws.recv()
                    await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth = json.loads(await ws.recv())
                    if auth.get("type") != "auth_ok":
                        raise RuntimeError(f"HA auth failed: {auth.get('type')}")
                    await ws.send(json.dumps({"id": 1, "type": "subscribe_events",
                                              "event_type": "mobile_app_notification_action"}))
                    await ws.send(json.dumps({"id": 2, "type": "subscribe_events",
                                              "event_type": "state_changed"}))
                    await ws.send(json.dumps({"id": 3, "type": "subscribe_events",
                                              "event_type": "leyla_announce"}))
                    await ws.send(json.dumps({"id": 4, "type": "subscribe_events",
                                              "event_type": "leyla_command"}))
                    logger.info("Listening for messages from Metin")
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        ev = msg.get("event", {})
                        data = ev.get("data", {})
                        if ev.get("event_type") == "leyla_command" and self.on_command:
                            task = asyncio.create_task(self.on_command(dict(data)))
                            task.add_done_callback(
                                lambda t: t.exception() and logger.warning(
                                    "Command failed: %s", t.exception()))
                        elif ev.get("event_type") == "leyla_announce":
                            task = asyncio.create_task(self.say(data.get("text", ""),
                                                             bool(data.get("zweisprachig"))))
                            task.add_done_callback(
                                lambda t: t.exception() and logger.warning(
                                    "Announcement failed: %s", t.exception()))
                        elif ev.get("event_type") == "mobile_app_notification_action":
                            if data.get("action") == "REPLY" and data.get("reply_text"):
                                await self.from_metin(data["reply_text"])
                        elif data.get("entity_id") in self.state_listeners:
                            new = (data.get("new_state") or {}).get("state", "")
                            try:
                                self.state_listeners[data["entity_id"]](new)
                            except Exception as e:
                                logger.warning("State listener %s: %s", data["entity_id"], e)
                        elif data.get("entity_id") == INPUT_HELPER:
                            new = (data.get("new_state") or {}).get("state", "")
                            if new and new not in ("unknown", "unavailable", ""):
                                await self.from_metin(new)
                                try:
                                    await self._service("input_text", "set_value", {
                                        "entity_id": INPUT_HELPER, "value": ""})
                                except Exception:
                                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("HA event listener: %s, reconnecting in 15 s", e)
                await asyncio.sleep(15)

    # HTTP for the announcement audio ------------------------------------------------
    async def _handle_http(self, reader, writer) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
            while True:
                h = await asyncio.wait_for(reader.readline(), 5)
                if h in (b"\r\n", b"\n", b""):
                    break
            parts = line.split()
            path = urlparse(parts[1] if len(parts) > 1 else "/").path
            key = path.rsplit("/", 1)[-1].removesuffix(".wav")
            data = self.audio.get(key) if path.startswith("/announce/") else None
            if data is None:
                head = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(head)
            else:
                writer.write((f"HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\n"
                              f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n")
                             .encode() + data)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def start(self) -> list:
        server = await asyncio.start_server(self._handle_http, "0.0.0.0", self.port)
        tasks = [asyncio.create_task(self.scheduler()), asyncio.create_task(self.listen())]
        logger.info("Messages: push %s, announce on %s via %s", self.notify_service,
                    self.media_player, self.base_url)
        return [server] + tasks


def from_env(speak) -> MessageCenter:
    mc = MessageCenter(
        speak,
        notify_service=_env("NOTIFY_SERVICE"),
        media_player=_env("ANNOUNCE_PLAYER", "media_player.home_assistant_voice_0ae305_media_player"),
        base_url=_env("ANNOUNCE_BASE_URL", "http://192.168.2.240:8082"),
        port=int(_env("ANNOUNCE_PORT", "8082")),
        path=_env("MESSAGES_PATH", "/data/messages.json"),
    )
    mc.mute_switch = _env("ANNOUNCE_MUTE_SWITCH", "switch.home_assistant_voice_0ae305_mute")
    return mc
