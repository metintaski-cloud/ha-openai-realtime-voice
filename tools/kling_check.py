#!/usr/bin/env python3
"""Check a Kling prompt before anyone clicks Generate.

Why this exists: on 23 Nov 2026 a 4K loop (clip 5030, 350 credits) came out in slow
motion. Kling had followed the prompt; the prompt itself was slow. It planned one weight
shift every two seconds and carried a brake word in almost every sentence, although our
own log already warned about exactly that. Metin: "darf nicht nochmal passieren".

Usage:  python3 tools/kling_check.py prompt.txt      (or pipe the prompt in)
Exit code 1 means: do not hand this prompt over yet.

The rules come from docs/KLING_PROMPTS.md (professional Kling 4.0 knowledge of 23 Nov 2026
and our own experience log). The script only finds what can be found mechanically; it
does not replace reading the prompt.
"""
import re
import sys

# Words that make Kling slow the movement down. One of them is fine when Metin wants one
# single movement slow; a prompt full of them is slow motion.
BRAKES = ("slowly", "slow", "gently", "gentle", "softly", "soft", "smoothly", "smooth",
          "calm", "calmly", "unhurried", "gradual", "gradually", "subtle", "subtly",
          "delicate", "delicately", "lazily", "leisurely", "languid")
MAX_BRAKES = 1

# The stillness at the end. The official Kling examples reserve the last half second; from
# 23 to 24 Nov 2026 our prompts asked for 1.5 s, and the clips stood frozen that long before
# the app handed over (measured on schwarz/freizeitbrust: no movement from 8.5 s to 10 s).
MAX_HOLD_S = 0.75

# The official guide: prefer positive descriptions; only these two are truly needed.
ALLOWED_NEGATIVES = ("no subtitles", "no background music", "no cuts", "no music")
NEGATIVE = re.compile(r"\b(no|never|without|don't|do not|not)\b", re.I)

# Abstract words a camera cannot see, and comparisons instead of visible action.
ABSTRACT = ("cinematic", "premium", "vintage", "elegant look", "beautiful", "stunning",
            "epic", "masterpiece", "atmospheric", "high quality", "8k")
SIMILE = re.compile(r"\b(like a|like an|like someone|as if|as though)\b", re.I)

# Things our own log says go wrong.
OWN_LOG = (
    (re.compile(r"\bglasses\b", re.I), "the word 'glasses' can make Kling add glasses (22.11.)"),
    (re.compile(r"\b(someone|somebody|another person|a hand strok)", re.I),
     "naming another person or a stroking hand makes Kling paint one (21.11.)"),
    (re.compile(r"\bbites? her (lower )?lip\b", re.I), "Kling 4.0 does not deliver a lip bite (22.11.)"),
)

SEGMENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)\s*(?:s\b|sec|seconds)", re.I)
# A movement she starts herself: "she shifts", "she turns" ... What her hair or dress does
# afterwards is a consequence and does not count.
ACTION = re.compile(r"\bshe\s+(?!is\b|stays\b|keeps\b|holds\b|remains\b|stands\b)([a-z]+s)\b", re.I)
MAX_SECONDS_PER_ACTION = 1.5
HOLD = re.compile(r"\b(holds|hold|still|settles|motionless)\b", re.I)


def check(text: str) -> tuple:
    """Return (problems, notes). Problems block the hand-over, notes are for the eye."""
    problems, notes = [], []
    low = text.lower()

    brakes = [w for w in re.findall(r"[a-z']+", low) if w in BRAKES]
    if len(brakes) > MAX_BRAKES:
        problems.append(f"{len(brakes)} brake words ({', '.join(sorted(set(brakes)))}): "
                        "this reads as slow motion. 'Calm' means small movements at normal "
                        "speed, not big movements at half speed.")
    elif brakes:
        notes.append(f"one brake word: {brakes[0]} (fine if exactly this movement should be slow)")

    cleaned = low
    for ok in ALLOWED_NEGATIVES:
        cleaned = cleaned.replace(ok, "")
    negs = NEGATIVE.findall(cleaned)
    if negs:
        problems.append(f"{len(negs)} negative instruction(s) ({', '.join(sorted(set(n.lower() for n in negs)))}): "
                        "say what should be visible instead. Allowed are only: "
                        + ", ".join(ALLOWED_NEGATIVES) + ".")

    for w in ABSTRACT:
        if w in low:
            problems.append(f"abstract word '{w}': describe what a camera sees instead.")
    if SIMILE.search(text):
        problems.append("a comparison ('like ...', 'as if ...') instead of visible action.")
    for rx, why in OWN_LOG:
        if rx.search(text):
            problems.append("own log: " + why)

    segs = [(float(a), float(b), m_end) for a, b, m_end in
            ((m.group(1), m.group(2), m.end()) for m in SEGMENT.finditer(text))]
    if not segs:
        notes.append("no time segments found: the model decides order and timing itself.")
    for i, (a, b, end) in enumerate(segs):
        body = text[end:segs[i + 1][2] if i + 1 < len(segs) else len(text)]
        body = body.split("No subtitles")[0]
        length = b - a
        actions = len(ACTION.findall(body))
        if HOLD.search(body) and actions == 0:
            if length > MAX_HOLD_S:
                problems.append(f"{a:g} to {b:g} s: a hold of {length:g} s. In the app that is a frozen "
                                f"picture before the hand over (Metin, 24.11.: 'hängt am Ende sehr "
                                f"auffallend'); the official examples keep the last half second still. "
                                f"At most {MAX_HOLD_S:g} s.")
            else:
                notes.append(f"{a:g} to {b:g} s: hold ({length:g} s)")
            continue
        if actions == 0:
            notes.append(f"{a:g} to {b:g} s: no movement of her own found")
            continue
        per = length / actions
        line = f"{a:g} to {b:g} s: {actions} movement(s) in {length:g} s = one every {per:.1f} s"
        if per > MAX_SECONDS_PER_ACTION:
            problems.append(line + ". That is slow. A natural weight shift or step takes "
                            "about one second; count more movements or shorten the segment.")
        else:
            notes.append(line)
    if segs and not HOLD.search(text[segs[-1][2]:]):
        notes.append("the last segment names no hold: the official examples end on stillness.")
    return problems, notes


def main() -> int:
    text = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    problems, notes = check(text)
    for n in notes:
        print("  ok   ", n)
    for p in problems:
        print("  STOP ", p)
    print("\nNicht übergeben, erst beheben." if problems else "\nMechanisch in Ordnung. Jetzt noch selbst lesen.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
