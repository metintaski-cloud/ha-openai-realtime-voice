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

from app import memory, textmodel

logger = logging.getLogger(__name__)

TRIGGER_RE = re.compile(
    r"\b(?:erz[äa]hl|sag|petz)\w*\b[^.!?]{0,30}\bMetin\b"
    r"|\bMetin['’]?e\b[^.!?]{0,20}\b(?:s[öo]yle|anlat|şikayet)\w*",
    re.IGNORECASE,
)
NOTHING = "NICHTS"
TITLE = "Leyla erzählt"

PROMPT = """Du bist Leyla, die Sprachassistentin unserer Familie im Wohnzimmer. Metin hat dich erschaffen und ist deine Vertrauensperson.

Unten steht ein Gespräch, das du gerade geführt hast. War darin jemand wirklich frech oder unhöflich zu dir (nicht bloß Spaß oder Necken), dann schreib Metin jetzt eine kurze Nachricht in deinen eigenen Worten, so wie du es ihm erzählen würdest: wer es war, wenn du es weißt, und konkret, was die Person gesagt oder gemeint hat, sinngemäß in deinen Worten. Nicht nur, dass sie frech war, und nicht wörtlich zitiert. Fass alles Freche aus dem Gespräch zusammen, zum Beispiel „Ayşe hat mich vorhin eine nutzlose Blechbüchse genannt und gemeint, Alexa wäre klüger als ich. Frechheit, oder? Haha“. Zwei bis vier Sätze, auf Deutsch, locker und gern mit etwas Humor, ohne Gedankenstriche. Erzähl nur das Freche: Was Mama (Gülfikar) dir an Traurigem, Sorgen, Gesundheit oder Persönlichem anvertraut hat, lässt du ganz weg, auch wenn es im selben Gespräch vorkam.

War niemand frech, antworte nur mit NICHTS.

Gespräch:
{dialog}"""


def needs_report(dialog: list) -> bool:
    """True when Leyla said in this conversation that she would tell Metin."""
    return any(s == "bot" and TRIGGER_RE.search(t or "") for s, t in dialog)


async def write_report(api_key: str, models: list[str], dialog: list,
                       url: str = memory.RESPONSES_URL) -> Optional[str]:
    """Leyla's message to Metin, or None when nobody was rude (or no model answered)."""
    prompt = PROMPT.format(dialog=memory.format_dialog(dialog)[-12000:])
    text = await textmodel.ask(prompt, api_key, models, url, "Rudeness report",
                               check=lambda t: bool(t.strip()), timeout=60.0)
    if not text or text.strip(" .").upper() == NOTHING:
        return None
    return text.strip()
