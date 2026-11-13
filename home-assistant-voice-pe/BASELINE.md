# Baseline of the current firmware component

Purpose: numbers of the current component (the one taken over from upstream) to compare with the own rewrite. Same measurements before and after, same conditions.

## How it is measured
- Server side: `/data/metrics.jsonl` in the add on (events `ready`, `first_audio`, `interrupt`, `session_end`), written since add on 2.53.0 (13 Nov 2026). Summary: median and 90th percentile per number.
- Device side (still to collect): free heap and CPU from the ESPHome log, WiFi dropouts, wake to ready on the device, interrupt reaction on the device.
- Wake behaviour: false wakes per day from the event `esphome.wake_word_detected` and the collected false wake recordings.

## Values
Collection started 13 Nov 2026 at 22:30. Fill in after a few days of normal use.
