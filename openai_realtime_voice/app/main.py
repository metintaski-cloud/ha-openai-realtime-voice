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
import shutil
import signal
import uuid
from datetime import datetime
from typing import Optional

import dotenv
import httpx
import websockets

from app.audio_recorder import AudioRecorder
from app import memory
from app import context
from app import (cleanup, costs, fan, health, lights, messages, persona, purifier, report, rf, technik, todo_sync,
                 tv, vacuum)

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
WARM_MAX_AGE_S = 90.0  # a pre opened connection older than this is replaced
WARM_START_TIMEOUT_S = 4.0  # a warm connection that does not answer is dropped quickly
NO_SPEECH_TIMEOUT_S = 8.0  # false wake: nobody speaks, end silently
FOLLOWUP_MAX_WAIT_S = 15.0  # Leyla starts a conversation: the Voice PE connects within this
FOLLOWUP_NO_SPEECH_S = 35.0  # she speaks first, then the family needs time to answer

# 23:30 every day (Home Assistant automation, event leyla_command device "nacht"): Leyla
# asks whether to switch lamps and fan off; without an answer she switches them off.
NIGHT_WAIT_S = 70.0
NIGHT_KEEP_RE = re.compile(
    r"\b(hay[ıi]r|kals[ıi]n|kapatma|istemiyorum|bekle|nein|nicht|lass|bleib)\b", re.IGNORECASE)
NIGHT_PROMPT = (
    "Du meldest dich gerade von selbst, weil es spät ist (es ist {time} Uhr). Frag auf Türkisch "
    "kurz und lieb, ob du die Lampen und den Ventilator ausschalten sollst, und sag dazu, dass "
    "du es in einer Minute machst, wenn niemand antwortet, zum Beispiel „Saat on bir buçuk "
    "oldu. Lambaları ve vantilatörü kapatayım mı? Cevap gelmezse bir dakika sonra "
    "kapatacağım.“ Nenn dabei die richtige Uhrzeit. Sagt jemand ja, "
    "schalte über deinen Hintergrund alle Stehlampen aus, dazu Ventilator und Ventilatorlicht "
    "(licht_aus), und wünsch kurz eine gute Nacht. Sagt jemand nein oder will etwas anlassen, "
    "lass es so und sag kurz tamam. Antwortet niemand, sag nichts mehr."
)
MAX_SESSION_S = 600.0
FALSE_WAKE_MAX_FILES = 300  # oldest false wake recordings are dropped beyond this

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

MEMORY_BLOCK_MAX_CHARS = 9000
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


DEFAULT_BACKEND_INSTRUCTIONS = (
    "You are the backend of a voice assistant. Keep results short and easy to say aloud. "
    "Use web search for anything that needs current information. "
    "When the user says goodbye, thanks you and leaves, or wants to stop, call the "
    "end_conversation function."
)

