"""Everything the bridge sends to the device: audio paced at playback rate, phases, interrupts and errors, in one
ordered stream (the output queue). Mixed into LiveVoiceBridge."""
import asyncio
import json
import logging

import websockets

from app.pacing import PacedSender

logger = logging.getLogger(__name__)


class OutputMixin:
    async def _send_phase(self, client_ws, phase: str) -> None:
        """Send phase message to client for LED/UX feedback."""
        try:
            await client_ws.send(json.dumps({"type": "phase", "phase": phase}))
            logger.info("Phase -> %s", phase)
        except Exception as e:
            logger.warning("Failed to send phase '%s': %s", phase, e)

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
        sender = PacedSender(client_ws)
        idle_ticks = 0
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(output_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    await sender.pump(flush=True)
                    if idle_ticks >= 3 and not sender.buffer:
                        sender.reset()  # reply is over: restart the pacing clock
                    continue
                idle_ticks = 0

                if isinstance(chunk, tuple) and chunk[0] == "phase":
                    await sender.pump(flush=True, force=True)
                    await self._send_phase(client_ws, chunk[1])
                    continue

                if isinstance(chunk, tuple) and chunk[0] == "interrupt":
                    sender.buffer.clear()
                    sender.reset()
                    try:
                        await client_ws.send(json.dumps({"type": "interrupt"}))
                    except Exception as e:
                        logger.warning("Failed to send interrupt: %s", e)
                    continue

                if isinstance(chunk, tuple) and chunk[0] == "error":
                    await sender.pump(flush=True, force=True)
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

                sender.add(chunk)
                await sender.pump()
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
