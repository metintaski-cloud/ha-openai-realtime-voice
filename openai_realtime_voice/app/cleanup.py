"""
Metin is the filter of Leyla's memory. Once a night a text model reads the stored entries and
only PROPOSES the clearly trivial ones (a single knowledge question, a command, small talk
without a person, duplicates, things that are done). Nothing is deleted by itself: the list goes
to Metin's phone, and Leyla deletes entries only after Metin, who said the code phrase, tells
her which ones. Entries he keeps are remembered and never proposed again.
"""
import datetime as _dt
import json
import logging
import os
from typing import Optional

import httpx

from app import memory

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 15
MAX_KEPT = 300
TITLE = "Leyla räumt auf"

CLEANUP_PROMPT = """Du hilfst Metin, das Gedächtnis seiner Sprachassistentin Leyla sauber zu halten.
Unten stehen alle gespeicherten Einträge, nummeriert. Metin entscheidet am Ende selbst, du
schlägst nur vor.

Schlag nur Einträge zum Streichen vor, die EINDEUTIG belanglos sind:
- eine einzelne Wissensfrage oder ein Befehl ohne Bezug zu einer Person (zum Beispiel wie hoch
  der Eiffelturm ist, Licht oder Fernseher an)
- Smalltalk, der nichts Bleibendes über eine Person sagt
- ein Doppelter oder fast Doppelter eines anderen Eintrags
- etwas, das erledigt oder abgelaufen ist

Schlag NIE vor: Einträge, die mit "Person:" beginnen, und alles, was Persönliches oder Kleines
über Menschen sagt (Gewohnheiten, Orte, Namen, Termine, Beruf, Gesundheit, Humor, Stimmungen,
Vorlieben, Sorgen, Pläne). Im Zweifel behalten. Lieber nichts vorschlagen als etwas Falsches.

Einträge:
{entries}

Antworte nur mit JSON in der Form
{{"streichen": [{{"nummer": 3, "grund": "kurzer Grund"}}]}}
und sonst nichts. Gibt es nichts Eindeutiges, antworte {{"streichen": []}}."""

CLEANUP_TOOL = {
    "type": "function",
    "name": "gedaechtnis_aufraeumen",
    "description": (
        "Metin keeps Leyla's memory clean. 'vorschlaege' lists the entries the nightly review "
        "proposed to delete (number, list, entry, reason). 'pruefen' runs the review now. "
        "'streichen' deletes proposed entries, 'behalten' keeps them for good (never proposed "
        "again). 'nummern' is a list like '1,3' of the proposal numbers, or null for all of "
        "them. Only for Metin after the code phrase. Delete only after Metin said which ones."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["vorschlaege", "pruefen", "streichen", "behalten"]},
            "nummern": {"type": ["string", "null"],
                        "description": "Proposal numbers like '1,3', or null for all."},
        },
        "required": ["action", "nummern"],
        "additionalProperties": False,
    },
}

CLEANUP_BACKEND_HINT = (
    " Metin decides what stays in your memory. With gedaechtnis_aufraeumen you can read him the "
    "entries that the nightly review proposed to delete ('vorschlaege'), briefly and one by one, "
    "then 'streichen' only the ones he names (nummern) or 'behalten' the ones he wants to keep. "
    "Delete nothing without his clear yes. All of it only for Metin after the code phrase; if "
    "the result says it is not allowed, say that only Metin can do that."
)


def parse_numbers(text: Optional[str], total: int) -> list:
    """'1,3' -> [0, 2] (zero based). None or empty means all. Out of range numbers are dropped."""
    if text is None or not str(text).strip() or str(text).strip().lower() in ("null", "alle"):
        return list(range(total))
    out = []
    for part in str(text).replace(";", ",").replace(" ", ",").split(","):
        if part.strip().isdigit():
            i = int(part.strip()) - 1
            if 0 <= i < total and i not in out:
                out.append(i)
    return out


