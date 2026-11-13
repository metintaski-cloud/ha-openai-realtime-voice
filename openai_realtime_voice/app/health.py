"""
Tells Metin on his phone when something is wrong, so he does not have to find out because
Leyla stays silent: the server was killed unexpectedly (crash, power loss), OpenAI cannot be
reached several times in a row, or the OpenAI credit is used up. Every kind of message has a
cooldown so a long outage does not flood the phone.
"""
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

HEARTBEAT_S = 60
FAILURES_BEFORE_ALERT = 3
COOLDOWN_S = 3 * 3600
QUOTA_COOLDOWN_S = 6 * 3600
TITLE = "Leyla Server"


class Health:
    def __init__(self, path: str, notify=None, clock=time.time) -> None:
        self.path = path
        self.notify = notify  # async (title, message)
        self.clock = clock
        self.failures = 0
        self.alerted_openai = False
        self._last_alert: dict = {}

    # ---- heartbeat: tells the next start whether the last run ended cleanly --------------
    def _read(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _write(self, clean: bool) -> None:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"t": self.clock(), "clean": clean}, f)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning("Could not write the heartbeat: %s", e)

    def beat(self) -> None:
        self._write(clean=False)

    def mark_clean(self) -> None:
        """Call on a normal shutdown (update, restart by the user)."""
        self._write(clean=True)

    def previous_run_crashed(self) -> Optional[float]:
        """Time of the last heartbeat when the previous run did not end cleanly, else None.
        Call once at start, before the first beat."""
        prev = self._read()
        if prev and prev.get("clean") is False and isinstance(prev.get("t"), (int, float)):
            return float(prev["t"])
        return None

    # ---- alerts ----------------------------------------------------------------------------
    async def _alert(self, kind: str, message: str, cooldown: float) -> bool:
        now = self.clock()
        last = self._last_alert.get(kind)
        if last is not None and now - last < cooldown:
            return False
        self._last_alert[kind] = now
        if not self.notify:
            return False
        try:
            await self.notify(TITLE, message)
            return True
        except Exception as e:
            logger.warning("Could not send the health message: %s", e)
            return False

    async def report_start(self, local_time=time.localtime) -> None:
        """At start: say so when the last run was killed unexpectedly."""
        last = self.previous_run_crashed()
        self.beat()
        if last is None:
            return
        stamp = time.strftime("%H:%M", local_time(last))
        await self._alert(
            "crash",
            f"Der Leyla Server wurde unerwartet beendet (zuletzt aktiv um {stamp} Uhr) und ist "
            "wieder gestartet. Wenn das öfter passiert, bitte melden.", 0)

    async def openai_ok(self) -> None:
        self.failures = 0
        if self.alerted_openai:
            self.alerted_openai = False
            await self._alert("openai_back", "Leyla erreicht OpenAI wieder.", 0)

    async def openai_failed(self, error: str = "") -> None:
        self.failures += 1
        if self.failures < FAILURES_BEFORE_ALERT:
            return
        sent = await self._alert(
            "openai",
            f"Leyla kann OpenAI seit {self.failures} Versuchen nicht erreichen. "
            "Internet, Zugangsdaten und Guthaben prüfen.", COOLDOWN_S)
        if sent:
            self.alerted_openai = True

    async def quota_exceeded(self) -> None:
        await self._alert(
            "quota", "Das OpenAI Guthaben ist aufgebraucht, Leyla kann nicht antworten. "
            "Bitte unter platform.openai.com Guthaben aufladen.", QUOTA_COOLDOWN_S)
