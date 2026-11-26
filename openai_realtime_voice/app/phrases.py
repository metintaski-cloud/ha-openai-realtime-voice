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
# 26 Nov 2026, 23:03: she asked with her own example sentence ("wer mir da Gesellschaft
# leistet"), Metin answered with his name, and two turns later the bridge made her ask again
# (he asked her why she asked a second time). The question was not in this list ("wer leistet"
# needs the two words side by side), so his short answer did not count.
WHO_ASKED_RE = re.compile(
    r"kiminle|kimle konuş|kimler var|kim var|sen kimsin|siz kimsiniz|kimsin|adın ne|ismin ne|"
    r"wer spricht|wer redet|mit wem|wer (?:ist|bist|seid) (?:da|du|ihr|das)|"
    r"wer (?:da|hier) (?:ist|spricht|redet)|wer leistet|gesellschaft leistet|wer von euch|"
    r"wer ist denn|wie (?:heißt|heisst) du|wie du (?:heißt|heisst)|dein(?:en)? namen?\b",
    re.IGNORECASE)
# 26 Nov 2026, 23:43: he said who he is in a long sentence with a small word between "ich bin" and
# the name, and it did not count (the log, read as yes and no only). Small words may stand between.
_NAME_GAP = (r"(?:(?:der|die|doch|ja|es|wieder|noch|immer|nämlich|halt|dein|deine|euer|eure|schon)"
             r"[\s,]+)*")
NAME_SAID_RE = re.compile(
    r"\b(?:ich bin's|ich bins|ich bin|ich heiße|ich heisse|hier ist|hier spricht|mein name ist|"
    r"mein name lautet|man nennt mich|ben|benim adım|adım|ismim)[\s,]+" + _NAME_GAP +
    r"([A-ZÄÖÜÇĞİŞ]\w+)", re.IGNORECASE)
# the name first: "Selin heiße ich", "weil ich Selin bin"
NAME_SAID_BACK_RE = re.compile(
    r"\b([A-ZÄÖÜÇĞİŞ]\w+)[\s,]+(?:heiße ich|heisse ich|ist mein name|benim adım)\b|"
    r"\bich[\s,]+([A-ZÄÖÜÇĞİŞ]\w+)[\s,]+(?:heiße|heisse|bin)\b", re.IGNORECASE)


def names_said(text: str) -> list:
    """The words people gave as their own name in `text`, in any of the ways above."""
    found = [m.group(1) for m in NAME_SAID_RE.finditer(text)]
    found += [m.group(1) or m.group(2) for m in NAME_SAID_BACK_RE.finditer(text)]
    return found


# A turn that is nothing but a name: these words may stand beside it. No hello ("Hallo Selin"
# greets someone else) and no "ist" or "da" ("ist Selin da" asks for someone else).
_BESIDE_NAME = frozenset("hier ich bin bins s es doch ja der die wieder nochmal burada ben benim adim adm "
                         "ismim mein name heisse heie also na evet genau leyla".split())
_SELF_WORDS = frozenset("hier ich bin bins ben benim burada adim adm ismim name heisse heie".split())


def bare_name(turn_words: list, name_words: set, asked: bool) -> bool:
    """The whole turn of a person is a name and at most small words of introducing oneself
    ("Selin", "Selin hier", "ich bin's, Selin"). Without her question before, one such small
    word must be there: a name alone can also be someone calling that person."""
    if not 0 < len(turn_words) <= 6:
        return False
    is_name = [any(near(w, n) for n in name_words) for w in turn_words]
    rest = [w for w, hit in zip(turn_words, is_name) if not hit]
    if not any(is_name) or any(w not in _BESIDE_NAME for w in rest):
        return False
    return asked or any(w in _SELF_WORDS for w in rest)


# She asked whether she talks to a certain person ("Spreche ich mit Selin?", "Selin, sen misin?")
# and the answer is a yes. The words as memory._words writes them (no ß, no dotless i).
YES_WORDS = frozenset("ja jo jap genau richtig stimmt klar naturlich evet tabii tabi aynen dogru".split())
NO_WORDS = frozenset("nein ne noe hayir hayr yok degil nicht kein keine".split())