class Cleaner:
    def __init__(self, store: "memory.MemoryStore", api_key: str, models: list,
                 url: str = memory.RESPONSES_URL, notify=None, state_path: Optional[str] = None
                 ) -> None:
        self.store = store
        self.api_key = api_key
        self.models = models
        self.url = url
        self.notify = notify  # async (title, message)
        self.state_path = state_path or os.path.join(
            os.path.dirname(store.path) or ".", "cleanup_state.json")

    # ---- state -------------------------------------------------------------------------
    def _state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        return {"pending": [p for p in data.get("pending", []) if isinstance(p, dict)],
                "kept": [k for k in data.get("kept", []) if isinstance(k, str)],
                "last_run": data.get("last_run")}

    def _save(self, state: dict) -> None:
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = self.state_path + ".tmp"
        state["kept"] = state["kept"][-MAX_KEPT:]
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    def _live_pending(self, state: dict) -> list:
        """Pending proposals whose entry still exists unchanged."""
        lists = self.store.load_all()
        return [p for p in state["pending"] if p.get("fact") in lists.get(p.get("kind"), [])]

    # ---- the review --------------------------------------------------------------------
    async def _ask(self, entries: list) -> Optional[list]:
        numbered = "\n".join(f"{i}. [{k}] {f}" for i, (k, f) in enumerate(entries, 1))
        prompt = CLEANUP_PROMPT.format(entries=numbered)
        async with httpx.AsyncClient(timeout=90.0) as client:
            for model in [m for m in self.models if m]:
                try:
                    resp = await client.post(
                        self.url,
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "Content-Type": "application/json"},
                        json={"model": model, "input": prompt})
                except Exception as e:
                    logger.warning("Cleanup review request failed (%s): %s", model, e)
                    continue
                if resp.status_code != 200:
                    logger.warning("Cleanup review with %s failed: HTTP %s", model,
                                   resp.status_code)
                    continue
                data = resp.json()
                text = data.get("output_text") or ""
                if not text:
                    for item in data.get("output", []):
                        if item.get("type") == "message":
                            for part in item.get("content", []):
                                if part.get("type") == "output_text":
                                    text += part.get("text", "")
                obj = memory._json_object(text)
                if obj is None or not isinstance(obj.get("streichen"), list):
                    logger.warning("Cleanup review: could not parse %r", text[:200])
                    continue
                return obj["streichen"]
        return None

    async def review(self, today: Optional[_dt.date] = None) -> dict:
        """Ask the model for candidates and store them as proposals. Deletes nothing."""
        state = self._state()
        lists = self.store.load_all()
        kept = set(state["kept"])
        entries = [(k, f) for k in memory.KINDS for f in lists.get(k, [])
                   if f not in kept and not f.startswith("Person:")]
        if not entries:
            state["last_run"] = (today or _dt.date.today()).isoformat()
            self._save(state)
            return {"neu": 0, "offen": len(self._live_pending(state))}
        picks = await self._ask(entries)
        if picks is None:
            return {"error": "Die Prüfung hat gerade nicht geklappt."}
        pending = self._live_pending(state)
        have = {p["fact"] for p in pending}
        new = []
        for pick in picks:
            try:
                kind, fact = entries[int(pick.get("nummer")) - 1]
            except (TypeError, ValueError, IndexError, AttributeError):
                continue  # a number that does not exist: never trust it
            if fact in have:
                continue
            have.add(fact)
            new.append({"kind": kind, "fact": fact,
                        "grund": str(pick.get("grund") or "")[:120]})
            if len(pending) + len(new) >= MAX_PROPOSALS:
                break
        state["pending"] = pending + new
        state["last_run"] = (today or _dt.date.today()).isoformat()
        self._save(state)
        logger.info("Cleanup review: %d new proposals, %d open", len(new), len(state["pending"]))
        if new and self.notify:
            try:
                await self.notify(TITLE, self.phone_text(state["pending"]))
            except Exception as e:
                logger.warning("Could not push the cleanup list: %s", e)
        return {"neu": len(new), "offen": len(state["pending"])}

    @staticmethod
    def phone_text(pending: list) -> str:
        lines = ["Diese Einträge würde ich streichen. Gelöscht wird nichts, bis du es mir sagst "
                 "(sag Leyla: „Räum auf“)."]
        for i, p in enumerate(pending, 1):
            tag = {"family": "Familie", "friends": "Freunde", "private": "privat"}.get(
                p.get("kind"), "")
            lines.append(f"{i}. ({tag}) {p['fact'][:160]}: {p.get('grund', '')}")
        return "\n".join(lines)

    # ---- what Metin decides ------------------------------------------------------------
    def proposals(self) -> dict:
        state = self._state()
        live = self._live_pending(state)
        if len(live) != len(state["pending"]):
            state["pending"] = live
            self._save(state)
        if not live:
            return {"offen": 0, "hinweis": "Es gibt nichts zum Aufräumen."}
        return {"offen": len(live), "vorschlaege": [
            {"nummer": i, "liste": p["kind"], "eintrag": p["fact"][:300], "grund": p.get("grund")}
            for i, p in enumerate(live, 1)]}

    def delete(self, numbers: Optional[str]) -> dict:
        state = self._state()
        live = self._live_pending(state)
        picked = parse_numbers(numbers, len(live))
        if not picked:
            return {"error": "Welche Nummern? Die habe ich nicht gefunden."}
        lists = self.store.load_all()
        gone = []
        for i in picked:
            p = live[i]
            if p["fact"] in lists[p["kind"]]:
                lists[p["kind"]].remove(p["fact"])
                gone.append(p["fact"])
        if gone:
            self.store.save_all(lists)
        state["pending"] = [p for i, p in enumerate(live) if i not in picked]
        self._save(state)
        logger.info("Cleanup: Metin deleted %d entries", len(gone))
        return {"gestrichen": len(gone), "offen": len(state["pending"])}

    def keep(self, numbers: Optional[str]) -> dict:
        state = self._state()
        live = self._live_pending(state)
        picked = parse_numbers(numbers, len(live))
        if not picked:
            return {"error": "Welche Nummern? Die habe ich nicht gefunden."}
        state["kept"] += [live[i]["fact"] for i in picked]
        state["pending"] = [p for i, p in enumerate(live) if i not in picked]
        self._save(state)
        return {"behalten": len(picked), "offen": len(state["pending"])}

    async def run(self, args: dict) -> dict:
        action = args.get("action")
        if action == "vorschlaege":
            return self.proposals()
        if action == "pruefen":
            result = await self.review()
            return result if "error" in result else {**result, **self.proposals()}
        if action == "streichen":
            return self.delete(args.get("nummern"))
        if action == "behalten":
            return self.keep(args.get("nummern"))
        return {"error": f"Unbekannte Aktion: {action}"}
