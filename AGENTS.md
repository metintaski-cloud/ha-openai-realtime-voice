# OpenAI Realtime Voice

## What this is

A voice system for Home Assistant using the OpenAI Realtime API. Two parts talk over a WebSocket with raw PCM audio:

- **Server** (`openai_realtime_voice/`): HA addon — WebSocket server that bridges the ESP32 to the OpenAI Realtime API and to web search (Responses API).
- **Client** (`home-assistant-voice-pe/`): ESPHome firmware for the Home Assistant Voice PE (ESP32-S3).

Each component has its own `AGENTS.md` with component-specific guidance.

## Dual Pipeline Architecture

The device supports two voice pipelines, selected by wake word or button press:

| Pipeline | Trigger | Path | Use case |
|----------|---------|------|----------|
| **OpenAI (ChatGPT)** | "Hallo Leyla", single-click | `voice_assistant_websocket` → HA addon → OpenAI Realtime API | General Q&A, web search |
| **HA Assist** | double-click only ("Hey Mycroft" removed) | ESPHome `voice_assistant` → HA native API → Assist pipeline | Local smart home commands |

```
ESP32-S3 Voice PE
┌──────────────────────┐
│   micro_wake_word    │
│         ↓            │
│  wake word routing   │
│    ┌────┴────┐       │                    HA Addon
│    ▼         ▼       │  WebSocket     ┌─────────────────────────┐
│  voice_     voice_   │   :8080       │  RealtimeVoiceBridge    │
│  assistant  assistant│  ── PCM ───►  │    client_ws ↔ openai_ws │
│  (built-in) _websocket│              │    (one Realtime session│
│    │         │       │  ◄── PCM ──   │     per connection)     │
│    ▼         ▼       │  ◄── JSON ──  │    + search_web → Resp. │
│  HA API   I2S Speaker│               │         API             │
│    │                 │               └─────────────────────────┘
│    ▼                 │
│  Assist Pipeline     │
│  (STT→Assist→        │
│   Piper, all local)  │
└──────────────────────┘
```

Only one pipeline runs at a time. Starting one stops the other (mutual exclusion via `active_pipeline` global in YAML).

## Contract between client and server

Both sides must follow this. If one side changes, the other may need updates.

**WebSocket endpoint:** `ws://<host>:<port>/` (default 8080)

**Audio (both ways):** 24 kHz, 16-bit, mono PCM in binary WebSocket frames. No extra headers or framing.

**Control (JSON text frames):**

| Direction        | Message              | Meaning                                      |
|-----------------|----------------------|----------------------------------------------|
| Client → Server | `{"type":"interrupt"}` | Stop current response and listen for input |
| Client → Server | `{"type":"stopped","reason":"auto_stop","ms":242262}` | Device ended the conversation itself; reason for the log (see `Stop` in `state_machine.h`). |
| Client → Server | `{"type":"preroll","rate":16000,"bytes":80000}` then exactly that many bytes in binary frames | Optional, right after the socket opens and before any audio of the talk: the last seconds of the microphone from before the wake word (16 bit mono PCM at `rate`, not resampled, no gain). The server never passes it to GPT Live; with the TV running it looks for her name in it (`app/wakecheck.py`). Optional `"wake_ms": N` in the same message: the wake word was heard N ms before the end of that history, and it started this talk; without it the talk was started by the button or by Leyla herself (or the firmware is older). No talk is turned away because of it (removed in 2.158.0). Firmware option `preroll` of `leyla_voice`, off by default; `preroll_channel` and `preroll_gain` choose the sound (Voice PE: 1 and 4, what the wake word model hears). |
| Server → Client | `{"type":"ready"}` | OpenAI connected; client should start sending audio and show "listening" (e.g. green LEDs). |
| Server → Client | `{"type":"phase","phase":"thinking"}` | User stopped speaking; OpenAI is processing. |
| Server → Client | `{"type":"phase","phase":"replying"}` | Bot started speaking. |
| Server → Client | `{"type":"phase","phase":"searching"}` | Background tool (e.g. web search) running; client should show processing+listening state and use extended auto-stop timeout (e.g. 60s). |
| *(client-derived)* | *(no message — client detects locally)* | "listening": client derives from `is_bot_speaking()` transitioning false while no search is active and no server phase arrived in the same loop iteration. |
| Server → Client | `{"type":"disconnect"}` (optional: `"message"`, `"reason"`) | Session ended (e.g. user said goodbye); client should stop and go idle. |
| Server → Client | `{"type":"error","code":"insufficient_quota"}` | OpenAI quota exceeded; client plays error sound, shows red-yellow LEDs for ~4s, then stops. |

