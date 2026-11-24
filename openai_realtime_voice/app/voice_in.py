"""
Metin's voice message as sound Leyla can hear (2.151.0).

Until then a voice message only became text: it was transcribed, the chat model wrote the
answer and GPT Live said that answer without ever hearing him, which sounded read to Metin
(24 Nov 2026: "klingt wie Roboter", "nicht die voice ai von gpt"). Now the recording itself is
played to GPT Live (app/announce_voice.py), in the format it takes: 24 kHz, 16 bit, mono PCM.
The phone records webm or mp4; ffmpeg (in the add on image) turns either into PCM.
"""
import asyncio
import logging

from app.pacing import BYTES_PER_SEC, SAMPLE_RATE

logger = logging.getLogger(__name__)

MAX_HEAR_S = 60.0     # a longer message is not played to her (she would answer too late)
MIN_HEAR_S = 0.4
DECODE_TIMEOUT_S = 8.0


async def to_pcm(audio: bytes, ffmpeg: str = "ffmpeg") -> bytes:
    """The recording as 24 kHz mono PCM, b"" when it cannot be read or is too short or long."""
    if not audio:
        return b""
    try:
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    except Exception as e:
        logger.warning("Voice message not decoded (ffmpeg missing?): %s", e)
        return b""
    try:
        pcm, err = await asyncio.wait_for(proc.communicate(audio), DECODE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("Voice message not decoded: ffmpeg took too long")
        return b""
    if proc.returncode != 0:
        logger.warning("Voice message not decoded: %s", (err or b"")[:200])
        return b""
    pcm = pcm[:len(pcm) - len(pcm) % 2]
    seconds = len(pcm) / BYTES_PER_SEC
    if not MIN_HEAR_S <= seconds <= MAX_HEAR_S:
        logger.info("Voice message of %.1f s is not played to her", seconds)
        return b""
    return pcm
