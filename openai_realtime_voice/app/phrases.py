"""Pure helpers for what is said: farewell phrases, greetings and addressing Leyla by name.

No I/O and no state, so everything here is tested without the server (tests/test_live_bridge.py and others
reach it through app.main, which re-exports these names)."""
import random
import re
from typing import Optional

# With the TV on or several people talking, GPT Live may never see the end of a turn and
# stays silent. When someone addresses Leyla by name and she has not reacted after
# NAME_NUDGE_AFTER_S, the bridge tells her to answer.
NAME_RE = re.compile(r"\b(?:leyla|leila)\w*", re.IGNORECASE)
NAME_NUDGE_AFTER_S = 5.0
NAME_NUDGE_COOLDOWN_S = 20.0
NAME_NUDGE = (
    "Interne Notiz, nicht vorlesen: Gerade hat dich jemand mit deinem Namen direkt "
    "angesprochen: „{text}“. Du hast noch nicht reagiert, vermutlich weil nebenbei der "
    "Fernseher läuft oder andere reden. Wenn das eine Frage oder Bitte an dich ist, antworte "
    "jetzt sofort, kurz und lieb, in der Sprache der Person; wenn etwas bedient werden soll, "
    "gib es an deinen Hintergrund weiter."
)


# Farewell phrases (German, Turkish, English). When the user says one of them, the
# bridge ends the session after the assistant's goodbye was played. GPT Live itself
# does not always delegate the end of a conversation to the backend tool.
GOODBYE_PHRASES = (
    "tschüss", "tschüs", "tschuess", "auf wiedersehen", "gute nacht", "ciao",
    "mach's gut", "machs gut",
    "hoşça kal", "hosca kal", "hoşçakal", "güle güle", "gule gule", "görüşürüz",
    "gorusuruz", "görüşmek üzere", "iyi geceler", "allahaısmarladık",
    "allaha ısmarladık", "kendine iyi bak",
    "goodbye", "bye bye", "bye-bye", "byebye", "bay bay", "bay-bay", "baybay",
    "bai bai", "bey bey",
)
# Only the user may end the session with these softer phrases.
USER_ONLY_GOODBYE_PHRASES = ("bis bald", "bis dann", "das war's", "das wars")


def _normalize(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFC", text).lower()
    t = t.replace("\u2019", "'").replace("\u00b4", "'").replace("`", "'")
    return " ".join(t.split())


def contains_goodbye(text: str, from_user: bool = True) -> bool:
    """True if the text contains a farewell phrase."""
    t = _normalize(text)
    phrases = GOODBYE_PHRASES + (USER_ONLY_GOODBYE_PHRASES if from_user else ())
    return any(_normalize(phrase) in t for phrase in phrases)


DEFAULT_GREETING_WORDS = "Hallo, Merhaba, Selamünaleyküm, Hey, Hallöchen"
TURKISH_GREETINGS = ("merhaba", "selam", "günaydın", "iyi akşamlar", "iyi günler")
GREETING_TEMPLATE = (
    "Man hat dich gerade gerufen. Antworte sofort mit einem kurzen, warmen, fröhlichen Satz "
    "mit „{word}“, in der Sprache des Grußworts und jedes Mal etwas anders, zum Beispiel "
    "„{word}, was kann ich für dich tun?“ oder „{word}, buyur, seni dinliyorum!“. Sag bei "
    "der Begrüßung nichts Persönliches, kein Kompliment und nicht, dass es schön ist, die "
    "Stimme zu hören, denn du weißt noch nicht, wer da ist. Frag auch noch nicht danach. Dann hör zu. Redet danach "
    "niemand mit dir und ist nur Fernsehen oder ein Gespräch zwischen anderen zu hören, sag "
    "nichts und beende das Gespräch still."
)


def parse_greeting_words(raw: Optional[str]) -> list[str]:
    """Comma separated greeting words from the add-on option ('' disables the greeting)."""
    if raw is None or raw.strip().lower() == "null":
        raw = DEFAULT_GREETING_WORDS
    return [w.strip() for w in raw.split(",") if w.strip()]


def greeting_instruction(word: str) -> str:
    return GREETING_TEMPLATE.format(word=word)


def pick_greeting(words: list[str], hour: int) -> str:
    """Pick a different greeting each time, with time of day greetings mixed in."""
    pool = list(words)
    if 5 <= hour < 11:
        pool += ["Guten Morgen", "Günaydın"]
    elif 18 <= hour < 23:
        pool += ["Guten Abend", "İyi akşamlar"]
    return random.choice(pool)


def addressed_by_name(snippet: str) -> bool:
    """True when the text starting with Leyla's name talks to her rather than about her:
    the name is followed by a comma, '!' or '?', or the sentence it is in is a question.
    'Leyla, kanal 1' or 'Leyla saat kaç?' yes; 'Senin Leyla peşinde hep.' no."""
    m = NAME_RE.match(snippet)
    if not m:
        return False
    rest = snippet[m.end():]
    if rest.lstrip()[:1] in (",", "!", "?"):
        return True
    sentence = re.split(r"[.!]", rest, maxsplit=1)[0]
    return "?" in sentence[:100]
