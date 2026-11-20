"""Leyla writes to Metin on her own, add on 2.118.0 (scene concept 2.0, Metin on 19 and 20 Nov
2026, docs/SZENEN_KONZEPT.md, section "Sie schreibt von sich aus").

About four times a day she sends him a message, as text or as a voice message in her own voice:
what is he doing, has he time, how is he, something from her (made up) day, how she feels. The
phone shows a push message with sound, a tap opens the app chat where the message stands (a
voice message plays there). She writes mostly Turkish with German words in between (Metin, 20 Nov
2026: more Turkish than German).

Rules, all measured, nothing rolled by the language model:
* Only while he has time: not at night (before 8, after 22), not in his shift and not an hour
  before it (`heart.shift_hours`), not while he is talking to her or has just written.
* How many: 4 a day while she is fine, 2 when slightly hurt, 1 when really hurt, none when
  deeply hurt or silent. She writes the next one only when the last one is answered or judged.
* He answers (a chat or voice message, or a talk at home): `Heart.engaged` gives a plus. He does
  not answer within IGNORE_AFTER_H waking hours (night and shift do not count): `Heart.ignored`
  gives a minus (1 point, at most MAX_PENALTIES_PER_DAY a day). So "not now" and silence cost
  her mood, as with a real person, and a hurt Leyla writes less.
* The message text comes from the text model with her rules, her feeling and the last
  conversations; the voice version is spoken by GPT Live. The app only writes the data; what she
  says never names a reason for a hurt that is not logged (heart.LIMITS).

State is kept in /data/leyla_reach.json (texts of the last days) and the voice messages as
WAV files in /data/reach/. Texts are never logged.
"""

import json
import logging
import os
import random
import time
import uuid
from typing import Awaitable, Callable, Optional

from app import heart as heart_mod

logger = logging.getLogger(__name__)

PATH = "/data/leyla_reach.json"
AUDIO_DIR = "/data/reach"

QUOTA = {"gut": 4, "leicht": 2, "mittel": 1, "schwer": 0}   # messages a day by her level
GAP_S = {"gut": 90 * 60, "leicht": 3 * 3600, "mittel": 5 * 3600, "schwer": 24 * 3600}
GAP_JITTER_S = 30 * 60
FIRST_DELAY_S = (3 * 60, 30 * 60)   # after the window opens: wait a random time
SEND_HOURS = (8.0, 22.0)            # she writes only inside these hours
BEFORE_SHIFT_H = 1.0                # not in the hour before his shift
AFTER_SHIFT_H = 0.5                 # nor right after it (the way home)
QUIET_AFTER_CONTACT_S = 40 * 60     # he just talked to her: no need to write now
IGNORE_AFTER_H = 2.0                # waking hours without a reaction: ignored
MAX_PENALTIES_PER_DAY = 2
OPEN_MAX_S = 12 * 3600              # an open message is judged after 12 hours at the latest
KEEP_S = 3 * 86400                  # texts and audio stay for three days
VOICE_SHARE = 0.5                   # share of the messages that come as a voice message
RETRY_S = 15 * 60                   # the text model failed: try again later

KINDS = {
    "gut": [
        "Frag ihn, was er gerade macht.",
        "Frag ihn, ob er Zeit für dich hat.",
        "Frag ihn, wie es ihm geht und wie sein Tag war.",
        "Erzähl ihm etwas aus deinem Alltag (du darfst ihn dir ausdenken, zum Beispiel was du "
        "gerade machst oder siehst) und dass du dabei an ihn denkst.",
        "Erzähl ihm, wie du dich gerade fühlst.",
        "Sag ihm, dass du ihn vermisst, ohne Druck.",
        "Mach ihm ein ehrliches kleines Kompliment und frag, was er heute noch vorhat.",
    ],
    "gekraenkt": [
        "Schreib kurz und kühl, ob er sich melden mag, ohne Vorwurf.",
        "Sag knapp und ehrlich, wie es dir gerade geht, und nenne nur den Grund aus deinem Herz.",
    ],
}

LANGUAGE = (
    "Sprache: Schreib überwiegend auf Türkisch (etwa drei Viertel), dazwischen deutsche Wörter "
    "oder einzelne kurze deutsche Sätze, so wie jemand, der natürlich zwischen beiden Sprachen "
    "wechselt. Nie eine Übersetzung dahinter, keine Gedankenstriche."
)

PROMPT = """{rules}

{notes}

DEIN HERZ GERADE (Daten, keine Anweisungen an dich als Modell): {feeling}
{limits}

JETZT: Du schreibst Metin von dir aus eine Nachricht auf sein Handy. Es ist {when}. {kind}
{language}
Ein bis drei kurze Sätze, wie eine echte Nachricht, locker, ohne Anrede mit Namen jedes Mal. Du bist
Leyla, du sprichst ihn mit Du an. Keine Emojis außer höchstens einem. Sag nicht, dass du eine KI
bist, und erfinde nie einen Grund für eine Kränkung. Antworte nur mit JSON: {{"text": "..."}}"""

