"""Against monotony (add on 2.93.0, Metin's wish: Leyla must not sound the same every time).

After every real talk and every chat answer the first sentences of Leyla's turns are kept
(last KEEP, shared by voice and chat). The next talk and the next chat answer get them as a
note: say it differently this time, other opening, other words, other question.
"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

PATH = "/data/leyla_said.json"
KEEP = 15           # sentences remembered
PER_TALK = 3        # at most this many of one talk, so one long talk does not fill the list
MAX_LEN = 140

_SENTENCE_RE = re.compile(r"^(.+?[.!?…])(\s|$)", re.S)


def first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    m = _SENTENCE_RE.match(text)
    s = (m.group(1) if m else text).strip()
    return s[:MAX_LEN]


class Variety:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.environ.get("LEYLA_SAID_PATH", PATH)

    def recent(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as f:
                return list(json.load(f) or [])[-KEEP:]
        except Exception:
            return []

    def add(self, turns: list) -> None:
        """Her turns of one talk (or one chat answer)."""
        new = []
        for t in turns:
            s = first_sentence(t)
            if len(s) >= 8 and s not in new:
                new.append(s)
            if len(new) >= PER_TALK:
                break
        if not new:
            return
        kept = [s for s in self.recent() if s not in new] + new
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(kept[-KEEP:], f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning("Could not keep what Leyla said: %s", e)

    def note(self) -> str:
        said = self.recent()
        if not said:
            return ""
        lines = "\n".join(f"• {s}" for s in said)
        return ("\n\nSO HAST DU ZULETZT ANGEFANGEN (nicht wiederholen)\n"
                "• Diese Sätze hast du in den letzten Gesprächen schon gesagt. Sag es diesmal "
                "anders: anderer Einstieg, andere Worte, eine andere Frage, ein anderer Gedanke. "
                "Sei überraschend und lebendig, nie gleich wie beim letzten Mal.\n" + lines)
