# Changelog

## Unreleased

### Leyla fork (deployed setup, 13 Nov 2026)

- Own wake word "Hallo Leyla" (`hallo_leyla.json`, 99% cutoff, gain factor 4). "Okay Nabu" and "Hey Mycroft" are removed on the device.
- Announcements (for example "Mama, X calls you on WhatsApp") play pre-recorded clips from a cache in Leyla's own voice, the TV is turned down before and restored after (add on 2.51.0 to 2.52.0).
- Add on 2.54.6: more server modules (phrases, tool link, session end, output link), main.py from 1475 to 1104 lines, behaviour unchanged.
- Server refactor into modules (night, live link, after talk, announce voice, pacing, automation edit), `credit_balance_exhausted` counts as used up credit (add on 2.52.1 to 2.52.7).
- Add on 2.54.0: option `backend_reasoning_effort` (minimal, low, medium, high) for the backend model of GPT Live delegation; unset keeps the model default. Lower effort should shorten the long wait after a web search.
- Add on 2.55.12: persona rule for personal small talk (how was your day), after a test where she asked back what was meant.
- Add on 2.55.13: memory page paints the dark blue background at once (no grey page before the start animation).
- Add on 2.55.14: farewell detection knows the spellings "bay bay", "bai bai", "bye-bye" (the speech to text wrote "Bay bay", so she did not hang up until the idle timeout, 180 s session).
- Add on 2.54.7: memory block cap 15000 characters (was 9000). Add on 2.55.0 to 2.55.11 (3 to 11: start animation with a ring that fills in cyan to violet around the icon for 2 s, futuristic synth tones (sweeps, filter, echo) on tick, untick, pick up, drop, save and delete with an on off button, manifest ready for a real install without the Chrome badge, neon blue and violet design like the icon, own icon, the KI app icon from Metin): memory page on port 8082 (`app/memory_web.py`): open lists with a tick box per entry, a delete button, tap to edit the text and long press then drag to reorder or move an entry to another list, refreshes itself, no login, private list never shown.
- Project notes: STATUS.md (decisions, state, open items) and home-assistant-voice-pe/DEPLOYED.md (live config differences).

### Upstream changes before the fork (kept for reference)

### Features

- **Dual pipeline support** — the device now supports two voice pipelines:
  - **OpenAI (ChatGPT)**: "Okay Nabu" / single-click button.
  - **HA Assist**: "Hey Mycroft" / double-click button → local Home Assistant Assist pipeline (Speech-to-Phrase STT → Assist → Piper TTS) for smart home commands.
- Wake word routing based on `micro_wake_word`'s detected wake word string.
- "Hey Jarvis" is no longer a wake word. "Hey Mycroft" uses a 99% probability cutoff to reduce false wakes.
- Each detected wake word is logged at INFO and fired as the Home Assistant event `esphome.wake_word_detected` (data: `wake_word`) so false wakes can be attributed. Requires `homeassistant_services: true` under `api:`.
- Mutual exclusion — only one pipeline active at a time; starting one stops the other.
- HA Assist uses ESPHome's built-in `voice_assistant` component with the existing media player for TTS.

### Fixes

- HA Assist microphone uses XMOS channel 0 (the speech-recognition channel) with ESP-side noise suppression and auto gain off, matching the stock Voice PE firmware. On channel 1 with ESP-side processing, HA often missed speech and garbled the first word.

## 1.0.0

First public release.

### Features

- **Speech-to-speech voice assistant** using the OpenAI Realtime API (GA) with server-side VAD for natural turn-taking.
- **Web search** via `search_web` tool — calls the OpenAI Responses API for live information (weather, news, etc.).
- **Conversation lifecycle** — back-and-forth in a single session until the user says goodbye, presses the button, or times out. Each wake word starts a fresh session.
- **Phase protocol** — server sends `thinking`, `replying`, and `searching` phases for client LED/UX feedback. Client derives `listening` locally to avoid phase races.
- **Interrupt** — say the wake word while the assistant is speaking to interrupt and ask something new.
- **Configurable voice, model, and web search model** — `voice`, `realtime_model`, and `web_search_model` options in the addon config.
- **Audio pacing** — token-bucket sender matches playback rate so the ESP32 buffer doesn't overflow.
- **Tool call deduplication** — duplicate in-flight `search_web` calls for the same query are collapsed.
- **Optional audio recording** — save input/output WAVs for debugging.
- **ESP32-S3 Voice PE client** — ESPHome firmware with wake word detection, audio resampling, LED feedback, button, and mute switch.
