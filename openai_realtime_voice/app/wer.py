"""Who talks to Leyla: the ears of the bridge (2.183.0).

Metin, 27 Nov 2026, after an evening in which she asked again and again for his name: "Ich glaube,
jetzt, wo die Brücke da ist und an Bedeutung gewonnen hat, sollte sie so oder so bessere Ohren
haben." Leyla herself understood his name every time; the bridge, which holds the personal part
of a person back until it is sure who talks and reminds her to ask, read the same words with
lists of wordings (`phrases.NAME_SAID_RE`, a short answer after her question) and missed three
of four ways he said it. Here the small text model reads the talk and says whether the person
has given one of the known names as their own. The lists stay as the way that costs no time; this
is the net behind them, asked once the person's turn is over.

The words of the talk go to the model and nowhere else: nothing of them is logged.
"""
from typing import Awaitable, Callable, Optional

from app import memory, schwer, spott

TIMEOUT_S = 4.0            # a judgement takes 1.0 to 1.2 s (schwer.py, measured 24 Nov 2026)
MAX_CHECKS = 8             # per talk; after that she goes by her own rules and the lists
MAX_CHARS = 3000           # the newest part of the talk
FAST = schwer.FAST         # one word, no thinking

PROMPT = """Unten steht ein Gespräch mit der Sprachassistentin Leyla im Wohnzimmer. Unter "Nutzer" können mehrere Personen stehen. Der Text ist eine Mitschrift von Gesprochenem: Namen können falsch geschrieben sein, und es kann ein Fernseher mitlaufen.

Diese Personen kennt Leyla: {names}

Frage: Hat die Person, die mit Leyla spricht, in diesem Gespräch selbst gesagt oder bestätigt, dass sie eine dieser Personen ist? Das zählt: sich vorstellen, in welchen Worten auch immer; auf Leylas Frage, wer da ist, mit dem Namen antworten; Leylas Frage, ob sie mit dieser Person spricht, bejahen. Das zählt nicht: über die Person reden, sie rufen, grüßen oder nach ihr fragen; Stimme, Sprache oder Thema; ein Name, den nur Leyla gesagt hat. Hat die Person einen Namen später zurückgenommen oder jemand anderes spricht inzwischen, zählt das Letzte.

Antworte mit genau einem der Namen oben, wenn es klar ist, sonst mit NIEMAND. Kein weiteres Wort.

Gespräch:
{dialog}"""


def first_names(profiles) -> dict:
    """{key: first name} of the people she has a profile of; one first name once."""
    out = {}
    for name in profiles:
        first = (str(name).split() or [""])[0]
        if first:
            out.setdefault(spott.key(first), first)
    return out


async def who(ask: Callable[[str], Awaitable[Optional[str]]], dialog: list, profiles) -> Optional[str]:
    """The key of the first name the person gave as their own, or None. `ask(prompt)` gives the
    answer of the text model or None."""
    names = first_names(profiles)
    if not names or not any(s == "user" and str(t).strip() for s, t in dialog):
        return None
    text = await ask(PROMPT.format(names=", ".join(names.values()),
                                   dialog=memory.format_dialog(dialog)[-MAX_CHARS:]))
    answer = spott.key((text or "").strip(" .\n\"'„“"))
    return answer if answer in names else None
