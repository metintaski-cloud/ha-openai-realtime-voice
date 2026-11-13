# leyla_voice (in development)

Own component for the conversation between the Voice PE and the server, see `../../../leyla_voice_spec.md` and `../../../REWRITE_PLAN.md`. Written from the contract, not from the old `voice_assistant_websocket`.

Done (step 2): the pure logic, header only and without ESPHome dependencies:
- `gain.h` slow software gain with soft limiter
- `resample.h` streaming linear upsampler (16 to 24 kHz, 24 to 48 kHz)
- `ring_buffer.h` fixed size buffer that counts what it had to drop
- `message.h` reader for the server's control messages
- `state_machine.h` all states, transitions and timeouts as events in, effects out

Tests run on the computer: `make -C tests` (g++, address and undefined behaviour checks). They were checked against deliberate bugs (a wrong resampler, no interrupt guard, gain below 1), which they catch.

Next (step 3): the ESPHome glue (socket, microphone, speaker, callbacks) that carries out the effects, compiled as `leyla_voice` next to the old component.
