"""
Notes to GPT Live in pieces it accepts.

GPT Live rejects a note (session.commentary.append) of more than 500 tokens: "Context append
text must not exceed 500 tokens." Found on 24 Nov 2026 in the add on log, which reaches back
to 17 Nov: every note after the code word was rejected (6 of 6: Metin's private list, their
closeness, her mood), and so were 20 notes with her diary and one with a person's personal
part, in 77 talks. Nothing told the bridge, the error was only logged, so in a spoken talk
Leyla never had what the code word should hand her.

So a long note is cut at line ends (a long line at sentence ends) into pieces of at most
NOTE_MAX_CHARS, each later piece under a line that says it continues the note. The measure is
characters, because there is no tokenizer for GPT Live here: a note of about 1490 German
characters passed, so 1000 leaves room for Turkish words and names. Should a piece still be
rejected, `Sent` remembers what went out under which event id and hands back two halves.
"""
import re
from collections import OrderedDict

NOTE_MAX_CHARS = 1000
NOTE_MIN_CHARS = 200   # a rejected piece this short is not halved again (it was not the size)
CONTINUES = "Interne Notiz, nicht vorlesen und nicht erwähnen (Fortsetzung, Teil {i} von {n}):\n"
MORE = "\n(Die Notiz geht gleich weiter.)"
_ROOM = NOTE_MAX_CHARS - len(CONTINUES) - len(MORE) - 4
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")


def _units(text: str, room: int) -> list:
    """Lines; a line longer than the room as sentences; a sentence longer than it as words."""
    out = []
    for line in text.split("\n"):
        if len(line) <= room:
            out.append((line, "\n"))
            continue
        parts = []
        for sentence in _SENTENCE_END.split(line):
            if len(sentence) <= room:
                parts.append(sentence)
                continue
            cur = ""
            for word in sentence.split(" "):
                while len(word) > room:  # one endless word: cut it hard
                    if cur:
                        parts.append(cur)
                        cur = ""
                    parts.append(word[:room])
                    word = word[room:]
                if cur and len(cur) + 1 + len(word) > room:
                    parts.append(cur)
                    cur = word
                else:
                    cur = (cur + " " + word) if cur else word
            if cur:
                parts.append(cur)
        out += [(p, " ") for p in parts[:-1]] + [(parts[-1], "\n")]
    return out


def pieces(text: str, max_chars: int = NOTE_MAX_CHARS) -> list:
    """The note as it goes out: itself when short, else its pieces in order."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text] if text else []
    room = max_chars - len(CONTINUES) - len(MORE) - 4
    bodies, cur = [], ""
    for unit, sep in _units(text, room):
        if cur and len(cur) + len(unit) > room:
            bodies.append(cur.rstrip())
            cur = ""
        cur += unit + sep
    if cur.strip():
        bodies.append(cur.rstrip())
    n = len(bodies)
    return [(CONTINUES.format(i=i + 1, n=n) if i else "") + body + (MORE if i < n - 1 else "")
            for i, body in enumerate(bodies)]


class Sent:
    """What went out under which event id, for a piece GPT Live rejects as too long."""

    def __init__(self, keep: int = 60):
        self.keep = keep
        self.items: OrderedDict = OrderedDict()

    def add(self, event_id: str, prefix: str, content: str) -> None:
        self.items[event_id] = (prefix, content)
        while len(self.items) > self.keep:
            self.items.popitem(last=False)

    def halves(self, event: dict) -> tuple:
        """(prefix, [two smaller pieces]) for an error event about a too long note of ours,
        else ("", [])."""
        err = event.get("error", event) if isinstance(event, dict) else {}
        if not isinstance(err, dict) or "exceed" not in str(err.get("message", "")):
            return "", []
        prefix, content = self.items.pop(str(err.get("client_event_id") or ""), ("", ""))
        if len(content) < NOTE_MIN_CHARS:
            return prefix, []
        return prefix, pieces(content, max(NOTE_MIN_CHARS, len(content) // 2 + len(CONTINUES) + len(MORE) + 4))
