"""Metin's recording becomes the PCM GPT Live takes (24 kHz mono), through ffmpeg."""
import asyncio
import math
import shutil
import struct
import subprocess

import pytest

from app import voice_in
from app.pacing import BYTES_PER_SEC

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg here")


def tone(seconds: float, rate: int = 48000) -> bytes:
    n = int(rate * seconds)
    return struct.pack("<%dh" % n, *(int(9000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)))


def encoded(seconds: float, fmt: str, codec: str) -> bytes:
    done = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", "48000", "-ac", "1",
                           "-i", "pipe:0", "-c:a", codec, "-f", fmt, "pipe:1"],
                          input=tone(seconds), capture_output=True)
    return done.stdout


@needs_ffmpeg
def test_a_webm_recording_becomes_24_khz_pcm_of_the_same_length():
    pcm = asyncio.run(voice_in.to_pcm(encoded(2.0, "webm", "libopus")))
    assert abs(len(pcm) / BYTES_PER_SEC - 2.0) < 0.1 and len(pcm) % 2 == 0
    assert max(abs(x) for x in struct.unpack("<%dh" % (len(pcm) // 2), pcm)) > 4000


@needs_ffmpeg
def test_what_cannot_be_read_or_is_too_short_or_long_is_not_played(monkeypatch):
    assert asyncio.run(voice_in.to_pcm(b"")) == b""
    assert asyncio.run(voice_in.to_pcm(b"this is no sound at all")) == b""
    assert asyncio.run(voice_in.to_pcm(encoded(0.1, "webm", "libopus"))) == b""
    monkeypatch.setattr(voice_in, "MAX_HEAR_S", 1.0)
    assert asyncio.run(voice_in.to_pcm(encoded(2.0, "webm", "libopus"))) == b""


def test_without_ffmpeg_nothing_is_played():
    assert asyncio.run(voice_in.to_pcm(b"abc", ffmpeg="/no/such/ffmpeg")) == b""
