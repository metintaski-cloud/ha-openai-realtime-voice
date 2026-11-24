"""The prompt check that must run before Metin clicks Generate (23 Nov 2026, clip 5030 came
out in slow motion because the prompt was slow; Metin: "darf nicht nochmal passieren")."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("kling_check", os.path.join(ROOT, "tools", "kling_check.py"))
kling_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kling_check)


def test_the_prompt_of_clip_5030_is_stopped():
    """The real prompt that cost 350 credits: brake words and one movement every two seconds."""
    text = open(os.path.join(ROOT, "tools", "kling_beispiel_zu_langsam.txt"), encoding="utf-8").read()
    problems, _ = kling_check.check(text)
    assert any("brake words" in p for p in problems)
    assert sum("That is slow" in p for p in problems) == 4, "four segments with a 2 s movement"


def test_a_lively_calm_prompt_passes():
    text = ("A single continuous shot with no cuts. The camera stays on a tripod. "
            "0 to 2 seconds: she shifts her weight onto her other leg, then she shifts back. "
            "2 to 4 seconds: she shifts her weight across again and she tilts her head a little. "
            "4 to 4.5 seconds: she steps back into her stance. "
            "4.5 to 5 seconds: she holds the pose of the last frame, completely still. "
            "No subtitles, no background music.")
    problems, notes = kling_check.check(text)
    assert problems == [], problems
    assert any("hold" in n for n in notes)


def test_negatives_similes_and_own_log_are_caught():
    problems, _ = kling_check.check("She never wears glasses and moves like someone dancing. "
                                    "0 to 1 seconds: she turns.")
    joined = " ".join(problems)
    assert "negative" in joined and "comparison" in joined and "glasses" in joined


def test_one_brake_word_is_only_a_note():
    problems, notes = kling_check.check("0 to 1 seconds: she turns slowly.")
    assert problems == [] and any("one brake word" in n for n in notes)


def test_a_long_hold_at_the_end_is_stopped():
    """24 Nov 2026: 1.5 s of stillness at the end showed in the app as a clip that hangs."""
    text = ("0 to 2 seconds: she shifts her weight onto her other leg, then she shifts back. "
            "2 to 3.5 seconds: she holds the pose of the last frame, completely still.")
    problems, _ = kling_check.check(text)
    assert any("a hold of 1.5 s" in p for p in problems)
