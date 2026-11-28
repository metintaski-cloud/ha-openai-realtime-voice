"""Open points of her memory (2.202.0, docs/GEDAECHTNIS_ORDNUNG.md).

Metin, 28 Nov 2026: she changes nothing by herself that contradicts what is there, she does not
enter a person she knows nothing about, nothing leaves by itself, and she tells him once what she
entered. So everything she may not decide waits here as a point until he has decided, and what she
entered waits here until she has told him. Going through the points in a talk is step 3
(app/aufraeumen.py); this module only keeps them.

Kinds (`art`):
- "neu": she entered something new that contradicts nothing; to be told once.
- "widerspruch": something new contradicts an entry; the old one stays valid, `neu` waits.
- "mensch": a name came up and she does not know who it is; nothing was entered.
- "unklar": an entry that fits no area, an old switching rule, a double; it stays where it is.
- "abgelaufen": an entry with a date that is over; it stays, she asks what to do with it.

Texts of points are private like the lists they come from: never logged, never in the repository.
The file lives in /data only.
"""
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

PATH = "/data/leyla_punkte.json"
KINDS = ("neu", "widerspruch", "mensch", "unklar", "abgelaufen")
MAX_OPEN = 200          # more than that and the oldest "neu" notices are dropped first
KEEP_DONE_S = 7 * 86400


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


class Points:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.environ.get("LEYLA_PUNKTE_PATH", PATH)

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f) or {}
            if isinstance(d.get("items"), list):
                return d
        except Exception:
            pass
        return {"items": [], "next": 1}

    def _save(self, d: dict) -> None:
        now = time.time()
        d["items"] = [p for p in d["items"]
                      if p.get("status") == "offen" or now - p.get("done_t", now) < KEEP_DONE_S]
        opened = [p for p in d["items"] if p.get("status") == "offen"]
        if len(opened) > MAX_OPEN:  # notices first, decisions never
            extra = [p for p in opened if p.get("art") == "neu"][:len(opened) - MAX_OPEN]
            d["items"] = [p for p in d["items"] if p not in extra]
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    @staticmethod
    def _key(p: dict) -> tuple:
        return (p.get("art"), p.get("liste", ""), _norm(p.get("alt")), _norm(p.get("neu")),
                _norm(p.get("name")))

    def add(self, points) -> int:
        """Store new points; one that is already open, or was decided in the last days, is not
        asked again. Returns how many were added."""
        points = [p for p in (points or []) if isinstance(p, dict) and p.get("art") in KINDS]
        if not points:
            return 0
        d = self._load()
        have = {self._key(p) for p in d["items"]}
        n = 0
        for p in points:
            key = self._key(p)
            if key in have:
                continue
            have.add(key)
            item = {k: p[k] for k in ("art", "liste", "alt", "neu", "name", "feld", "privat") if p.get(k)}
            item.update(id=d["next"], t=time.time(), status="offen")
            d["next"] += 1
            d["items"].append(item)
            n += 1
        if n:
            self._save(d)
            logger.info("Points: %d new (%s)", n, ", ".join(sorted({p["art"] for p in points})))
        return n

    def open(self, private: bool = True) -> list:
        """The open points, decisions first, then what she entered; oldest first in each."""
        items = [p for p in self._load()["items"] if p.get("status") == "offen"
                 and (private or not p.get("privat"))]
        return sorted(items, key=lambda p: (p.get("art") == "neu", p.get("t", 0)))

    def get(self, point_id) -> Optional[dict]:
        return next((p for p in self._load()["items"] if p.get("id") == point_id), None)

    def done(self, point_id, decision: str = "") -> bool:
        d = self._load()
        for p in d["items"]:
            if p.get("id") == point_id and p.get("status") == "offen":
                p.update(status="erledigt", done_t=time.time(), entscheidung=str(decision)[:40])
                self._save(d)
                logger.info("Points: one %s point decided (%s)", p.get("art"), p["entscheidung"] or "done")
                return True
        return False

    def counts(self) -> dict:
        """Numbers only, for the log and the status page."""
        out = {k: 0 for k in KINDS}
        for p in self._load()["items"]:
            if p.get("status") == "offen":
                out[p["art"]] = out.get(p["art"], 0) + 1
        return out
