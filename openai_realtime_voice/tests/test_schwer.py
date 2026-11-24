"""Hard questions for the strong model: his own words always count, in German and Turkish."""
import asyncio

import pytest

from app import schwer


@pytest.mark.parametrize("text", [
    "Denk genau nach: wie viel bleibt mir im Monat übrig?",
    "denk bitte mal gut nach, was das Beste wäre",
    "Denk da bitte gründlich darüber nach",
    "Überleg dir das genau, bevor du antwortest",
    "überleg gut",
    "İyi düşün, hangisi daha ucuz?",
    "Bunu dikkatli düşün lütfen",
    "iyice düşünüp söyle",
])
def test_his_own_words_send_it_to_the_strong_model(text):
    assert schwer.asked(text)


@pytest.mark.parametrize("text", [
    "Guten Morgen meine Süße",
    "Ich denke gerade an dich",
    "Ich habe gut geschlafen und denke nach",
    "Seni düşünüyorum",
    "Mach bitte das Licht aus",
    "",
])
def test_everyday_words_do_not(text):
    assert not schwer.asked(text)


def test_the_phrase_needs_no_model_and_a_short_message_is_never_judged():
    calls = []

    async def ask(prompt):
        calls.append(prompt)
        return "SCHWER"
    assert asyncio.run(schwer.judge("Denk genau nach, was kostet das?", [], ask)) == {
        "schwer": True, "how": "phrase", "s": 0.0}
    assert asyncio.run(schwer.judge("Hallo du", [], ask))["schwer"] is False and not calls


def test_the_small_model_judges_and_in_doubt_it_is_easy():
    async def hard(prompt):
        assert "«Wie verteile ich fünf Leute auf drei Schichten mit Urlaub?»" in prompt
        assert "Er davor: «Ich brauche Hilfe»" in prompt
        return " schwer\n"

    async def nothing(prompt):
        return None

    async def broken(prompt):
        raise RuntimeError("down")
    history = [{"role": "user", "text": "Ich brauche Hilfe"}]
    message = "Wie verteile ich fünf Leute auf drei Schichten mit Urlaub?"
    out = asyncio.run(schwer.judge(message, history, hard))
    assert out["schwer"] and out["how"] == "judged"
    for ask in (nothing, broken, None):
        assert asyncio.run(schwer.judge(message, history, ask))["schwer"] is False


def _bridge(settings, spend=0.0, monkeypatch=None):
    import types
    from app import main
    b = types.SimpleNamespace(recall=types.SimpleNamespace(settings=settings), chat_model="",
                              chat_budget=40.0, memory_model="gpt-6-luna", backend_model="gpt-6-luna",
                              openai_api_key="k")
    b._hard_model = lambda: main.LiveVoiceBridge._hard_model(b)
    monkeypatch.setattr(main.chat, "month_spend", lambda: spend)
    return main, b


def test_a_hard_question_takes_the_strong_model_while_the_budget_lasts(monkeypatch):
    main, b = _bridge({"schwer_model": "gpt-6.2-astra", "budget": 50}, monkeypatch=monkeypatch)
    models = main.LiveVoiceBridge._chat_models
    assert models(b) == ["gpt-6-luna"]                               # everyday: the small one
    assert models(b, hard=True) == ["gpt-6.2-astra", "gpt-6-luna"]   # hard: strong first, small as net
    assert models(b, strong=False, hard=True) == ["gpt-6-luna"]      # a touch never
    main, b = _bridge({"schwer_model": "gpt-6.2-astra", "budget": 50}, spend=50.0, monkeypatch=monkeypatch)
    assert main.LiveVoiceBridge._chat_models(b, hard=True) == ["gpt-6-luna"]   # budget used up
    main, b = _bridge({"schwer_model": ""}, monkeypatch=monkeypatch)
    assert main.LiveVoiceBridge._chat_models(b, hard=True) == ["gpt-6-luna"]   # switched off


def test_without_the_setting_only_his_own_words_count(monkeypatch):
    main, b = _bridge({"schwer_model": "gpt-6.2-astra", "schwer": 0}, monkeypatch=monkeypatch)
    asked = []

    async def ask(prompt, *a, **k):
        asked.append(prompt)
        return "SCHWER"
    monkeypatch.setattr(main.textmodel, "ask", ask)
    hard = lambda text, **k: asyncio.run(main.LiveVoiceBridge._hard(b, text, [], **k))
    long_question = "Wie verteile ich fünf Leute auf drei Schichten, wenn zwei im Urlaub sind?"
    assert hard(long_question)["schwer"] is False and not asked
    assert hard("Denk genau nach: " + long_question)["how"] == "phrase" and not asked
    b.recall.settings["schwer"] = 1
    assert hard(long_question)["how"] == "judged" and len(asked) == 1
    b.recall.settings["schwer_model"] = ""
    assert hard("Denk genau nach: " + long_question)["schwer"] is False


def test_a_day_limit_keeps_the_strong_model_from_getting_too_much(monkeypatch, tmp_path):
    main, b = _bridge({"schwer_model": "gpt-6.2-astra", "schwer": 0, "schwer_tag": 1.5}, monkeypatch=monkeypatch)
    monkeypatch.setattr(main.chat, "SPEND_PATH", str(tmp_path / "spend.json"))
    hard = lambda text: asyncio.run(main.LiveVoiceBridge._hard(b, text, []))
    assert hard("Denk genau nach, was ist günstiger?")["schwer"]
    main.chat.spend_add("gpt-6.2-astra", {"input_tokens": 100_000, "output_tokens": 0})     # 0.80 dollars
    assert main.chat.day_spend() == 0.8 and hard("Denk genau nach, was ist günstiger?")["schwer"]
    main.chat.spend_add("gpt-6.2-astra", {"input_tokens": 100_000, "output_tokens": 0})     # 1.60 dollars
    assert hard("Denk genau nach, was ist günstiger?") == {"schwer": False, "how": "day limit", "s": 0.0}
