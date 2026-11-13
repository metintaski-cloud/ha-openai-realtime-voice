#pragma once
// ESPHome glue of leyla_voice. All decisions are made by the pure state machine (state_machine.h);
// this class turns events (socket, microphone, speaker, timers) into machine events and carries out
// the effects. See leyla_voice_spec.md.
#ifdef USE_ESP32

#include <atomic>
#include <string>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include "esp_websocket_client.h"

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/helpers.h"
#include "esphome/components/microphone/microphone.h"
#include "esphome/components/speaker/speaker.h"

#include "gain.h"
#include "message.h"
#include "resample.h"
#include "ring_buffer.h"
#include "state_machine.h"

namespace esphome {
namespace leyla_voice {

class EventTrigger : public Trigger<> {
 public:
  void fire() { this->trigger(); }
};

class LeylaVoice : public Component {
 public:
  LeylaVoice();

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  void set_server_url(const std::string &url) { this->url_ = url; }
  void set_microphone(microphone::Microphone *mic) { this->mic_ = mic; }
  void set_speaker(speaker::Speaker *spk) { this->speaker_ = spk; }
  void set_auto_stop_timeout(uint32_t ms) { this->config_.auto_stop_ms = ms; }
  void set_full_duplex(bool on) { this->full_duplex_ = on; }
  void set_mic_gain(float max_gain, float target, float floor) { this->gain_.configure(max_gain, target, floor); }
  void set_trigger(uint8_t index, EventTrigger *trigger) {
    if (index < kTriggers) this->triggers_[index] = trigger;
  }

  // Actions and conditions of the YAML
  void start();
  void stop();
  void interrupt();
  bool is_running() const { return this->machine_.running(); }
  bool is_bot_speaking() const { return this->bot_speaking_.load(); }

 protected:
  static constexpr size_t kTriggers = 10;
  static constexpr uint32_t kMicRate = 16000, kWireRate = 24000;
  static constexpr size_t kRxBytes = 48000;       // 1 s of reply audio at 24 kHz, 16 bit
  static constexpr size_t kTxBytes = 24000;       // 0.5 s of microphone audio
  static constexpr size_t kPlayChunk = 2048;
  static constexpr uint32_t kPrebufferMs = 100;   // reply audio collected before the speaker starts
  static constexpr uint32_t kDrainGapMs = 150;    // quiet this long after the last frame: reply is over

  void apply_(const leyla::Effects &e, uint32_t now);
  void fire_(uint8_t index);
  void open_socket_();
  void close_socket_();
  void send_text_(const char *text);
  void on_mic_data_(const std::vector<uint8_t> &data);
  void pump_speaker_(uint32_t now);
  void pump_mic_tx_();
  void handle_text_(const std::string &text, uint32_t now);
  void log_summary_();

  static void socket_event_(void *args, esp_event_base_t base, int32_t id, void *data);
  static void cleanup_task_(void *handle);
  void on_socket_event_(int32_t id, esp_websocket_event_data_t *d);

  // Configuration
  std::string url_;
  microphone::Microphone *mic_{nullptr};
  speaker::Speaker *speaker_{nullptr};
  bool full_duplex_{false};
  leyla::Config config_{};
  EventTrigger *triggers_[kTriggers]{};

  // Logic
  leyla::Machine machine_;
  leyla::GainStage gain_;
  leyla::Resampler mic_resampler_{kMicRate, kWireRate};
  leyla::RingBuffer rx_{kRxBytes};  // reply audio from the socket thread to the loop
  leyla::RingBuffer tx_{kTxBytes};  // microphone audio from the microphone thread to the loop
  SemaphoreHandle_t lock_{nullptr};

  // Socket
  esp_websocket_client_handle_t socket_{nullptr};
  std::atomic<bool> ev_connected_{false}, ev_closed_{false}, ev_error_{false};
  std::vector<std::string> texts_;  // control messages, filled by the socket thread
  std::string text_part_;           // a message that arrives in pieces

  // Audio state
  std::atomic<bool> mic_active_{false};
  std::atomic<bool> bot_speaking_{false};
  std::atomic<uint32_t> drop_until_{0};      // reply frames before this time (millis) are dropped
  std::atomic<uint32_t> last_rx_ms_{0};      // time of the last reply frame
  uint32_t seen_rx_ms_{0}, wait_since_{0};
  uint8_t carry_{0};
  bool carry_has_{false};
  std::vector<int16_t> mono_;
  std::vector<int16_t> wire_;
  uint8_t play_buf_[kPlayChunk];
  size_t play_len_{0}, play_off_{0};
  bool playing_{false};

  // Diagnostics, logged once per conversation
  uint32_t started_ms_{0}, ready_ms_{0}, first_reply_ms_{0}, sent_frames_{0};
};

template<typename... Ts> class StartAction : public Action<Ts...>, public Parented<LeylaVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->start(); }
};
template<typename... Ts> class StopAction : public Action<Ts...>, public Parented<LeylaVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->stop(); }
};
template<typename... Ts> class InterruptAction : public Action<Ts...>, public Parented<LeylaVoice> {
 public:
  void play(const Ts &...x) override { this->parent_->interrupt(); }
};
template<typename... Ts> class IsRunningCondition : public Condition<Ts...>, public Parented<LeylaVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->is_running(); }
};
template<typename... Ts> class IsBotSpeakingCondition : public Condition<Ts...>, public Parented<LeylaVoice> {
 public:
  bool check(const Ts &...x) override { return this->parent_->is_bot_speaking(); }
};

}  // namespace leyla_voice
}  // namespace esphome

#endif  // USE_ESP32
