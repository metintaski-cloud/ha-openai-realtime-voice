"""When and how a session ends: nobody spoke (false wake), idle, maximum length, or the goodbye was played.

Mixed into LiveVoiceBridge. Needs nothing from it except the state dict of the session. The time limits live here
(tests change them on this module)."""
import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

# After the model said goodbye, wait this long without audio before hanging up.
GOODBYE_IDLE_S = 1.5
GOODBYE_MAX_WAIT_S = 15.0
# End the session when nobody spoke for this long (GPT Live is billed per minute).
IDLE_TIMEOUT_S = 30.0
NO_SPEECH_TIMEOUT_S = 6.0  # false wake: nobody speaks, end silently (counted from the end of her greeting)
VOICE_HOLD_S = 2.5  # while a voice was heard this recently the session is not ended for silence
NO_SPEECH_MAX_S = 14.0  # but never longer than this after the start (TV noise must not hold a false wake)
MAX_SESSION_S = 600.0


class SessionEndMixin:
    @staticmethod
    def _no_speech_over(state: dict, session_start: float, now: float) -> bool:
        """Nobody spoke: the wait counts from the end of Leyla's own greeting (it used to
        count from the start, so a slow answer was cut off), and a voice heard just now
        (the transcript comes a little later) holds the session open up to a limit."""
        limit = state.get("no_speech_s", NO_SPEECH_TIMEOUT_S)
        quiet_since = max(session_start, state.get("last_audio_time", 0.0))
        if now - session_start > max(limit, NO_SPEECH_MAX_S):
            return True
        if now - state.get("last_voice_at", 0.0) < VOICE_HOLD_S:
            return False
        return now - quiet_since > limit

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
                elif not state.get("user_spoke") and self._no_speech_over(
                        state, session_start, now):
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
