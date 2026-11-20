"""`ReachMixin`: the bridge side of Leyla's own messages to Metin (app/reach.py, add on 2.118.0).

It gives `Reach` its helpers: the text model, her voice (GPT Live, like a voice reply in the app
chat), the push message with sound that opens the app chat, and her rules and memory of the last
talks for the prompt. Mixed into the bridge in `main.py`.
"""

import logging
import os
from typing import Optional
from urllib.parse import urlparse

from app import chat, memory, messages, persona, reach, textmodel

logger = logging.getLogger(__name__)

# the Home Assistant app plays this channel with sound and shows the message on top
PUSH_EXTRA = {"channel": "leyla_nachricht", "importance": "high", "priority": "high", "ttl": 0}


def app_url() -> str:
    """Where a tap on the push message goes: the memory app on the add on host."""
    url = os.environ.get("REACH_APP_URL", "")
    if url:
        return url
    host = urlparse(os.environ.get("ANNOUNCE_BASE_URL", "http://192.168.2.240:8084")).hostname
    return f"http://{host or '192.168.2.240'}:{os.environ.get('MEMORY_WEB_PORT', '8082')}/"


class ReachMixin:
    def _init_reach(self, love: str) -> None:
        self._reach_love = love
        self.reach = reach.Reach(
            self.mood, write=self._reach_write, speak=self._reach_speak,
            push=self._reach_push if self.messages.available else None,
            busy=lambda: bool(self._active_sessions), rules=self._reach_rules,
            notes=self._reach_notes)

    def _reach_rules(self) -> str:
        return persona.build([], fan=False, tv=False, messages=False, extra=self.instructions)

    async def _reach_notes(self) -> str:
        # a noted plan of his that is over: her own message may ask how it went (2.121.0)
        return (self.diary.note("Metin", private=True) + self.variety.note()
                + self.diary.followup_note("Metin", private=True))

    async def _reach_write(self, prompt: str) -> str:
        return await textmodel.ask(
            prompt, self.openai_api_key, [self.memory_model, self.backend_model],
            os.environ.get("OPENAI_RESPONSES_URL", memory.RESPONSES_URL), "Reach message",
            check=lambda t: bool(reach.parse_text(t))) or ""

    async def _reach_speak(self, text: str) -> Optional[bytes]:
        pcm = await self._speak_once(
            reach.SPEAK.format(text=text), max_s=45.0,
            instructions=chat.voice_reply_instructions(self.mood.feeling(), self._reach_love))
        return messages.pcm_to_wav(pcm) if pcm else None

    async def _reach_push(self, title: str, message: str) -> None:
        await self.messages.push(title, message, extra={**PUSH_EXTRA, "clickAction": app_url()})

    async def _reach_tick(self) -> None:
        item = await self.reach.tick()
        if item:  # her thread in the chat knows what she asked, his answer finds it
            self.diary.leyla_wrote(item["text"])
            self.variety.add([item["text"]])
