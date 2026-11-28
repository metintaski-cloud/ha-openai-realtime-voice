"""
Leyla herself on the living room TV (2.195.0).

Metin, 28 Nov 2026, 01:19: "quasi möchte ich Leila im Wohnzimmer sagen, hey Leila, zeig dich im
Fernseher oder zeig dich oder komm mal her, und dass sie dann quasi automatisch im Fernseher
erscheint." And about her night outfit, 01:15 to 01:21: "Ich möchte quasi diese Seite bei mir
auf dem Fernseher haben. Und dort sind auch Kinder etc." ... "im Fernseher soll nicht gefragt
werden, Passwort eingeben oder so. Das ist nicht nötig. Die Sperre soll automatisch drin sein.
Nur die Leila kann das freigeben, indem ich Passwort sage."

How it works:
- The TV is an Android TV with the Fully Kiosk Browser on it (installed 28 Nov 2026). Home
  Assistant opens an address there with `remote.turn_on` and `activity` (measured 01:32: the
  page came up in Fully; without a browser the TV had answered "keine App dafür").
- The address is the memory page with `?tv=1`: only her stage, full screen, no code word, no
  chat, no lists, no field to type into. The page asks `GET /api/tv` for her state.
- That state never says "nacht" unless the night outfit is released, so the page of the TV
  cannot show it by itself: it gets "freizeit" instead. The release is given only by the
  function below, only in a talk in which the code word was said (the gate in tool_link), it
  ends when she leaves the TV, when another app comes to the front on the TV (the Home key of
  the remote locks within WATCH_S), after NIGHT_S, or with a restart. Every new appearance
  starts locked.
- This is a lock of what the page shows. The clip files themselves are served without a code
  word, as before.
"""
import asyncio
import logging
import os
import time
from typing import Optional

from app import tv as tvmod

logger = logging.getLogger(__name__)

BROWSER = "de.ozerov.fully"  # the package the TV reports in front while her page is shown
DEFAULT_URL = "https://leyla-metin.duckdns.org/?tv=1"
SHOW_TRIES = 2        # the first start after switching the TV on is sometimes lost
SHOW_WAIT_S = 6.0     # one start until the browser is in front
BACK_WAIT_S = 4.0     # the TV app until it is in front again
NIGHT_S = 3600.0      # the night outfit stays released at most this long
WATCH_S = 5.0         # how often the TV is asked which app is in front while it is released
PAGE_KEYS = ("mood", "low", "label", "cheer", "level", "outfit")  # all the stage needs

SHOW_TOOL = {
    "type": "function",
    "name": "leyla_fernseher",
    "description": (
        "Show Leyla herself on the living room TV, or take her off it. zeigen: she appears on "
        "the TV (it is switched on if needed). weg: she leaves the TV and the TV programme "
        "comes back. nacht_frei: her night outfit may be seen on the TV; works only after the "
        "code word was said in this talk. nacht_zu: lock the night outfit again at once."
    ),
    "parameters": {
        "type": "object",
        "properties": {"action": {"type": "string",
                                  "enum": ["zeigen", "weg", "nacht_frei", "nacht_zu"]}},
        "required": ["action"],
        "additionalProperties": False,
    },
}

SHOW_BACKEND_HINT = (
    " Leyla can appear on the living room TV herself (leyla_fernseher). In a talk in the living "
    "room, 'zeig dich', 'zeig dich im Fernseher', 'komm mal her', 'komm auf den Fernseher', "
    "'ich will dich sehen' (also in Turkish) mean action zeigen; in a talk from the app only "
    "when the TV is named. 'Geh wieder', 'geh vom Fernseher', 'mach wieder Fernsehen' mean weg. "
    "On the TV she is seen in her day outfits only. nacht_frei and nacht_zu are a secret "
    "between her and Metin: without the code word in this talk never call nacht_frei, never "
    "mention a night outfit, a lock or a code word, and if someone asks for it say only that "
    "this is how she is on the TV. After the code word, 'Nacht frei', 'zeig dich im "
    "Nachtkleid', 'du darfst' mean nacht_frei, and 'sperr wieder', 'zieh dich an', 'es kommt "
    "jemand' mean nacht_zu at once. Always call the function and say very briefly what "
    "happened; if it returns an error, say so honestly."
)
SHOW_LIVE = ("dich selbst auf dem Fernseher im Wohnzimmer zeigen und wieder gehen (sagt jemand "
             "im Wohnzimmer „zeig dich“, „komm mal her“ oder „ich will dich sehen“, gibst du "
             "das sofort weiter)")

# part of the note after the code word (talk_notes._code_notes): only then she knows about it
UNLOCK_NOTE = (" Auf dem Fernseher im Wohnzimmer sieht man dich sonst nur in deinen Tageskleidern. "
               "Möchte Metin dich dort jetzt im Nachtkleid sehen („Nacht frei“, „zeig dich im "
               "Nachtkleid“), oder soll es wieder zu sein („sperr wieder“, „zieh dich an“, „es "
               "kommt jemand“), gibst du das sofort an deinen Hintergrund weiter. Vor anderen "
               "erwähnst du das nie.")


