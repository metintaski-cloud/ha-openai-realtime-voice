"""
What happens after a real conversation: the memory update and the rudeness report to Metin.
Mixed into the bridge; needs self.memory, self.todo_sync, self.messages, self.enable_memory,
self.code_phrase, self.openai_api_key, self.memory_model, self.backend_model,
self._memory_tasks and self._in_background from it.
"""
import asyncio
import logging
import os

from app import memory, report

logger = logging.getLogger(__name__)


class AfterTalkMixin:
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
