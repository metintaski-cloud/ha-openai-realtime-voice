# leyla_voice: specification (step 1 of REWRITE_PLAN.md)

Written 13 Nov 2026 from the contract in the root `AGENTS.md` and from the server (`openai_realtime_voice/app/main.py`, our own code), not from the old component.

## Job
Carry one conversation between the Voice PE and the server: microphone to server, reply audio from server to the speaker, phase and end signals from the server to the LEDs and sounds. One conversation at a time.

## Wire format (fixed by the server)
- WebSocket `ws://host:port/`. Binary frames: 24 kHz, 16 bit, mono PCM both ways, no header. Text frames: JSON.
- Client to server: audio, and `{"type":"interrupt"}`.
- Server to client: `ready`, `phase` (`thinking`, `replying`, `searching`), `disconnect` (optional message and reason), `error` (code `insufficient_quota`). Unknown types are ignored, never an error.
- The client sends no microphone audio before `ready`.
- The microphone gives 16 kHz stereo 32 bit from the I2S input, the speaker takes 48 kHz: the component converts (take one channel, 32 to 16 bit, 16 to 24 kHz up, 24 to 48 kHz up) on the device.

## States
`idle` (nothing runs), `connecting` (socket opening), `waiting_ready` (socket open, no `ready` yet), `listening` (talking, bot silent), `thinking`, `replying`, `searching`, `stopping`.
- start: `idle` to `connecting`. Refused when muted (caller checks), when already running, or when free heap is below a safe minimum.
- socket open: `waiting_ready`. No `ready` within the ready timeout: close and retry once, then error. The server needs about 1.1 s, so a timeout of 5 s is generous.
- `ready`: `listening`, start the microphone stream and fire `on_ready`.
- `phase thinking` / `replying` / `searching`: switch state and fire the matching callback. `searching` means a tool runs: extend the inactivity timeout to 60 s.
- Listening is derived locally: when the speaker has played out its last audio (bot no longer speaking) and no search is active and no phase arrived in the same loop pass, go to `listening` and fire `on_listening`.
- `disconnect` from the server: play out what is queued, then `stopping` and `on_stopped`.
- `error insufficient_quota`: fire `on_quota_exceeded`, stop after the error sound (about 4 s).
- socket closed or lost: `stopping`, `on_disconnected`, back to `idle`; no automatic reconnect inside a conversation.
- stop (action, button, wake word while the bot is silent): close the socket cleanly, clear queues, stop microphone and speaker stream, `idle`.
- inactivity: no audio from the server and none worth sending for the auto stop timeout (default 20 s, 60 s while `searching`): stop.

## Interrupt
- Action `interrupt` (wake word or button while the bot speaks): send `{"type":"interrupt"}`, clear the local playback queue at once, stop the speaker, go to `listening`. Late audio from before the interrupt is dropped for a short guard time so old words do not come back.
- The server also sends no reply audio of its own after an interrupt it has seen; the guard covers frames already in flight.

## Audio paths
- Microphone path: take left channel, convert, optional gain stage (below), resample to 24 kHz, send in frames of about 20 ms to 100 ms. Never block the microphone callback; drop the oldest frame when the socket is slow, never grow memory.
- Speaker path: ring buffer between the socket callback and the speaker. Start the speaker only after a small lead (the server already holds 200 ms), keep feeding, stop when empty for a moment. A bounded buffer: when full, drop the newest data and count it (counter for diagnostics).
- `full_duplex` true: keep sending the microphone while the bot speaks (the user can talk over her). False: mute the microphone path while the bot speaks.
- `is_bot_speaking`: true from the first reply audio until the buffer is empty and the speaker has finished.

## Gain stage (own design)
- Input is the XMOS processed channel with its own AGC (stays on, see DEPLOYED.md). The component adds a slow software gain: quiet voices up to `mic_auto_gain_max`, never below 1, towards `mic_auto_gain_target` rms, held below `mic_noise_floor`, attack fast and release slow, soft limiter before 16 bit full scale. Pure function on a buffer, so it is tested on the computer.

## Callbacks and actions (same names as before so the YAML hardly changes)
`on_connected`, `on_disconnected`, `on_error`, `on_stopped`, `on_ready`, `on_thinking`, `on_replying`, `on_listening`, `on_searching`, `on_quota_exceeded`. Actions `start`, `stop`, `interrupt`. Conditions `is_running`, `is_bot_speaking`.

## Diagnostics
Counters: audio frames sent, dropped on the microphone side, dropped on the speaker side, reconnects, ready time in ms, time from last mic frame to first reply frame. Logged once per conversation at INFO, so they can go into BASELINE.md.

## Pure logic that gets tests on the computer
- Gain stage (levels, no clipping, quiet voice lifted, noise not chased).
- Resamplers (length, no clicks at block borders).
- State machine (every transition above, timeouts, interrupt guard).
- Ring buffer (wrap, overflow count, drain).
- Message parser (unknown type, broken JSON, missing fields).

## Open questions
- Whether a different frame size on the socket lowers latency without costing CPU (measure).
- Whether the speaker start lead can be lower on the device if the server keeps 200 ms (measure).
- Reconnect inside a conversation: not wanted now, revisit if WiFi drops show up in the sensors.