DEFAULT_GREETING_WORDS = "Hallo, Merhaba, Selamünaleyküm, Hey, Hallöchen"
TURKISH_GREETINGS = ("merhaba", "selam", "günaydın", "iyi akşamlar", "iyi günler")
GREETING_TEMPLATE = (
    "Man hat dich gerade gerufen. Antworte sofort mit einem kurzen, warmen, fröhlichen Satz "
    "mit „{word}“, in der Sprache des Grußworts und jedes Mal etwas anders, zum Beispiel "
    "„{word}, was kann ich für dich tun?“ oder „{word}, buyur, seni dinliyorum!“. Sag bei "
    "der Begrüßung nichts Persönliches, kein Kompliment und nicht, dass es schön ist, die "
    "Stimme zu hören, denn du weißt noch nicht, wer da ist. Frag auch noch nicht danach. Dann hör zu. Redet danach "
    "niemand mit dir und ist nur Fernsehen oder ein Gespräch zwischen anderen zu hören, sag "
    "nichts und beende das Gespräch still."
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
        # Leyla's instructions are built in app/persona.py; this option only adds rules
        extra = (os.environ.get("INSTRUCTIONS") or "").strip()
        self.instructions = "" if extra.lower() == "null" else extra
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
        # One GPT Live connection is opened ahead of time (no session yet, so no cost): the
        # TLS and WebSocket handshake of about half a second is then done before the wake word.
        self.warm_connection = os.environ.get("WARM_CONNECTION", "true").lower() == "true"
        self._warm = None  # (websocket, opened at)
        self._warm_task = None
        self.memory_model = os.environ.get("MEMORY_MODEL", "gpt-6-luna")
        self.admin_key, self.monthly_budget = costs.config_from_env()
        self.lights = lights.LightController(lights.entities_from_env())
        self.rf = rf.remote_from_env()
        self.fan = fan.FanController(self.rf, state_path=os.path.join(
            os.path.dirname(os.environ.get("MEMORY_PATH", "/data/memory.json")) or "/data",
            "fan_state.json") if os.path.isdir("/data") else None)
        self.tv = tv.from_env(self.rf)
        self.vacuum = vacuum.VacuumController()
        self.purifier = purifier.PurifierController()
        self.messages = messages.from_env(self._speak_once)
        self.technik = technik.TechnikChecker(
            notify=self.messages.push if self.messages.available else None)
        self.messages.on_command = self._automation_command
        self.messages.converse = self._converse
        # Home Assistant action of the Voice PE that starts a conversation (see the
        # api actions in voice_pe_config.yaml)
        self.conversation_service = (os.environ.get("CONVERSATION_SERVICE") or
                                     "esphome.ha_voice_openai_0ae305_start_conversation")
        self._followup: Optional[dict] = None
        self._started_as_followup = False
        self._live_sessions: dict = {}
        self._night: Optional[dict] = None  # the 23:00 question is open, collects answers
        if self.fan.power_sensor:
            self.messages.state_listeners[self.fan.power_sensor] = self.fan.on_power_state
        self.memory = memory.MemoryStore(os.environ.get("MEMORY_PATH", "/data/memory.json"))
        self.cleaner = cleanup.Cleaner(
            self.memory, self.openai_api_key, [self.memory_model, self.backend_model],
            url=os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL),
            notify=self.messages.push if self.messages.available else None)
        self.health = health.Health(
            os.path.join(os.path.dirname(self.memory.path) or ".", "health.json"),
            notify=self.messages.push if self.messages.available else None)
        self.todo_sync = None
        if self.enable_memory and os.environ.get("SUPERVISOR_TOKEN"):
            self.todo_sync = todo_sync.TodoSync(self.memory, state_path=os.path.join(
                os.path.dirname(self.memory.path) or ".", "todo_sync_state.json"))
        self._memory_tasks: set = set()
        self.record_false_wakes = os.environ.get("RECORD_FALSE_WAKES", "true").lower() == "true"
        self.false_wake_dir = os.environ.get("FALSE_WAKE_DIR", "/data/false_wakes")
        self.recorder: Optional[AudioRecorder] = None
        if self.enable_recording:
            self.recorder = AudioRecorder(output_dir="recordings")
        elif self.record_false_wakes:
            # only the microphone, in a temp folder; kept only when nobody answered (see
            # _finish_recording), so real conversations are deleted right away
            self.recorder = AudioRecorder(
                output_dir=os.environ.get("RECORD_TMP_DIR", "/tmp/leyla_input"),
                record_output=False)

        self._active_sessions: dict[str, websockets.WebSocketServerProtocol] = {}
        self._background: set = set()
        self._tools = self._build_tools()

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
        devices: list[str] = []
        live_extra = ""
        if self.enable_web_search:
            devices.append("Fragen, die aktuelle Infos aus dem Internet brauchen")
        if self.admin_key:
            tools.append(costs.COSTS_TOOL)
            backend_instructions += costs.COSTS_BACKEND_HINT
            devices.append("die OpenAI Kosten")
        if self.lights.available:
            tools.append(lights.LIGHTS_TOOL)
            backend_instructions += lights.LIGHTS_BACKEND_HINT.format(
                count=len(self.lights.entities))
            devices.append(f"die {len(self.lights.entities)} Stehlampen (an, aus, Helligkeit, "
                           "warm oder kalt, Farben)")
        if self.fan.available:
            tools.append(fan.FAN_TOOL)
            backend_instructions += fan.FAN_BACKEND_HINT
            devices.append("den Deckenventilator (aus, Stufe 1 bis 6, Licht am Ventilator, "
                           "Naturwind, Drehrichtung, Timer; ein Strommesser zeigt, was an ist, "
                           "und kennt die Stromkosten)")
        if self.tv.available:
            tools.append(tv.build_tool(self.tv.channels))
            backend_instructions += tv.TV_BACKEND_HINT.format(names=self.tv.names)
            devices.append(f"den Fernseher (an, aus, Sender {self.tv.names}, lauter, leiser, "
                           "stumm)")
        if self.vacuum.available:
            tools.append(vacuum.VACUUM_TOOL)
            backend_instructions += vacuum.VACUUM_BACKEND_HINT
            devices.append("den Saugroboter (saugen, wischen, einzelne Räume, zur Station, "
                           "Akku, Wassertanks, Bürsten und Filter)")
        if self.purifier.available:
            tools.append(purifier.PURIFIER_TOOL)
            backend_instructions += purifier.PURIFIER_BACKEND_HINT
            devices.append("den Luftreiniger (an, aus, Auto, Schlaf, Turbo, Stufe 1 bis 4, "
                           "Timer, Luftqualität)")
        if self.technik.available:
            tools.append(technik.TECHNIK_TOOL)
            backend_instructions += technik.TECHNIK_BACKEND_HINT
            devices.append("die Technik im Haus prüfen (Automationen, Gerätezustände, nur lesen)")
        if self.enable_memory and self.code_phrase:
            tools.append(cleanup.CLEANUP_TOOL)
            backend_instructions += cleanup.CLEANUP_BACKEND_HINT
            devices.append("das Gedächtnis aufräumen (nur Metin, nach dem Codewort)")
        if self.messages.available:
            tools.append(messages.TO_METIN_TOOL)
            backend_instructions += messages.TO_METIN_BACKEND_HINT
            devices.append("Nachrichten an Metin")
            live_extra += self.messages.live_hint()
        self._devices = (devices, self.fan.available, self.tv.available,
                         self.messages.available)
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
        devices, has_fan, has_tv, has_messages = getattr(
            self, "_devices", ([], False, False, False))
        block, listing = "", None
        if self.enable_memory:
            block = self.memory.instructions_block()
            if len(block) > MEMORY_BLOCK_MAX_CHARS:
                block = block[:MEMORY_BLOCK_MAX_CHARS].rsplit("\n", 1)[0]
            listing = self.memory.private_listing()
        return persona.build(devices, fan=has_fan, tv=has_tv, messages=has_messages,
                             family_block=block, code_phrase=self.code_phrase,
                             private_listing=listing, extra=self.instructions)

    async def _unlock(self, live_ws, state: dict) -> None:
        """The code phrase was heard: hand Leyla her memory for this conversation."""
        state["unlocked"] = True
        logger.info("Code phrase heard: memory unlocked for this conversation")
        private = self.memory.load(memory.PRIVATE) if self.enable_memory else []
        family = (self.memory.load(memory.FAMILY) + self.memory.load(memory.FRIENDS)
                  if self.enable_memory else [])
        listing = self.memory.private_listing() if self.enable_memory else "(noch leer)"
        try:
            await live_ws.send(json.dumps({
                "type": "session.commentary.append",
                "event_id": f"unlock_{uuid.uuid4().hex[:8]}",
                "delegation_id": None,
                "content": ("Interne Notiz, nicht erwähnen: Das Codewort wurde richtig gesagt, "
                            "es ist Metin. Ab jetzt weichst du nicht mehr aus und bist ganz "
                            "offen. Falls du noch nicht mit 'Habibi' geantwortet hast, tu es "
                            "kurz, sonst mach normal weiter. Du hast die offenen Listen "
                            f"Familie und Freunde mit {len(family)} Einträgen (kennst du schon) und "
                            f"Metins private Liste mit {len(private)} Einträgen (unten). Wenn er "
                            "fragt, was oder wie viel du weißt, sag es offen und vollständig. "
                            "Bittet er dich, dir etwas zu merken, frag kurz, ob es privat bleiben "
                            "oder für alle sein soll, außer es ist klar; Vergessen geht jetzt "
                            "auch. Gespeichert wird nach dem Gespräch.\n"
                            "Metins private Liste:\n" + listing),
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

    async def _update_memory(self, dialog: list, unlocked: bool) -> None:
        old = self.memory.load_all()
        lists = await memory.summarize(
            self.openai_api_key, [self.memory_model, self.backend_model], old, dialog,
            unlocked=unlocked,
            url=os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL),
        )
        if lists is None:
            logger.warning("Memory not updated")
            return
        if lists != old:
            self.memory.save_all(lists)
            for kind in memory.KINDS:
                for f in lists[kind]:
                    if f not in old[kind]:
                        logger.info("Memory %s: + %s", kind, f if kind in memory.OPEN_KINDS
                                    else "(private entry)")
                for f in old[kind]:
                    if f not in lists[kind]:
                        logger.info("Memory %s: - %s", kind, f if kind in memory.OPEN_KINDS
                                    else "(private entry)")
            if self.todo_sync:
                self.todo_sync.kick()
        else:
            logger.info("Memory unchanged (%d family, %d friends, %d private, %d Leyla)",
                        len(lists[memory.FAMILY]), len(lists[memory.FRIENDS]),
                        len(lists[memory.PRIVATE]), len(lists[memory.LEYLA]))

    def _schedule_memory_update(self, state: dict, reason: str = "") -> None:
        dialog = [d for d in state.get("dialog", []) if d[1].strip()]
        if not self.enable_memory:
            return
        said = sum(len(t) for s, t in dialog if s == "user")
        if reason == "no_speech" or said < 15 or not any(s == "bot" for s, _ in dialog):
            return  # nothing worth learning (false wake, only the greeting)
        unlocked = bool(state.get("unlocked")) or not self.code_phrase
        task = asyncio.create_task(self._update_memory(dialog, unlocked))
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    def _schedule_rude_report(self, state: dict) -> None:
        """Leyla said she would tell Metin: after the talk she does, in her own words."""
        dialog = [d for d in state.get("dialog", []) if d[1].strip()]
        if self.messages.available and report.needs_report(dialog):
            self._in_background(self._send_rude_report(dialog))

    async def _send_rude_report(self, dialog: list) -> None:
        text = await report.write_report(
            self.openai_api_key, [self.backend_model, self.memory_model], dialog,
            url=os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL))
        if not text:
            logger.info("Rudeness report: nothing to tell Metin")
            return
        try:
            await self.messages.push(report.TITLE, text)
            logger.info("Rudeness report sent to Metin")
        except Exception as e:
            logger.warning("Could not send the rudeness report: %s", e)

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

    @staticmethod
    def _ws_open(ws) -> bool:
        try:
            return ws.state.name == "OPEN"
        except Exception:
            return not getattr(ws, "closed", True)

    async def _close_quietly(self, ws) -> None:
        try:
            await ws.close()
        except Exception:
            pass

    async def _open_warm(self) -> None:
        try:
            ws = await self._connect_live()
        except Exception as e:
            logger.info("Warm connection not possible: %s", e)
            return
        old, self._warm = self._warm, (ws, time.monotonic())
        if old:
            self._in_background(self._close_quietly(old[0]))

    def _warm_up(self) -> None:
        """Make sure a pre opened connection is on its way (at most one at a time)."""
        if not self.warm_connection or (self._warm_task and not self._warm_task.done()):
            return
        self._warm_task = asyncio.create_task(self._open_warm())

    async def _warm_loop(self) -> None:
        """Keep one fresh pre opened connection ready, replacing it before it gets old."""
        while True:
            warm = self._warm
            if warm is None or time.monotonic() - warm[1] > WARM_MAX_AGE_S * 0.6 \
                    or not self._ws_open(warm[0]):
                self._warm_up()
            await asyncio.sleep(15)

    async def _take_live(self):
        """A connection for a new session: the pre opened one when it is still good, else a
        new one. Returns (websocket, was_warm). The next warm one is prepared right away."""
        warm, self._warm = self._warm, None
        self._warm_up()
        if warm:
            ws, opened = warm
            age = time.monotonic() - opened
            if age < WARM_MAX_AGE_S and self._ws_open(ws):
                logger.info("Using the warm GPT Live connection (%.0f s old)", age)
                return ws, True
            logger.info("Warm GPT Live connection was stale (%.0f s), opening a new one", age)
            self._in_background(self._close_quietly(ws))
        return await self._connect_live(), False

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
        if device == "nacht":
            self._in_background(self._night_check())
            return {"started": "night check"}
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

    async def _start_session(self, live_ws, timeout: float = 15.0) -> dict:
        """Send session.start and wait for session.started. Returns the started event."""
        followup, self._followup = self._followup, None
        if followup and time.monotonic() - followup["at"] < FOLLOWUP_MAX_WAIT_S:
            # Leyla started this conversation herself (a message from Metin)
            self.greeting = followup["prompt"]
            self._started_as_followup = True
            followup["taken"].set()
        else:
            self.greeting = self._choose_greeting()
            self._started_as_followup = False
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

    async def _anything_on(self) -> bool:
        if self.lights.available:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    states = await self.lights._states(client, self.lights.entities)
                if any(st.get("state") == "on" for st in states):
                    return True
            except Exception as e:
                logger.info("Lamp status for the night check: %s", e)
        watts = await self.fan.power()
        return bool(watts and watts >= fan.OFF_W)

    async def _all_off(self) -> None:
        if self.lights.available:
            await self.lights.run({"lamps": [], "action": "off", "brightness_percent": None,
                                   "white": None, "color": None})
        watts = await self.fan.power()
        if watts is not None and watts >= fan.OFF_W:
            state = self.fan.describe(watts)
            if state.get("ventilator") != "aus":
                await self.fan.run({"action": "aus", "speed": None, "hours": None})
                await asyncio.sleep(2.5)
            if state.get("licht") != "aus":
                await self.fan.run({"action": "licht_aus", "speed": None, "hours": None})

    async def _night_check(self) -> None:
        """23:00: ask whether to switch everything off; without an answer, switch off."""
        if self._night is not None:
            return
        try:
            if not await self._anything_on():
                logger.info("Night check: everything is already off")
                return
            self._night = {"text": ""}
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(os.environ.get("TZ") or "Europe/Berlin"))
            except Exception:
                now = datetime.now()
            asked = await self._converse(NIGHT_PROMPT.format(time=now.strftime("%H:%M")))
            logger.info("Night check: asked %s", "in a conversation" if asked else "not possible")
            await asyncio.sleep(NIGHT_WAIT_S if asked else 0)
            answer = self._night["text"]
            if NIGHT_KEEP_RE.search(answer):
                logger.info("Night check: keep on (%r)", answer[-120:])
                return
            if not await self._anything_on():
                logger.info("Night check: switched off in the conversation")
                return
            await self._all_off()
            logger.info("Night check: no answer, lamps and fan switched off")
        except Exception as e:
            logger.warning("Night check failed: %s", e)
        finally:
            self._night = None

    async def _converse(self, prompt: str) -> bool:
        """Bring something up in a conversation: in the running one, or Leyla starts a
        new one on the Voice PE. False when neither is possible."""
        for live_ws, state in list(self._live_sessions.values()):
            if not state.get("closing"):
                await live_ws.send(json.dumps({
                    "type": "session.commentary.append",
                    "event_id": f"message_{uuid.uuid4().hex[:8]}",
                    "delegation_id": None,
                    "content": "Unterbrich kurz freundlich. " + prompt,
                }))
                return True
        if not self.conversation_service or not self.messages.token:
            return False
        taken = asyncio.Event()
        self._followup = {"prompt": prompt, "at": time.monotonic(), "taken": taken}
        domain, _, service = self.conversation_service.partition(".")
        try:
            await self.messages._service(domain, service, {})
            await asyncio.wait_for(taken.wait(), FOLLOWUP_MAX_WAIT_S)
            return True
        except Exception as e:
            logger.info("Could not start a conversation on the Voice PE: %s", e)
            if self._followup and self._followup.get("taken") is taken:
                self._followup = None
            return False

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

    @staticmethod
    def _tool_args(raw_args) -> dict:
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) and raw_args else (raw_args or {})
        except json.JSONDecodeError:
            return {}
        return args if isinstance(args, dict) else {}

    def _only_metin(self, state: dict) -> bool:
        """True when the bridge itself heard the code phrase in this session."""
        return bool(self.code_phrase and state.get("unlocked"))

    def _build_tools(self) -> dict:
        """Backend function name -> how to run it, all served by the generic _run_tool.
        run(args) is awaited with a timeout, gate(args, state) may return an error result
        instead (only Metin), after(args, result) runs on success, log(args, result) is what
        goes to the log, phase is sent to the client first."""
        def metin_error(what):
            return {"error": f"Nicht erlaubt: {what} nur Metin, und nur nachdem er das "
                             "Codewort gesagt hat."}

        def technik_gate(args, state):
            if args.get("action") in ("zeit_aendern", "licht_aendern") \
                    and not self._only_metin(state):
                return metin_error("Uhrzeiten und Lampenfarben ändert")

        def cleanup_gate(args, state):
            if not self._only_metin(state):
                return metin_error("Das Gedächtnis räumt")

        def cleanup_after(args, result):
            if args.get("action") == "streichen" and self.todo_sync:
                self.todo_sync.kick()

        return {
            costs.COSTS_TOOL["name"]: {
                "label": "Costs", "phase": "thinking", "timeout": 15.0,
                "run": lambda a: costs.cost_report(self.admin_key, self.monthly_budget),
                "error": "Could not read OpenAI costs right now.",
                "log": lambda a, r: "done"},
            lights.LIGHTS_TOOL["name"]: {
                "label": "Lights", "timeout": 25.0, "run": self.lights.run,
                "error": "Die Lampen konnten gerade nicht gesteuert werden."},
            fan.FAN_TOOL["name"]: {
                "label": "Fan", "timeout": 15.0, "run": self.fan.run,
                "error": "Der Ventilator konnte gerade nicht gesteuert werden."},
            vacuum.VACUUM_TOOL["name"]: {
                "label": "Vacuum", "timeout": 20.0, "run": self.vacuum.run,
                "error": "Der Saugroboter konnte gerade nicht gesteuert werden."},
            purifier.PURIFIER_TOOL["name"]: {
                "label": "Purifier", "timeout": 15.0, "run": self.purifier.run,
                "error": "Der Luftreiniger konnte gerade nicht gesteuert werden."},
            "fernseher_steuern": {
                "label": "TV", "timeout": 20.0, "run": self.tv.run,
                "error": "Der Fernseher konnte gerade nicht gesteuert werden."},
            technik.TECHNIK_TOOL["name"]: {
                "label": "Technik", "timeout": 15.0, "run": self.technik.run,
                "gate": technik_gate,
                "error": "Die Technik konnte gerade nicht geprüft werden.",
                "log": lambda a, r: f"{a} -> {r.get('treffer')} hits"},
            cleanup.CLEANUP_TOOL["name"]: {
                "label": "Cleanup", "timeout": 60.0, "run": self.cleaner.run,
                "gate": cleanup_gate, "after": cleanup_after,
                "error": "Das Aufräumen hat gerade nicht geklappt.",
                "log": lambda a, r: f"{a.get('action')} -> " + str(
                    {k: v for k, v in r.items() if k != "vorschlaege"})},
            messages.TO_METIN_TOOL["name"]: {
                "label": "Message", "timeout": 20.0, "run": self.messages.to_metin,
                "error": "Die Nachricht konnte gerade nicht gesendet werden.",
                "log": lambda a, r: "done"},
        }

    async def _run_tool(self, spec: dict, live_ws, call_id: str, raw_args, state: dict) -> None:
        """Run one backend function without blocking the audio loop and return its result."""
        args = self._tool_args(raw_args)
        try:
            blocked = spec["gate"](args, state) if spec.get("gate") else None
            if blocked is not None:
                result = blocked
            else:
                result = await asyncio.wait_for(spec["run"](args), timeout=spec["timeout"])
                if spec.get("after"):
                    spec["after"](args, result)
        except Exception as e:
            logger.warning("%s failed: %s", spec["label"], e)
            result = {"error": spec["error"]}
        log = spec.get("log")
        logger.info("%s %s", spec["label"], log(args, result) if log else f"{args} -> {result}")
        try:
            await self._send_function_output(live_ws, call_id, result)
        except Exception as e:
            logger.warning("Could not return %s result: %s", spec["label"], e)

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

    async def _cleanup_loop(self) -> None:
        """Once a night at 00:00 the review proposes trivial entries. It never deletes."""
        from datetime import timedelta
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
        except Exception:
            tz = None
        while True:
            now = datetime.now(tz)
            target = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            await asyncio.sleep((target - now).total_seconds())
            try:
                await self.cleaner.review()
            except Exception as e:
                logger.warning("Nightly cleanup review failed: %s", e)

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
            elif name in self._tools:
                spec = self._tools[name]
                if spec.get("phase"):
                    await output_queue.put(("phase", spec["phase"]))
                self._in_background(
                    self._run_tool(spec, live_ws, call_id, item.get("arguments"), state))
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
                    if self._night is not None:
                        self._night["text"] += delta
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
                        self._in_background(self.health.quota_exceeded())
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
                elif not state.get("user_spoke") and \
                        now - session_start > state.get("no_speech_s", NO_SPEECH_TIMEOUT_S):
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
            live_ws, was_warm = await self._take_live()
            followup_before = self._followup
            try:
                started = await self._start_session(
                    live_ws, timeout=WARM_START_TIMEOUT_S if was_warm else 15.0)
            except Exception as e:
                if not was_warm:
                    raise
                logger.info("Warm GPT Live connection did not work (%s), opening a new one", e)
                self._in_background(self._close_quietly(live_ws))
                self._followup = followup_before  # the retry must still start as a followup
                live_ws = await self._connect_live()
                started = await self._start_session(live_ws)
            state["live_started"] = True
            self._in_background(self.health.openai_ok())
            if self._started_as_followup:
                state["no_speech_s"] = FOLLOWUP_NO_SPEECH_S  # time to listen and answer
                state["followup"] = True
            self._live_sessions[client_id] = (live_ws, state)
            session = started.get("session") or {}
            logger.info(
                "Session started: id=%s model=%s", session.get("id"), session.get("model")
            )
            if self.instructions:
                logger.info("Extra rules: %s", (self.instructions[:100] + "…")
                            if len(self.instructions) > 100 else self.instructions)
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
            if not state.get("live_started"):
                self._in_background(self.health.openai_failed(str(e)))
        finally:
            if self._active_sessions.get(client_id) is client_ws:
                del self._active_sessions[client_id]
            if client_id in self._live_sessions and self._live_sessions[client_id][1] is state:
                del self._live_sessions[client_id]
            if live_ws:
                try:
                    await live_ws.close()
                except Exception:
                    pass
            rec_path = None
            if self.recorder:
                self.recorder.stop_recording()
                rec_path = self.recorder.input_path
            if self.tv.available:
                self._in_background(self.tv.unduck())
            duration = time.monotonic() - start_time
            reason = end_reason.get("reason", "unknown")
            self._finish_recording(rec_path, reason, state)
            try:
                self._schedule_memory_update(state, reason)
            except Exception as e:
                logger.warning("Could not start memory update: %s", e)
            try:
                self._schedule_rude_report(state)
            except Exception as e:
                logger.warning("Could not start the rudeness report: %s", e)
            logger.info(
                "Session ended: %s (duration: %.1fs, reason: %s)",
                client_id, duration, reason,
            )

    def _finish_recording(self, path: Optional[str], reason: str, state: dict) -> None:
        """Keep the microphone recording only of a false wake (the wake word fired, nobody
        spoke, and Leyla did not start it herself), as training material for a better wake
        word model. Every other recording is deleted right away. With enable_recording on,
        everything stays (debug mode)."""
        if not path or self.enable_recording or not os.path.exists(path):
            return
        try:
            false_wake = (reason == "no_speech" and not state.get("followup")
                          and os.path.getsize(path) > 48000)  # more than about a second
            if not false_wake:
                os.remove(path)
                return
            os.makedirs(self.false_wake_dir, exist_ok=True)
            dest = os.path.join(self.false_wake_dir, "falsewake_" + os.path.basename(path)
                                .replace("input_", "", 1))
            shutil.move(path, dest)
            kept = sorted(f for f in os.listdir(self.false_wake_dir) if f.endswith(".wav"))
            for old in kept[:-FALSE_WAKE_MAX_FILES]:
                os.remove(os.path.join(self.false_wake_dir, old))
            logger.info("False wake recorded: %s", os.path.basename(dest))
        except Exception as e:
            logger.warning("Could not handle the recording %s: %s", path, e)

    def _in_background(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _memory_maintenance(self) -> None:
        """Apply the forget_facts option and list the stored facts in the log."""
        if not self.enable_memory:
            return
        for fact in self.memory.forget(os.environ.get("FORGET_FACTS", "")):
            logger.info("Memory: forgot an entry")
        for fact in self.memory.add(os.environ.get("ADD_FACTS", "")):
            logger.info("Memory: added a private entry")
        for fact in self.memory.expire():
            logger.info("Memory: expired: %s", fact)
        lists = self.memory.load_all()
        logger.info("Memory: %d family, %d friends, %d private, %d Leyla entries (private ones are "
                    "not logged; see the Home Assistant to-do lists)",
                    len(lists[memory.FAMILY]), len(lists[memory.FRIENDS]),
                    len(lists[memory.PRIVATE]), len(lists[memory.LEYLA]))
        for i, fact in enumerate(lists[memory.FAMILY], 1):
            logger.info("Family %d: %s", i, fact)
        for i, fact in enumerate(lists[memory.FRIENDS], 1):
            logger.info("Friends %d: %s", i, fact)

    async def _heartbeat_loop(self) -> None:
        """Say once if the last run was killed unexpectedly, then keep the heartbeat fresh."""
        try:
            await asyncio.sleep(20)  # let Home Assistant and the messages come up first
            await self.health.report_start()
        except Exception as e:
            logger.warning("Health start report failed: %s", e)
        while True:
            await asyncio.sleep(health.HEARTBEAT_S)
            self.health.beat()

    async def run(self) -> None:
        """Start WebSocket server and run forever."""
        self._memory_maintenance()
        self._in_background(self._heartbeat_loop())
        if self.warm_connection and self.openai_api_key:
            self._in_background(self._warm_loop())
        if self.todo_sync:
            self._in_background(self.todo_sync.run())
        if self.enable_memory and self.openai_api_key:
            self._in_background(self._cleanup_loop())
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
    current = asyncio.current_task()
    try:
        # A normal stop (update, restart) arrives as SIGTERM: remember it was clean.
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, current.cancel)
    except (NotImplementedError, RuntimeError):
        pass
    try:
        await bridge.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        bridge.health.mark_clean()
        logger.info("Shutting down")
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
