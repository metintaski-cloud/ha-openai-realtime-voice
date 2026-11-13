#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>

namespace esphome {
namespace voice_assistant_websocket {

// Slow automatic gain for the mono microphone signal that goes to the server.
// Quiet speakers are lifted towards a target level, loud speakers are left alone
// (gain never drops below 1), pauses and background noise do not pump the gain,
// and a soft limiter keeps peaks from clipping hard. No ESPHome dependencies.
class MicAgc {
 public:
  void configure(float max_gain, float target_rms, float noise_floor_rms) {
    this->max_gain_ = max_gain < 1.0f ? 1.0f : max_gain;
    this->target_rms_ = target_rms;
    this->noise_floor_ = noise_floor_rms;
    this->gain_ = this->max_gain_ < INITIAL_GAIN ? this->max_gain_ : INITIAL_GAIN;
  }

  bool enabled() const { return this->max_gain_ > 1.0f; }
  float gain() const { return this->gain_; }
  float last_rms() const { return this->last_rms_; }

  // Processes one chunk in place. sample_rate is only used to turn time constants into per chunk steps.
  void process(int16_t *samples, size_t n, float sample_rate) {
    if (n == 0 || !this->enabled()) {
      return;
    }
    float sum = 0.0f;
    for (size_t i = 0; i < n; i++) {
      sum += (float) samples[i] * (float) samples[i];
    }
    float rms = std::sqrt(sum / (float) n);
    this->last_rms_ = rms;

    float start_gain = this->gain_;
    if (rms > this->noise_floor_) {
      float wanted = this->target_rms_ / rms;
      if (wanted > this->max_gain_) wanted = this->max_gain_;
      if (wanted < 1.0f) wanted = 1.0f;
      float dt = (float) n / sample_rate;
      // Loud passages pull the gain down fast, quiet ones raise it slowly (no pumping).
      float tau = wanted < this->gain_ ? ATTACK_TAU_S : RELEASE_TAU_S;
      this->gain_ += (wanted - this->gain_) * (1.0f - std::exp(-dt / tau));
    }
    // Below the noise floor the gain is held, so noise is never chased and the next word starts level.

    float step = (this->gain_ - start_gain) / (float) n;
    float g = start_gain;
    for (size_t i = 0; i < n; i++) {
      g += step;
      samples[i] = soft_limit((float) samples[i] * g);
    }
  }

  static int16_t soft_limit(float x) {
    const float knee = 24000.0f;
    const float room = 32767.0f - knee;
    float a = x < 0 ? -x : x;
    if (a > knee) {
      a = knee + room * std::tanh((a - knee) / room);
    }
    if (a > 32767.0f) a = 32767.0f;
    return (int16_t) (x < 0 ? -a : a);
  }

 private:
  static constexpr float INITIAL_GAIN = 2.0f;
  static constexpr float ATTACK_TAU_S = 0.05f;
  static constexpr float RELEASE_TAU_S = 1.5f;
  float max_gain_{1.0f};
  float target_rms_{3000.0f};
  float noise_floor_{150.0f};
  float gain_{1.0f};
  float last_rms_{0.0f};
};

}  // namespace voice_assistant_websocket
}  // namespace esphome
