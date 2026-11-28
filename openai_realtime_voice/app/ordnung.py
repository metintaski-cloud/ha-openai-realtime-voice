"""Order in her memory (2.201.0, Metin 28 Nov 2026: "Ich möchte die Kontrolle haben, Sauberkeit und Ordnung",
"dieser zweite KI, der quasi alles speichert ... muss quasi genau perfektioniert sein").

The models that write (the memory update after a talk, the proposals in the chat) get rules in their prompts, but
a prompt is a wish. What must hold is checked here, in code, after the model answered.

Rule 1: a rule about switching devices (which lamps go on or off at which sentence, what "alle Lichter" means)
never enters a memory list as free text. As text it is followed only most of the time, and every rewrite can
change it (on 24 Nov 2026 a summary turned a lamp rule into its opposite). Such rules are fixed commands
(app/befehle.py). An entry that is already in a list is never dropped and never rewritten here: she changes or
deletes nothing by herself, Metin deletes.
"""
import logging
import re

logger = logging.getLogger(__name__)

_DEVICE = re.compile(
    r"lamp\w*|licht\w*|lamba\w*|[ıi][sş][ıi]k\w*|ventilator\w*|vantilat[oö]r\w*|fernseh\w*|\btv\b|televizyon\w*"
    r"|saugrobot\w*|staubsaug\w*|luftreinig\w*|steckdose\w*", re.I)
# "an" and "aus" only count at the end of a clause ("gehen mit aus.", "bleiben an;"), not "geht an den Rhein"
_END = r"\b(?:aus|an)\b(?=\s*(?:[.;,!?]|$|und\b|oder\b))"
_SWITCH = re.compile(
    r"schalte\w*|\w*geschaltet|\b(?:aus|ein|an|ab)zuschalten|\b(?:aus|ein|an|ab)schalt\w*"
    r"|\b(?:geh(?:t|en)|bleib(?:t|en)|mach(?:t|en|e)?)\b[^.;!?]{0,60}?" + _END
    + r"|\bkapat\w*|\bkapan\w*|\ba[çc]ar?\b|\ba[çc][ıi]l\w*|\bs[öo]nd[üu]r\w*|\byak(?:ar|[ıi]l\w*)?\b", re.I)
_MARKER = re.compile(r"\bwenn\b|\bbei[m]?\b|\bimmer\b|\bsagt\b|\bsobald\b|\bjedes ?mal\b|\bgeh[öo]r\w*|\bdenince\b"
                     r"|\bderse\b|[„“”\"']", re.I)


def is_switch_rule(text: str) -> bool:
    """True for a free text rule about switching devices. Profiles ("Person: ...") are never one."""
    t = " ".join(str(text or "").split())
    if not t or t.startswith("Person:"):
        return False
    return bool(_DEVICE.search(t) and _SWITCH.search(t) and _MARKER.search(t))


def keep_switch_rules_out(old: dict, new: dict, kinds) -> tuple[dict, int, int]:
    """After a memory update: new or rewritten switching rules are dropped, and a switching rule that was
    already stored comes back exactly as it was when the model changed or removed it.
    Returns (lists, dropped, put back)."""
    out, dropped, back = dict(new), 0, 0
    for k in kinds:
        before = list(old.get(k, []))
        had = set(before)
        kept = []
        for e in new.get(k, []):
            if is_switch_rule(e) and e not in had:
                dropped += 1
            else:
                kept.append(e)
        for e in before:
            if is_switch_rule(e) and e not in kept:
                kept.append(e)
                back += 1
        out[k] = kept
    if dropped or back:
        logger.info("Order: %d switching rule(s) kept out of the memory lists, %d stored one(s) left as they were",
                    dropped, back)
    return out, dropped, back


_FILLER = re.compile(r"^(?:hallo|hey|hi|merhaba|selam|leyla|leila|bitte|danke|te[sş]ekk[üu]r\w*|ok(?:ay)?|ja|nein|evet"
                     r"|hay[ıi]r|tamam|gut|super|tsch[üu]ss|bye|g[öo]r[üu][sş][üu]r[üu]z|stopp?|lauter|leiser|und|noch|mal"
                     r"|jetzt|[.,!?\s])+$", re.I)
COMMAND_WORDS = 6  # a longer turn may carry something personal next to the command


def only_commands(turns) -> bool:
    """True when a person only gave commands (rule 2, 2.201.0): every turn is short and either
    names a device or is nothing but hello, thanks and the like, and at least one names a device.
    Such a talk is no diary entry; the model is not even asked."""
    turns = [" ".join(str(t or "").split()) for t in turns]
    turns = [t for t in turns if t]
    if not turns or not any(_DEVICE.search(t) for t in turns):
        return False
    return all(len(t.split()) <= COMMAND_WORDS and (_DEVICE.search(t) or _FILLER.match(t)) for t in turns)
