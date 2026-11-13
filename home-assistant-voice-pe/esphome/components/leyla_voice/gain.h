#pragma once
// Slow software gain for the microphone signal that goes to the server.
// Quiet voices are lifted towards a target level, loud ones are left alone (gain never below 1),
// pauses and noise below the floor hold the gain, a soft limiter keeps peaks below full scale.
// Pure code, no ESPHome dependencies, tested on the computer.
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace leyla {

class GainStage {
 public:
  void configure(float max_gain, float target_rms, float noise_floor) {
    max_gain_ = max_gain < 1.0f ? 1.0f : max_gain;
    target_ = target_rms;
    floor_ = noise_floor;
    gain_ = max_gain_ < kStartGain ? max_gain_ : kStartGain;
  }
  bool enabled() const { return max_gain_ > 1.0f; }
  float gain() const { return gain_; }

  // Processes one block in place. sample_rate only turns the time constants into block steps.
  void process(int16_t *s, size_t n, float sample_rate) {
    if (n == 0 || !enabled()) return;
    double sum = 0;
    for (size_t i = 0; i < n; i++) sum += (double) s[i] * s[i];
    float rms = (float) std::sqrt(sum / (double) n);
    float from = gain_;
    if (rms > floor_) {
      float want = target_ / rms;
      if (want > max_gain_) want = max_gain_;
      if (want < 1.0f) want = 1.0f;
      float tau = want < gain_ ? kAttackS : kReleaseS;  // loud: down fast, quiet: up slowly
      gain_ += (want - gain_) * (1.0f - std::exp(-((float) n / sample_rate) / tau));
    }
    float step = (gain_ - from) / (float) n, g = from;
    for (size_t i = 0; i < n; i++) {
      g += step;
      s[i] = limit((float) s[i] * g);
    }
  }

  static int16_t limit(float x) {
    const float knee = 24000.0f, room = 32767.0f - knee;
    float a = x < 0 ? -x : x;
    if (a > knee) a = knee + room * std::tanh((a - knee) / room);
    if (a > 32767.0f) a = 32767.0f;
    return (int16_t) (x < 0 ? -a : a);
  }

 private:
  static constexpr float kStartGain = 2.0f, kAttackS = 0.05f, kReleaseS = 1.5f;
  float max_gain_{1.0f}, target_{3000.0f}, floor_{150.0f}, gain_{1.0f};
};

}  // namespace leyla
