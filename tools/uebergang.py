#!/usr/bin/env python3
"""Measure the hand overs of the clips of one look: does a clip end in the picture the next begins with,
and how much double picture does the blend of the app make.

Fixed rule since 27 Nov 2026 (Metin: "diese Art von prüfen als Regel festhalten. Das müssen wir immer
machen. Es verbessert die Qualität enorm"): run this for a look whenever a clip is new or replaced, and
before a blend, a lead or a cut mark of one of its clips is changed. See docs/KLING_PROMPTS.md,
"Übergänge prüfen".

    python3 tools/uebergang.py <clips folder> <look> <values.json> [--cache DIR]

<values.json> is the object of that look from GET /clips.json of the app ({"clips": [...], "s": {...},
"r": {...}, "k": {...}, "l": {...}, "b": {...}}), so the cut marks, tempi, leads and blends that are
stored count. Needs ffmpeg, ffprobe and numpy. Nothing is changed, it only reads.

What the numbers mean (all on the body crop at 147 x 220, mean difference of the grey values):
  passt    how far the last picture of the clip before is from the first picture of this clip.
           About 1.0 is the floor between two different clips in the same pose. Above 1.6 the poses differ.
  doppelt  the amount of double picture over the hand over, computed like the stage of the app does it
           (the old clip stands on its last picture, the new one runs, CSS ease). "weich" = blend 0.8 s and
           lead 0.25 s, "hart" = blend 0.1 s and lead 0.1 s.
  normal   what this clip changes from one picture to the next in its first half second.
A loop counts as fitting when the middle value of its "passt" is at the floor (one clip before it with a wrong
end does not make the loop wrong; the line names that clip). The other clips are judged against the fitting
loops only.
Reading: a clip whose "passt" is at the floor can come in hard (no double picture, the step at the cut is
not larger than its normal movement). A clip whose "passt" is high must not be set hard: that would jump.
It needs other cut marks, its original, or a new clip; until then it stays soft.
The blend belongs to the clip that comes in, at every tight hand over: a loop that is set hard also comes in
hard after a touch, a talk clip, a dance or a scene. So RAUS of every clip that can run before a loop must be
at the floor before the loops of that look are set hard; a clip whose RAUS is high is the one to repair.
Clips that belong to a chain of their own (sprichtpose between sprichtrein and sprichtraus, the middle of a
dance chain, eifersuechtig) meet no loop on that side; read their line with that in mind.
"""
import argparse
import json
import os
import re
import subprocess

import numpy as np

W, H = 147, 220
N = 36                      # pictures kept of the begin and of the end of a clip (1.5 s)
FLOOR_OK = 1.6              # up to here two pictures count as the same pose
LOOP_RE = re.compile(r"^(freizeit)?gluecklich(extra)?[0-9]*$")
OTHER_DRESS_RE = re.compile(r"umziehen|bettvon|anziehen")   # these end in another outfit


def grab(path: str, start: float, count: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % max(0.0, start), "-i", path, "-vf",
                          "scale=%d:%d,format=gray" % (W, H), "-frames:v", str(count), "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)[:, 10:210, 31:116]


def duration(path: str) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)


