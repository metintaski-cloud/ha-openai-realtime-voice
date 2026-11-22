"""Her real movement speed per clip, measured instead of judged by feel (2.137.0, Metin)."""
import asyncio
import os
import shutil

import pytest

from app import motion


def test_cadence_finds_the_rhythm_of_the_movement():
    """Counting peaks was too coarse for a dance (2.137.2), this lays the signal over
    itself like a tempo detector on music."""
    import math
    for hz in (0.5, 0.8, 1.0, 1.5, 2.0):
        sig = [1 + math.sin(2 * math.pi * hz * i / 12) for i in range(120)]
        found, conf = motion.cadence(sig, 12.0)
        assert abs(found - hz) <= hz * 0.12, f"{hz} read as {found}"
        assert conf > 0.8
    assert motion.cadence([5.0] * 120, 12.0) == (0.0, 0.0), "a still clip has no cadence"
    assert motion.cadence([1.0, 2.0], 12.0) == (0.0, 0.0), "too short to say"


def test_cadence_is_not_fooled_by_the_double_shift():
    """Two steps fit the shift as well as one, the shorter one is the real cadence."""
    import math
    sig = [1 + math.sin(2 * math.pi * 2.0 * i / 12) for i in range(120)]
    assert motion.cadence(sig, 12.0)[0] >= 1.8


def test_factors_ignore_an_unclear_cadence():
    items = {"a/b": {"beat": 1.0, "conf": 0.9}, "a/b2": {"beat": 1.0, "conf": 0.9},
             "a/b3": {"beat": 0.5, "conf": 0.9}, "a/b4": {"beat": 0.4, "conf": 0.1}}
    out = motion.factors(items)
    assert out["a/b3"] == 1.6 and "a/b4" not in out


def test_factors_bring_a_group_to_one_cadence():
    items = {"nacht/tanz": {"beat": 2.0}, "nacht/tanz2": {"beat": 2.0},
             "nacht/tanz3": {"beat": 1.0}, "nacht/tanz4": {"beat": 8.0},
             "nacht/kuss": {"beat": 1.0}, "nacht/kuss2": {"beat": 3.0}}
    items = {k: dict(v, conf=0.9) for k, v in items.items()}
    out = motion.factors(items)
    assert out["nacht/tanz3"] == 1.6, "half the cadence of the group, capped at 1.6"
    assert out["nacht/tanz4"] == 0.6, "far too fast, capped at 0.6"
    assert "nacht/tanz" not in out and "nacht/tanz2" not in out, "they are the cadence"
    assert "nacht/kuss" not in out, "two clips cannot say which one is the odd one"


def test_factors_leave_a_still_clip_alone():
    items = {"a/b": {"beat": 0, "conf": 0}, "a/b2": {"beat": 0, "conf": 0},
             "a/b3": {"beat": 2, "conf": 0.9}}
    assert motion.factors(items) == {}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg only in the addon image")
def test_measure_reads_a_real_clip(tmp_path):
    path = str(tmp_path / "x.mp4")
    os.system(f"ffmpeg -v error -f lavfi -i testsrc=size=320x480:rate=24:duration=3 "
              f"-pix_fmt yuv420p {path}")
    m = asyncio.run(motion.measure(path))
    assert 2.5 <= m["dur"] <= 3.2 and m["rate"] > 0


def test_runner_skips_what_it_already_knows(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    calls = []

    async def fake(path):
        calls.append(path)
        return {"dur": 5.0, "rate": 10.0, "beat": 2.0, "conf": 0.9}

    r = motion.Runner(lambda: {"nacht/a": str(src)}, lambda n, f: None,
                      cache=str(tmp_path / "m.json"))
    r_measure, motion.measure = motion.measure, fake  # noqa
    try:
        asyncio.run(r.run())
        asyncio.run(r.run())
    finally:
        motion.measure = r_measure
    assert len(calls) == 1, "the second run has nothing new to measure"
    assert r.items["nacht/a"]["beat"] == 2.0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg only in the addon image")
def test_measure_sees_an_uneven_clip(tmp_path):
    """A clip that moves a lot in one half and little in the other gets a high drift."""
    even, uneven = str(tmp_path / "even.mp4"), str(tmp_path / "uneven.mp4")
    os.system(f"ffmpeg -v error -f lavfi -i testsrc=size=240x320:rate=24:duration=4 "
              f"-pix_fmt yuv420p {even}")
    os.system(f"ffmpeg -v error -f lavfi -i testsrc=size=240x320:rate=24:duration=2 "
              f"-f lavfi -i color=c=gray:size=240x320:rate=24:duration=2 "
              f"-filter_complex '[0:v][1:v]concat=n=2:v=1' -pix_fmt yuv420p {uneven}")
    a = asyncio.run(motion.measure(even))
    b = asyncio.run(motion.measure(uneven))
    assert b["drift"] > a["drift"] * 3
