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
import uuid
from typing import Optional

import dotenv
import websockets

from app.audio_recorder import AudioRecorder

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
        self.live_model = os.environ.get("LIVE_MODEL", "gpt-live-1")
        self.backend_model = os.environ.get("BACKEND_MODEL", "gpt-5.6-luna")
        self.enable_web_search = os.environ.get("ENABLE_WEB_SEARCH", "true").lower() == "true"
        self.enable_recording = os.environ.get("ENABLE_RECORDING", "false").lower() == "true"
        self.recorder: Optional[AudioRecorder] = None
        if self.enable_recording:
            self.recorder = AudioRecorder(output_dir="recordings")

        self._active_sessions: dict[str, websockets.WebSocketServerProtocol] = {}

        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

    def _session_start(self) -> dict:
        """Build the session.start payload for GPT Live."""
        tools: list[dict] = [END_CONVERSATION_TOOL]
        if self.enable_web_search:
            tools.append({"type": "web_search"})
        return {
            "type": "session.start",
            "event_id": "event_start",
            "session": {
                "model": self.live_model,
                "instructions": self.instructions,
                "audio": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "output": {"voice": self.voice},
                },
                "delegation": {
                    "type": "responses",
                    "responses": {
                        "model": self.backend_model,
                        "instructions": self.backend_instructions,
                        "tools": tools,
                        "tool_choice": "auto",
                        "parallel_tool_calls": False,
                    },
                },
            },
        }

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

    async def _start_session(self, live_ws, timeout: float = 15.0) -> dict:
        """Send session.start and wait for session.started. Returns the started event."""
        await live_ws.send(json.dumps(self._session_start()))
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
    ) -> None:
        """Forward ESP32 binary audio to GPT Live. Client only sends audio after ready."""
        try:
            async for message in client_ws:
                if isinstance(message, bytes):
                    if not first_audio_from_client[0]:
                        first_audio_from_client[0] = True
                        logger.info("First audio from client (%d bytes)", len(message))
                    if len(message) % 2 != 0:
                        message = message + b"\x00"
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
                        if now - state["last_audio_time"] > REPLY_GAP_S:
                            await output_queue.put(("phase", "replying"))
                            if delta_count:
                                logger.info(
                                    "Reply audio: %d deltas, %d bytes (%.1f s)",
                                    delta_count, delta_bytes_total,
                                    delta_bytes_total / BYTES_PER_SEC,
                                )
                            delta_count = 0
                            delta_bytes_total = 0
                        state["last_audio_time"] = now
                        audio_bytes = base64.standard_b64decode(delta_b64)
                        await output_queue.put(audio_bytes)
                        delta_count += 1
                        delta_bytes_total += len(audio_bytes)
                        if self.recorder:
                            self.recorder.record_output_audio(audio_bytes)

                elif ev_type == "response.event":
                    inner = event.get("event") or {}
                    await self._handle_backend_event(inner, live_ws, output_queue, state)

                elif ev_type == "session.delegation.created":
                    logger.info("Delegation created: %s", event.get("delegation"))
                    await output_queue.put(("phase", "thinking"))

                elif ev_type == "session.input_transcript.delta":
                    user_text.append(event.get("delta", ""))
                elif ev_type == "session.output_transcript.delta":
                    bot_text.append(event.get("delta", ""))

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
                    logger.debug("Unhandled GPT Live event: %s", ev_type)
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
            if user_text or bot_text:
                logger.info("Transcript user: %s", "".join(user_text).strip())
                logger.info("Transcript bot: %s", "".join(bot_text).strip())
            if "reason" not in end_reason:
                end_reason["reason"] = "live_disconnected"

    async def _goodbye_watcher(
        self,
        client_ws,
        live_ws,
        output_queue: asyncio.Queue,
        end_reason: dict,
        state: dict,
    ) -> None:
        """After end_conversation was called: let the farewell finish playing, then hang up."""
        try:
            while not state.get("closing"):
                await asyncio.sleep(0.1)
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
                    break
                if heard_audio and idle > GOODBYE_IDLE_S and output_queue.empty():
                    break
                # No farewell audio at all: do not hang up instantly, give it a moment.
                if not heard_audio and waited > 6.0:
                    break
            logger.info("End of conversation, notifying client")
            end_reason["reason"] = "end_conversation"
            try:
                await client_ws.send(
                    json.dumps({
                        "type": "disconnect",
                        "message": "User requested disconnect",
                        "reason": "user_requested_stop",
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
        idle_ticks = 0
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(output_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    if buffer:
                        await client_ws.send(bytes(buffer))
                        buffer.clear()
                    if idle_ticks >= 3:
                        # Reply is over: restart the pacing clock for the next one.
                        bytes_sent = 0
                        start_time = None
                    continue
                idle_ticks = 0

                if isinstance(chunk, tuple) and chunk[0] == "phase":
                    if buffer:
                        await client_ws.send(bytes(buffer))
                        buffer.clear()
                    await self._send_phase(client_ws, chunk[1])
                    continue

                if isinstance(chunk, tuple) and chunk[0] == "error":
                    if buffer:
                        await client_ws.send(bytes(buffer))
                        buffer.clear()
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

                buffer.extend(chunk)

                while len(buffer) >= SEND_CHUNK_SIZE:
                    to_send = bytes(buffer[:SEND_CHUNK_SIZE])
                    del buffer[:SEND_CHUNK_SIZE]

                    if start_time is None:
                        start_time = loop.time()

                    bytes_sent += len(to_send)
                    target_time = start_time + bytes_sent / BYTES_PER_SEC
                    now = loop.time()
                    if target_time > now:
                        await asyncio.sleep(target_time - now)

                    await client_ws.send(to_send)
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
        state: dict = {"closing": False, "fatal": False, "last_audio_time": 0.0}
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

            tasks = [
                asyncio.create_task(
                    self._client_to_live(
                        client_ws, live_ws, output_queue, first_audio_from_client, end_reason
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
                    self._goodbye_watcher(client_ws, live_ws, output_queue, end_reason, state)
                ),
            ]
            finished, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

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
            duration = time.monotonic() - start_time
            reason = end_reason.get("reason", "unknown")
            logger.info(
                "Session ended: %s (duration: %.1fs, reason: %s)",
                client_id, duration, reason,
            )

    async def run(self) -> None:
        """Start WebSocket server and run forever."""
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
