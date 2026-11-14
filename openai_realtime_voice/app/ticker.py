"""
The news line of the memory app: the last messages that went to Metin's phone (a message from
Mama through Leyla, Leyla's own reports, Mama's confirmations), shown as a running text left of
the status heart. Mama's confidences never reach a push, so they never reach this file either.
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

PATH = os.environ.get("TICKER_PATH", "/data/ticker.json")
KEEP = 20          # stored items
SHOW_HOURS = 72    # what the app shows
SHOW_ITEMS = 6
MAX_TEXT = 160


def _load(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("Could not read the news line %s: %s", path, e)
        return []


def who(title: str) -> str:
    """'Leyla: Nachricht von Mama' -> 'Mama'; every other push title is Leyla speaking."""
    _, sep, sender = title.partition("Nachricht von ")
    return sender.strip() if sep and sender.strip() else "Leyla"


def plain(text: str) -> str:
    """One line; a Turkish message with its German line '(...)' shows the German one."""
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    if len(lines) > 1 and lines[-1].startswith("(") and lines[-1].endswith(")"):
        lines = [lines[-1][1:-1]]
    line = " ".join(" ".join(lines).split())
    return line if len(line) <= MAX_TEXT else line[:MAX_TEXT - 1].rstrip() + "…"


def add(title: str, text: str, path: str = None, now: float = None) -> None:
    path = path or PATH
    items = _load(path)
    items.append({"ts": int(now or time.time()), "who": who(title), "text": plain(text)})
    items = items[-KEEP:]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning("Could not write the news line: %s", e)


def recent(path: str = None, now: float = None) -> list[str]:
    """Newest first: 'HH:MM Mama: text' (with the day when not today)."""
    path = path or PATH
    now = now or time.time()
    out = []
    today = time.localtime(now)[:3]
    for it in reversed(_load(path)):
        ts = it.get("ts", 0)
        if ts < now - SHOW_HOURS * 3600 or not it.get("text"):
            continue
        t = time.localtime(ts)
        when = time.strftime("%H:%M" if t[:3] == today else "%d.%m. %H:%M", t)
        out.append(f"{when} {it.get('who', 'Leyla')}: {it['text']}")
        if len(out) >= SHOW_ITEMS:
            break
    return out
