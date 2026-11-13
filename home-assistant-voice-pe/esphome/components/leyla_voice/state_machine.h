#pragma once
// The conversation state machine of the component, as pure code: events go in, a list of effects
// comes out (open the socket, fire a callback, clear the playback ...). The ESPHome glue only
// carries the effects out, so every transition and timeout can be tested on the computer.
// Specification: ../../../leyla_voice_spec.md
#include <cstdint>

namespace leyla {

enum class State : uint8_t { Idle, Connecting, WaitingReady, Listening, Thinking, Replying, Searching, Stopping };
enum class Phase : uint8_t { Thinking, Replying, Searching };

struct Effects {
  bool open_socket = false, close_socket = false, start_mic = false, stop_mic = false;
  bool send_interrupt = false, clear_playback = false;
  bool fire_connected = false, fire_ready = false, fire_thinking = false, fire_replying = false;
  bool fire_listening = false, fire_searching = false, fire_stopped = false, fire_disconnected = false;
  bool fire_error = false, fire_quota = false;
};

struct Config {
  uint32_t ready_timeout_ms = 5000;      // socket open and server ready, each, before one retry
  uint32_t auto_stop_ms = 20000;         // nothing heard from the server for this long: stop
  uint32_t searching_stop_ms = 60000;    // the same while a tool (web search) runs
  uint32_t quota_show_ms = 4000;         // how long the quota error is shown before stopping
  uint32_t interrupt_guard_ms = 300;     // drop late reply audio after an interrupt
  uint32_t farewell_max_ms = 30000;      // after a server disconnect: wait at most this for the playback
  uint32_t min_free_heap = 15000;        // refuse to start below this
};

class Machine {
 public:
  explicit Machine(Config c = Config()) : c_(c) {}

  State state() const { return state_; }
  bool running() const { return state_ != State::Idle; }
  bool bot_speaking() const { return bot_speaking_; }
  // True for a short time after an interrupt: reply audio from before it must be dropped.
  bool drop_audio(uint32_t now) const { return (int32_t) (guard_until_ - now) > 0; }

  Effects start(uint32_t now, uint32_t free_heap) {
    Effects e;
    if (state_ != State::Idle) return e;
    if (free_heap < c_.min_free_heap) { e.fire_error = true; return e; }
    state_ = State::Connecting;
    retries_ = 0;
    since_ = last_activity_ = now;
    bot_speaking_ = false;
    pending_disconnect_ = false;
    e.open_socket = true;
    return e;
  }

  Effects socket_open(uint32_t now) {
    Effects e;
    if (state_ != State::Connecting) return e;
    state_ = State::WaitingReady;
    since_ = now;
    e.fire_connected = true;
    return e;
  }

  Effects ready(uint32_t now) {
    Effects e;
    if (state_ != State::WaitingReady) return e;
    state_ = State::Listening;
    last_activity_ = now;
    e.start_mic = true;
    e.fire_ready = true;
    return e;
  }

  Effects phase(Phase p, uint32_t now) {
    Effects e;
    if (!(state_ == State::Listening || state_ == State::Thinking || state_ == State::Replying ||
          state_ == State::Searching)) return e;
    last_activity_ = now;
    switch (p) {
      case Phase::Thinking: state_ = State::Thinking; e.fire_thinking = true; break;
      case Phase::Replying: state_ = State::Replying; bot_speaking_ = true; e.fire_replying = true; break;
      case Phase::Searching: state_ = State::Searching; e.fire_searching = true; break;
    }
    return e;
  }

  // Any audio from the server keeps the conversation alive.
  void audio_from_server(uint32_t now) { last_activity_ = now; }

  // The speaker has played out everything it was given.
  Effects speaker_drained(uint32_t now) {
    Effects e;
    bot_speaking_ = false;
    if (state_ == State::Replying) {
      state_ = State::Listening;
      last_activity_ = now;
      e.fire_listening = true;
    } else if (state_ == State::Stopping && pending_disconnect_) {
      finish(e);
    }
    return e;
  }

  Effects server_disconnect(uint32_t now) {
    Effects e;
    if (!running() || state_ == State::Stopping) return e;
    if (bot_speaking_) {  // let the goodbye play out
      state_ = State::Stopping;
      pending_disconnect_ = true;
      stop_at_ = now + c_.farewell_max_ms;
      e.stop_mic = true;
    } else {
      finish(e);
    }
    return e;
  }

  Effects quota_error(uint32_t now) {
    Effects e;
    if (!running() || state_ == State::Stopping) return e;
    state_ = State::Stopping;
    pending_disconnect_ = false;
    stop_at_ = now + c_.quota_show_ms;
    e.stop_mic = true;
    e.fire_quota = true;
    return e;
  }

  Effects socket_closed(uint32_t) {
    Effects e;
    if (!running()) return e;
    state_ = State::Idle;
    bot_speaking_ = false;
    e.stop_mic = true;
    e.fire_disconnected = true;
    return e;
  }

  Effects stop(uint32_t) {
    Effects e;
    if (!running()) return e;
    finish(e);
    e.clear_playback = true;
    return e;
  }

  Effects interrupt(uint32_t now) {
    Effects e;
    bool active = state_ == State::Thinking || state_ == State::Replying || state_ == State::Searching;
    if (!active && !bot_speaking_) return e;
    if (state_ == State::Idle || state_ == State::Stopping) return e;
    state_ = State::Listening;
    bot_speaking_ = false;
    last_activity_ = now;
    guard_until_ = now + c_.interrupt_guard_ms;
    e.send_interrupt = true;
    e.clear_playback = true;
    e.fire_listening = true;
    return e;
  }

  Effects tick(uint32_t now) {
    Effects e;
    switch (state_) {
      case State::Connecting:
      case State::WaitingReady:
        if (now - since_ >= c_.ready_timeout_ms) {
          if (retries_ < 1) {  // one more try, from the socket
            retries_++;
            state_ = State::Connecting;
            since_ = now;
            e.close_socket = true;
            e.open_socket = true;
          } else {
            state_ = State::Idle;
            e.close_socket = true;
            e.fire_error = true;
          }
        }
        break;
      case State::Listening:
      case State::Thinking:
      case State::Replying:
      case State::Searching: {
        uint32_t limit = state_ == State::Searching ? c_.searching_stop_ms : c_.auto_stop_ms;
        if (now - last_activity_ >= limit) finish(e);
        break;
      }
      case State::Stopping:
        if ((int32_t) (now - stop_at_) >= 0) finish(e);
        break;
      case State::Idle:
        break;
    }
    return e;
  }

 private:
  void finish(Effects &e) {
    state_ = State::Idle;
    bot_speaking_ = false;
    pending_disconnect_ = false;
    e.close_socket = true;
    e.stop_mic = true;
    e.fire_stopped = true;
  }

  Config c_;
  State state_{State::Idle};
  bool bot_speaking_{false}, pending_disconnect_{false};
  uint8_t retries_{0};
  uint32_t since_{0}, last_activity_{0}, stop_at_{0}, guard_until_{0};
};

}  // namespace leyla
