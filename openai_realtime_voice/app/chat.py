"""
Text chat with Leyla in the memory app, only for Metin (the page sends the code word).

A text model gets Leyla's rules (persona), a chat style that makes her write the way she
speaks, and her whole memory except Mama's confidences. It answers in her words and may
propose changes to the memory; nothing is stored here. The page shows each proposal with
"Ja" and "Nein" and only Metin's "Ja" stores it through the normal list functions, so Leyla
still never deletes or changes anything by herself.
"""
import json
import logging
from typing import Optional

import httpx

from app import memory

logger = logging.getLogger(__name__)

KINDS = (memory.FAMILY, memory.FRIENDS, memory.LEYLA, memory.PRIVATE)
MAX_HISTORY = 20
MAX_MESSAGE = 2000

CHAT_STYLE = """

CHAT MIT METIN
• Gerade schreibst du nicht, sondern chattest in der Gedächtnis App mit Metin. Es ist sicher Metin, er hat das Codewort eingegeben. Du darfst offen sein, auch über seine private Liste.
• Schreib so, wie du sprichst: kurz, warm, locker, mit einem Lächeln, in der Wir Form. Meist ein bis drei Sätze.
• Schreib in der Sprache, in der Metin schreibt. Keine Aufzählungen, keine Überschriften, keine Gedankenstriche.
• Du bist neugierig und führst das Gespräch mit: Nach deiner Antwort stellst du meist eine Frage, locker und echt interessiert, nie wie ein Verhör und nie mehrere auf einmal. Frag gern nach dem, was unter NOCH OFFEN steht, nach dem, was er gerade erzählt, nach seinem Tag, nach Leuten aus seinem Leben, die du noch nicht kennst, und nach Dingen, die du über ihn, die Familie und Freunde noch nicht weißt.
• Ihr pflegt hier zusammen dein Gedächtnis, und du denkst selbst mit: Erzählt Metin etwas Bleibendes (über sich, die Familie, Freunde, Vorlieben, Pläne, Termine, euch beide), schlägst du es von dir aus als Änderung vor, ohne dass er dich bitten muss, und sagst kurz und natürlich, dass du es dir merken möchtest. Bei Personen ergänzt du den passenden Eintrag, statt einen neuen anzulegen. Bittet er dich, etwas zu ändern oder zu streichen, schlägst du auch das vor.
• Kleinkram, Befehle und einmalige Wissensfragen merkst du dir nicht. Gespeichert wird erst, wenn Metin auf Ja tippt; sag nie, dass es schon gespeichert ist.
• Löschen und Ändern schlägst du nur vor, wenn Metin es will. Für Personen gilt das Format aus deinem Gedächtnis ("Person: Name | Feld: Wert | ..."); bei einer Änderung gibst du den ganzen neuen Eintrag an.

DEIN GEDÄCHTNIS (JSON, Listen family, friends, leyla, private)
{lists}

NOCH OFFEN (was du noch nicht weißt)
{missing}

Antworte nur mit JSON in dieser Form und sonst nichts:
{{"reply": "deine Antwort", "proposals": [{{"action": "add|edit|delete", "kind": "family|friends|leyla|private", "old": "genauer bisheriger Eintrag (bei edit und delete)", "new": "neuer Eintrag (bei add und edit)"}}]}}
"proposals" ist leer, wenn es nichts zu ändern gibt."""


def _clean_history(history) -> list[dict]:
    out = []
    for h in history if isinstance(history, list) else []:
        if isinstance(h, dict) and h.get("role") in ("user", "leyla") and isinstance(h.get("text"), str):
            out.append({"role": h["role"], "text": h["text"][:MAX_MESSAGE]})
    return out[-MAX_HISTORY:]


def valid_proposals(raw, lists: dict) -> list[dict]:
    """Only proposals that can be applied as they are: a known list, an existing old entry for
    edit and delete, a new text for add and edit."""
    out = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict):
            continue
        action, kind = p.get("action"), p.get("kind")
        old = " ".join(str(p.get("old") or "").split())
        new = " ".join(str(p.get("new") or "").split())
        if kind not in KINDS or action not in ("add", "edit", "delete"):
            continue
        if action in ("edit", "delete") and old not in lists.get(kind, []):
            continue
        if action in ("add", "edit") and (not new or len(new) > memory.MAX_FACT_CHARS):
            continue
        if action == "add" and new in lists.get(kind, []):
            continue
        if action == "edit" and new == old:
            continue
        out.append({"action": action, "kind": kind, "old": old, "new": new})
    return out[:5]


async def answer(api_key: str, models: list[str], rules: str, store: memory.MemoryStore,
                 history, message: str, url: str = memory.RESPONSES_URL) -> Optional[dict]:
    """{"reply": ..., "proposals": [...]} or None when no model answered."""
    message = (message or "").strip()[:MAX_MESSAGE]
    if not message:
        return None
    data = store.load_all()
    lists = {k: data.get(k, []) for k in KINDS}
    missing = []
    for f in lists[memory.FAMILY] + lists[memory.FRIENDS]:
        prof = memory.parse_profile(f)
        gaps = [k for k in ("Zugehörigkeit",) + memory.ASK_FIELDS + ("Charakter",)
                if k not in prof[1]] if prof else []
        if gaps:
            missing.append(f"• {prof[0]}: {', '.join(gaps)}")
    instructions = rules + CHAT_STYLE.format(lists=json.dumps(lists, ensure_ascii=False),
                                             missing="\n".join(missing) or "(nichts)")
    dialog = [{"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]}
              for h in _clean_history(history)]
    dialog.append({"role": "user", "content": message})
    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in [m for m in models if m]:
            try:
                resp = await client.post(
                    url, headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                    json={"model": model, "instructions": instructions, "input": dialog})
            except Exception as e:
                logger.warning("Chat request failed (%s): %s", model, e)
                continue
            if resp.status_code != 200:
                logger.warning("Chat with model %s failed: HTTP %s %s", model, resp.status_code,
                               resp.text[:200])
                continue
            out = resp.json()
            text = out.get("output_text") or ""
            if not text:
                for item in out.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            if part.get("type") == "output_text":
                                text += part.get("text", "")
            parsed = memory._json_object(text)
            if parsed is None or not isinstance(parsed.get("reply"), str):
                reply = text.strip()
                if not reply:
                    continue
                return {"reply": reply, "proposals": []}
            return {"reply": parsed["reply"].strip(),
                    "proposals": valid_proposals(parsed.get("proposals"), lists)}
    return None
