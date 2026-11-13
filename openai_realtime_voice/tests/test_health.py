"""Metin hears about a crash, a lasting OpenAI problem and a used up credit, without a flood."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import health  # noqa: E402


def make(tmp_path, clock):
    sent = []

    async def notify(title, message):
        sent.append((title, message))

    return health.Health(str(tmp_path / "health.json"), notify=notify, clock=clock), sent


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


async def test_first_start_says_nothing(tmp_path):
    h, sent = make(tmp_path, Clock())
    await h.report_start()
    assert sent == []


async def test_clean_shutdown_says_nothing_but_a_kill_does(tmp_path):
    clock = Clock()
    h, sent = make(tmp_path, clock)
    await h.report_start()
    h.mark_clean()
    h2, sent2 = make(tmp_path, clock)
    await h2.report_start()
    assert sent2 == []
    clock.t += 600
    h2.beat()  # running, then killed without mark_clean
    h3, sent3 = make(tmp_path, clock)
    await h3.report_start()
    assert len(sent3) == 1 and "unerwartet" in sent3[0][1]


async def test_openai_alert_after_three_failures_with_cooldown_and_recovery(tmp_path):
    clock = Clock()
    h, sent = make(tmp_path, clock)
    await h.openai_failed("x")
    await h.openai_failed("x")
    assert sent == []
    await h.openai_failed("x")
    assert len(sent) == 1
    await h.openai_failed("x")  # inside the cooldown
    assert len(sent) == 1
    clock.t += health.COOLDOWN_S + 1
    await h.openai_failed("x")
    assert len(sent) == 2
    await h.openai_ok()
    assert len(sent) == 3 and "wieder" in sent[2][1]
    await h.openai_ok()  # nothing more once recovered
    assert len(sent) == 3


async def test_a_success_resets_the_failure_count(tmp_path):
    h, sent = make(tmp_path, Clock())
    await h.openai_failed()
    await h.openai_failed()
    await h.openai_ok()
    await h.openai_failed()
    await h.openai_failed()
    assert sent == []


async def test_quota_message_once_per_cooldown(tmp_path):
    clock = Clock()
    h, sent = make(tmp_path, clock)
    await h.quota_exceeded()
    await h.quota_exceeded()
    assert len(sent) == 1 and "Guthaben" in sent[0][1]
    clock.t += health.QUOTA_COOLDOWN_S + 1
    await h.quota_exceeded()
    assert len(sent) == 2
