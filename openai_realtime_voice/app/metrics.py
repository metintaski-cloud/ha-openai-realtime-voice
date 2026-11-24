"""Small persistent timing log (JSON lines) so changes can be compared with numbers.

One line per event in /data/metrics.jsonl, for example how long it took from the connection of
the Voice PE to ready, from the last word of the user to the first reply audio, and how long a
session lasted and why it ended. The file is cut to its newer half when it gets big. Never
raises: measuring must not break a conversation.
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

PATH = os.environ.get("METRICS_PATH", "/data/metrics.jsonl")
MAX_BYTES = 1_000_000


def record(event: str, **fields) -> None:
    try:
        line = json.dumps({"ts": round(time.time(), 1), "event": event,
                           **{k: (round(v, 3) if isinstance(v, float) else v)
                              for k, v in fields.items()}}, ensure_ascii=False)
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if event != "interrupt":  # also in the add on log, which is the only place to read it from
            logger.info("Metrics %s", line)
        if os.path.getsize(PATH) > MAX_BYTES:
            _trim()
    except Exception as e:  # pragma: no cover
        logger.debug("metrics not written: %s", e)


def _trim() -> None:
    with open(PATH, encoding="utf-8") as f:
        lines = f.readlines()
    with open(PATH, "w", encoding="utf-8") as f:
        f.writelines(lines[len(lines) // 2:])


def load(path: str = "") -> list[dict]:
    out = []
    try:
        with open(path or PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def mic_summary(stats: dict | None) -> dict:
    """Median of the window averages of the rms (not the loudest moment) and highest peak of the microphone, while Leyla spoke and while she was quiet."""
    out: dict = {}
    for key in ("speaking", "quiet"):
        rows = (stats or {}).get(key) or []
        if rows:
            rms = sorted(r for r, _ in rows)
            out[f"mic_{key}_rms_avg_median"] = round(rms[len(rms) // 2])
            out[f"mic_{key}_peak_max"] = max(p for _, p in rows)
            out[f"mic_{key}_windows"] = len(rows)
    return out


def wake_stats(entries: list, days: int = 14) -> list:
    """Per day (newest first): talks woken by the wake word and how many of them were false
    wakes (ended with no_speech). Talks Leyla started herself (followup) do not count."""
    by_day: dict = {}
    for e in entries:
        if e.get("event") != "session_end" or e.get("followup") or e.get("app"):
            continue  # a live talk from the app is started by a tap (marked since 2.156.0)
        day = time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))
        d = by_day.setdefault(day, {"tag": day, "geweckt": 0, "fehlstarts": 0})
        d["geweckt"] += 1
        d["fehlstarts"] += e.get("reason") in ("no_speech", "false_wake")
    return [by_day[k] for k in sorted(by_day, reverse=True)[:days]]
