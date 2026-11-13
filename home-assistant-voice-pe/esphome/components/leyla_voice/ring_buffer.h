#pragma once
// Fixed size byte ring buffer between a producer (socket callback) and a consumer (speaker).
// Never grows. When full the newest bytes are dropped and counted, so a slow consumer shows up as a
// number instead of memory growth. Single thread use; the caller adds locking where two tasks meet.
#include <cstddef>
#include <cstdint>
#include <vector>

namespace leyla {

class RingBuffer {
 public:
  explicit RingBuffer(size_t capacity) : buf_(capacity) {}

  size_t write(const uint8_t *data, size_t len) {
    size_t room = buf_.size() - size_;
    size_t n = len < room ? len : room;
    for (size_t i = 0; i < n; i++) buf_[(head_ + size_ + i) % buf_.size()] = data[i];
    size_ += n;
    dropped_ += len - n;
    return n;
  }
  size_t read(uint8_t *out, size_t len) {
    size_t n = len < size_ ? len : size_;
    for (size_t i = 0; i < n; i++) out[i] = buf_[(head_ + i) % buf_.size()];
    head_ = (head_ + n) % buf_.size();
    size_ -= n;
    return n;
  }
  void clear() { head_ = 0; size_ = 0; }
  size_t size() const { return size_; }
  size_t capacity() const { return buf_.size(); }
  uint64_t dropped() const { return dropped_; }

 private:
  std::vector<uint8_t> buf_;
  size_t head_{0}, size_{0};
  uint64_t dropped_{0};
};

}  // namespace leyla
