# Baseline of the current firmware component

Purpose: numbers of the current component (the one taken over from upstream) to compare with the own rewrite. Same measurements before and after, same conditions.

## How it is measured
- Server side: `/data/metrics.jsonl` in the add on (events `ready`, `first_audio`, `interrupt`, `session_end`), written since add on 2.53.0 (13 Nov 2026). Summary: median and 90th percentile per number.
- Device side: Home Assistant sensors "Leyla free heap", "Leyla largest free block", "Leyla loop time" (a measure for CPU load), "Leyla WiFi signal" and "Leyla uptime" (installed 13 Nov 2026 at 23:35); read their history in Home Assistant. Still to collect: wake to ready on the device, interrupt reaction on the device.
- Wake behaviour: false wakes per day from the event `esphome.wake_word_detected` and the collected false wake recordings.

## Values
First device values (13 Nov 2026, 23:50, 8 minutes after boot, idle): WiFi signal -51 dBm (good), free heap 122 KB, largest free block 111 KB, loop time 17 ms. Look again after a conversation and after a day of uptime: a free heap that keeps sinking means a memory leak, a loop time that jumps during talking shows CPU load.
Microphone level to the server (add on 2.53.x, XMOS AGC on): Leyla speaking about rms 2600 (peak 6900), quiet about rms 380 (peak 860) in the first clean test after the reflash.
With leyla_voice built in but idle (14 Nov 2026, 00:20): free heap 107 KB, largest block 94 KB, loop time 17 ms. Cost of the idle component: about 15 KB heap, no loop time change.
Collection started 13 Nov 2026 at 22:30. Fill in after a few days of normal use.