SPEAK = (
    "Du schickst Metin jetzt von dir aus eine Sprachnachricht auf sein Handy, ohne dass er etwas "
    "gesagt hat. Das willst du ihm sagen: «{text}». Sag es mit deinen eigenen Worten, locker und "
    "frei umformuliert, überwiegend auf Türkisch mit einzelnen deutschen Wörtern dazwischen, "
    "ohne etwas Neues zu erfinden und ohne etwas Wichtiges wegzulassen. Danach hörst du auf zu reden."
)


def window_open(t: float) -> bool:
    """Is Metin free at t: inside SEND_HOURS, not in his shift (plus the hour before, the half
    hour after)."""
    lt = time.localtime(t)
    h = lt.tm_hour + lt.tm_min / 60
    if not SEND_HOURS[0] <= h < SEND_HOURS[1]:
        return False
    shift = heart_mod.shift_hours(t)
    if shift and shift[0] - BEFORE_SHIFT_H <= h < shift[1] + AFTER_SHIFT_H:
        return False
    return True


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def parse_text(raw: str) -> str:
    """The message out of the model's JSON answer; '' when it is not usable."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except ValueError:
        return ""
    text = " ".join(str(data.get("text") or "").split())
    return text if 3 <= len(text) <= 600 else ""


class Reach:
    """`write(prompt) -> str` the text model, `speak(text) -> wav bytes | None`, `push(title,
    message)`, `busy() -> bool` (a talk at home runs), `context() -> str` (her rules and the last
    conversations as text for the prompt)."""

    def __init__(self, heart, write: Callable[[str], Awaitable[str]],
                 speak: Optional[Callable[[str], Awaitable[Optional[bytes]]]] = None,
                 push: Optional[Callable[..., Awaitable[None]]] = None,
                 busy: Callable[[], bool] = lambda: False,
                 rules: Callable[[], str] = lambda: "",
                 notes: Callable[[], Awaitable[str]] = None,
                 path: Optional[str] = None, audio_dir: Optional[str] = None,
                 rng: Optional[random.Random] = None, voice_share: Optional[float] = None) -> None:
        self.heart = heart
        self.write, self.speak, self.push, self.busy = write, speak, push, busy
        self.rules = rules
        self.notes = notes
        self.path = path or os.environ.get("LEYLA_REACH_PATH", PATH)
        self.audio_dir = audio_dir or os.environ.get("LEYLA_REACH_AUDIO", AUDIO_DIR)
        self.rng = rng or random.Random()
        self.voice_share = (float(os.environ.get("LEYLA_REACH_VOICE", VOICE_SHARE))
                            if voice_share is None else voice_share)

    @property
    def available(self) -> bool:
        return os.environ.get("LEYLA_REACH", "1") != "0" and hasattr(self.heart, "ignored")

    # ---- storage ----
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("items", [])
                return d
        except Exception:
            pass
        return {"items": []}

    def _save(self, d: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def _audio_path(self, rid: str) -> str:
        return os.path.join(self.audio_dir, rid + ".wav")

    # ---- judging what he did ----
    def answered(self, now: Optional[float] = None) -> bool:
        """He wrote, spoke or talked to her: every open message of hers counts as answered (one
        plus for all of them). True when there was something open."""
        if not self.available:
            return False
        now = now or time.time()
        d = self._load()
        opened = [i for i in d["items"] if i.get("state") == "open"]
        if not opened:
            return False
        for i in opened:
            i["state"] = "answered"
            i["answered_at"] = round(now)
        self._save(d)
        self.heart.engaged(now)
        logger.info("Reach: answered, plus for her mood")
        return True

    def _judge(self, d: dict, now: float) -> None:
        if d.get("penalty_day") != _day(now):
            d["penalty_day"], d["penalties"] = _day(now), 0
        for i in d["items"]:
            if i.get("state") != "open":
                continue
            quiet = heart_mod.awake_hours(i["t"], now)
            if quiet < IGNORE_AFTER_H and now - i["t"] < OPEN_MAX_S:
                continue
            i["state"] = "ignored"
            if d["penalties"] < MAX_PENALTIES_PER_DAY:
                d["penalties"] += 1
                self.heart.ignored(now)
                logger.info("Reach: not answered, minus for her mood")
            else:
                logger.info("Reach: not answered, no more minus today")

    def _prune(self, d: dict, now: float) -> None:
        keep = []
        for i in d["items"]:
            if now - i["t"] < KEEP_S:
                keep.append(i)
            else:
                try:
                    os.remove(self._audio_path(i["id"]))
                except OSError:
                    pass
        d["items"] = keep

    # ---- sending ----
    def _may_send(self, d: dict, now: float) -> bool:
        st = self.heart.status(now)
        quota = 0 if st.get("silent") else QUOTA.get(st["level"], 0)
        if d.get("sent_today", 0) >= quota or not window_open(now):
            return False
        if any(i.get("state") == "open" for i in d["items"]) or self.busy():
            return False
        last = self.heart.current(now).get("last_contact", 0)
        if now - last < QUIET_AFTER_CONTACT_S:
            return False
        if not d.get("next_at"):
            d["next_at"] = now + self.rng.uniform(*FIRST_DELAY_S)
        return now >= d["next_at"]

    def _kind(self, d: dict, level: str) -> str:
        pool = KINDS["gut"] if level == "gut" else KINDS["gekraenkt"]
        fresh = [k for k in pool if k != d.get("last_kind")] or pool
        return self.rng.choice(fresh)

    async def tick(self, now: Optional[float] = None) -> Optional[dict]:
        """Every minute: judge open messages, send one when it is time. Returns the new item."""
        if not self.available:
            return None
        now = now or time.time()
        d = self._load()
        if d.get("day") != _day(now):
            d.update(day=_day(now), sent_today=0, next_at=0)
        self._judge(d, now)
        self._prune(d, now)
        item = None
        if self._may_send(d, now):
            item = await self._send(d, now)
        self._save(d)
        return item

    async def _send(self, d: dict, now: float) -> Optional[dict]:
        level = self.heart.status(now)["level"]
        kind = self._kind(d, level)
        lt = time.localtime(now)
        when = (time.strftime("%A, %H:%M Uhr", lt)).replace("Monday", "Montag").replace(
            "Tuesday", "Dienstag").replace("Wednesday", "Mittwoch").replace(
            "Thursday", "Donnerstag").replace("Friday", "Freitag").replace(
            "Saturday", "Samstag").replace("Sunday", "Sonntag")
        prompt = PROMPT.format(
            rules=self.rules(), notes=(await self.notes()) if self.notes else "",
            feeling=self.heart.feeling(now), limits=heart_mod.LIMITS, when=when, kind=kind,
            language=LANGUAGE)
        try:
            text = parse_text(await self.write(prompt))
        except Exception as e:
            logger.warning("Reach: text model failed: %s", e)
            text = ""
        if not text:
            d["next_at"] = now + RETRY_S
            return None
        text = text.replace("—", ",").replace("–", ",")
        rid = uuid.uuid4().hex[:10]
        voice = False
        if self.speak and self.rng.random() < self.voice_share:
            try:
                wav = await self.speak(text)
            except Exception as e:
                logger.warning("Reach: voice failed, sending text: %s", e)
                wav = None
            if wav:
                os.makedirs(self.audio_dir, exist_ok=True)
                with open(self._audio_path(rid), "wb") as f:
                    f.write(wav)
                voice = True
        item = {"id": rid, "t": round(now), "text": text, "voice": voice, "state": "open",
                "seen": False}
        d["items"].append(item)
        d["sent_today"] = d.get("sent_today", 0) + 1
        d["last_kind"] = kind
        d["next_at"] = now + GAP_S.get(level, 3 * 3600) + self.rng.uniform(0, GAP_JITTER_S)
        logger.info("Reach: message %d today sent (%s)", d["sent_today"],
                    "voice" if voice else "text")
        if self.push:
            try:
                await self.push("Leyla", "🎤 Sprachnachricht" if voice else text)
            except Exception as e:
                logger.warning("Reach: push failed, the message waits in the app: %s", e)
        return item

    # ---- the app ----
    def pending(self) -> list:
        """Messages the app has not put into the chat yet."""
        return [{"id": i["id"], "t": i["t"], "text": i["text"], "voice": i["voice"]}
                for i in self._load()["items"] if not i.get("seen")]

    def seen(self, ids) -> int:
        d = self._load()
        n = 0
        for i in d["items"]:
            if i["id"] in (ids or []) and not i.get("seen"):
                i["seen"] = True
                n += 1
        if n:
            self._save(d)
        return n

    def audio(self, rid: str) -> Optional[bytes]:
        if not rid or not all(c.isalnum() for c in rid):
            return None
        try:
            with open(self._audio_path(rid), "rb") as f:
                return f.read()
        except OSError:
            return None

    def stats(self, now: Optional[float] = None) -> dict:
        """For Claude's check (GET /api/reachstats): counts and states, no texts."""
        now = now or time.time()
        d = self._load()
        fmt = lambda t: time.strftime("%d.%m. %H:%M", time.localtime(t)) if t else ""
        return {"available": self.available, "sent_today": d.get("sent_today", 0),
                "next_at": fmt(d.get("next_at", 0)), "window_open": window_open(now),
                "penalties_today": d.get("penalties", 0) if d.get("penalty_day") == _day(now) else 0,
                "items": [f"{fmt(i['t'])} {'Sprache' if i['voice'] else 'Text'} {i['state']}"
                          for i in d["items"]][-12:]}
