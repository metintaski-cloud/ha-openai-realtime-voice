# Deployed device config: differences to the repo template

Checked against the live file on the Mini PC on 13 Nov 2026 (1397 lines, template has 1386). The live file is `voice_pe_config.yaml` in the ESPHome Device Builder add on (slug `5c53de3b_esphome`). The repo file `voice_pe_config.yaml` is only the template.

The template was synced with the live file on the same day (wake word, component source, full duplex, auto stop timeout, ready sound switch). What is still different is listed here.

## What still differs in the live file
- Wake words: only `hallo_leyla` (the template now matches this too) (model `github://metintaski-cloud/ha-openai-realtime-voice/hallo_leyla.json@main`, `sliding_window_size: 6`, `probability_cutoff` 99 percent, `gain_factor` 4). `okay_nabu` and `hey_mycroft` are removed, `micro_wake_word.enable_model: hallo_leyla` replaces them in the wake routing.
- WiFi: a second network `wifi_ssid_neu` from secrets is added.
- Log line "Wake word ignored: conversation already running" in the wake while running branch.
- Template still contains the routing lambda for "Hey Mycroft" which never fires.

- `voice_kit` `channel_0_stage` stays `AGC` (stock). Test with `NS` on 13 Nov 2026 failed: the raw voice was only about rms 100 to 250, even the software gain of up to 6x could not lift it, GPT Live heard nothing and Leyla hung up (`no_speech`). With `AGC` the level to the server is high (rms 19000 to 25000, peaks to 32766) but she understands everyone reliably. Next idea if the level must come down: keep `AGC` and lower it on the server side or find a middle XMOS setting, not `NS`.

- Extra diagnostic sensors in the live `sensor:` block (added 13 Nov 2026, for the baseline): `platform: debug` (free heap, largest free block, loop time; `debug: update_interval: 5s` already existed), `wifi_signal`, `uptime`, all named "Leyla ..." and `entity_category: diagnostic`. They show up in Home Assistant with history, so memory trends, WiFi quality and reboots can be read over days.

## Keep this file true
- Whenever the live config is changed (by Claude or by hand), update the list above in the same session and commit it.
- Before relying on any value, re-check the live file instead of trusting this list. Quick check in the browser pane on the ESPHome editor page: find the element `ESPHOME-YAML-EDITOR` through the shadow roots and iframe, its `.value` holds the whole YAML. Compare line by line with the raw template from GitHub; the lines that exist only on one side are the differences.
- Change the `Checked` date at the top after every check.

## leyla_voice test wiring (14 Nov 2026)
The live config has a `leyla_voice:` block (id leyla_voice_test) with the same LED, sound and ducking callbacks as the old component, plus the button "Leyla Test neu" (starts it only when nothing else runs and the device is not muted). Wake words still use the old component. on_stopped and on_error restart micro_wake_word. The component is also listed in external_components next to voice_assistant_websocket.
