from app import main

over = main.LiveVoiceBridge._no_speech_over


def test_counts_from_end_of_greeting():
    state = {"last_audio_time": 105.0}  # greeting ended at 105
    assert not over(state, 100.0, 110.0)   # 5 s after the greeting
    assert over(state, 100.0, 111.5)       # 6.5 s after the greeting


def test_voice_holds_session_open_but_not_forever():
    state = {"last_audio_time": 105.0, "last_voice_at": 111.0}
    assert not over(state, 100.0, 112.0)   # heard a voice a second ago
    state["last_voice_at"] = 119.0
    assert over(state, 100.0, 121.0)       # past the hard limit of 20 s


def test_followup_keeps_its_long_wait():
    state = {"no_speech_s": 35.0, "last_audio_time": 105.0}
    assert not over(state, 100.0, 130.0)
    assert over(state, 100.0, 141.0)
