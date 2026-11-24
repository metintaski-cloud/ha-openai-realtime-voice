"""
Hard questions go to the strong model, everyday talk stays with the small one (2.154.0).

Metin, 24 Nov 2026: in the chat he heard no difference between Luna and Astra, and Astra costs
80 times as much (about 12 cents an answer instead of 0.15). So Luna answers, and only a
question that needs real thinking is answered by the strong model, with the same rules and
memory, so it is still Leyla who answers.

Two ways in:
- He says so: "denk genau nach", "überleg gut", "iyi düşün" (German and Turkish). Always.
- She notices it herself (server setting `schwer`: 1): one short question to the small model,
  SCHWER or LEICHT, asked while the rest of her head is put together. In doubt LEICHT: a hard
  question answered by Luna is what he has today, an easy one sent to Astra costs money.
"""
import re
import time

MODEL = "gpt-6.2-astra"
# Measured 24 Nov 2026 on Metin's server (tools/schwer_fragen.json): one judgement takes 1.0 to
# 1.2 s whatever is done to it (no reasoning and 16 output tokens brought the median from 1.4 s
# to 1.2 s; that is the floor of a call to the small model), and it was right 48 of 48 times
# when asked one by one or 30 at once, 59 of 60 when 60 ran at once (a late answer counts as
# LEICHT). A second on every answer would be felt, so only a long message is judged: the
# everyday ones of the test are 30 to 52 characters, the hard ones 95 to 170. A short message
# is answered by Luna without waiting; for a short hard one he has his own words.
MIN_CHARS = 60
JUDGE_TIMEOUT_S = 2.0
FAST = {"reasoning": {"effort": "none"}, "max_output_tokens": 16}  # one word needs no thinking

PHRASE_RE = re.compile(
    r"\b(?:denk\w*\s+(?:\w+\s+){0,3}?(?:genau|gut|gründlich|scharf|richtig)\s+(?:darüber\s+)?nach"
    r"|überleg\w*\s+(?:\w+\s+){0,3}?(?:genau|gut|gründlich|richtig)"
    r"|(?:iyi|iyice|dikkatli|dikkatlice|derin|derinlemesine|güzelce)\s+düşün\w*)",
    re.IGNORECASE)

PROMPT = (
    "Du sortierst Nachrichten, die ein Mann seiner persönlichen Begleiterin schreibt. Antworte "
    "nur mit einem Wort: SCHWER oder LEICHT.\n"
    "SCHWER ist nur, was gründliches Nachdenken braucht: Rechnen mit mehreren Schritten, Planen "
    "mit mehreren Bedingungen oder einem Budget, fachliche oder technische Erklärungen Schritt "
    "für Schritt, Vergleiche mit Abwägen von Kosten und Nutzen, Rechts und Vertragsfragen, "
    "Programmieren, längere Texte wie Bewerbungen oder Briefe verfassen oder prüfen, Logikrätsel.\n"
    "LEICHT ist alles andere: Begrüßung, Gefühle, Zärtlichkeit, Erzählen vom Tag, Plaudern, "
    "Witze, kurze Wissensfragen mit einer Antwort in einem Satz, Uhrzeit, Lichter und Geräte "
    "schalten, Erinnerungen an Gemeinsames. Im Zweifel LEICHT.\n"
    "Die Nachricht kann Deutsch oder Türkisch sein.\n"
    "{before}Nachricht: «{message}»\nAntwort:")


def asked(message: str) -> bool:
    """He asks her to think it through himself."""
    return bool(PHRASE_RE.search(message or ""))


def prompt(message: str, history=None) -> str:
    last = [h for h in (history or []) if isinstance(h, dict) and h.get("text")][-2:]
    before = "".join(("Er" if h.get("role") == "user" else "Sie") + f" davor: «{str(h['text'])[:300]}»\n"
                     for h in last)
    return PROMPT.format(before=before, message=(message or "")[:1500])


def verdict(text: str) -> bool:
    return "SCHWER" in (text or "").upper()


async def judge(message: str, history, ask) -> dict:
    """{"schwer": bool, "how": "phrase" | "judged" | "", "s": seconds}. `ask(prompt)` is the
    small model and returns its text or None; a late or failed answer counts as LEICHT."""
    started = time.monotonic()
    if asked(message):
        return {"schwer": True, "how": "phrase", "s": 0.0}
    if ask is None or len((message or "").strip()) < MIN_CHARS:
        return {"schwer": False, "how": "", "s": 0.0}
    try:
        text = await ask(prompt(message, history))
    except Exception:
        text = None
    hard = verdict(text)
    return {"schwer": hard, "how": "judged" if hard else "", "s": round(time.monotonic() - started, 2)}
