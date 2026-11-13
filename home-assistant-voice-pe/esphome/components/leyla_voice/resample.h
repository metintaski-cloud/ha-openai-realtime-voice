#pragma once
// Streaming linear resampler for 16 bit mono audio, upsampling only (in_rate <= out_rate), which is
// all the device needs (16 to 24 kHz for the microphone, 24 to 48 kHz for the speaker). It keeps its
// position between blocks, so block borders make no clicks and the output length follows the rate
// ratio exactly over time.
#include <cstddef>
#include <cstdint>

namespace leyla {

class Resampler {
 public:
  Resampler(uint32_t in_rate, uint32_t out_rate) : in_(in_rate), out_(out_rate) {}

  // Writes at most cap samples and returns how many. Samples that do not fit are dropped and
  // counted in dropped(); size cap as n * out_rate / in_rate + 2 to never lose any.
  size_t process(const int16_t *in, size_t n, int16_t *out, size_t cap) {
    size_t w = 0;
    for (size_t i = 0; i < n; i++) {
      int16_t cur = in[i];
      // pos_ is the place of the next output sample after prev_, in 1/out_ of an input step.
      while (pos_ < out_) {
        if (w < cap) {
          out[w++] = (int16_t) (prev_ + (int32_t) (((int64_t) (cur - prev_) * pos_) / out_));
        } else {
          dropped_++;
        }
        pos_ += in_;
      }
      pos_ -= out_;
      prev_ = cur;
    }
    return w;
  }
  uint32_t dropped() const { return dropped_; }
  void reset() { prev_ = 0; pos_ = 0; dropped_ = 0; }

 private:
  uint32_t in_, out_;
  int16_t prev_{0};
  uint32_t pos_{0};
  uint32_t dropped_{0};
};

}  // namespace leyla
