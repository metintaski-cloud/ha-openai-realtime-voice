# Deployed device config: differences to the repo template

Checked against the live file on the Mini PC on 13 Nov 2026 (1397 lines, template has 1386). The live file is `voice_pe_config.yaml` in the ESPHome Device Builder add on (slug `5c53de3b_esphome`). The repo file `voice_pe_config.yaml` is only the template.

The template was synced with the live file on the same day (wake word, component source, full duplex, auto stop timeout, ready sound switch). What is still different is listed here.

## What still differs in the live file
- Wake words: only `hallo_leyla` (the template now matches this too) (model `github://metintaski-cloud/ha-openai-realtime-voice/hallo_leyla.json@main`, `sliding_window_size: 6`, `probability_cutoff` 99 percent, `gain_factor` 4). `okay_nabu` and `hey_mycroft` are removed, `micro_wake_word.enable_model: hallo_leyla` replaces them in the wake routing.
- WiFi: a second network `wifi_ssid_neu` from secrets is added.
- Log line "Wake word ignored: conversation already running" in the wake while running branch.
- Template still contains the routing lambda for "Hey Mycroft" which never fires.

## Keep this file true
- Whenever the live config is changed (by Claude or by hand), update the list above in the same session and commit it.
- Before relying on any value, re-check the live file instead of trusting this list. Quick check in the browser pane on the ESPHome editor page: find the element `ESPHOME-YAML-EDITOR` through the shadow roots and iframe, its `.value` holds the whole YAML. Compare line by line with the raw template from GitHub; the lines that exist only on one side are the differences.
- Change the `Checked` date at the top after every check.