**Near wakes (HTTP, not the WebSocket):** `POST http://<host>:8082/api/weckton?rate=16000`, body = raw 16 bit mono PCM (0.5 to 4.5 s), no code word, answer `{"ok": true|false}`. The device sends the microphone history there when a silent second copy of the wake word model with a low cutoff fires (`leyla_voice` options `collect_host`, `collect_port`; `collect()`); nothing starts on the device. The server files the clips for training the wake word (`app/sammler.py`, `docs/WECKWORT.md`).

**Client:** Resample mic 16 kHz → 24 kHz before send; resample received 24 kHz → 48 kHz for the speaker.

**Server:** Encode PCM to base64 and send as `input_audio_buffer.append`; decode `response.output_audio.delta` (Realtime API GA) and send raw PCM to the client. Tool calls such as `search_web` run in the background so the event loop stays responsive.

Every detection is logged at INFO (`Wake word detected: <phrase>`) and fired as the Home Assistant event `esphome.wake_word_detected` with data `wake_word: <phrase>`, so a false wake can be traced to the word that caused it. The event needs `homeassistant_services: true` under `api:` in the ESPHome config. HA accepts `esphome.*` events from the device without the integration option "Allow the device to perform Home Assistant actions", which stays off.

## Installation and deployment

### Server addon on HAOS

The addon lives in the repo under `openai_realtime_voice/` (directory name matches slug). To install from this repo:

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → add `https://github.com/metintaski-cloud/ha-openai-realtime-voice`
2. Install “OpenAI Realtime Voice”
3. Configure in the addon Configuration tab (see `openai_realtime_voice/config.yaml`). Required: `openai_api_key`. Optional: `web_search_api_key`, VAD, `instructions`, `enable_recording`

### Client firmware

The ESPHome config in `home-assistant-voice-pe/` pulls the `voice_assistant_websocket` component from this repo via git on compile. See `home-assistant-voice-pe/AGENTS.md` for details.

### HA Assist pipeline (local smart home commands)

The HA Assist pipeline runs entirely through Home Assistant's built-in voice infrastructure. Setup:

1. **Install addons** in HAOS:
   - **Speech-to-Phrase** (local STT) — Settings → Add-ons → "Speech-to-Phrase". Recognizes only fixed templates filled with exposed entity names and aliases; in English, "turn on/off <name>" covers lights, switches, fans, media players and input booleans, while scenes only take "activate <name>". Whisper is the free-form alternative and mishears short commands more often.
   - **Piper** (local TTS) — Settings → Add-ons → "Piper". Config: select a voice (e.g. `en_US-lessac-medium`).
   - openWakeWord is **not needed** — wake word detection runs on-device.

2. **Create a voice pipeline** — Settings → Voice assistants → Add assistant:
   - Conversation agent: Home Assistant (built-in, handles intents)
   - Speech-to-text: Speech-to-Phrase
   - Text-to-speech: Piper
   - Wake word: leave empty (on-device)

3. **Assign pipeline to device** — Settings → Devices → select Voice PE → Configure → select the pipeline.

4. **Expose entities** — Settings → Voice assistants → Expose tab. Select which entities (lights, switches, climate, etc.) Assist can control. Most entities are **not exposed by default**.

5. **Device must be adopted** in HA — Settings → Devices → ESPHome. The `api:` connection (already in firmware) is required for the Assist pipeline.

## Owner’s deployed setup

HAOS on a dedicated host. ESPHome config under e.g.:

```
/homeassistant/esphome/
├── home-assistant-voice-0acf1a.yaml
├── secrets.yaml
└── wake_sound.flac
```

Device name, friendly name, wake words, and other production settings can differ from the repo default.

Home Assistant answers on `http://192.168.2.240` (port 80, not 8123). The add on is called "GPT Live Voice" there and has the slug `5b94124a_openai_realtime_voice` (the hash `a0d7b954` belongs to the Tailscale add on). The exact update steps through the browser are in `STATUS.md`, section Umgebung.

## Remote access from the phone (Tailscale, 15 Nov 2026)

The memory app (port 8082) and live talk (port 8080) are reachable from outside the home through Tailscale, never through an open port on the router (the page has no login besides the code word).

