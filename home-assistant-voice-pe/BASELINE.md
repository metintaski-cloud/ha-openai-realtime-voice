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

leyla_voice first conversation (14 Nov 2026, 00:57, 40 s): ready after 1124 ms, first reply audio after 2146 ms, no dropped bytes, free heap during talking 53 KB to 62 KB, after the conversation 81 KB. Server side first_audio after last word 0.01 to 0.1 s. Mic level was hot (rms about 20000) but the old component showed the same in the next conversation, so the level is a device or room matter, not the component. Old component for comparison still to measure with the same wording: ready time on the device and reply time.

Direct comparison on the device (14 Nov 2026, 01:21 to 01:32), old component: WebSocket connected to ready 1.0 to 1.5 s (1.53, 1.07, 1.00). New component: start to ready 1.0 to 1.3 s (1.14, 1.30, 1.03, includes connect), so equal within noise, the time is dominated by the server opening the live session. Free heap after the first conversation is 81 KB with both components (106 KB only before the first conversation after boot), so the 25 KB step is not caused by leyla_voice. Server side after a finished web search it takes about 16 s until the reply starts (old component, 01:26): the biggest speed gain still on the table.
