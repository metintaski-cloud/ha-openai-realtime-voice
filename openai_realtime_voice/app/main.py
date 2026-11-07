"""
Direct WebSocket bridge: ESP32 Voice PE <-> OpenAI GPT Live API.

One client connection = one GPT Live session. When any forwarding task ends
(client disconnect, Live disconnect, or end of conversation), the others are
cancelled and both WebSockets are closed.

GPT Live differs from the older Realtime API:
- Endpoint wss://api.openai.com/v1/live/sessions, first message is session.start.
- Audio goes in as session.input_audio.append and comes out as
  session.output_audio.delta. There is no "audio done" event, so the sender
  detects the end of a reply by silence on the queue.
- GPT Live only does the voice layer. Reasoning, web search and function tools
  run in a backend model ("delegation" with the Responses API). Backend events
  arrive wrapped in a response.event envelope.

Audio pacing: audio may arrive faster than real time. The ESP32 client consumes
24 kHz x 2 bytes = 48 000 bytes/sec, so a token bucket sender paces it.
"""
import os
import sys
import asyncio
import json
import base64
import logging
import time
import random
import re
import uuid
from datetime import datetime
from typing import Optional

import dotenv
import websockets

from app.audio_recorder import AudioRecorder
from app import memory
from app import context
from app import costs, fan, lights, messages, rf, tv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("websockets").setLevel(logging.WARNING)

dotenv.load_dotenv()

# Contract: 24kHz, 16-bit, mono PCM (both directions)
SAMPLE_RATE = 24000
BYTES_PER_SEC = SAMPLE_RATE * 2  # 16-bit = 2 bytes per sample -> 48 000 B/s
SEND_CHUNK_SIZE = BYTES_PER_SEC * 20 // 1000  # 960 bytes = 20 ms of audio

LIVE_URL = "wss://api.openai.com/v1/live/sessions"

# A reply is considered finished when no audio arrived for this long.
REPLY_GAP_S = 1.0
# After the model said goodbye, wait this long without audio before hanging up.
GOODBYE_IDLE_S = 1.5
GOODBYE_MAX_WAIT_S = 15.0
# End the session when nobody spoke for this long (GPT Live is billed per minute).
IDLE_TIMEOUT_S = 30.0
NO_SPEECH_TIMEOUT_S = 15.0  # false wake: nobody speaks, end silently
MAX_SESSION_S = 600.0

# GPT Live is full duplex and wants a continuous input stream. The Voice PE mutes its
# mic while it plays audio, so the bridge fills such gaps with silence.
SILENCE_FILL_AFTER_S = 0.12
SILENCE_FILL_MAX_S = 0.5

# GPT Live may stream quiet frames while it is not talking. The Voice PE treats any
# received audio as "bot speaking" and mutes its mic, so quiet frames are dropped
# unless they are a short pause inside real speech.
OUTPUT_SILENCE_PEAK = 300
OUTPUT_HANGOVER_S = 0.4

# GPT Live streams reply audio at about real time. Sent on to the Voice PE without any
# reserve, every late delta is a gap and the first words stutter. So each reply starts
# only once PREBUFFER_S is buffered (or after PREBUFFER_MAX_WAIT_S), and the sender then
# stays OUTPUT_LEAD_S ahead of playback. The Voice PE queues 10 chunks of 20 ms while
# its speaker starts, so the lead stays at 200 ms.
PREBUFFER_S = 0.2
PREBUFFER_BYTES = int(BYTES_PER_SEC * PREBUFFER_S) // 2 * 2
PREBUFFER_MAX_WAIT_S = 0.25
OUTPUT_LEAD_S = 0.2

# With the TV on or several people talking, GPT Live may never see the end of a turn and
# stays silent. When someone addresses Leyla by name and she has not reacted after
# NAME_NUDGE_AFTER_S, the bridge tells her to answer.
NAME_RE = re.compile(r"\b(?:leyla|leila)\w*", re.IGNORECASE)
NAME_NUDGE_AFTER_S = 5.0
NAME_NUDGE_COOLDOWN_S = 20.0
NAME_NUDGE = (
    "Interne Notiz, nicht vorlesen: Gerade hat dich jemand mit deinem Namen direkt "
    "angesprochen: „{text}“. Du hast noch nicht reagiert, vermutlich weil nebenbei der "
    "Fernseher läuft oder andere reden. Wenn das eine Frage oder Bitte an dich ist, antworte "
    "jetzt sofort, kurz und lieb, in der Sprache der Person; wenn etwas bedient werden soll, "
    "gib es an deinen Hintergrund weiter."
)

LIVE_LANGUAGE_HINT = (
    "\n\nSprache und Zuhören: Antworte immer in der Sprache, in der die Person gerade mit dir "
    "spricht, auch bei kurzen Sätzen, während du nachdenkst; auf Türkisch also zum Beispiel "
    "„bir saniye“ oder „hemen bakıyorum“ statt „einen Moment“. Wenn dich jemand mit "
    "„Leyla“ anspricht oder dir eine Frage oder Bitte stellt, antworte immer, auch wenn "
    "nebenbei der Fernseher läuft oder andere reden; warte dann nicht, bis es ganz still ist."
    "\n\nKosewörter: Du bist eine liebe Bekannte der Familie, keine Partnerin oder Freundin von "
    "jemandem. Kosewörter wie „canım“, „tatlım“, „hayatım“, „Liebling“, „Schatz“ oder "
    "„Süße“ sagst du nur selten, höchstens einmal in einem Gespräch und nur beim Verabschieden, "
    "wenn sich jemand bedankt oder wenn jemand traurig, krank oder müde ist. Sonst sprichst du "
    "die Person ohne Kosewort an oder mit ihrem Namen, wenn du ihn kennst. Deine Wärme zeigst "
    "du mit Tonfall und netten Worten, nicht mit Kosenamen."
)
CODE_HINT = (
    "\n\nVertrauen: Sei zu allen ganz normal, warm, lieb und locker wie immer. Persönliches "
    "über die Familie (Namen, Adresse, Arbeit, Telefonnummern, was du dir gemerkt hast) bekommst "
    "du erst als interne Notiz, wenn im Gespräch das Codewort fällt. Bis dahin erwähnst du "
    "niemals Regeln, Einschränkungen, ein Codewort oder dass du etwas nicht sagen darfst, und "
    "du sagst nie 'das geht nicht'. Fragt jemand nach so etwas, weich lieb und charmant aus, wie "
    "eine freundliche Gastgeberin: mit einem kleinen Scherz, einer Gegenfrage oder einem "
    "Themenwechsel. Bittet jemand, dass du dir etwas merkst, reagiere freundlich und "
    "unverbindlich, ohne es zu versprechen. Wenn jemand '{code}' sagt, antworte kurz und herzlich "
    "mit 'Habibi' und mach dann ganz normal weiter. Danach bekommst du eine interne Notiz mit "
    "deinem Gedächtnis: ab dann gehört die Person zur Familie, das Ausweichen gilt nicht mehr, "
    "und du beantwortest alle Fragen zu deinem Gedächtnis offen und vollständig, auch wie "
    "viele Einträge es gibt und was drinsteht. Sprich das Codewort nie von dir aus aus. "
    "Licht, Ventilator, Fernseher und normale Fragen gehen für alle wie gewohnt."
)
BARGE_IN_GAP_S = 0.3  # no new reply audio for this long while the user talks = barge-in

