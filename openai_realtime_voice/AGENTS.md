# Server Addon — Agent Guide

## Design intent

This addon is a **direct WebSocket bridge** between the Voice PE device and the OpenAI Realtime API. It receives raw PCM over WebSocket, forwards it to Realtime, and streams response audio back. Implementation is a single Python module (`app/main.py`) plus optional recording.

**Lifecycle:** One client connection = one OpenAI Realtime session. The
three forwarding tasks (client→OpenAI, OpenAI→client, output_sender) run
concurrently; the first to finish (client disconnect, OpenAI disconnect,
or `disconnect_client` tool) triggers cancellation of the other two and
immediate closure of both WebSockets. No polling a done flag — cleanup
is prompt and predictable. Session end is logged with duration and reason.

## Architecture

```
ESP32 Voice PE                    Addon
+------------------+  WebSocket   +---------------------------+
| micro_wake_word  |   :8080     |  RealtimeVoiceBridge      |
| voice_assistant  | --- PCM ---> |    client_ws <-> openai_ws|
| _websocket       | <--- PCM --- |    (one openai_ws per     |
| I2S Speaker      | <-- JSON --  |     client connection)    |
+------------------+             +---------------------------+
                                       | disconnect_client tool
                                       | search_web tool ------> Responses API
```

- **Audio:** 24 kHz, 16-bit, mono PCM. Device binary frames are base64-encoded and sent as `input_audio_buffer.append`; `response.output_audio.delta` (Realtime API GA) is base64-decoded and sent as binary to the device.
- **Interrupt:** Device sends `{"type":"interrupt"}`; server sends `response.cancel` to OpenAI.
- **Disconnect:** When the user says goodbye, OpenAI calls `disconnect_client`; server sends `{"type":"disconnect"}` to the device, returns from the handler so the task ends, and the cancellation cascade closes both WebSockets.
- **Web search:** The `search_web` tool calls the OpenAI Responses API (GA `web_search` tool, `gpt-4.1-mini` model) using `WEB_SEARCH_API_KEY` or `OPENAI_API_KEY`. Non-reasoning search is used for low latency (single lookup, typically 3–10s). The key must have **Responses (Write)** permission in the OpenAI dashboard.

## Design decisions

