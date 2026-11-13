#pragma once
// Fixed size byte ring buffer between a producer (socket callback) and a consumer (speaker).
// Never grows. When full the newest bytes are dropped and counted, so a slow consumer shows up as a
// number instead of memory growth. Single thread use; the caller adds locking where two tasks meet.
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace leyla {

// Where the bytes live is decided by the caller: on the device the glue points these at external RAM,
// because the internal heap is small and the audio drivers need it. On the computer plain malloc is used.
using AllocFn = uint8_t *(*) (size_t);
using FreeFn = void (*)(uint8_t *);
inline uint8_t *default_alloc(size_t n) { return static_cast<uint8_t *>(malloc(n)); }
inline void default_free(uint8_t *p) { free(p); }
inline AllocFn g_alloc = default_alloc;
inline FreeFn g_free = default_free;

class RingBuffer {
 public:
  RingBuffer() = default;
  explicit RingBuffer(size_t capacity) { acquire(capacity); }
  RingBuffer(const RingBuffer &) = delete;
  RingBuffer &operator=(const RingBuffer &) = delete;
  ~RingBuffer() { release(); }

  // The memory is only held while a conversation runs: acquire() at the start, release() at the end.
  // Returns false when the memory is not there; the buffer then has capacity 0 and drops everything.
  bool acquire(size_t capacity) {
    if (cap_ != capacity) {
      release();
      buf_ = capacity ? g_alloc(capacity) : nullptr;
      cap_ = buf_ ? capacity : 0;
    }
    head_ = 0;
    size_ = 0;
    return cap_ == capacity;
  }
  void release() {
    if (buf_) g_free(buf_);
    buf_ = nullptr;
    cap_ = 0;
    head_ = 0;
    size_ = 0;
  }

  size_t write(const uint8_t *data, size_t len) {
    size_t room = cap_ - size_;
    size_t n = len < room ? len : room;
    for (size_t i = 0; i < n; i++) buf_[(head_ + size_ + i) % cap_] = data[i];
    size_ += n;
    dropped_ += len - n;
    return n;
  }
  size_t read(uint8_t *out, size_t len) {
    size_t n = len < size_ ? len : size_;
    if (n == 0) return 0;
    for (size_t i = 0; i < n; i++) out[i] = buf_[(head_ + i) % cap_];
    head_ = (head_ + n) % cap_;
    size_ -= n;
    return n;
  }
  void clear() { head_ = 0; size_ = 0; }
  size_t size() const { return size_; }
  size_t capacity() const { return cap_; }
  uint64_t dropped() const { return dropped_; }

 private:
  uint8_t *buf_{nullptr};
  size_t cap_{0}, head_{0}, size_{0};
  uint64_t dropped_{0};
};

}  // namespace leyla
