"""
What happens after a real conversation: the memory update and the rudeness report to Metin.
Mixed into the bridge; needs self.memory, self.todo_sync, self.messages, self.enable_memory,
self.code_phrase, self.openai_api_key, self.memory_model, self.backend_model,
self._memory_tasks and self._in_background from it.
"""
import asyncio
import logging
import os

from app import memory, report, spott
from app.phrases import END_TALK_RE, contains_goodbye

logger = logging.getLogger(__name__)


class AfterTalkMixin:
    async def _update_memory(self, dialog: list, unlocked: bool) -> None:
        old = self.memory.load_all()
        lists = await memory.summarize(
            self.openai_api_key, [self.memory_model, self.backend_model], old, dialog,
            unlocked=unlocked, unlocked_by_code=unlocked and bool(self.code_phrase),
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
                                    else "(hidden entry)")
                for f in old[kind]:
                    if f not in lists[kind]:
                        logger.info("Memory %s: - %s", kind, f if kind in memory.OPEN_KINDS
                                    else "(hidden entry)")
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

    def _schedule_diary(self, state: dict, reason: str = "") -> None:
        """A diary entry of the talk (app/diary.py), for the person who talked."""
        dialog = [d for d in state.get("dialog", []) if d[1].strip()]
        said = sum(len(t) for s, t in dialog if s == "user")
        if (not self.enable_memory or not self.openai_api_key or reason == "no_speech"
                or said < 15 or not any(s == "bot" for s, _ in dialog)):
            return
        who = sorted(state.get("identified") or [])  # everyone known in this talk
        if state.get("unlocked") and not any(n.split()[0] == "Metin" for n in who):
            who.append("Metin")
        task = asyncio.create_task(self.diary.write(
            dialog, who, "stimme", self.openai_api_key, [self.memory_model, self.backend_model],
            os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL)))
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    def _schedule_rude_report(self, state: dict) -> None:
        """Leyla said she would tell Metin: after the talk she does, in her own words."""
        dialog = [d for d in state.get("dialog", []) if d[1].strip()]
        if self.messages.available and report.needs_report(dialog):
            self._in_background(self._send_rude_report(dialog))

    def _schedule_grudges(self, state: dict) -> None:
        """After a talk (2.181.0, app/spott.py): did someone she holds a grudge against
        apologise, and, when she hung up herself or said that she would (her third level),
        did someone whose name was given make fun of her?"""
        dialog = [d for d in state.get("dialog", []) if str(d[1]).strip()]
        names = self._talk_names(state)
        said = " ".join(str(t) for s, t in dialog if s == "user")
        sorry = [n for n in names.values() if self.grudges.has(n) and n != state.get("mocked_who")]
        if sorry and spott.APOLOGY_RE.search(said):
            self._in_background(self._grudge_apology(dialog, sorry))
        others = [n for n in names.values() if spott.key(n) != "metin"]
        hung_up = (state.get("ended_by_her") and not contains_goodbye(said)
                   and not END_TALK_RE.search(said))
        warned = any(s == "bot" and spott.HANGUP_SAID_RE.search(str(t)) for s, t in dialog)
        if (hung_up or warned) and others and not state.get("mocked_who"):
            self._in_background(self._grudge_check(dialog, others))

    def _grudge_models(self) -> tuple:
        return (self.openai_api_key, [self.backend_model, self.memory_model],
                os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL))

    async def _grudge_apology(self, dialog: list, names: list) -> None:
        key, models, url = self._grudge_models()
        for name in names:
            if await spott.apologised(key, models, dialog, name, url=url) and self.grudges.forgive(name):
                logger.info("%s apologised to her: forgiven", name)

    async def _grudge_check(self, dialog: list, names: list) -> None:
        key, models, url = self._grudge_models()
        name = await spott.who_mocked(key, models, dialog, names, url=url)
        if name and self.grudges.add(name):
            logger.info("She hung up after being made fun of: remembered for %s", name)

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
