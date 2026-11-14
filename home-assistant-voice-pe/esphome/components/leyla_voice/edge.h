#pragma once
// Soft edges for the reply audio. When the speaker runs dry (end of a reply or a pause in it) the signal
// would jump from its last value to zero, which is heard as a click. This appends a short ramp down to zero
// at that moment and fades the next audio in. Pure code, no ESPHome dependencies, tested on the computer.
#include <cstddef>
#include <cstdint>

namespace leyla {

class EdgeSmoother {
 public:
  static constexpr size_t kFadeOut = 360;  // 15 ms at 24 kHz
  static constexpr size_t kFadeIn = 120;   // 5 ms at 24 kHz

  // A reply starts: the first audio is faded in, nothing is left over.
  void start() {
    last_ = 0;
    tail_sent_ = false;
    fade_in_ = true;
  }

  // Audio that is about to be played: fades in when it follows a ramp or the start, remembers the last sample.
  void on_play(int16_t *s, size_t n) {
    if (n == 0) return;
    if (fade_in_) {
      size_t m = n < kFadeIn ? n : kFadeIn;
      for (size_t i = 0; i < m; i++) s[i] = (int16_t) ((int32_t) s[i] * (int32_t) (i + 1) / (int32_t) (kFadeIn + 1));
      fade_in_ = false;
    }
    last_ = s[n - 1];
    tail_sent_ = false;
  }

  // The speaker has nothing left: writes the ramp from the last sample down to zero into out (room for kFadeOut
  // samples) and returns its length, or 0 when the signal is already at zero or the ramp was written before.
  size_t make_tail(int16_t *out) {
    if (tail_sent_ || last_ == 0) return 0;
    for (size_t i = 0; i < kFadeOut; i++)
      out[i] = (int16_t) ((int32_t) last_ * (int32_t) (kFadeOut - 1 - i) / (int32_t) kFadeOut);
    tail_sent_ = true;
    fade_in_ = true;
    last_ = 0;
    return kFadeOut;
  }

 private:
  int16_t last_{0};
  bool tail_sent_{false}, fade_in_{true};
};

}  // namespace leyla
