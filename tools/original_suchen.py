#!/usr/bin/env python3
"""Find the Kling original a clip of the app was made from, and say how the clip differs from it.

Why (27 Nov 2026): three clips of the app did not fit anything at their begin (`kurz/freizeittanz2`,
`kurz/freizeittanz3`, `nacht/gluecklich4`). Metin: "Wo sind die Originale? Wie du weißt, löschten wir ja
nichts. Deswegen müssen sie irgendwo sein. Such und finde sie." All three were in `Leyla Kling Originale`:
the files in the app had been cut by half a second at the begin and their tempo had been baked in (0.70,
0.73 and 1.5 times), so neither their length nor a search at the same time found them.

    python3 tools/original_suchen.py <clip of the app> <folder> [<folder> ...]

How it works: every picture of the clip is kept small (body crop, grey). From every candidate file ONE
picture is taken (one seek, so hundreds of files take a few minutes) and compared with all pictures of
the clip; a distance under 4 is a hit, whatever the offset or the tempo. For each hit the whole original
is then read and mapped: which picture of the original each picture of the clip is. That gives the cut
at the begin and at the end and the baked tempo. State is kept in --state, so a run that is stopped
(the shell on Metin's PC ends a call after 180 s) goes on where it was.

To rebuild: copy the picture stream of the original unchanged (`-c:v copy`), set the stored tempo of the
name to old stored tempo times baked tempo, look at marks and pieces of the name, then measure with
tools/uebergang.py. Needs ffmpeg, ffprobe, numpy. Reads only.
"""
import argparse
import glob
import json
import os
import subprocess
import time

import numpy as np

W, H = 147, 220


def crop(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W)[:, 10:210, 31:116].astype(np.float32)


def all_pictures(path: str) -> np.ndarray:
    return crop(subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=%d:%d,format=gray" % (W, H),
                                "-f", "rawvideo", "-"], capture_output=True).stdout)


def one_picture(path: str, at: float):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % at, "-i", path, "-vf",
                          "scale=%d:%d,format=gray" % (W, H), "-frames:v", "1", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    return crop(raw[:W * H])[0] if len(raw) >= W * H else None


def duration(path: str) -> float:
    try:
        return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                    capture_output=True, text=True).stdout)
    except ValueError:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--state", default="original_suchen.json")
    ap.add_argument("--seconds", type=float, default=150.0, help="stop after this time and keep the state")
    args = ap.parse_args()
    ours = all_pictures(args.clip)
    state = json.load(open(args.state)) if os.path.exists(args.state) else {"done": [], "hits": []}
    files = sorted({f for d in args.folders for f in glob.glob(os.path.join(d, "**", "*.mp4"), recursive=True)}
                   - {os.path.abspath(args.clip), args.clip})
    done, t0 = set(state["done"]), time.time()
    for f in files:
        if f in done:
            continue
        if time.time() - t0 > args.seconds:
            break
        d = duration(f)
        if d >= 4:
            x = one_picture(f, min(6.0, d * 0.5))
            if x is not None:
                dist = np.abs(ours - x[None]).mean(axis=(1, 2))
                if float(dist.min()) < 4.0:
                    state["hits"].append([f, round(float(dist.min()), 2)])
        state["done"].append(f)
    json.dump(state, open(args.state, "w"))
    print("%d of %d files looked at, %d hit(s)" % (len(state["done"]), len(files), len(state["hits"])))
    for f, dist in state["hits"]:
        orig = all_pictures(f)
        idx = [int(np.argmin(np.abs(orig - p[None]).mean(axis=(1, 2)))) for p in ours]
        tempo = (idx[-1] - idx[0]) / max(1, len(ours) - 1)
        print("%s (distance %.2f)" % (f, dist))
        print("  clip: %d pictures, original: %d pictures" % (len(ours), len(orig)))
        print("  the clip begins at picture %d of the original (%.2f s cut at the begin) and ends at picture %d "
              "(%.2f s cut at the end)" % (idx[0], idx[0] / 24.0, idx[-1], (len(orig) - 1 - idx[-1]) / 24.0))
        print("  baked tempo about %.2f (1.00 = unchanged)" % tempo)


if __name__ == "__main__":
    main()