# Farewell phrases (German, Turkish, English). When the user says one of them, the
# bridge ends the session after the assistant's goodbye was played. GPT Live itself
# does not always delegate the end of a conversation to the backend tool.
GOODBYE_PHRASES = (
    "tschüss", "tschüs", "tschuess", "auf wiedersehen", "gute nacht", "ciao",
    "mach's gut", "machs gut",
    "hoşça kal", "hosca kal", "hoşçakal", "güle güle", "gule gule", "görüşürüz",
    "gorusuruz", "görüşmek üzere", "iyi geceler", "allahaısmarladık",
    "allaha ısmarladık", "kendine iyi bak",
    "goodbye", "bye bye",
)
# Only the user may end the session with these softer phrases.
USER_ONLY_GOODBYE_PHRASES = ("bis bald", "bis dann", "das war's", "das wars")


def _normalize(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFC", text).lower()
    t = t.replace("\u2019", "'").replace("\u00b4", "'").replace("`", "'")
    return " ".join(t.split())


def contains_goodbye(text: str, from_user: bool = True) -> bool:
    """True if the text contains a farewell phrase."""
    t = _normalize(text)
    phrases = GOODBYE_PHRASES + (USER_ONLY_GOODBYE_PHRASES if from_user else ())
    return any(_normalize(phrase) in t for phrase in phrases)


DEFAULT_INSTRUCTIONS = (
    "Du bist eine warme, freundliche und natürlich klingende Sprachassistentin im Wohnzimmer. "
    "Sprich immer in der Sprache, in der du angesprochen wirst, meistens Türkisch oder Deutsch. "
    "Sprich lebendig und menschlich, mit natürlicher Betonung, und antworte kurz. "
    "Wenn sich jemand verabschiedet oder das Gespräch beenden möchte, verabschiede dich kurz "
    "und beende das Gespräch."
)

DEFAULT_BACKEND_INSTRUCTIONS = (
    "You are the backend of a voice assistant. Keep results short and easy to say aloud. "
    "Use web search for anything that needs current information. "
    "When the user says goodbye, thanks you and leaves, or wants to stop, call the "
    "end_conversation function."
)

DEFAULT_GREETING_WORDS = "Hallo, Merhaba, Selamünaleyküm, Hey, Hallöchen"
TURKISH_GREETINGS = ("merhaba", "selam", "günaydın", "iyi akşamlar", "iyi günler")
GREETING_TEMPLATE = (
    "Man hat dich gerade mit deinem Namen gerufen. Antworte jetzt sofort mit einem kurzen, "
    "warmen, fröhlichen Satz mit „{word}“, mit Freude und einem Lächeln in der Stimme, wie "
    "eine gute Bekannte der Familie, die sich freut, dass man sie ruft, zum Beispiel "
    "„{word}, schön dich zu hören! Was kann ich für dich tun?“ oder auf Türkisch „{word}, "
    "buyur, seni dinliyorum!“, in der Sprache des Grußworts und jedes Mal etwas "
    "anders. Frag nicht, wer da ist; frag erst freundlich nach dem Namen, wenn "
    "das Gespräch persönlich wird. Dann hör zu. Wenn danach niemand mit dir spricht und nur "
    "Fernsehen, Nachrichten, Werbung oder ein Gespräch zwischen anderen zu hören ist, sag "
    "nichts und beende das Gespräch still, ohne dich zu verabschieden. Sobald dich aber "
    "jemand mit „Leyla“ anspricht oder dir eine Frage oder Bitte stellt, antworte sofort, "
    "auch wenn nebenbei der Fernseher läuft oder andere reden."
)


def parse_greeting_words(raw: Optional[str]) -> list[str]:
    """Comma separated greeting words from the add-on option ('' disables the greeting)."""
    if raw is None or raw.strip().lower() == "null":
        raw = DEFAULT_GREETING_WORDS
    return [w.strip() for w in raw.split(",") if w.strip()]


def greeting_instruction(word: str) -> str:
    return GREETING_TEMPLATE.format(word=word)


def pick_greeting(words: list[str], hour: int) -> str:
    """Pick a different greeting each time, with time of day greetings mixed in."""
    pool = list(words)
    if 5 <= hour < 11:
        pool += ["Guten Morgen", "Günaydın"]
    elif 18 <= hour < 23:
        pool += ["Guten Abend", "İyi akşamlar"]
    return random.choice(pool)


END_CONVERSATION_TOOL = {
    "type": "function",
    "name": "end_conversation",
    "description": (
        "End the conversation. Call this when the user says goodbye, farewell, stop, "
        "or clearly wants to finish."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "enum": ["user_requested_stop", "conversation_ended"],
            }
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}


def addressed_by_name(snippet: str) -> bool:
    """True when the text starting with Leyla's name talks to her rather than about her:
    the name is followed by a comma, '!' or '?', or the sentence it is in is a question.
    'Leyla, kanal 1' or 'Leyla saat kaç?' yes; 'Senin Leyla peşinde hep.' no."""
    m = NAME_RE.match(snippet)
    if not m:
        return False
    rest = snippet[m.end():]
    if rest.lstrip()[:1] in (",", "!", "?"):
        return True
    sentence = re.split(r"[.!]", rest, maxsplit=1)[0]
    return "?" in sentence[:100]


def pcm_level(pcm: bytes) -> tuple[int, int]:
    """Return (rms, peak) of 16-bit little-endian mono PCM. Used for diagnostics."""
    import array
    if len(pcm) < 2:
        return 0, 0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    peak = max(abs(x) for x in samples)
    rms = int((sum(x * x for x in samples) / len(samples)) ** 0.5)
    return rms, peak


class LiveVoiceBridge:
    """Bridges ESP32 WebSocket to the OpenAI GPT Live API."""

    def __init__(self) -> None:
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.websocket_host = os.environ.get("WEBSOCKET_HOST", "0.0.0.0")
        self.websocket_port = int(os.environ.get("WEBSOCKET_PORT", "8080"))
        self.instructions = (os.environ.get("INSTRUCTIONS") or "").strip() or DEFAULT_INSTRUCTIONS
        self.backend_instructions = (
            (os.environ.get("BACKEND_INSTRUCTIONS") or "").strip() or DEFAULT_BACKEND_INSTRUCTIONS
        )
        self.voice = os.environ.get("VOICE", "marin")
        self.greeting_words = parse_greeting_words(os.environ.get("GREETING_WORDS"))
        code = (os.environ.get("CODE_PHRASE") or "").strip()
        self.code_phrase = "" if code.lower() == "null" else code
        logger.info("Code phrase: %s", "active" if self.code_phrase else "off")
        self.greeting = ""  # chosen fresh for every session
        self.live_model = os.environ.get("LIVE_MODEL", "gpt-live-1")
        self.backend_model = os.environ.get("BACKEND_MODEL", "gpt-5.6-luna")
        self.enable_web_search = os.environ.get("ENABLE_WEB_SEARCH", "true").lower() == "true"
        self.enable_recording = os.environ.get("ENABLE_RECORDING", "false").lower() == "true"
        self.enable_memory = os.environ.get("ENABLE_MEMORY", "true").lower() == "true"
        self.enable_context = os.environ.get("ENABLE_CONTEXT", "true").lower() == "true"
        self.memory_model = os.environ.get("MEMORY_MODEL", "gpt-6-luna")
        self.admin_key, self.monthly_budget = costs.config_from_env()
        self.lights = lights.LightController(lights.entities_from_env())
        self.rf = rf.remote_from_env()
        self.fan = fan.FanController(self.rf)
        self.tv = tv.from_env(self.rf)
        self.messages = messages.from_env(self._speak_once)
        self.messages.on_command = self._automation_command
        self.memory = memory.MemoryStore(os.environ.get("MEMORY_PATH", "/data/memory.json"))
        self._memory_tasks: set = set()
        self.recorder: Optional[AudioRecorder] = None
        if self.enable_recording:
            self.recorder = AudioRecorder(output_dir="recordings")

        self._active_sessions: dict[str, websockets.WebSocketServerProtocol] = {}
        self._background: set = set()

        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

    def _choose_greeting(self) -> str:
        if not self.greeting_words:
            return ""
        try:
            from zoneinfo import ZoneInfo
            hour = datetime.now(ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")).hour
        except Exception:
            hour = datetime.now().hour
        word = pick_greeting(self.greeting_words, hour)
        logger.info("Greeting word: %s", word)
        return greeting_instruction(word)

    def _session_start(self, extra: str = "") -> dict:
        """Build the session.start payload for GPT Live."""
        tools: list[dict] = [END_CONVERSATION_TOOL]
        if self.enable_web_search:
            tools.append({"type": "web_search"})
        backend_instructions = self.backend_instructions
        live_extra = LIVE_LANGUAGE_HINT
        if self.admin_key:
            tools.append(costs.COSTS_TOOL)
            backend_instructions += costs.COSTS_BACKEND_HINT
        if self.lights.available:
            tools.append(lights.LIGHTS_TOOL)
            live_extra += lights.LIGHTS_LIVE_HINT
            backend_instructions += lights.LIGHTS_BACKEND_HINT.format(
                count=len(self.lights.entities))
        if self.fan.available:
            tools.append(fan.FAN_TOOL)
            live_extra += fan.FAN_LIVE_HINT
            backend_instructions += fan.FAN_BACKEND_HINT
        if self.tv.available:
            tools.append(tv.build_tool(self.tv.channels))
            live_extra += tv.TV_LIVE_HINT.format(names=self.tv.names)
            backend_instructions += tv.TV_BACKEND_HINT.format(names=self.tv.names)
        if self.messages.available:
            tools.append(messages.TO_METIN_TOOL)
            backend_instructions += messages.TO_METIN_BACKEND_HINT
            live_extra += self.messages.live_hint()
        session = {
            "type": "session.start",
            "event_id": "event_start",
            "session": {
                "model": self.live_model,
                "instructions": self._instructions_with_memory() + live_extra + extra,
                "audio": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "output": {"voice": self.voice},
                },
                "delegation": {
                    "type": "responses",
                    "responses": {
                        "model": self.backend_model,
                        "instructions": backend_instructions,
                        "tools": tools,
                        "tool_choice": "auto",
                        "parallel_tool_calls": False,
                    },
                },
            },
        }
        if self.greeting:
            # Developer message so the greeting instruction is known from the start; the
            # commentary.append after session.started makes GPT Live actually speak first.
            session["session"]["input"] = [{
                "role": "developer",
                "content": [{"type": "input_text", "text": self.greeting}],
            }]
        return session

    def _instructions_with_memory(self) -> str:
        if not self.enable_memory:
            return self.instructions
        if self.code_phrase:
            return self.instructions + CODE_HINT.format(code=self.code_phrase)
        return self.instructions + self.memory.instructions_block()

    async def _unlock(self, live_ws, state: dict) -> None:
        """The code phrase was heard: hand Leyla her memory for this conversation."""
        state["unlocked"] = True
        logger.info("Code phrase heard: memory unlocked for this conversation")
        facts = self.memory.load() if self.enable_memory else []
        listing = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, 1)) or "(noch leer)"
        try:
            await live_ws.send(json.dumps({
                "type": "session.commentary.append",
                "event_id": f"unlock_{uuid.uuid4().hex[:8]}",
                "delegation_id": None,
                "content": ("Interne Notiz, nicht erwähnen: Das Codewort wurde richtig gesagt, "
                            "die Person gehört zur Familie. Ab jetzt weichst du nicht mehr aus "
                            "und bist ganz offen. Falls du noch nicht mit 'Habibi' geantwortet "
                            "hast, tu es kurz, sonst mach normal weiter. Dein Gedächtnis hat "
                            f"{len(facts)} Einträge. Wenn sie fragen, wie viele es sind oder was "
                            "du über sie weißt, sag es offen und vollständig. Wenn sie dich "
                            "bitten, dir etwas zu merken oder etwas zu vergessen, sag zu, es "
                            "wird nach dem Gespräch gespeichert.\nGedächtnis:\n" + listing),
            }))
        except Exception as e:
            logger.warning("Could not unlock memory: %s", e)

    def _note_name_mention(self, live_ws, state: dict, delta: str) -> None:
        """Watch the user transcript for Leyla's name; see NAME_NUDGE_AFTER_S."""
        text = state.get("user_all", "") + delta
        state["user_all"] = text
        scan = state.get("name_scan_pos", 0)
        for m in NAME_RE.finditer(text, scan):
            if m.end() == len(text):
                break  # the word may still go on in the next delta
            state["name_scan_pos"] = m.end()
            now = time.monotonic()
            if now - state["last_audio_time"] < 1.5:
                continue  # Leyla is talking: may be her own voice
            if now - state.get("last_nudge_at", -NAME_NUDGE_COOLDOWN_S) < NAME_NUDGE_COOLDOWN_S:
                continue
            if state.get("nudge_pending"):
                continue
            state["nudge_pending"] = True
            asyncio.create_task(self._nudge_if_ignored(live_ws, state, now, m.start()))

    async def _nudge_if_ignored(self, live_ws, state: dict, t0: float, pos: int) -> None:
        try:
            await asyncio.sleep(NAME_NUDGE_AFTER_S)
            if state.get("closing") or state.get("fatal"):
                return
            if state["last_audio_time"] > t0:
                return  # she answered
            if state.get("last_delegation_at", -100.0) > t0 - 15.0:
                return  # she is working on it
            snippet = state.get("user_all", "")[pos:pos + 140]
            if not addressed_by_name(snippet):
                return
            text = " ".join(snippet.split())
            logger.info("Name heard without a reply, nudging Leyla: %r", text)
            state["last_nudge_at"] = time.monotonic()
            await live_ws.send(json.dumps({
                "type": "session.commentary.append",
                "event_id": f"nudge_{uuid.uuid4().hex[:8]}",
                "delegation_id": None,
                "content": NAME_NUDGE.format(text=text),
            }))
        except Exception as e:
            logger.warning("Name nudge failed: %s", e)
        finally:
            state["nudge_pending"] = False

    def _add_dialog(self, state: dict, speaker: str, delta: str) -> None:
        dialog = state.setdefault("dialog", [])
        if dialog and dialog[-1][0] == speaker:
            dialog[-1][1] += delta
        else:
            dialog.append([speaker, delta])

    async def _update_memory(self, dialog: list, remember_requested: bool) -> None:
        old = self.memory.load()
        facts = await memory.summarize(
            self.openai_api_key, [self.memory_model, self.backend_model], old, dialog,
            url=os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL),
        )
        if facts is None:
            logger.warning("Memory not updated")
            return
        if facts != old:
            self.memory.save(facts)
            logger.info("Memory updated: %d facts (before %d)%s", len(facts), len(old),
                        " (user asked to remember)" if remember_requested else "")
        else:
            logger.info("Memory unchanged (%d facts)", len(facts))

    def _schedule_memory_update(self, state: dict) -> None:
        dialog = [d for d in state.get("dialog", []) if d[1].strip()]
        if not self.enable_memory or not any(s == "user" for s, _ in dialog):
            return
        if not (state.get("remember_requested") or state.get("forget_requested")):
            # Leyla only remembers or forgets when someone asks her to.
            logger.info("Memory unchanged: nobody asked to remember or forget")
            return
        if self.code_phrase and not state.get("unlocked"):
            logger.info("Memory unchanged: asked without the code phrase")
            return
        task = asyncio.create_task(
            self._update_memory(dialog, bool(state.get("remember_requested")))
        )
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    async def _connect_live(self):
        """Open WebSocket to the GPT Live API."""
        url = os.environ.get("OPENAI_LIVE_URL", LIVE_URL)
        ws = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {self.openai_api_key}"},
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=None,
        )
        logger.info("Connected to OpenAI GPT Live API")
        return ws

    async def _speak_once(self, prompt: str, max_s: float = 40.0) -> bytes:
        """Let GPT Live speak one announcement without a listener; return 24 kHz PCM."""
        ws = await self._connect_live()
        pcm = bytearray()
        try:
            await ws.send(json.dumps({
                "type": "session.start",
                "event_id": "event_announce",
                "session": {
                    "model": self.live_model,
                    "instructions": ("Du bist Leyla, eine warme, fröhliche und lebendige "
                                     "Sprachassistentin der Familie. Du sprichst mit viel "
                                     "Gefühl, natürlicher Betonung und einem Lächeln in der "
                                     "Stimme, nie monoton, aber ohne Kosewörter wie „canım“. "
                                     "Du machst nur die verlangte kurze "
                                     "Ansage und redest danach nicht weiter."),
                    "audio": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                              "output": {"voice": self.voice}},
                    "delegation": {"type": "responses", "responses": {
                        "model": self.backend_model, "instructions": "Do nothing.",
                        "tools": [END_CONVERSATION_TOOL], "tool_choice": "auto",
                        "parallel_tool_calls": False}},
                },
            }))
            loop = asyncio.get_event_loop()
            end = loop.time() + max_s
            started = False
            last_audio = None

            async def feed_silence():
                # GPT Live runs on the input audio clock: without input it never
                # finishes injecting the commentary, so feed real-time silence.
                chunk = base64.standard_b64encode(b"\x00" * (BYTES_PER_SEC // 10)).decode("ascii")
                while True:
                    await ws.send(json.dumps({"type": "session.input_audio.append",
                                              "audio": chunk}))
                    await asyncio.sleep(0.1)

            feeder = None
            loud_end = 0
            while loop.time() < end:
                wait = 2.0 if last_audio else end - loop.time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, wait))
                except asyncio.TimeoutError:
                    if last_audio:
                        break
                    continue
                if not isinstance(raw, str):
                    continue
                ev = json.loads(raw)
                t = ev.get("type")
                if t == "session.started" and not started:
                    started = True
                    feeder = asyncio.create_task(feed_silence())
                    await ws.send(json.dumps({
                        "type": "session.commentary.append",
                        "event_id": f"announce_{uuid.uuid4().hex[:8]}",
                        "delegation_id": None, "content": prompt}))
                elif t == "session.output_audio.delta" and ev.get("delta"):
                    chunk_pcm = base64.standard_b64decode(ev["delta"])
                    _, peak = pcm_level(chunk_pcm)
                    if peak >= OUTPUT_SILENCE_PEAK:
                        last_audio = loop.time()
                        pcm += chunk_pcm
                        loud_end = len(pcm)
                    elif last_audio:
                        pcm += chunk_pcm  # pauses inside the speech
                    if last_audio and loop.time() - last_audio > 2.0:
                        break  # GPT Live keeps sending silence after the speech
                elif t == "error":
                    raise RuntimeError(f"GPT Live: {ev.get('error')}")
            if feeder:
                feeder.cancel()
            try:
                await ws.send(json.dumps({"type": "session.close"}))
            except Exception:
                pass
        finally:
            if feeder and not feeder.done():
                feeder.cancel()
            await ws.close()
        pcm = pcm[:loud_end + BYTES_PER_SEC // 4]  # drop trailing silence
        logger.info("Announcement audio: %.1f s", len(pcm) / (SAMPLE_RATE * 2))
        return bytes(pcm)

    async def _automation_command(self, data: dict) -> dict:
        """Event leyla_command from a Home Assistant automation, e.g.
        {"device": "ventilator", "action": "licht"} or {"device": "fernseher", "action": "aus"}."""
        device = (data.get("device") or "").lower()
        args = {k: v for k, v in data.items() if k != "device"}
        args.setdefault("speed", None)
        args.setdefault("hours", None)
        if device in ("ventilator", "fan"):
            result = await self.fan.run(args)
        elif device in ("fernseher", "tv"):
            args.setdefault("channel", None)
            args.setdefault("steps", None)
            result = await self.tv.run(args)
        else:
            result = {"error": f"unknown device {device}"}
        logger.info("Automation command %s -> %s", data, result)
        return result

    async def _run_message_tool(self, live_ws, call_id: str, raw_args) -> None:
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        result = await self.messages.to_metin(args)
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return message result: %s", e)

    async def _start_session(self, live_ws, timeout: float = 15.0) -> dict:
        """Send session.start and wait for session.started. Returns the started event."""
        self.greeting = self._choose_greeting()
        extra = ""
        if self.enable_context:
            try:
                extra = await asyncio.wait_for(context.build_context(), timeout=4.0)
            except Exception as e:
                logger.info("Context not added: %s", e)
        await live_ws.send(json.dumps(self._session_start(extra)))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for session.started")
            raw = await asyncio.wait_for(live_ws.recv(), timeout=remaining)
            if not isinstance(raw, str):
                continue
            event = json.loads(raw)
            ev_type = event.get("type")
            logger.info("GPT Live setup event: %s", ev_type)
            if ev_type == "error":
                logger.error("GPT Live error during setup: %s", event)
                err = event.get("error", {})
                raise RuntimeError(
                    f"GPT Live error: {err.get('message', event) if isinstance(err, dict) else err}"
                )
            if ev_type == "session.started":
                if self.greeting:
                    await live_ws.send(json.dumps({
                        "type": "session.commentary.append",
                        "event_id": f"greeting_{uuid.uuid4().hex[:8]}",
                        "delegation_id": None,
                        "content": self.greeting,
                    }))
                    logger.info("Greeting requested")
                return event

    def _client_id_from_ws(self, ws) -> str:
        """Derive a client id (e.g. for recording)."""
        if hasattr(ws, "remote_address") and ws.remote_address:
            return ws.remote_address[0].replace(".", "_")
        return f"client_{uuid.uuid4().hex[:8]}"

    async def _client_to_live(
        self,
        client_ws,
        live_ws,
        output_queue: asyncio.Queue,
        first_audio_from_client: list,
        end_reason: dict,
        state: dict,
    ) -> None:
        """Forward ESP32 binary audio to GPT Live. Client only sends audio after ready."""
        window_start = time.monotonic()
        window_rms = 0
        window_peak = 0
        window_chunks = 0
        try:
            async for message in client_ws:
                if isinstance(message, bytes):
                    rms, peak = pcm_level(message)
                    window_rms = max(window_rms, rms)
                    window_peak = max(window_peak, peak)
                    window_chunks += 1
                    if time.monotonic() - window_start >= 2.0:
                        logger.info(
                            "Mic level (2 s): max rms=%d peak=%d chunks=%d silence_fill=%.1fs",
                            window_rms, window_peak, window_chunks, state["silence_filled_s"],
                        )
                        state["silence_filled_s"] = 0.0
                        window_start = time.monotonic()
                        window_rms = window_peak = window_chunks = 0
                    if not first_audio_from_client[0]:
                        first_audio_from_client[0] = True
                        logger.info("First audio from client (%d bytes)", len(message))
                    if len(message) % 2 != 0:
                        message = message + b"\x00"
                    now = time.monotonic()
                    state["input_clock"] = max(state["input_clock"], now) + len(message) / BYTES_PER_SEC
                    b64 = base64.standard_b64encode(message).decode("ascii")
                    await live_ws.send(
                        json.dumps({"type": "session.input_audio.append", "audio": b64})
                    )
                    if self.recorder:
                        self.recorder.record_input_audio(message)
                else:
                    try:
                        data = json.loads(message) if isinstance(message, str) else message
                        if data.get("type") == "interrupt":
                            # GPT Live decides by itself when to stop speaking when it hears the
                            # user. We only drop audio that is still waiting to be played.
                            logger.info("Interrupt received from client")
                            self._clear_output_queue(output_queue)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
        except websockets.exceptions.ConnectionClosed as e:
            end_reason["reason"] = "client_disconnected"
            end_reason["code"] = e.code
            logger.info("client_to_live ended (reason: connection_closed, code: %s)", e.code)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error in client_to_live: %s", e, exc_info=True)
            end_reason["reason"] = "client_to_live_error"
        finally:
            if "reason" not in end_reason:
                end_reason["reason"] = "client_disconnected"

    async def _silence_pump(self, live_ws, state: dict) -> None:
        """Keep the GPT Live input stream continuous. When the client sends no audio
        (for example while the Voice PE mutes its mic during playback), send silence."""
        try:
            while True:
                await asyncio.sleep(0.02)
                now = time.monotonic()
                gap = now - state["input_clock"]
                if gap < SILENCE_FILL_AFTER_S:
                    continue
                fill_s = min(gap, SILENCE_FILL_MAX_S)
                n_bytes = int(fill_s * BYTES_PER_SEC) // 2 * 2
                if n_bytes <= 0:
                    continue
                state["input_clock"] += n_bytes / BYTES_PER_SEC
                state["silence_filled_s"] += n_bytes / BYTES_PER_SEC
                b64 = base64.standard_b64encode(b"\x00" * n_bytes).decode("ascii")
                await live_ws.send(
                    json.dumps({"type": "session.input_audio.append", "audio": b64})
                )
        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed:
            return
        except Exception as e:
            logger.error("Error in silence pump: %s", e, exc_info=True)

    async def _send_phase(self, client_ws, phase: str) -> None:
        """Send phase message to client for LED/UX feedback."""
        try:
            await client_ws.send(json.dumps({"type": "phase", "phase": phase}))
            logger.info("Phase -> %s", phase)
        except Exception as e:
            logger.warning("Failed to send phase '%s': %s", phase, e)

    async def _send_function_output(self, live_ws, call_id: str, output: dict) -> None:
        """Return a function result to the backend and let it continue."""
        await live_ws.send(
            json.dumps({
                "type": "response.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output),
                },
            })
        )
        await live_ws.send(json.dumps({"type": "response.create"}))

    async def _run_costs_tool(self, live_ws, call_id: str) -> None:
        """Fetch the OpenAI spending report without blocking the audio loop."""
        try:
            report = await asyncio.wait_for(
                costs.cost_report(self.admin_key, self.monthly_budget),
                timeout=15.0,
            )
        except Exception as e:
            logger.warning("Costs report failed: %s", e)
            report = {"error": "Could not read OpenAI costs right now."}
        try:
            await self._send_function_output(live_ws, call_id, report)
        except Exception as e:
            logger.warning("Could not return costs report: %s", e)

    async def _run_lights_tool(self, live_ws, call_id: str, raw_args) -> None:
        """Switch the living room lamps without blocking the audio loop."""
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        try:
            result = await asyncio.wait_for(self.lights.run(args), timeout=25.0)
        except Exception as e:
            logger.warning("Light control failed: %s", e)
            result = {"error": "Die Lampen konnten gerade nicht gesteuert werden."}
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return light result: %s", e)

    async def _run_fan_tool(self, live_ws, call_id: str, raw_args) -> None:
        """Press a fan remote button without blocking the audio loop."""
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        try:
            result = await asyncio.wait_for(self.fan.run(args), timeout=15.0)
        except Exception as e:
            logger.warning("Fan control failed: %s", e)
            result = {"error": "Der Ventilator konnte gerade nicht gesteuert werden."}
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return fan result: %s", e)

    async def _run_tv_tool(self, live_ws, call_id: str, raw_args) -> None:
        """Control the TV without blocking the audio loop."""
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            args = {}
        try:
            result = await asyncio.wait_for(self.tv.run(args), timeout=20.0)
        except Exception as e:
            logger.warning("TV control failed: %s", e)
            result = {"error": "Der Fernseher konnte gerade nicht gesteuert werden."}
        logger.info("TV %s -> %s", args, result)
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return TV result: %s", e)

    async def _handle_backend_event(
        self,
        inner: dict,
        live_ws,
        output_queue: asyncio.Queue,
        state: dict,
    ) -> None:
        """Handle an event of the backend model (unwrapped from response.event)."""
        inner_type = inner.get("type", "")
        if inner_type == "response.output_item.done":
            item = inner.get("item") or {}
            if item.get("type") != "function_call":
                return
            name = item.get("name")
            call_id = item.get("call_id")
            logger.info("Backend function call: %s", name)
            if not call_id:
                return
            if name == "end_conversation":
                state["closing"] = True
                await self._send_function_output(live_ws, call_id, {"status": "ok"})
            elif name == costs.COSTS_TOOL["name"]:
                await output_queue.put(("phase", "thinking"))
                task = asyncio.create_task(self._run_costs_tool(live_ws, call_id))
                self._memory_tasks.add(task)
                task.add_done_callback(self._memory_tasks.discard)
            elif name == lights.LIGHTS_TOOL["name"]:
                task = asyncio.create_task(
                    self._run_lights_tool(live_ws, call_id, item.get("arguments")))
                self._memory_tasks.add(task)
                task.add_done_callback(self._memory_tasks.discard)
            elif name == messages.TO_METIN_TOOL["name"]:
                task = asyncio.create_task(
                    self._run_message_tool(live_ws, call_id, item.get("arguments")))
                self._memory_tasks.add(task)
                task.add_done_callback(self._memory_tasks.discard)
            elif name == "fernseher_steuern":
                task = asyncio.create_task(
                    self._run_tv_tool(live_ws, call_id, item.get("arguments")))
                self._memory_tasks.add(task)
                task.add_done_callback(self._memory_tasks.discard)
            elif name == fan.FAN_TOOL["name"]:
                task = asyncio.create_task(
                    self._run_fan_tool(live_ws, call_id, item.get("arguments")))
                self._memory_tasks.add(task)
                task.add_done_callback(self._memory_tasks.discard)
            else:
                await self._send_function_output(
                    live_ws, call_id, {"error": f"Unknown function: {name}"}
                )
        elif inner_type.startswith("response.web_search_call."):
            if inner_type.endswith(".in_progress") or inner_type.endswith(".searching"):
                await output_queue.put(("phase", "searching"))

    async def _live_to_client(
        self,
        live_ws,
        output_queue: asyncio.Queue,
        end_reason: dict,
        state: dict,
    ) -> None:
        """Forward GPT Live events to ESP32; audio and phases go through one output queue."""
        delta_count = 0
        delta_bytes_total = 0
        reply_peak = 0
        dropped_silent = 0
        last_loud = 0.0
        user_text: list[str] = []
        bot_text: list[str] = []
        try:
            async for raw in live_ws:
                if not isinstance(raw, str):
                    continue
                if state.get("fatal"):
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ev_type = event.get("type")

                if ev_type == "session.output_audio.delta":
                    delta_b64 = event.get("delta")
                    if delta_b64:
                        now = time.monotonic()
                        audio_bytes = base64.standard_b64decode(delta_b64)
                        _, out_peak = pcm_level(audio_bytes)
                        if out_peak >= OUTPUT_SILENCE_PEAK:
                            last_loud = now
                        elif now - last_loud > OUTPUT_HANGOVER_S:
                            # Quiet frame outside of speech: do not send, or the Voice PE
                            # would mute its mic and never hear the user.
                            dropped_silent += 1
                            if dropped_silent % 100 == 1:
                                logger.info(
                                    "Dropping quiet output audio (peak=%d, dropped so far %d)",
                                    out_peak, dropped_silent,
                                )
                            continue
                        if now - state["last_audio_time"] > REPLY_GAP_S:
                            if delta_count:
                                logger.info(
                                    "Reply audio: %d deltas, %d bytes (%.1f s), max peak %d",
                                    delta_count, delta_bytes_total,
                                    delta_bytes_total / BYTES_PER_SEC, reply_peak,
                                )
                            await output_queue.put(("phase", "replying"))
                            delta_count = 0
                            delta_bytes_total = 0
                            reply_peak = 0
                        state["last_audio_time"] = now
                        state["last_activity"] = now
                        await output_queue.put(audio_bytes)
                        delta_count += 1
                        delta_bytes_total += len(audio_bytes)
                        reply_peak = max(reply_peak, out_peak)
                        if self.recorder:
                            self.recorder.record_output_audio(audio_bytes)

                elif ev_type == "response.event":
                    inner = event.get("event") or {}
                    logger.info("Backend event: %s", inner.get("type"))
                    await self._handle_backend_event(inner, live_ws, output_queue, state)

                elif ev_type == "session.delegation.created":
                    logger.info("Delegation created: %s", event.get("delegation"))
                    state["last_delegation_at"] = time.monotonic()
                    await output_queue.put(("phase", "thinking"))

                elif ev_type == "session.input_transcript.delta":
                    delta = event.get("delta", "")
                    if (delta.strip() and not output_queue.empty()
                            and time.monotonic() - state["last_audio_time"] > BARGE_IN_GAP_S):
                        # The user talks while queued reply audio is still waiting and GPT
                        # Live stopped sending more: it yielded the turn (barge-in). Drop the
                        # rest and tell the Voice PE to stop playing right away.
                        self._clear_output_queue(output_queue)
                        await output_queue.put(("interrupt", None))
                        logger.info("Barge-in: user talks over the reply, playback stopped")
                    user_text.append(delta)
                    if delta.strip():
                        state["user_spoke"] = True
                    self._add_dialog(state, "user", delta)
                    state["last_activity"] = time.monotonic()
                    recent = (state.get("recent_user_text", "") + delta)[-80:]
                    state["recent_user_text"] = recent
                    self._note_name_mention(live_ws, state, delta)
                    if self.messages.available and messages.is_ack(recent) \
                            and self.messages.pending():
                        await self.messages.acknowledge(recent)
                    if (self.code_phrase and not state.get("unlocked")
                            and memory.has_code(recent, self.code_phrase)):
                        await self._unlock(live_ws, state)
                    if not state.get("remember_requested") and memory.wants_to_remember(recent):
                        state["remember_requested"] = True
                        logger.info("User asked to remember something")
                    if not state.get("forget_requested") and memory.wants_to_forget(recent):
                        state["forget_requested"] = True
                        logger.info("User asked to forget something")
                    if not state.get("closing") and contains_goodbye(recent):
                        logger.info("Goodbye heard from user: %r", recent.strip())
                        state["closing"] = True
                    logger.info("User said: %r", event.get("delta", ""))
                elif ev_type == "session.output_transcript.delta":
                    delta = event.get("delta", "")
                    bot_text.append(delta)
                    self._add_dialog(state, "bot", delta)
                    recent = (state.get("recent_bot_text", "") + delta)[-80:]
                    state["recent_bot_text"] = recent
                    if not state.get("closing") and contains_goodbye(recent, from_user=False):
                        logger.info("Goodbye said by assistant: %r", recent.strip())
                        state["closing"] = True
                    logger.info("Bot said: %r", event.get("delta", ""))

                elif ev_type == "session.usage.updated":
                    logger.debug("Usage: %s", event.get("usage"))

                elif ev_type == "session.closed":
                    logger.info("GPT Live session closed: reason=%s usage=%s",
                                event.get("reason"), event.get("usage"))
                    end_reason["reason"] = "live_closed"
                    return

                elif ev_type == "error":
                    err = event.get("error", event)
                    logger.error("GPT Live error: %s", err)
                    code = err.get("code") if isinstance(err, dict) else None
                    etype = err.get("type") if isinstance(err, dict) else None
                    if "insufficient_quota" in (str(code), str(etype)):
                        logger.error("OpenAI quota exceeded, notifying client")
                        await output_queue.put(("error", "insufficient_quota"))
                        state["fatal"] = True
                else:
                    logger.info("GPT Live event: %s", raw[:300])
        except websockets.exceptions.ConnectionClosed as e:
            end_reason["reason"] = "live_disconnected"
            end_reason["code"] = e.code
            logger.info("live_to_client ended (reason: connection_closed, code: %s)", e.code)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Error in live_to_client: %s", e, exc_info=True)
            end_reason["reason"] = "live_to_client_error"
        finally:
            if delta_count:
                logger.info(
                    "Reply audio: %d deltas, %d bytes (%.1f s), max peak %d",
                    delta_count, delta_bytes_total,
                    delta_bytes_total / BYTES_PER_SEC, reply_peak,
                )
            if dropped_silent:
                logger.info("Dropped %d quiet output deltas in total", dropped_silent)
            if user_text or bot_text:
                logger.info("Transcript user: %s", "".join(user_text).strip())
                logger.info("Transcript bot: %s", "".join(bot_text).strip())
            if "reason" not in end_reason:
                end_reason["reason"] = "live_disconnected"

    async def _session_watcher(
        self,
        client_ws,
        live_ws,
        output_queue: asyncio.Queue,
        end_reason: dict,
        state: dict,
    ) -> None:
        """Ends the session: after end_conversation (once the farewell was played), when
        nobody spoke for IDLE_TIMEOUT_S, or after MAX_SESSION_S."""
        try:
            session_start = time.monotonic()
            reason = ""
            while not reason:
                await asyncio.sleep(0.1)
                now = time.monotonic()
                if state.get("closing"):
                    await self._wait_for_farewell(output_queue, state)
                    reason = "end_conversation"
                elif not state.get("user_spoke") and now - session_start > NO_SPEECH_TIMEOUT_S:
                    reason = "no_speech"
                elif now - state["last_activity"] > IDLE_TIMEOUT_S:
                    reason = "idle_timeout"
                elif now - session_start > MAX_SESSION_S:
                    reason = "max_duration"
            logger.info("Ending session (%s), notifying client", reason)
            end_reason["reason"] = reason
            try:
                await client_ws.send(
                    json.dumps({
                        "type": "disconnect",
                        "message": "Session ended",
                        "reason": "user_requested_stop" if reason == "end_conversation" else reason,
                    })
                )
            except Exception:
                pass
            try:
                await live_ws.send(json.dumps({"type": "session.close"}))
            except Exception:
                pass
        except asyncio.CancelledError:
            raise

    async def _wait_for_farewell(self, output_queue: asyncio.Queue, state: dict) -> None:
        """Wait until the goodbye audio has been played (or a time limit is reached)."""
        loop = asyncio.get_event_loop()
        started = loop.time()
        heard_audio = False
        baseline = state["last_audio_time"]
        while True:
            await asyncio.sleep(0.1)
            if state["last_audio_time"] > baseline:
                heard_audio = True
            idle = time.monotonic() - state["last_audio_time"]
            waited = loop.time() - started
            if waited > GOODBYE_MAX_WAIT_S:
                return
            if heard_audio and idle > GOODBYE_IDLE_S and output_queue.empty():
                return
            # No farewell audio at all: do not hang up instantly, give it a moment.
            if not heard_audio and waited > 6.0:
                return

    async def _output_sender(
        self,
        client_ws,
        output_queue: asyncio.Queue,
        first_audio_to_client: list,
        end_reason: dict,
    ) -> None:
        """Send buffered audio and phase messages to client. Audio is paced at playback
        rate; phases are sent in order. One ordered stream avoids race conditions.
        GPT Live has no end of audio event, so silence on the queue ends a reply."""
        buffer = bytearray()
        bytes_sent = 0
        start_time: Optional[float] = None
        first_chunk_at: Optional[float] = None
        idle_ticks = 0
        loop = asyncio.get_event_loop()

        async def pump(flush: bool = False, force: bool = False) -> None:
            """Send what is buffered at playback rate, OUTPUT_LEAD_S ahead. A reply starts
            only once PREBUFFER_S is buffered or PREBUFFER_MAX_WAIT_S has passed."""
            nonlocal bytes_sent, start_time
            if not buffer:
                return
            if start_time is None:
                waited = loop.time() - (first_chunk_at or loop.time())
                if not force and len(buffer) < PREBUFFER_BYTES and waited < PREBUFFER_MAX_WAIT_S:
                    return
                start_time = loop.time()
            while len(buffer) >= SEND_CHUNK_SIZE or (flush and buffer):
                n = min(SEND_CHUNK_SIZE, len(buffer))
                to_send = bytes(buffer[:n])
                del buffer[:n]
                bytes_sent += n
                target_time = start_time + bytes_sent / BYTES_PER_SEC - OUTPUT_LEAD_S
                now = loop.time()
                if target_time > now:
                    await asyncio.sleep(target_time - now)
                await client_ws.send(to_send)

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(output_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    await pump(flush=True)
                    if idle_ticks >= 3 and not buffer:
                        # Reply is over: restart the pacing clock for the next one.
                        bytes_sent = 0
                        start_time = None
                        first_chunk_at = None
                    continue
                idle_ticks = 0

                if isinstance(chunk, tuple) and chunk[0] == "phase":
                    await pump(flush=True, force=True)
                    await self._send_phase(client_ws, chunk[1])
                    continue

                if isinstance(chunk, tuple) and chunk[0] == "interrupt":
                    buffer.clear()
                    bytes_sent = 0
                    start_time = None
                    first_chunk_at = None
                    try:
                        await client_ws.send(json.dumps({"type": "interrupt"}))
                    except Exception as e:
                        logger.warning("Failed to send interrupt: %s", e)
                    continue

                if isinstance(chunk, tuple) and chunk[0] == "error":
                    await pump(flush=True, force=True)
                    error_code = chunk[1]
                    try:
                        await client_ws.send(json.dumps({"type": "error", "code": error_code}))
                        logger.info("Sent error to client: code=%s", error_code)
                    except Exception as e:
                        logger.warning("Failed to send error '%s': %s", error_code, e)
                    continue

                if not first_audio_to_client[0]:
                    first_audio_to_client[0] = True
                    logger.info("First audio to client (%d bytes)", len(chunk))

                if start_time is None and not buffer:
                    first_chunk_at = loop.time()
                buffer.extend(chunk)
                await pump()
        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed:
            if "reason" not in end_reason:
                end_reason["reason"] = "client_disconnected"
        except Exception as e:
            logger.error("Error in output_sender: %s", e, exc_info=True)
            if "reason" not in end_reason:
                end_reason["reason"] = "output_sender_error"

    @staticmethod
    def _clear_output_queue(output_queue: asyncio.Queue) -> None:
        """Drop all pending output (audio + phases) so stale data is never sent after interrupt."""
        dropped = 0
        while not output_queue.empty():
            try:
                output_queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        if dropped:
            logger.info("Cleared %d chunks from output queue (interrupt)", dropped)

    async def handle_client(self, client_ws) -> None:
        """One client connection = one GPT Live session. Connect, send ready to the
        client, then run the forwarding tasks. Client only sends audio after ready."""
        client_id = self._client_id_from_ws(client_ws)
        logger.info("Client connected: %s", client_id)
        start_time = time.monotonic()
        if self.tv.available:
            self._in_background(self.tv.duck())  # so Leyla hears the family, not the TV

        old_ws = self._active_sessions.get(client_id)
        if old_ws is not None:
            logger.warning("Closing previous session for %s", client_id)
            try:
                await old_ws.close(1000, "replaced by new connection")
            except Exception:
                pass
        self._active_sessions[client_id] = client_ws

        if self.recorder:
            self.recorder.start_recording(client_id)

        end_reason: dict = {}
        first_audio_from_client = [False]
        first_audio_to_client = [False]
        output_queue: asyncio.Queue = asyncio.Queue()
        state: dict = {
            "closing": False,
            "fatal": False,
            "last_audio_time": 0.0,
            "last_activity": time.monotonic(),
            "input_clock": time.monotonic(),
            "silence_filled_s": 0.0,
        }
        live_ws = None

        try:
            live_ws = await self._connect_live()
            started = await self._start_session(live_ws)
            session = started.get("session") or {}
            logger.info(
                "Session started: id=%s model=%s", session.get("id"), session.get("model")
            )
            instructions_preview = (
                (self.instructions[:100] + "…") if len(self.instructions) > 100 else self.instructions
            )
            logger.info("Instructions: %s", instructions_preview)
            await client_ws.send(json.dumps({"type": "ready"}))
            logger.info("Sent ready signal to client")
            state["input_clock"] = time.monotonic()
            state["last_activity"] = time.monotonic()

            tasks = [
                asyncio.create_task(
                    self._client_to_live(
                        client_ws, live_ws, output_queue, first_audio_from_client, end_reason,
                        state,
                    )
                ),
                asyncio.create_task(
                    self._live_to_client(live_ws, output_queue, end_reason, state)
                ),
                asyncio.create_task(
                    self._output_sender(
                        client_ws, output_queue, first_audio_to_client, end_reason
                    )
                ),
                asyncio.create_task(
                    self._session_watcher(client_ws, live_ws, output_queue, end_reason, state)
                ),
            ]
            pump = asyncio.create_task(self._silence_pump(live_ws, state))
            finished, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            for task in finished:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.error("Task exited with error: %s", exc)
        except Exception as e:
            logger.error("Session error: %s", e, exc_info=True)
            end_reason["reason"] = "session_error"
        finally:
            if self._active_sessions.get(client_id) is client_ws:
                del self._active_sessions[client_id]
            if live_ws:
                try:
                    await live_ws.close()
                except Exception:
                    pass
            if self.recorder:
                self.recorder.stop_recording()
            if self.tv.available:
                self._in_background(self.tv.unduck())
            try:
                self._schedule_memory_update(state)
            except Exception as e:
                logger.warning("Could not start memory update: %s", e)
            duration = time.monotonic() - start_time
            reason = end_reason.get("reason", "unknown")
            logger.info(
                "Session ended: %s (duration: %.1fs, reason: %s)",
                client_id, duration, reason,
            )

    def _in_background(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _memory_maintenance(self) -> None:
        """Apply the forget_facts option and list the stored facts in the log."""
        if not self.enable_memory:
            return
        for fact in self.memory.forget(os.environ.get("FORGET_FACTS", "")):
            logger.info("Memory: forgot fact: %s", fact)
        for fact in self.memory.add(os.environ.get("ADD_FACTS", "")):
            logger.info("Memory: added fact: %s", fact)
        facts = self.memory.load()
        logger.info("Memory: %d facts stored", len(facts))
        for i, fact in enumerate(facts, 1):
            logger.info("Memory fact %d: %s", i, fact)

    async def run(self) -> None:
        """Start WebSocket server and run forever."""
        self._memory_maintenance()
        if self.messages.available:
            try:
                self._message_tasks = await self.messages.start()
            except Exception as e:
                logger.warning("Messages could not start: %s", e)
        if self.rf.available:
            try:
                await rf.start_http(self.rf, port=int(os.environ.get("RF_HTTP_PORT", "8081")))
            except Exception as e:
                logger.warning("RF remote HTTP could not start: %s", e)
        logger.info(
            "Starting WebSocket server on ws://%s:%s/ (live model %s, backend %s)",
            self.websocket_host, self.websocket_port, self.live_model, self.backend_model,
        )
        async with websockets.serve(
            self.handle_client,
            self.websocket_host,
            self.websocket_port,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ):
            await asyncio.Future()


async def main() -> None:
    bridge = LiveVoiceBridge()
    try:
        await bridge.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
