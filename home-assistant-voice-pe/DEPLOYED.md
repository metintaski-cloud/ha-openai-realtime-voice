# Deployed device config: differences to the repo template

Checked against the live file on the Mini PC on 13 Nov 2026 (1397 lines, template has 1386). The live file is `voice_pe_config.yaml` in the ESPHome Device Builder add on (slug `5c53de3b_esphome`). The repo file `voice_pe_config.yaml` is only the template.

## What differs in the live file
- Wake words: only `hallo_leyla` (model `github://metintaski-cloud/ha-openai-realtime-voice/hallo_leyla.json@main`, `sliding_window_size: 6`, `probability_cutoff` 99 percent, `gain_factor` 4). `okay_nabu` and `hey_mycroft` are removed, `micro_wake_word.enable_model: hallo_leyla` replaces them in the wake routing.
- Component source: `https://github.com/metintaski-cloud/ha-openai-realtime-voice` (template points to the just-jeb fork), `refresh: always`.
- WiFi: a second network `wifi_ssid_neu` from secrets is added.
- Voice assistant block: `full_duplex: true`, `auto_stop_timeout: 60s`, automatic gain comment says up to 6x for quiet voices.
- Log line "Wake word ignored: conversation already running" and a ready sound that only plays when the switch "Wake sound" is on.

## Keep this file true
- Whenever the live config is changed (by Claude or by hand), update the list above in the same session and commit it.
- Before relying on any value, re-check the live file instead of trusting this list. Quick check in the browser pane on the ESPHome editor page: find the element `ESPHOME-YAML-EDITOR` through the shadow roots and iframe, its `.value` holds the whole YAML. Compare line by line with the raw template from GitHub; the lines that exist only on one side are the differences.
- Change the `Checked` date at the top after every check.
