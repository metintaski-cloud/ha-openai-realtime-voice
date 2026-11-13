"""
The connection to GPT Live: opening it, and keeping one warm connection ready (opened ahead
of time, no session started, so no cost) so the TLS and WebSocket handshake is done before
the wake word. Mixed into the bridge; needs self.openai_api_key, self.warm_connection,
self._warm, self._warm_task and self._in_background from it.
"""
import asyncio
import logging
import os
import time

import websockets

logger = logging.getLogger(__name__)

LIVE_URL = "wss://api.openai.com/v1/live/sessions"

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
WARM_MAX_AGE_S = 90.0  # a pre opened connection older than this is replaced


class LiveLinkMixin:
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