def ease(x: float) -> float:
    """CSS 'ease', cubic-bezier(.25, .1, .25, 1)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(30):
        u = (lo + hi) / 2
        if 3 * (1 - u) ** 2 * u * .25 + 3 * (1 - u) * u * u * .25 + u ** 3 < x:
            lo = u
        else:
            hi = u
    u = (lo + hi) / 2
    return 3 * (1 - u) ** 2 * u * .1 + 3 * (1 - u) * u * u + u ** 3


def hand_over(tail, head, lead, fade, rate_a=1.0, rate_b=1.0, first=0.083, off=0.3, fade_out=0.8, dt=1 / 48.0):
    """The stage of the app: the new clip starts `lead` (clip time of the old one) before the end of the old
    clip and shows after `first` s, fading in for `fade` s; the old one loses its place `off` s later and
    fades out. Returns (amount of double picture, step from the last picture seen of the old clip to the
    first seen of the new one)."""
    lead_s = lead / rate_a
    a = lambda t: tail[max(0, len(tail) - 1 + int(round(min(0.0, -lead_s + t) * 24 * rate_a)))]
    b = lambda t: head[min(int(round(max(0.0, t - 0.04) * 24 * rate_b)), len(head) - 1)]
    ghost, t = 0.0, 0.0
    while t < first + max(fade, off + fade_out) + 0.05:
        ab = ease((t - first) / fade)
        aa = 1 - ease((t - first - off) / fade_out)
        ghost += 2 * min(ab, (1 - ab) * aa) * float(np.abs(b(t) - a(t)).mean()) * dt
        t += dt
    return ghost, float(np.abs(b(first) - a(first)).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("look")
    ap.add_argument("values")
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/uebergang"))
    args = ap.parse_args()
    val = json.load(open(args.values, encoding="utf-8"))
    val = val.get(args.look, val)
    marks, rates, curves = val.get("s", {}), val.get("r", {}), val.get("k", {})
    leads, fades = val.get("l", {}), val.get("b", {})
    os.makedirs(args.cache, exist_ok=True)

    def rate(name: str, t: float) -> float:
        for a, b, r in curves.get(name, []):
            if a <= t < b:
                return r
        return rates.get(name, 1.0)

    clips = {}
    for name in sorted(val["clips"]):
        path = os.path.join(args.folder, args.look, name + ".mp4")
        if not os.path.exists(path):
            continue
        dur = duration(path)
        s, e = marks.get(name, [0, 0])
        e = e if e and e < dur else dur - 0.02
        key = os.path.join(args.cache, "%s_%s_%d_%.3f_%.3f.npz" % (args.look, name, int(os.path.getmtime(path)), s, e))
        if os.path.exists(key):
            z = np.load(key)
            head, tail = z["head"], z["tail"]
        else:
            head, tail = grab(path, s, N), grab(path, e - N / 24.0, N)
            np.savez(key, head=head, tail=tail)
        clips[name] = dict(head=head, tail=tail, rb=rate(name, s + 0.1), ra=rate(name, e - 0.1),
                           step=float(np.mean([np.abs(head[i + 1] - head[i]).mean() for i in range(12)])))

    def group(name: str) -> str:
        return "freizeit" if name.startswith("freizeit") else "arbeit"

    def setting(name: str) -> str:
        return "Blende %.2f Einsatz %.2f" % (fades.get(name, 0.8), leads.get(name, 0.25))

    for g in ("arbeit", "freizeit"):
        loops = [n for n in clips if LOOP_RE.match(n) and group(n) == g]
        others = [n for n in clips if not LOOP_RE.match(n) and group(n) == g and not OTHER_DRESS_RE.search(n)]
        if not loops:
            continue
        print("\n== %s, %s: Schleife nach Schleife ==" % (args.look, g))
        good = []   # loops that begin in the pose the others end in; the other clips are judged against these
        for b in loops:
            before = [a for a in loops if a != b] or [b]
            fit = [float(np.abs(clips[a]["tail"][-1] - clips[b]["head"][0]).mean()) for a in before]
            soft = [hand_over(clips[a]["tail"], clips[b]["head"], 0.25, 0.8, clips[a]["ra"], clips[b]["rb"]) for a in before]
            hard = [hand_over(clips[a]["tail"], clips[b]["head"], 0.1, 0.1, clips[a]["ra"], clips[b]["rb"]) for a in before]
            worst = before[int(np.argmax(fit))]
            print("%-22s passt %.1f (max %.1f nach %s) | doppelt weich %.2f hart %.2f | normal %.2f | %s | %s" % (
                b, np.mean(fit), max(fit), worst, np.mean([x[0] for x in soft]), np.mean([x[0] for x in hard]),
                clips[b]["step"] * clips[b]["rb"], setting(b), "kann hart" if np.median(fit) <= FLOOR_OK else "PASST NICHT"))
            if np.median(fit) <= FLOOR_OK:
                good.append(b)
        ref = good or loops
        if len(ref) < len(loops):
            print("(die anderen Clips werden nur an den passenden Schleifen gemessen: %s)" % ", ".join(ref))
        print("\n== %s, %s: andere Clips gegen die Schleifen (REIN = der Clip löst eine Schleife ab, RAUS = eine Schleife kommt danach) ==" % (args.look, g))
        for x in others:
            fin = [float(np.abs(clips[a]["tail"][-1] - clips[x]["head"][0]).mean()) for a in ref]
            fout = [float(np.abs(clips[x]["tail"][-1] - clips[b]["head"][0]).mean()) for b in ref]
            soft = [hand_over(clips[a]["tail"], clips[x]["head"], 0.25, 0.8, clips[a]["ra"], clips[x]["rb"]) for a in ref]
            hard = [hand_over(clips[a]["tail"], clips[x]["head"], 0.1, 0.1, clips[a]["ra"], clips[x]["rb"]) for a in ref]
            print("%-22s REIN passt %.1f (max %.1f) doppelt weich %.2f hart %.2f %s | RAUS passt %.1f (max %.1f) %s | %s" % (
                x, np.mean(fin), max(fin), np.mean([v[0] for v in soft]), np.mean([v[0] for v in hard]),
                "ok" if max(fin) <= FLOOR_OK else "PASST NICHT", np.mean(fout), max(fout),
                "ok" if max(fout) <= FLOOR_OK else "PASST NICHT", setting(x)))


if __name__ == "__main__":
    main()
