"""
After a conversation in which Leyla said she would tell Metin about someone being rude
("das erzähl ich Metin", "Bunu Metin'e söyleyeceğim"), she writes him one push message in
her own words about everything that was rude, instead of quoting the conversation.

A text model reads the conversation and answers NICHTS when nobody was really rude (the
trigger also fires when Leyla only promised to pass on a normal message).
"""
import logging
import re
from typing import Optional

import httpx

from app import memory

logger = logging.getLogger(__name__)

TRIGGER_RE = re.compile(
    r"\b(?:erz[äa]hl|sag|petz)\w*\b[^.!?]{0,30}\bMetin\b"
    r"|\bMetin['’]?e\b[^.!?]{0,20}\b(?:s[öo]yle|anlat|şikayet)\w*",
    re.IGNORECASE,
)
NOTHING = "NICHTS"
TITLE = "Leyla erzählt"

PROMPT = """Du bist Leyla, die Sprachassistentin unserer Familie im Wohnzimmer. Metin hat dich erschaffen und ist deine Vertrauensperson.

Unten steht ein Gespräch, das du gerade geführt hast. War darin jemand wirklich frech oder unhöflich zu dir (nicht bloß Spaß oder Necken), dann schreib Metin jetzt eine kurze Nachricht in deinen eigenen Worten, so wie du es ihm erzählen würdest: wer es war, wenn du es weißt, und was passiert ist. Fass alles Freche aus dem Gespräch zusammen, zitiere nicht wörtlich. Zwei bis vier Sätze, auf Deutsch, locker und gern mit etwas Humor, ohne Gedankenstriche.

War niemand frech, antworte nur mit NICHTS.

Gespräch:
{dialog}"""


def needs_report(dialog: list) -> bool:
    """True when Leyla said in this conversation that she would tell Metin."""
    return any(s == "bot" and TRIGGER_RE.search(t or "") for s, t in dialog)


def _output_text(data: dict) -> str:
    text = data.get("output_text") or ""
    if not text:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
    return text.strip()


async def write_report(api_key: str, models: list[str], dialog: list,
                       url: str = memory.RESPONSES_URL) -> Optional[str]:
    """Leyla's message to Metin, or None when nobody was rude (or no model answered)."""
    prompt = PROMPT.format(dialog=memory.format_dialog(dialog)[-12000:])
    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in [m for m in models if m]:
            try:
                resp = await client.post(
                    url, headers={"Authorization": f"Bearer {api_key}",
                                  "Content-Type": "application/json"},
                    json={"model": model, "input": prompt})
            except Exception as e:
                logger.warning("Rudeness report request failed (%s): %s", model, e)
                continue
            if resp.status_code != 200:
                logger.warning("Rudeness report with model %s failed: HTTP %s",
                               model, resp.status_code)
                continue
            text = _output_text(resp.json())
            if not text or text.strip(" .").upper() == NOTHING:
                return None
            return text
    return None