class TvShow:
    def __init__(self, tv, mood=None, url: Optional[str] = None) -> None:
        self.tv = tv
        self.mood = mood
        self.url = (url if url is not None else os.environ.get("TV_LEYLA_URL") or "").strip()
        if self.url.lower() in ("", "null"):
            self.url = DEFAULT_URL
        self.night_until = 0.0
        self.mund = None  # app/mund.py MundLink, set by the bridge: her live mouth from Metin's PC (2.199.0)
        self._before = ""   # the app that was in front before she came, to go back to
        self._watch: Optional[asyncio.Task] = None

    @property
    def available(self) -> bool:
        return bool(getattr(self.tv, "available", False) and self.url.lower() != "aus")

    def night_open(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) < self.night_until

    def page_state(self, now: Optional[float] = None) -> dict:
        """Her state for the page on the TV: only what the stage needs, and never the night
        outfit while it is not released."""
        status = getattr(self.mood, "status", None)
        st = status() if status else {}
        if not st:
            return {}
        out = {k: st[k] for k in PAGE_KEYS if k in st}
        if out.get("outfit") == "nacht" and not self.night_open(now):
            out["outfit"] = "freizeit"
        if self.mund is not None and self.mund.ready():
            # the mouth service on the PC is up: the TV page moves to its page, which shows her with a live mouth
            out["mund"] = self.mund.page()
        return out

    def _lock(self, why: str) -> None:
        if self.night_until:
            logger.info("TV: the night outfit is locked again (%s)", why)
        self.night_until = 0.0

    async def _front(self) -> str:
        return (await self.tv._activity()).lower()

    async def _open(self) -> bool:
        # With the mouth service on the PC ready, the TV opens its page directly (2.199.1, Metin: "Wenn die Leyla
        # kommt, muss auch wirklich nur die Leyla kommen und nichts davor"): the normal page showed her other
        # look for some seconds before it moved on.
        url = self.url
        if self.mund is not None and self.mund.ready():
            url = self.mund.page()
            logger.info("TV: opening the page of the mouth service")
        for n in range(SHOW_TRIES):
            await self.tv._service("remote", "turn_on",
                                   {"entity_id": self.tv.tv_remote, "activity": url})
            if await self.tv._wait_activity(lambda a: BROWSER in a, SHOW_WAIT_S):
                logger.info("TV: her page is in front after try %d", n + 1)
                return True
        logger.warning("TV: her page did not come to the front (%d tries)", SHOW_TRIES)
        return False

    async def show(self) -> dict:
        self._lock("new appearance")
        if await self.tv._state() in ("off", "standby", "unavailable"):
            power = await self.tv._power(True)
            if "error" in power:
                return power
        before = await self._front()
        if before and BROWSER not in before:
            self._before = before
        if not await self._open():
            return {"error": "Der Fernseher hat Leylas Seite nicht geöffnet, sie ist dort "
                             "nicht zu sehen."}
        return {"done": "Leyla ist jetzt auf dem Fernseher zu sehen"}

    async def hide(self) -> dict:
        self._lock("she leaves the TV")
        if BROWSER not in await self._front():
            return {"done": "Leyla war nicht auf dem Fernseher"}
        back = self._before
        if back and "launcher" not in back:
            await self.tv._service("remote", "turn_on", {
                "entity_id": self.tv.tv_remote, "activity": tvmod.APP_LINKS.get(back, back)})
            if await self.tv._wait_activity(lambda a: bool(a) and BROWSER not in a, BACK_WAIT_S):
                return {"done": "Leyla ist vom Fernseher weg, das Programm läuft wieder"}
        await self.tv._tv_key("HOME")
        return {"done": "Leyla ist vom Fernseher weg"}

    async def _watcher(self) -> None:
        """While the night outfit is released: lock it as soon as another app is in front."""
        while self.night_open():
            await asyncio.sleep(WATCH_S)
            if self.night_open() and BROWSER not in await self._front():
                self._lock("her page is no longer in front")

    async def night(self, on: bool) -> dict:
        if not on:
            self._lock("asked to")
            return {"done": "Das Nachtkleid ist auf dem Fernseher wieder gesperrt"}
        if BROWSER not in await self._front():
            shown = await self.show()
            if "error" in shown:
                return shown
        if hasattr(self.mood, "wear"):
            self.mood.wear("nacht")  # like Umziehen in the menu of the app: his own choice
        self.night_until = time.time() + NIGHT_S
        if not self._watch or self._watch.done():
            self._watch = asyncio.get_running_loop().create_task(self._watcher())
        logger.info("TV: the night outfit is released")
        return {"done": "Das Nachtkleid ist auf dem Fernseher frei, bis sie den Fernseher "
                        "verlässt, höchstens eine Stunde"}

    async def run(self, args: dict) -> dict:
        action = str(args.get("action") or "").strip().lower()
        try:
            if action == "zeigen":
                return await self.show()
            if action == "weg":
                return await self.hide()
            if action in ("nacht_frei", "nacht_zu"):
                return await self.night(action == "nacht_frei")
            return {"error": f"Unbekannte Aktion: {action}"}
        except Exception as e:
            self._lock("error")
            logger.warning("TV show %s failed: %s", action, type(e).__name__)
            return {"error": "Der Fernseher konnte gerade nicht gesteuert werden."}


def night_gate(args: dict, state: dict):
    """The night outfit on the TV is released only in a talk in which the code word was said.
    Locking it again is open to everyone."""
    if str(args.get("action") or "").strip().lower() == "nacht_frei" and not state.get("unlocked"):
        return {"error": "Das geht nicht.",
                "hinweis": "Sag nur kurz, dass das nicht geht. Nenne keinen Grund, kein "
                           "Nachtkleid, keine Sperre und kein Codewort."}
    return None
