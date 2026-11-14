# Changelog

## Unreleased

### Leyla fork (deployed setup, 13 Nov 2026)

- Own wake word "Hallo Leyla" (`hallo_leyla.json`, 99% cutoff, gain factor 4). "Okay Nabu" and "Hey Mycroft" are removed on the device.
- Announcements (for example "Mama, X calls you on WhatsApp") play pre-recorded clips from a cache in Leyla's own voice, the TV is turned down before and restored after (add on 2.51.0 to 2.52.0).
- Add on 2.54.6: more server modules (phrases, tool link, session end, output link), main.py from 1475 to 1104 lines, behaviour unchanged.
- Server refactor into modules (night, live link, after talk, announce voice, pacing, automation edit), `credit_balance_exhausted` counts as used up credit (add on 2.52.1 to 2.52.7).
- Add on 2.54.0: option `backend_reasoning_effort` (minimal, low, medium, high) for the backend model of GPT Live delegation; unset keeps the model default. Lower effort should shorten the long wait after a web search.
- Add on 2.55.12: persona rule for personal small talk (how was your day), after a test where she asked back what was meant.
- Add on 2.55.13: memory page paints the dark blue background at once (no grey page before the start animation).
- Add on 2.60.8: Leyla's rules (`app/persona.py`) tightened without dropping a rule: doubled statements merged (name only when sure, part of the family, thread rules, question rules), long example pairs shortened. Measured with all options on: 13631 to 12147 characters (minus 11 percent), 2247 to 1990 words, 54 to 50 points; all 242 tests pass, including the checks for every core rule. Metin reads the result in the app (So ist Leyla) and listens for changes in her behaviour.
- Add on 2.60.7: NOCH OFFEN lists only people who talked with Leyla themselves (their profile has "Spricht" or "Zuletzt"); a name that was only mentioned gets a profile but no open questions until that person talks with her, because she asks only the person. The memory step fills "Spricht" only when the person talked with Leyla.
- Add on 2.60.6: memory step: chain for new names made explicit. When Leyla asked about an unknown name and someone said who it is, a profile is made at once even with only name and relation ("Person: Ali | Zugehörigkeit: Nachbar") and filled in later; nothing is stored when it was said to be from TV, radio or news or nobody of ours. (Metin, 14 Nov 2026.)
- Add on 2.60.5: persona: the rule for unknown names no longer assumes she can tell names from TV or news apart (she cannot); she is curious about every unknown name and drops it at once when told it is from the TV or nobody of ours. (Metin, 14 Nov 2026.)
- Add on 2.60.4: persona: "keep the name until the end" replaced, because several people may talk one after another. Signs that someone else talks: the language changes, someone speaks about the known person in the third person, someone is addressed by another name, or something does not fit the profile; after such a sign, a longer silence or a new "Hallo Leyla" the speaker counts as unknown and she talks without a name. Before anything personal from a profile she asks "Wer spricht gerade?" when there was such a sign or the introduction was a while ago. (Metin's criteria, 14 Nov 2026.)
- Add on 2.60.3: persona: removed the rule "someone who explicitly will not say their name: she does not talk to strangers and ends the conversation"; it contradicted the other rules about unknown people (Metin, from the rules view of the app).
- Add on 2.60.2: persona: only what Mama confides (sorrow, worry, health, personal) stays between her and Leyla; for everybody else Metin is the trusted person as before. Insults are never a confidence, also from Mama and also in a sad talk: the rudeness rule always applies and she says she will tell Metin. The rudeness report tells only the rude part and leaves out what Mama confided in the same talk. (Metin found the contradiction in the new rules view of the app.)
- Add on 2.60.1: persona: the rule for personal questions ("Wie war dein Tag?") no longer tells her to guess the most likely meaning when something is unclear; she answers the question as it sounds and asks once only when she really understood nothing (Metin: she never guesses).
- Add on 2.60.0: Leyla app: button "So ist Leyla" (only after the code word) shows all of Leyla's rules read only, section by section, as she gets them, without memory and with the code word replaced by "(dein Codewort)"; changes still go through Claude so rules do not contradict each other.
- Add on 2.59.0: Leyla app: "+ Neuer Eintrag" under every list (empty, duplicate or over 700 characters refused), and Metin's private list opens after typing the code word (exact words, the name Leyla may be left out; 5 wrong tries lock it for 5 minutes; the code word is entered once per phone and remembered there in the browser storage, never in a link; other devices still need it; "Private Liste schließen" hides the list and forgets the code on that phone). Mama's confidential list is never shown.
- Add on 2.58.0: lamp colours in the Leyla app (section Lampenfarben below the lists): one colour each for listening and thinking or searching, two for speaking (quiet and loud), each with a Testen button that shows the colour for 4 s and then puts the lamps back (not during a conversation), Standardfarben, and Lampen zurücksetzen for a lamp left in a show colour. Stored in `/data/lamp_colors.json`. Less load on the Matter lamps against timeouts like the one on 14 Nov: at most two commands a second (was three), the loudness smoothed over about 0.25 s and taken in 5 steps; simulated over 60 s of speech 2.73 commands a second before, about 0.4 after.
- Add on 2.57.22: lamp show restore made safe. On 14 Nov 2026 at 19:19 Lamba 1 did not answer three commands (Matter timeout, `Operation aborted` in the Home Assistant log), the restore at the end was lost, and from the next talk on its stuck blue was taken as its normal state, so it stayed on. Now the state before the show is kept in `/data/lamp_show.json` as pending until the lamp really reports it again (checked after each restore), a failed restore is tried 3 times, then again in the background after 10, 30, 90 and 300 s and at the next add on start, the next talk starts from the pending state, a show colour (blue to magenta or cyan at full strength) is never learned as a lamp's normal setting, reading the lamps waits for a running restore, and both lamps are restored at the same time (Lamba 2 no longer waits about 1.2 s for Lamba 1).
- Add on 2.57.21: hidden list `confidential` for what Mama confides (sorrow, worry, health): stored in the memory file only for Leyla, never on the memory page, in a to-do list, in the log or in the nightly cleanup, and `forget` never touches it. Entries are "Aktuell bis" states that expire after about two weeks or are removed by the summarizer when she says it is over. Leyla may follow up gently once, only with Mama and only after Mama said she is alone. Only when she is sure it is Mama, never guessed. (Metin: it must be deleted again when no longer current, like the stomach ache entry.)
- Add on 2.57.20: persona scenario 2 of the character list: when someone, especially Mama, says something sad or worrying, she listens warmly, comforts without advice, asks at most one gentle question, and keeps it between the two of them (never tells Metin, does not bring it up later). The memory step never writes what Mama confides (mood, health, worries) into the list that Metin can read in his app. Only an acute danger falls under the safety rule. (Metin: "das bleibt privat bei Leyla und Mama".)
- Add on 2.57.19: persona: after a couple word from an unknown person, a claim to be Metin is met with playful skepticism ("Soso, das könnte jeder sagen") until the code word falls; she never reveals how she recognises him. Outside couple words nothing changes (a general version was dropped, it would have made her doubt Metin whenever he introduces himself).
- Add on 2.57.18: persona: when someone whose name she has not learned from him says a couple word (bitanem, aşkım, sevgilim, mein Schatz), she reacts at once, wants to know who it is, and if it is not Metin she declines cleverly ("Mein Herz ist schon vergeben"). Metin counts as known only when he says so himself or names the code word, never by guessing. canım and tatlım are normal. (Metin's wording, 14 Nov 2026; earlier broader versions were reverted.)
- Firmware `leyla_voice` (14 Nov 2026, 17:40): fixed the random mid conversation stop (15:54 and 17:32, both while she was replying). Cause: the 20 s inactivity check used an unsigned time difference, and when the last audio frame arrived a few milliseconds after the loop read the clock, the difference wrapped to about 4 billion and the conversation ended as `auto_stop`. The check is now signed; a test reproduces the failure on the old code.
- Add on 2.57.17: announcements add no greeting or address of their own (she had said "Hallo, ihr Lieben" in German before a Turkish text) and only use the language of the content; the breath in comes without a word.
- Add on 2.57.16: `froh: true` no longer laughs (every placement sounded staged, Metin); it keeps the audible breath in, a happy voice and a hearable smile.
- Add on 2.57.15: `froh: true` says explicitly that she does not laugh at the end of the announcement (in 2.57.14 she laughed at the end, which sounded unnatural to Metin).
- Add on 2.57.14: the evening lights announcement is Turkish only (Metin: drop the German part; Mama speaks only Turkish). `froh: true` without `zweisprachig` laughs after the first sentence; single language announcements may have three short sentences instead of two (the evening text has three facts).
- Add on 2.57.13: the laugh of `froh: true` is a required step (a real "Haha" or "Hihi" after the first German sentence); in 2.57.12 she skipped it. The breath in before the first word works (Metin).
- Add on 2.57.12: the soft breath before the first word was inaudible because the announcement recorder dropped everything below the speech threshold; it now starts at peak 30 (idle frames are exactly 0). `froh: true` laughs only once in total (in the first part), the second part was a synchronous copy and sounded artificial. If the breath is still not audible, the fallback is a short "hmm, ok" instead.
- Add on 2.57.11: `froh: true` starts with a soft audible breath in, as if preparing to speak (Metin).
- Add on 2.57.10: `froh: true` now laughs once in between instead of at the start (Metin did not like the laugh at the start).
- Add on 2.57.9: optional event data `froh: true` for `leyla_announce`: she starts with a short happy laugh and sounds glad. Used by the evening lights automation, whose text now also wishes a nice evening.
- Add on 2.57.8: announcement prompt puts the facts rule first and the delivery (warmth, smile, melody) last. With 2.57.7 the numbers were right but the voice was flat, because the strict facts rule came after the style.
- Add on 2.57.7: announcements must keep every number and the time exactly as written (nothing left out, converted or added). In a test on 14 Nov 2026 she left out the time and said the sun sets in one minute instead of 15 ("in her own words" let her change facts).
- Add on 2.57.6: in Turkish announcements (and the Turkish pass of bilingual ones) numbers and times are spoken in Turkish; she had said the time in German (16:44 test, 14 Nov 2026).
- Add on 2.57.5: announcements are warm again (smile in the voice, lively, normal volume). The calm wording from 13 Nov 2026 (9529ad6, meant for `direkt` announcements) made the voice sound like a standard assistant instead of Leyla.
- Add on 2.57.4: bilingual announcements (`zweisprachig: true`) ask for two separate passes, all German, then all Turkish. Before, the prompt also demanded at most two short sentences, so at 16:31 on 14 Nov 2026 the sunset announcement came out half Turkish, half German.
- Add on 2.57.3 and firmware `leyla_voice` (14 Nov 2026): the device reports why it ended a conversation (`{"type":"stopped","reason":...,"ms":...}`, reasons external, auto_stop, server_disconnect, farewell_done, farewell_timeout, quota, socket_closed, connect_failed, low_heap) and logs it as a warning; the server logs `Device ended the conversation: <reason> after <ms> ms`. Added after Leyla switched off mid conversation at 15:54 and only the device knew why.
- Firmware `leyla_voice` (14 Nov 2026): a 15 ms ramp to zero and 5 ms fade in when the speaker runs dry was tried against the click at the end of a sentence and reverted after 13 minutes because the speech stuttered.
- Add on 2.57.2: fix, the announcement server (messages, "Mama, X calls you") moves to port 8084; since 2.55.0 the memory page took 8082 first and the announcements could not start.
- Add on 2.57.1: maskable app icon (full square) so the launcher shows the Leyla icon as large as other shortcuts.
- Add on 2.57.0: memory page folders, entries with points (Person profiles and anything with " | ") open as a folder where every point is its own card to tick, edit, delete, reorder and add; storage format unchanged.
- Add on 2.56.1: lamp show always at 100 percent (the breathing is in the colour); a lamp that was off is set back to its last known strength before it is switched off.
- Add on 2.56.0: lamp show, the rear lamps (Lamba 1 and 2, also from off) follow the conversation in the icon colours (cyan, violet, breathing blue to magenta with her voice) and return to their old state afterwards; options `lamp_show` and `lamp_show_lights`.
- Add on 2.55.15: soft edges on the server (last 15 ms of a reply faded out, next audio faded in over 5 ms) against the click at the end of a sentence; start of a reply waits 15 ms more for the held back tail.
- Add on 2.55.14: farewell detection knows the spellings "bay bay", "bai bai", "bye-bye" (the speech to text wrote "Bay bay", so she did not hang up until the idle timeout, 180 s session).
- Add on 2.54.7: memory block cap 15000 characters (was 9000). Add on 2.55.0 to 2.55.11 (3 to 11: start animation with a ring that fills in cyan to violet around the icon for 2 s, futuristic synth tones (sweeps, filter, echo) on tick, untick, pick up, drop, save and delete with an on off button, manifest ready for a real install without the Chrome badge, neon blue and violet design like the icon, own icon, the KI app icon from Metin): memory page on port 8082 (`app/memory_web.py`): open lists with a tick box per entry, a delete button, tap to edit the text and long press then drag to reorder or move an entry to another list, refreshes itself, no login, private list never shown.
- Project notes: STATUS.md (decisions, state, open items) and home-assistant-voice-pe/DEPLOYED.md (live config differences).

### Upstream changes before the fork (kept for reference)

### Features

- **Dual pipeline support** — the device now supports two voice pipelines:
  - **OpenAI (ChatGPT)**: "Okay Nabu" / single-click button.
  - **HA Assist**: "Hey Mycroft" / double-click button → local Home Assistant Assist pipeline (Speech-to-Phrase STT → Assist → Piper TTS) for smart home commands.
- Wake word routing based on `micro_wake_word`'s detected wake word string.
- "Hey Jarvis" is no longer a wake word. "Hey Mycroft" uses a 99% probability cutoff to reduce false wakes.
- Each detected wake word is logged at INFO and fired as the Home Assistant event `esphome.wake_word_detected` (data: `wake_word`) so false wakes can be attributed. Requires `homeassistant_services: true` under `api:`.
- Mutual exclusion — only one pipeline active at a time; starting one stops the other.
- HA Assist uses ESPHome's built-in `voice_assistant` component with the existing media player for TTS.

### Fixes

- HA Assist microphone uses XMOS channel 0 (the speech-recognition channel) with ESP-side noise suppression and auto gain off, matching the stock Voice PE firmware. On channel 1 with ESP-side processing, HA often missed speech and garbled the first word.

## 1.0.0

First public release.

### Features

- **Speech-to-speech voice assistant** using the OpenAI Realtime API (GA) with server-side VAD for natural turn-taking.
- **Web search** via `search_web` tool — calls the OpenAI Responses API for live information (weather, news, etc.).
- **Conversation lifecycle** — back-and-forth in a single session until the user says goodbye, presses the button, or times out. Each wake word starts a fresh session.
- **Phase protocol** — server sends `thinking`, `replying`, and `searching` phases for client LED/UX feedback. Client derives `listening` locally to avoid phase races.
- **Interrupt** — say the wake word while the assistant is speaking to interrupt and ask something new.
- **Configurable voice, model, and web search model** — `voice`, `realtime_model`, and `web_search_model` options in the addon config.
- **Audio pacing** — token-bucket sender matches playback rate so the ESP32 buffer doesn't overflow.
- **Tool call deduplication** — duplicate in-flight `search_web` calls for the same query are collapsed.
- **Optional audio recording** — save input/output WAVs for debugging.
- **ESP32-S3 Voice PE client** — ESPHome firmware with wake word detection, audio resampling, LED feedback, button, and mute switch.
