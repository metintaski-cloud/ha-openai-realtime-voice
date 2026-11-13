# Plan: own firmware component (replaces voice_assistant_websocket)

Goal: an independent component written by us, more efficient and faster than the one taken over, with the same behaviour for the family. Decision by Metin on 13 Nov 2026: no ties to the old code, in the end a new repo with its own license.

## Rules
- Write from the contract in the root `AGENTS.md` (WebSocket protocol, audio format) and from this plan, with an own structure. Do not copy code or file layout of the old component.
- New component name `leyla_voice` (own directory `esphome/components/leyla_voice/`), so old and new can sit side by side and the switch is one line in the YAML. The old one stays as the fallback until the new one has proven itself.
- Same YAML interface so the device config hardly changes: `server_url`, `microphone`, `speaker`, `auto_stop_timeout`, `full_duplex`, `mic_auto_gain_max`, `mic_auto_gain_target`, `mic_noise_floor`, the callbacks `on_connected`, `on_disconnected`, `on_error`, `on_stopped`, `on_ready`, `on_thinking`, `on_replying`, `on_listening`, `on_searching`, `on_quota_exceeded`, and the actions start, stop, interrupt plus the conditions is_running, is_bot_speaking.
- No flashing while Mama uses the device; every flash is announced, and the old component is the way back.

## What has to be better (measured against BASELINE.md)
- Wake to ready and to first reply, interrupt reaction on the device.
- Free heap stays flat over days, no leak; largest free block does not shrink; loop time stays low while talking.
- No dropped audio at the start of a reply (the old one needed a 200 ms lead on the server).
- Clean behaviour when the server is gone, WiFi drops, or the quota error arrives.
- Microphone level handled on purpose (own gain stage, no clipping, quiet voices lifted).

## Steps
1. Spec: write the protocol and the state machine (idle, connecting, ready, listening, thinking, replying, searching, stopping) as a short document from the contract. Check it against the server code in `openai_realtime_voice/app/main.py` (that is ours).
2. Pure logic with tests that run here on the computer, not on the device: gain stage, resampler, state machine, queue handling. Fast to iterate, numbers instead of feelings.
3. Component code and ESPHome glue, compiled as `leyla_voice` next to the old one.
4. Test window on the device (when nobody needs Leyla): conversation, interrupt, search, goodbye, server off, WiFi off, quota error, false wake. Compare with the baseline.
5. Switch the live config, watch the sensors for a few days, then remove the old component and its mentions, and create the new repo with the own license (history of the old repo stays as an archive).

## Status
Step 1 done: specification in `leyla_voice_spec.md` (13 Nov 2026). Step 2 done (13 Nov 2026): pure logic in `esphome/components/leyla_voice/` (gain, resampler, ring buffer, message reader, state machine) with 68 checks (`make -C tests`). Next: step 3, the ESPHome glue. Baseline collection runs since 13 Nov 2026 22:30.