def asked_if(told: str, first_name: str) -> bool:
    name = re.escape(first_name)
    return bool(re.search(
        r"(?:bist du|sind sie|spreche ich|sprech ich|rede ich|ist da|ist das)\b[^.?!]{0,14}\b%s\b[^.?!]{0,25}\?|"
        r"\b%s\b[^.?!]{0,25}(?:bist du|sind sie|m[iı]s[iı]n(?:[iı]z)?|mi konuşuyorum)[^.?!]{0,15}\?"
        % (name, name), told, re.IGNORECASE))


def near(a: str, b: str) -> bool:
    """One letter apart (changed, missing or added): a name as the transcript may write it
    ("Mettin", "Medin" for Metin). Only for words of four letters or more."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:] if len(a) < len(b) else a[i + 1:] == b[i + 1:]


# A wrong name (2.181.0). Metin, 26 Nov 2026: his niece spoke too quietly, Leyla understood another
# name of the family, "und ist drauf geritten, obwohl wir es mehrfach gesagt haben". The bridge had
# taken the misheard word as the answer to "who is there" and handed her that person's profile, so
# no correction got through. Two signs take such a name back (main._maybe_name_wrong): the name is
# denied ("nicht X", "X değil"), or the people name someone else ("das ist Y", "nein, Y" said twice).
NAME_NO_RE = re.compile(r"\b(?:nein|nee|nö|nicht|kein|keine|falsch|hayır|hayir|yok|değil|degil|yanlış|yanlis)\b",
                        re.IGNORECASE)
_NAME = r"([A-ZÄÖÜÇĞİŞ][a-zäöüßçğıöşü]{2,})"
NAME_GIVEN_RE = re.compile(  # a naming sentence: once is enough
    r"\b(?i:sie hei(?:ß|ss)t|er hei(?:ß|ss)t|ich hei(?:ß|ss)e|ich bin|hier ist|mein name ist|"
    r"ben|adı|adım|ismi|ismim)\s+(?i:doch |ja |die |der )?" + _NAME)
# German writes every noun with a capital ("Das ist Quatsch", "Nein, Danke"): after these words a
# capital word only counts as a name when the people say it at least twice
NAME_AFTER_NO_RE = re.compile(
    r"\b(?i:nein|nee|hayır|hayir|falsch|yanlış|das ist|sie ist|er ist|bu)\b[\s,.!]+"
    r"(?i:doch |ja |die |der )?" + _NAME)
NOT_A_NAME = {"leyla", "leila", "danke", "bitte", "licht", "lampe", "nein", "doch", "aber", "nicht",
              "hallo", "tamam", "evet", "anne", "mama", "baba", "papa", "abla", "abi", "teyze", "amca",
              "dayı", "hala", "oma", "opa", "das", "die", "der", "sie", "ich", "wir", "eine", "ein"}
NAME_WRONG = (
    "Interne Notiz, nicht vorlesen: Du hast dich im Namen geirrt. Wer gerade mit dir spricht, ist "
    "nicht {old}.{new} Hast du die Person {old} genannt oder so behandelt, entschuldige dich kurz "
    "und herzlich. Benutze für sie den Namen {old} nicht mehr und nichts, was du über {old} weißt. "
    "Verstehst du einen Namen nicht sicher, bitte darum, ihn noch einmal laut und deutlich zu "
    "sagen, und nimm genau den Namen, den man dir sagt, auch wenn er einem bekannten ähnelt."
)


def name_given(text: str, not_these=()) -> str:
    """A name the people gave in `text` for someone who talks: in a naming sentence ("sie heißt",
    "ich bin"), or said at least twice and once right after a no or "das ist". '' when none."""
    skip = NOT_A_NAME | {str(w).casefold() for w in not_these}
    for m in reversed(list(NAME_GIVEN_RE.finditer(text))):
        if m.group(1).casefold() not in skip:
            return m.group(1)
    for m in reversed(list(NAME_AFTER_NO_RE.finditer(text))):
        word = m.group(1)
        if word.casefold() not in skip and len(re.findall(r"\b%s\b" % re.escape(word), text)) >= 2:
            return word
    return ""


# Someone asks what they told her before (16 Nov 2026: "nerem ağrıyor" from a speaker she did not
# know yet; she answered from an old entry and failed). Before an answer she must know who it is.
RECALL_RE = re.compile(
    r"nerem (?:ağrı|acı)|neremin|ne demiştim|ne söylemiştim|ne anlatmıştım|hatırlıyor musun|"
    r"hatırladın mı|unuttun mu|was tut mir weh|wo tut('?s| es) mir weh|was hab(?:e)? ich dir "
    r"(?:erzählt|gesagt)|weißt du noch|erinnerst du dich|hast du (?:dir )?gemerkt|"
    r"was hatte ich gesagt", re.IGNORECASE)
RECALL_NUDGE = (
    "Interne Notiz, nicht vorlesen: Die Person fragt nach etwas, das sie dir erzählt hat, und du "
    "weißt noch nicht sicher, wer spricht. Beantworte es jetzt noch nicht und rate nichts: Frag "
    "zuerst kurz und freundlich, wer da ist, in ihrer Sprache. Sobald du es weißt, bekommst du "
    "deine Erinnerung an diese Person und antwortest dann. Sagt sie es nicht, darfst du "
    "erzählen, was dir ein Unbekannter vorhin gesagt hat, und fragen, ob sie das war.")
WHO_NUDGE = (
    "Interne Notiz, nicht vorlesen: Du weißt noch nicht, wer mit dir spricht, und hast noch "
    "nicht gefragt. Ist das, was die Person gerade sagt, kein kurzer Befehl, dann beantworte "
    "es und frag danach in derselben Antwort nebenbei und mit Charme, wer da ist, in ihrer "
    "Sprache. Sonst frag bei der nächsten passenden Antwort."
)

# The person has said a known name, but not in a way that shows it is their own (26 Nov 2026,
# 23:42: his first words held his name, the bridge did not count it and made her ask openly who
# is there, twice; Metin: "als würde sie richtig sicher gehen wollen"). Then she asks for that name.
WHO_NUDGE_NAMED = (
    "Interne Notiz, nicht vorlesen: Die Person hat den Namen {name} genannt, du weißt aber noch "
    "nicht sicher, ob sie selbst {name} ist. Frag deshalb nicht offen, wer da ist, und bitte nicht "
    "noch einmal um den Namen: Beantworte, was sie sagt, und frag danach in derselben Antwort "
    "kurz und herzlich, ob du mit {name} sprichst, in ihrer Sprache."
)

# She asked who is there and the person went on without a name: after WHO_AGAIN_TURNS more turns
# of theirs the bridge reminds her once to ask again and to let it show that she wants the name
# now (Metin, 24 Nov 2026: with Opus this was only a rule of her character, so it was not sure).
WHO_AGAIN_TURNS = 2
WHO_NUDGE_AGAIN = (
    "Interne Notiz, nicht vorlesen: Du hast schon gefragt, wer mit dir spricht, und noch keinen "
    "Namen bekommen. Beantworte, was die Person gerade sagt, und hak danach in derselben "
    "Antwort noch einmal nach, freundlich und mit einem Augenzwinkern, aber so, dass klar ist: "
    "du möchtest jetzt wirklich wissen, mit wem du sprichst, damit du dich an sie oder ihn "
    "erinnern kannst. In ihrer Sprache, ein Satz, nicht beleidigt. Bei einem kurzen Befehl "
    "erst den Befehl erledigen und dann fragen."
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


# Called again within a minute after a talk ended (2.180.0, Metin, 26 Nov 2026: "soll sie nicht neu
# beginnen mit Hallo, sondern da, wo das letzte Gespräch beendet wurde. Quasi: ah, war noch was?").
_RESUME_HEAD = (
    "Man hat dich gerade wieder gerufen, weniger als eine Minute nachdem euer Gespräch zu Ende "
    "war. Fang nicht neu an: kein Hallo, kein Grußwort, keine Begrüßung und keine Frage, wer da "
    "ist. Knüpf sofort mit einem einzigen kurzen, lockeren Satz an, wie jemand, der sich noch "
    "einmal umdreht, zum Beispiel „Ah, war noch was?“, „Ja? Noch etwas vergessen?“ oder „Efendim, "
    "bir şey mi kaldı?“, jedes Mal etwas anders und in der Sprache von eben. ")
_RESUME_TAIL = (
    "Dann hör zu. Es kann auch jemand anderes sein als eben: Sprich niemanden mit Namen an, "
    "bevor klar ist, wer da ist. Redet danach niemand mit dir und ist nur Fernsehen oder ein "
    "Gespräch zwischen anderen zu hören, sag nichts und beende das Gespräch still.")
RESUME_OPEN = (_RESUME_HEAD +
    "Das Gespräch von eben steht oben: Du weißt noch, worum es ging, und machst dort weiter, "
    "wenn die Person darauf zurückkommt. Wiederhole nichts davon und fass nichts zusammen. "
    + _RESUME_TAIL)
# who was known by name in the talk before goes along (2.182.8). Since 2.182.10 the instruction
# she speaks from says it too: until then its end told her "es kann auch jemand anderes sein,
# sprich niemanden mit Namen an", and her character says a new "Hallo Leyla" makes the person
# unknown, so she asked again in both talks of 23:45 and 23:46 (Metin, 26 Nov 2026: "sie kann
# sich innerhalb dieser 1 Minute meinen Namen nicht merken").
RESUME_WHO = (
    "Interne Notiz, nicht vorlesen und nicht erwähnen: Du sprichst weiter mit {names}, wie eben vor "
    "dem Auflegen. Dass man dich neu gerufen hat, ändert daran nichts: Frag nicht noch einmal, wer "
    "da ist. Erst nach einem Zeichen, dass jemand anderes spricht, gilt wieder, was in WER MIT DIR "
    "SPRICHT steht.")
_RESUME_TAIL_KNOWN = (
    "Dann hör zu. Du sprichst weiter mit {names}, wie eben vor dem Auflegen. Dass man dich neu "
    "gerufen hat, ändert daran nichts: Du weißt, wer da ist, fragst nicht danach und sagst den "
    "Namen, wenn es passt oder wenn man dich fragt, ob du noch weißt, mit wem du sprichst. Erst "
    "nach einem Zeichen, dass jemand anderes spricht, gilt wieder, was in WER MIT DIR SPRICHT "
    "steht. Redet danach niemand mit dir und ist nur Fernsehen oder ein Gespräch zwischen anderen "
    "zu hören, sag nichts und beende das Gespräch still.")
RESUME_OPEN_KNOWN = (_RESUME_HEAD +
    "Das Gespräch von eben steht oben: Du weißt noch, worum es ging, und machst dort weiter, "
    "wenn die Person darauf zurückkommt. Wiederhole nichts davon und fass nichts zusammen. "
    + _RESUME_TAIL_KNOWN)
RESUME_PRIVATE = (_RESUME_HEAD +
    "Worum es eben ging, erwähnst du mit keinem Wort und spielst auch nicht darauf an: Das "
    "Codewort gilt für dieses Gespräch noch nicht, und inzwischen kann jemand ins Zimmer gekommen "
    "sein. Du bist normal herzlich wie zu jedem in der Familie, bis du das Codewort wieder hörst. "
    + _RESUME_TAIL)
RESUME_PRIVATE_KNOWN = (_RESUME_HEAD +
    "Worum es eben ging, erwähnst du mit keinem Wort und spielst auch nicht darauf an: Das "
    "Codewort gilt für dieses Gespräch noch nicht, und inzwischen kann jemand ins Zimmer gekommen "
    "sein. Du bist normal herzlich wie zu jedem in der Familie, bis du das Codewort wieder hörst. "
    + _RESUME_TAIL_KNOWN)


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