- **No MCP.** Smart home is intended as a separate, local HA voice pipeline (e.g. different wake word). This addon is for voice Q&A and web search only.
- **Realtime API GA.** The addon uses the GA interface (no beta header); session config uses GA shape (`audio.input`/`audio.output`, `type: "realtime"`); server events are `response.output_audio.delta` / `response.output_audio.done`.
- **Two tools:** `disconnect_client` and `search_web`, both in `main.py`. `disconnect_client` is handled synchronously in `_handle_tool_call` (ends session). Other tools (e.g. `search_web`) run in the background via `_run_tool_in_background` so the event loop stays responsive and the model can acknowledge the user while a tool is pending.
- **Async function calling (GA):** The Realtime API supports the model continuing the conversation while a tool is pending (user can ask "how much longer?" and the model responds). The model does NOT reliably speak before calling tools regardless of instructions; instruction-based pre-acknowledgment was tested and failed. See [developer blog](https://developers.openai.com/blog/realtime-api).
- **Phase protocol:** The server sends `thinking`, `replying`, and `searching` phases only. "listening" was removed — the client derives it locally from audio playback state (`is_bot_speaking()` transitioning false). This eliminates the race where "listening" was sent at `response.done` before knowing if another response (with a tool call) would follow, which caused a brief green flash between replying and searching. At `response.done`, if `pending_tool_tasks` is non-empty, the server sends `searching`; otherwise no phase is sent. **All phases** go through a single **output queue** and are sent to the client in order by `_output_sender`; this eliminates race conditions and keeps LED/UX in sync with what the user hears. The client uses phase to show a distinct state (blue-green LEDs) and a 60s auto-stop timeout so long searches don't kill the session.
- **Tool call deduplication:** In-flight `search_web` calls are deduplicated by query. If the model issues the same query again while a search is already running (e.g. user asks "what's taking so long?" and the model redundantly calls search again), the server reuses the first result for the duplicate call and does not trigger a second `response.create`, avoiding duplicate spoken answers.
- **Stale tool results:** When the user moves on before a search completes, the old result may still be sent and the model may read it back. Deduplication only covers same-query duplicates while a search is in flight; cancelling on speech would break the "how much longer?" use case.
- **Web search:** Responses API with `gpt-4.1-mini` (non-reasoning) typically completes in 3–10s; httpx timeout is 45s. `response_idle` prevents sending tool results while the model is mid-speech.
- **Config:** HA Addon UI → `config.yaml` → `run.sh` (bashio) → env vars → `main.py`. No config file parsing in Python.

## Config options

- `openai_api_key` — Required. Must have **Realtime (Request)** permission. Also used for web search if `web_search_api_key` is unset, in which case it must also have **Responses (Write)**.
- `websocket_port` — Default 8080.
- `vad_threshold`, `vad_prefix_padding_ms`, `vad_silence_duration_ms` — Server-side VAD.
- `instructions` — Optional extra rules, appended after Leyla's instructions. Leyla's instructions themselves live in `app/persona.py`.
- `voice` — OpenAI Realtime voice (default `marin`).
- `realtime_model` — OpenAI Realtime model (default `gpt-realtime`). Constructs the WebSocket URL as `wss://api.openai.com/v1/realtime?model={realtime_model}`. For full URL override, set `OPENAI_REALTIME_URL` env var directly.
- `web_search_model` — Model for Responses API web search (default `gpt-4.1-mini`).
- `web_search_api_key` — Optional; if empty (or whitespace-only), `openai_api_key` is used for web search. Must have **Responses (Write)** permission. A 401 on web search means the key lacks this permission.
- `lamp_show`, `lamp_show_lights` — Lamp show (see `app/lamp_show.py`): on by default, comma separated light entities.
- `enable_recording` — If true, WAVs written under `recordings/` via `app/audio_recorder.py`.

## Adding a tool

1. Put the tool schema (`..._TOOL` dict with `name`) and its `run(args)` coroutine in its own module and add the schema to the tools list of `_session_start`.
2. Register it in `ToolLinkMixin._build_tools` (`app/tool_link.py`): label, timeout, `run`, the friendly error text, and optionally `gate(args, state)` (return an error result to refuse, for example for anyone but Metin), `after`, `log`, `phase`. The generic `_run_tool` runs it in the background with a timeout and returns the result, so there is no per tool runner code. `end_conversation` is the only function handled inline in `_handle_backend_event`.
3. Add a case to `tests/test_session_flow.py` when the tool has a gate or special behavior.

## Docker build

Single-stage Alpine image. Dependencies in `requirements.txt` (websockets, httpx, python-dotenv). Dockerfile runs `pip install -r requirements.txt`; no Poetry or LLVM.

## Version

When you change the addon (behavior, config, contract, or fixes), update the addon version in `config.yaml` using semver-like rules: breaking → bump major, new feature → minor, fix → patch. Do this until we have a better release/versioning solution.

## File layout (addon directory: `openai_realtime_voice/`)

- `config.yaml` — Addon options schema and image URL (used by Supervisor).
- `root/run.sh` — Entrypoint; reads bashio config and exports env for `app.main`.
- `app/main.py` — Bridge logic, tools, WebSocket handlers.
- `app/night.py` — Night check options and `NightMixin` (the 23:30 check, mixed into the bridge; `NIGHT_WAIT_S` lives here).
- `app/live_link.py` — `LiveLinkMixin`: opening the GPT Live connection and the warm connection (`_connect_live`, `_take_live`, `_warm_loop`). `app/after_talk.py` — `AfterTalkMixin`: memory update and rudeness report after a conversation. Both are mixed into the bridge in `main.py`.
- `app/session_end.py` — `SessionEndMixin`: when a session ends (`_session_watcher`: no speech, idle, maximum length, farewell played) and the time limits `IDLE_TIMEOUT_S`, `NO_SPEECH_TIMEOUT_S`, `GOODBYE_MAX_WAIT_S` and so on; tests change the limits on this module, not on `main`. `app/output_link.py` — `OutputMixin`: everything sent to the device (`_output_sender` with paced audio, phases, interrupts, errors; `_send_phase`).
- `app/memory_web.py` — small web page on port 8082 (`MEMORY_WEB_PORT`, plain asyncio HTTP, no login, home network only): the open lists (family, friends, leyla; never private) with a tick box per entry, a delete button and tap on the text to edit it (`edit_item`, replaces in place, empty, duplicate or over 700 characters refused), long press (450 ms) then drag moves an entry within or to another list (`move_items`: accepted only when it holds exactly the stored entries, so an outdated page cannot overwrite what Leyla learned meanwhile; touch events, tested with headless Chromium touch emulation), short futuristic synth tones made with the Web Audio API (sweeps through a filter plus an echo bus, no sound files; tick, untick, pick up, drop, save, delete; switch "Ton an/aus" in the header, remembered in localStorage), start animation (`#splash`, icon with a gradient ring that fills in about 2 s on the same navy as the manifest background so it continues the Android splash, tap skips it), entries with points ("Person: Metin | Zugehörigkeit: ... | Alter: 45", every entry that starts with `Person:` or contains " | ") show as a folder card (name, number of points, first keys, chevron); a tap opens it (`view`, browser history entry so the Android back button and the ‹ button close it) and every point is its own card with tick box, tap to edit, long press and drag to reorder (within the folder only) and "+ Punkt hinzufügen"; `edit_folder` (`/api/folder`, the stored text stays in the same format, the name stays first, `old` must still be the stored text so a page that is out of date cannot overwrite what Leyla learned, " | " inside a point becomes " / ") writes the new order, edit, addition or deletion; refreshes every 4 s (paused while editing or dragging); deleting, editing and moving write the memory file and kick `todo_sync`. `app/memory_icon.png` is its icon (the KI app icon supplied by Metin, cropped to the rounded square with transparent corners, 512 px, shown after the shortcut is created again). Open `http://<HA host>:8082/` on the phone and add it to the home screen.
- `app/lamp_show.py` — `LampShow`: the rear lamps (`lamp_show_lights`, default Lamba 1 and 2, also when they are off) follow the conversation in the colours of the KI icon: always full strength (100 %, Metin's wish 14 Nov 2026): listening cyan, thinking and searching violet, speaking a colour breathing between blue and magenta with the loudness of the reply audio (`pcm_level` rms of each chunk in `_output_sender`, delayed by the 0.2 s send lead; no audio for 0.7 s means back to cyan). One `light.turn_on` with transition 0.35 s at most every 0.33 s (Matter lamps cannot follow faster). `begin()` in `handle_client` stores state, brightness and colour of each lamp, `end()` in `_end_session` restores it (white stays white). A lamp that was off first fades back to the strength and colour it had when it was last seen on (`/data/lamp_show.json`, written whenever a conversation starts and the lamp is on) and is then switched off, so the next normal switch on has the old strength; before the first sighting there is nothing to restore and a Matter lamp keeps the last level (100 %). Options `lamp_show` (on or off) and `lamp_show_lights`. A false wake shows the cyan for a moment too.
- `app/tool_link.py` — `ToolLinkMixin`: the table of backend functions (`_build_tools`, with the gates for Metin only) and the generic runner `_run_tool`; mixed into the bridge in `main.py`.
- `app/phrases.py` — pure helpers without I/O: farewell phrases (`contains_goodbye`), greetings (`parse_greeting_words`, `pick_greeting`, `greeting_instruction`) and addressing Leyla by name (`NAME_RE`, `addressed_by_name`, `NAME_NUDGE`). `main.py` imports them, so tests can still reach them as `app.main.<name>`.
- `app/announce_voice.py` — `AnnounceVoiceMixin`: GPT Live speaks one announcement without a listener (`_speak_once`) and the TV volume around it. `app/pacing.py` — `PacedSender` (reply audio at playback rate) and the audio constants and `pcm_level`.
- `app/technik.py` — the `technik_pruefen` tool: reads and writes the Home Assistant automation configs (network). `app/automation_edit.py` — its pure helpers (search words, colours, lamp and fan step handling, clock times; dicts in and out, no network); names are imported into `technik.py`.
- `app/metrics.py` — persistent timing log `/data/metrics.jsonl` (JSON lines: `ready` with `live_open_s` and `connect_to_ready_s`, `first_audio` with `after_last_word_s` measured from the last input transcript delta, `interrupt`, `session_end` with duration, reason and the microphone rms (average per 2 s window, median over the session) and peak while Leyla spoke versus while she was quiet, as `mic_speaking_*` and `mic_quiet_*`). Used for baseline and before/after comparisons (see `home-assistant-voice-pe/BASELINE.md`). Trimmed to its newer half at 1 MB. Every line except `interrupt` is also logged at INFO as `Metrics {json}`, because the add on log is the only way to read the numbers from outside.
- `app/audio_recorder.py` — Optional WAV recording when `enable_recording` is true.
- `requirements.txt` — websockets, httpx, python-dotenv.
- `requirements-dev.txt` — for tests: pytest, pytest-asyncio.
- `tests/` — pytest tests. `tests/test_session_flow.py` plays whole sessions against a fake GPT Live server (ready, audio both ways, phases, tools and their gates, quota, hang up reasons).
- `pytest.ini` — asyncio_mode = auto for tests.
- `Dockerfile` — Single-stage; no Poetry. Used by `.github/workflows/build-addon.yml`.

## Running tests

Tests use the virtualenv at `openai_realtime_voice/.venv/`. System `python`/`python3` don't have pytest installed. Run from the `openai_realtime_voice/` directory:

```bash
.venv/bin/pytest tests/ -v
```

Or a single file:

```bash
.venv/bin/pytest tests/test_session_flow.py -v
```

## Keeping this doc current

Update when:

- The WebSocket contract (audio format, control messages) changes
- A config option or tool is added or changed
- The Docker build or dependencies change
- When shipping a fix or feature: update version in `config.yaml` (semver-like; see Version above).
- **Session learnings:** If you discover something during a session that cost time or caused confusion (e.g. environment quirks, tool invocation details, non-obvious gotchas), add it here before finishing. Future sessions start fresh and won't have that context unless it's written down.

## Session learnings (GPT Live)

- A false wake is ended with `no_speech` (`_no_speech_over`): the wait of 6 s counts from the end of Leyla's own greeting, not from the start (before, the greeting used up about half of the 8 s and she hung up while the user was answering), a voice heard in the last 2.5 s (microphone chunk rms 300 or more) holds the session open, and a hard limit of 14 s after the start applies so TV noise cannot keep a false wake alive. The transcript, which sets `user_spoke`, arrives a little after the words.

- The httpx logger is set to WARNING: it wrote one INFO line per Home Assistant request (to-do sync every minute, four lists) and pushed the useful lines out of the Supervisor log, which only keeps about the last 100 lines. The to-do sync interval is back at 30 s (the requests are cheap, only the log noise was the problem).

- GPT Live streams reply audio at about real time. `_output_sender` holds each reply until 200 ms are buffered and then stays 200 ms ahead of playback; without that reserve the first words stuttered. The Voice PE queues only 10 chunks of 20 ms while its speaker starts, so keep the lead at 200 ms or the ESP drops audio.
- GPT Live has no turn detection setting. With the TV on or people talking, it may never see the end of a turn and stays silent. When the transcript addresses Leyla by name (`addressed_by_name`) and she has not reacted within 5 s, the bridge sends a commentary nudge.
- While a delegation runs, GPT Live does not start the next one: a request said meanwhile is acknowledged ("I'll look at the lamps") but never done, and the user has to repeat it. Keep tool calls short: the TV power call waits at most 4.5 s, volume keys use 0.1 s steps.
- The TV is turned down while Leyla listens (`tv.duck`), also when it is switched on during the conversation, and again 4 s after a volume request; the requested volume is restored afterwards.
- Messages from Metin are brought up in a real conversation: the bridge calls the Voice PE action `esphome.ha_voice_openai_0ae305_start_conversation` (api `actions:` in the YAML), and the session that connects within 15 s starts with the message instead of the greeting, so Mama can answer by voice. Without the action, or when a session already runs, it falls back to injecting into the running session or to the old media player announcement.
- Memory has three lists (`app/memory.py`): `family` (open; only Metin, his mother and his siblings plus household facts; one profile line per person plus "Aktuell bis TT.MM.JJJJ" states that expire), `friends` (open; relatives, friends, neighbours, same profile format, mirrored to `todo.leyla_freunde_und_verwandte`) and `private` (Metin's private things; only after the code phrase, and the summarizer may only change it then). After every real conversation the summarizer updates both; there is no need to say "merk dir" for family knowledge. Both lists are mirrored to the Home Assistant to-do lists `todo.leyla_familie` and `todo.leyla_privat` (`app/todo_sync.py`, every 30 s, three-way merge with the last agreed state in `/data/todo_sync_state.json`). Ticking an item off must not forget it: a tap in the app or the widget ticks items off by accident (on 8 Nov a widget tap emptied both lists); ticked items are unticked again, only deleting an item forgets it. Private entries are never written to the log.
- Continuity ("same Leyla"): each person profile also carries `Stimmung`, `Humor`, `Zuletzt` (date and one sentence about the last real talk), `Offen` (real threads such as an appointment or a promise) and `Eindruck` (Leyla's own impression). The summarizer replaces `Zuletzt` and `Stimmung` after real personal talks only (not after commands, small talk or one-off trivia questions) and drops finished `Offen` threads. `persona.py` (WAS DU WEISST) tells her to pick up at most one or two threads per conversation, after doing the request, and never to say she looked something up. Entries may be up to 700 characters. There is no conversation archive on purpose.
- Leyla's whole character and behaviour is one package in `app/persona.py` (sections WER DU BIST, WIE DU SPRICHST, WER MIT DIR SPRICHT, WAS DU WEISST, KENNENLERNEN, DEIN KLEINES GEHEIMNIS, SICHERHEIT, ERLEDIGEN, VERTRAUEN, then the family list from `app/memory.py`). Add new behaviour there, in the fitting section, one rule per line; do not add hints in other modules or in the `instructions` option, because spread out rules contradicted each other (she was told she is "eine Bekannte der Familie" and part of the family, "nie wie eine Partnerin" and to hint she loves Metin, and Metin's birthday was private while it is in the family list).
- When Leyla says she will tell Metin about someone being rude ("das erzähl ich Metin", "Bunu Metin'e söyleyeceğim"), `app/report.py` lets a text model read the finished conversation and push one message in her own words ("Leyla erzählt"), or nothing when nobody was really rude. The live model sends nothing during the talk.
- The robot vacuum (Dreame X60, `vacuum.x60_pro_ultra_complete`) comes from the HACS integration Tasshack/dreame-vacuum (Dreamehome cloud login; a Google login needs a password set in the Dreamehome app first). `app/vacuum.py` gives Leyla the tool `saugroboter`: full clean, rooms by name from the map (Turkish names mapped), mode and suction via the select entities, pause, stop, return to base, status and maintenance. The camera stream is not available to Home Assistant.
- The air purifier (Dreo 530S, DR-HAP010S, `fan.luftreiniger`) comes from the HACS integration JeffSteinbok/hass-dreo (the official dreo-team integration has no air purifiers). `app/purifier.py` gives Leyla the tool `luftreiniger`: on, off, preset auto/sleep/turbo, level 1 to 4 (25 % steps), off timer, status with PM2.5. Login failed until the phone keyboard's capital letter and trailing space were removed from the e-mail.
- Leyla has her own story as a fourth memory list (`memory.LEYLA`, key `leyla`, mirrored to `todo.leyla_selbst`, max 30 short first person entries): shared insiders, rituals, her quirks in the family. The summarizer writes it carefully (a wipe of more than 3 entries is ignored), `instructions_block` shows it as "DEINE EIGENE GESCHICHTE MIT DER FAMILIE", persona tells her to use it sparingly in the we form. Metin reviews and corrects it together with Claude in the to-do list, no push messages on purpose. The nightly cleanup never proposes entries of this list. The to-do list `todo.leyla_selbst` must exist in Home Assistant (Local To-do).
- False wakes are collected as training material for a better Hallo Leyla model (`record_false_wakes`, default on, `main.py: _finish_recording`): the microphone audio of every session is written to `/tmp/leyla_input` and deleted at the end, except when the session ended with `no_speech`, was not started by Leyla herself (`state["followup"]`) and is longer than about a second; those go to `/data/false_wakes/` (max 300, oldest dropped). The recording starts only after the wake word fired, so the exact trigger sound is only partly in it. `enable_recording` (debug) keeps everything as before.
- Warm GPT Live connection (`_take_live`, `_warm_loop` in `app/live_link.py`, env `WARM_CONNECTION`, default true): one WebSocket to GPT Live is opened ahead of time (no session started, so no cost) and replaced before it is 90 s old, so the TLS and WebSocket handshake (about 0.55 s median, 1 s p90) is done before the wake word. A warm connection that is stale, closed or does not answer `session.start` within 4 s is dropped and a fresh one is opened, so it can only help. Measured before: wake word to `ready` 1.6 s median; the rest is the `session.start` round trip of GPT Live itself (about 1 s).
- Fresh data for cloud devices (`app/freshness.py`, used by `vacuum.py` and `purifier.py`): before a status is read the integration is asked to refresh (`homeassistant.update_entity`, 6 s cap, never fails the status). The result carries `data_age_minutes` from the entity's `last_reported`, a `warning` from 15 minutes on, and an unavailable device returns `reachable: false` with a plain error instead of cached values. The backend hint tells Leyla to say this and never present old values as current.
- Health messages (`app/health.py`, state in `/data/health.json`): the server pushes to Metin's phone when it was killed unexpectedly (a heartbeat file every 60 s; a SIGTERM from an update or restart marks the run clean, so only crashes and power loss are reported), when OpenAI cannot be reached 3 sessions in a row (cooldown 3 h, plus a note when it works again), and when the OpenAI credit is used up (cooldown 6 h; OpenAI reports it as `insufficient_quota` or, since November 2026, `credit_balance_exhausted`, both in `QUOTA_ERRORS`; the client still gets `insufficient_quota`). A device that is offline and failed backups are watched by the Home Assistant automation "Leyla Überwachung" (not in this repo), HA makes a daily automatic backup at 03:00 with 7 copies including this add-on.
- Metin is the filter of the memory (`app/cleanup.py`, tool `gedaechtnis_aufraeumen`, state in `/data/cleanup_state.json`): once a night at 00:00 a text model only PROPOSES clearly trivial entries (single knowledge questions, commands, small talk, duplicates, done things; never `Person:` profiles, in doubt keep), the list goes to Metin's phone, nothing is deleted by itself. Leyla reads the proposals and deletes (`streichen`) or keeps for good (`behalten`, never proposed again) only the numbers Metin names; `main.py` lets the tool through only when the code phrase was heard (`state["unlocked"]`).
- Leyla can check the house technology herself (`app/technik.py`, tool `technik_pruefen`, read only): `automationen` searches the Home Assistant automations by word (name, trigger time, action) and returns on/off, triggers, conditions, what they do and when they last ran, `geraete` reads the state of devices (light, switch, fan, media player, vacuum, sensors; no person, camera or lock). Five changes, all only after the code phrase: `nacht_aendern` (the 23:30 night check is configured in the event data of its automation, see `app/night.py`: `lampen` list of lamp numbers, `ventilator`, `ventilatorlicht`, `fragen` false = switch off without asking, `warten` seconds; missing keys mean the old behaviour, default values are written as no key), `ventilator_aendern` (the fan is not an HA entity, automations drive it with `event: leyla_command` and `event_data: {device: ventilator, action: ...}`; modus hinzufuegen, entfernen or ersetzen of such a step, steps aus, an, stufe 1 to 6, licht_an, licht_aus, timer 1/2/4, naturwind, links, rechts; the fixed 23:30 `device: nacht` check cannot be edited this way), `lampen_aendern` (which lamps the `light.turn_on` actions switch on: `modus` entfernen, hinzufuegen or nur, lamp names resolved against the light entities, unclear names return the candidates; actions that target an area or device are refused, the last lamp cannot be removed; colours and brightness stay), `zeit_aendern` (the clock time of one time trigger of one automation) and `licht_aendern` (colour as a German word or `r,g,b`, brightness 1 to 100 percent, optional lamp word; written into the `light.turn_on` actions of the one matching automation, also inside choose/if, a new colour replaces the old white tone and vice versa; automations that use scenes are refused). All write the config back to `config/automation/config/<id>`, nothing else is touched, and the `automationen` result shows the current colour and brightness of each action. `main.py` lets it through only when the code phrase was heard in the conversation (`state["unlocked"]`, set by the bridge, not by the model) and a code phrase is configured; Metin gets a push "Leyla hat eine Zeit geändert". The automation config is read through the supervisor proxy.
- Announcements (`leyla_announce`, `messages.say`, `main._speak_once`): the whole clip is generated at about real time before it is played, so the prompt asks for at most two short sentences in her own warm words (meaning of the content, not a literal reading), and `_speak_once` uses the warm GPT Live connection and stops 1.2 s after the last speech.
- `leyla_announce` with `merken: true` keeps the finished clip in `/data/announce_cache` (keyed by the text and `CACHE_VERSION`, max 200): the first time it is generated by GPT Live (about 10 s, the whole clip is made at about real time before it is played), every later time with the same text plays at once in the same voice. The HA event `leyla_announce_prepare` with `texts: [...]` records clips ahead. The speech endpoint was tried and dropped on purpose: Leyla's live voice (Brise) does not exist there and the family does not want a different voice. Change `CACHE_VERSION` when the wording prompt changes.
- Announcements turn the TV down first and back up afterwards (`MessageCenter.before_play` and `after_play`, wired in `main` to `tv.duck` and `tv.unduck`), but only when no conversation runs (`_active_sessions` empty), because a session ducks and restores the TV itself.

## Backend reasoning effort

Option `backend_reasoning_effort` (config.yaml, run.sh env `BACKEND_REASONING_EFFORT`) is passed as `session.delegation.responses.reasoning.effort` in `session.start`. Unset or `null` leaves the model default. Reason: after a finished web search the backend needed about 16 s until the reply started (14 Nov 2026), see STATUS.md. Source: OpenAI guide "Delegation and tools in GPT-Live".

## Deep thinking was tried and removed (14 Nov 2026)

A backend tool `tief_nachdenken` (high reasoning effort for one answer) plus a persona rule was built and removed again: GPT Live's live voice answers hard questions itself and does not reliably delegate, even when asked to "think harder", and OpenAI offers no reasoning depth for the live voice. Its own answers were good and personal (they know the household). Only the session wide `backend_reasoning_effort` stays (web search replies 16 s to 1.6 s).
- Soft edges (`app/pacing.py`, `fade_out`, `fade_in`, add on 2.55.15): where the reply audio stops (a flush: reply end, a pause of 0.1 s, a phase message) the last 15 ms are faded to zero and the next audio fades in over 5 ms, against the click at the end of a sentence. `PacedSender` holds the last 15 ms back until more audio comes, so the prebuffer threshold is `PREBUFFER_BYTES + FADE_OUT_BYTES`. Only existing samples change, nothing is added. A firmware version that appended a ramp whenever the speaker ran dry (`edge.h`, 14 Nov 2026) made the speech stutter because it could not tell the end from a pause inside a sentence, and was reverted.
- Reading the add on log from outside: the Supervisor `/addons/<slug>/logs` call returns only about 100 lines by default (the 2 s mic level and `first_audio` lines push the start of a conversation out). Send the header `Range: entries=:-1000:` to get 1000 lines, enough for the `ready` metric of a short test.