- Home Assistant add on **Tailscale** (`a0d7b954_tailscale`, from the community repository hassio-addons) is installed, starts with Home Assistant (boot auto, watchdog on).
- Add on option `advertise_routes: ["192.168.2.0/24"]`: Home Assistant acts as subnet router, so the phone reaches the same addresses as at home (`http://192.168.2.240:8082/` for the app, `ws://192.168.2.240:8080/app` for live talk). That keeps the Chrome flag "Insecure origins treated as secure" for `http://192.168.2.240:8082` valid, which the microphone needs.
- Tailscale account: Metin's Google account, free Personal plan. In the admin console (login.tailscale.com/admin/machines) the machine "homeassistant" has the route 192.168.2.0/24 approved and key expiry disabled (otherwise the connection would stop in May 2027).
- Phone: Tailscale app, signed in with the same Google account. With the VPN on, the app works on mobile data exactly as in the WLAN.
- Why not the Speedport Smart 4 Plus WireGuard VPN: it needs a DynDNS account (free providers are reported as unreliable with the Speedport) and breaks when the public address changes; Tailscale needs neither and works behind changing addresses.
- To undo: uninstall the add on and remove the machine in the Tailscale admin console.

## Secure address for the app (HTTPS, 24 Nov 2026)

The app is also reachable at **https://leyla-metin.duckdns.org/** (port 443, live talk on wss port 8443). Reason: Metin wants the installed app to open in full screen at once, and Chrome on Android only does that from a real secure address; from the plain http address the installed app opened as a tab with the address bar.

- DuckDNS account: Metin's Google login at duckdns.org, sub domain `leyla-metin`. The name points to the private address 192.168.2.240 on purpose (add on option `ipv4`), nothing is opened to the internet. At home it resolves straight to Home Assistant, on the go the Tailscale subnet route carries it.
- Home Assistant add on **Duck DNS** (`core_duckdns`, installed 24 Nov 2026): keeps the name and gets a Let's Encrypt certificate through the DNS challenge, written to `/ssl/fullchain.pem` and `/ssl/privkey.pem` and renewed by the add on. The token was typed in by Metin himself and is stored only in that add on's options.
- GPT Live Voice maps `/ssl` read only and serves the page on 443 and live talk on 8443 as soon as the certificate is there (`app/tls.py`); a renewed certificate is loaded without a restart.
- Checked from Metin's PC on 24 Nov 2026 at 02:00: the page loads without a certificate warning, the context is secure, the wss connection opens.
- Installed on Metin's phone from this address on 24 Nov 2026 at 02:05: the app reports `mode=fullscreen` at start (`GET /api/diag`), before it was always `browser`. This is the address to use from now on.
- The old addresses (`http://192.168.2.240:8082`, `ws://192.168.2.240:8080`) keep working. With the secure address the Chrome flag "Insecure origins treated as secure" is no longer needed for the microphone.
- A new address has its own storage in the browser: the code word has to be typed once more there, and the full screen and music choices start fresh.
- To undo: uninstall the Duck DNS add on and delete its files in `/ssl`; the add on then serves only the plain addresses again.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/): `type: description`.

| Type | When |
|------|------|
| `fix:` | Bug fix |
| `feat:` | New feature |
| `chore:` | Build, config, deps, version bumps |
| `docs:` | Documentation only |
| `refactor:` | Code change that neither fixes a bug nor adds a feature |
| `test:` | Adding or updating tests |

Optional scope in parentheses: `fix(client):`, `feat(server):`, `chore(build):`.

## Keeping docs current

Read `STATUS.md` first in every new session: it holds decisions, current state and open items. Update it whenever one of them changes.

Before any work on the wake word (false wakes, missed calls, thresholds, training), read `docs/WECKWORT.md`: research of 24 Nov 2026 on how it really works, what was tried and dropped, and the plan.

Before any work on Kling clips (prompts, settings, replacing clips), read `docs/KLING_PROMPTS.md`, starting with the note at its top: the section on professional Kling 4.0 knowledge of 23 Nov 2026 is the standard and overrides older sections. Metin asked for professional knowledge only, nothing invented, and wants to be told which part of a prompt comes from the sources and which from our own log. Every new clip, with prompt, settings and result, goes into that file. Before a prompt is handed to Metin it must pass `python3 tools/kling_check.py` (brake words, movements per second, negatives, known traps); this is mandatory since clip 5030 came out in slow motion on 23 Nov 2026 because the prompt itself was slow.

| What changed                         | Update |
|--------------------------------------|--------|
| Audio format, WebSocket protocol, control messages | This file (contract) |
| Server tools, config, Docker         | `openai_realtime_voice/AGENTS.md` |
| Client firmware, ESPHome, hardware  | `home-assistant-voice-pe/AGENTS.md` |
| Deployment, owner setup              | This file (deployment) |
| Release notes, version history       | `CHANGELOG.md` |

If a change affects how the two components talk, update this file. If it’s internal to one component, update that component’s `AGENTS.md`.
