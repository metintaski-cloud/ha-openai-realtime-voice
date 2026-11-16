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


# GPT Live sometimes says it will do something ("ich mache das Licht an") without handing it
# to its backend (14 Nov 2026). When her words promise an action and no delegation follows
# within PROMISE_NUDGE_AFTER_S, the bridge reminds her once.
PROMISE_RE = re.compile(
    r"\b(?:ich (?:mache|mach|schalte|stelle|starte|kümmere mich)|(?:mache|mach|schalte|stelle) ich"
    r"|wird gemacht|hemen (?:açıyorum|kapatıyorum|yapıyorum|hallediyorum|ayarlıyorum)"
    r"|(?:açıyorum|kapatıyorum|ayarlıyorum)\b)", re.IGNORECASE)
PROMISE_NUDGE_AFTER_S = 4.0
PROMISE_NUDGE = (
    "Interne Notiz, nicht vorlesen: Du hast gerade gesagt „{text}“, es aber nicht an deinen "
    "Hintergrund weitergegeben. Wenn das eine Zusage war, etwas zu bedienen oder "
    "nachzusehen, gib es jetzt sofort weiter, ohne es noch einmal anzukündigen. Sonst "
    "mach einfach weiter."
)

# GPT Live does not always ask who is talking, though the rules say so (14 Nov 2026).
# When the person starts their second turn (or later) and nobody has said a name and Leyla
# has not asked, the bridge reminds her once to ask in the coming answer.
WHO_ASKED_RE = re.compile(
    r"kiminle|kimle konuş|kimler var|kim var|sen kimsin|siz kimsiniz|wer spricht|mit wem|"
    r"wer (?:ist|bist|seid) (?:da|du|ihr)|wer leistet|wer von euch|wer ist denn", re.IGNORECASE)
NAME_SAID_RE = re.compile(
    r"\b(?:ich bin|hier ist|hier spricht|mein name ist|ben|benim adım|adım|ismim)\s+([A-ZÄÖÜÇĞİŞ]\w+)",
    re.IGNORECASE)
WHO_NUDGE = (
    "Interne Notiz, nicht vorlesen: Du weißt noch nicht, wer mit dir spricht, und hast noch "
    "nicht gefragt. Ist das, was die Person gerade sagt, kein kurzer Befehl, dann beantworte "
    "es und frag danach in derselben Antwort nebenbei und mit Charme, wer da ist, in ihrer "
    "Sprache. Sonst frag bei der nächsten passenden Antwort."
)

# Pet words someone says to Leyla: she must ask at once who says it (persona rule), which
# GPT Live may skip. Kosewörter Leyla herself says: at most one per conversation.
COUPLE_WORD_RE = re.compile(r"\b(?:bir ?tanem|aşkım|askim|sevgilim|mein schatz|schatzi)\b",
                            re.IGNORECASE)
COUPLE_NUDGE = (
    "Interne Notiz, nicht vorlesen: Gerade hat jemand ein Paarwort zu dir gesagt („{word}“), "
    "und du weißt nicht sicher, wer es ist. Frag jetzt sofort neugierig und spielerisch, wer "
    "das sagt, noch vor dem Anliegen. Ist es nicht Metin, wehr charmant ab."
)
PET_WORD_RE = re.compile(r"\b(?:canım|canim|tatlım|tatlim|hayatım|hayatim|schatz)\b",
                         re.IGNORECASE)
PET_NUDGE = (
    "Interne Notiz, nicht vorlesen und nicht darauf antworten: Du hast in diesem Gespräch "
    "schon ein Kosewort benutzt. Ab jetzt keins mehr, nimm den Namen, wenn du ihn sicher "
    "weißt, sonst gar keine Anrede."
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
# "das war's" is not one: it is also the answer to "soll ich ihm noch etwas sagen?" and ended
# a talk that went on (15 Nov 2026); a real goodbye after it still ends through Leyla.
USER_ONLY_GOODBYE_PHRASES = ("bis bald", "bis dann", "bis gleich")

# "Leyla, das Gespräch beenden" (16 Nov 2026: she said "bis gleich" and stayed open until the
# idle timeout); also in reversed order as the transcript gave it: "beenden, das Gespräch".
END_TALK_RE = re.compile(
    r"(gespr[äa]ch|unterhaltung)\W+(\w+\W+){0,2}(beenden|beende|beendet|abbrechen|aus\b)"
    r"|(beenden|beende|abbrechen)\W+(\w+\W+){0,2}(gespr[äa]ch|unterhaltung)"
    r"|konuşmay[ıi] (bitir|kapat|sonland[ıi]r)|görüşmeyi (bitir|kapat)",
    re.IGNORECASE)


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
