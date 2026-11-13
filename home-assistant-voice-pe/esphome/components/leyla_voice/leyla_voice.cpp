#ifdef USE_ESP32

#include "leyla_voice.h"

#include <cstring>

#include <esp_system.h>

#include "esphome/components/audio/audio.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome {
namespace leyla_voice {

static const char *const TAG = "leyla_voice";

enum TriggerIndex : uint8_t {
  T_CONNECTED = 0, T_READY, T_THINKING, T_REPLYING, T_LISTENING, T_SEARCHING, T_STOPPED,
  T_DISCONNECTED, T_ERROR, T_QUOTA,
};

LeylaVoice::LeylaVoice() { this->lock_ = xSemaphoreCreateMutex(); }

void LeylaVoice::setup() {
  this->machine_ = leyla::Machine(this->config_);
  auto info = this->mic_->get_audio_stream_info();
  if (info.get_sample_rate() > 0 && info.get_sample_rate() <= kWireRate)
    this->mic_resampler_ = leyla::Resampler(info.get_sample_rate(), kWireRate);
  this->mono_.reserve(2048);
  this->wire_.reserve(4096);
  this->mic_->add_data_callback([this](const std::vector<uint8_t> &data) { this->on_mic_data_(data); });
}

void LeylaVoice::dump_config() {
  ESP_LOGCONFIG(TAG, "Leyla voice:");
  ESP_LOGCONFIG(TAG, "  Server: %s", this->url_.c_str());
  ESP_LOGCONFIG(TAG, "  Auto stop: %u ms, full duplex: %s", (unsigned) this->config_.auto_stop_ms,
                YESNO(this->full_duplex_));
  ESP_LOGCONFIG(TAG, "  Microphone gain: %s (max %.1f)", this->gain_.enabled() ? "on" : "off", this->gain_.gain());
}

// ---------- actions ----------

void LeylaVoice::start() {
  uint32_t now = millis();
  xSemaphoreTake(this->lock_, portMAX_DELAY);
  this->rx_.clear();
  this->tx_.clear();
  this->carry_has_ = false;
  xSemaphoreGive(this->lock_);
  this->play_len_ = this->play_off_ = 0;
  this->ev_connected_ = this->ev_closed_ = this->ev_error_ = false;
  this->texts_.clear();
  this->started_ms_ = now;
  this->ready_ms_ = this->first_reply_ms_ = this->sent_frames_ = 0;
  this->apply_(this->machine_.start(now, esp_get_free_heap_size()), now);
}

void LeylaVoice::stop() {
  uint32_t now = millis();
  this->apply_(this->machine_.stop(now), now);
}

void LeylaVoice::interrupt() {
  uint32_t now = millis();
  this->apply_(this->machine_.interrupt(now), now);
}

// ---------- effects ----------

void LeylaVoice::fire_(uint8_t index) {
  if (index < kTriggers && this->triggers_[index] != nullptr) this->triggers_[index]->fire();
}

void LeylaVoice::apply_(const leyla::Effects &e, uint32_t now) {
  if (e.close_socket) this->close_socket_();
  if (e.open_socket) this->open_socket_();
  if (e.start_mic) {
    xSemaphoreTake(this->lock_, portMAX_DELAY);
    this->tx_.clear();
    xSemaphoreGive(this->lock_);
    this->mic_resampler_.reset();
    this->ready_ms_ = now - this->started_ms_;
    this->mic_active_ = true;
  }
  if (e.stop_mic) this->mic_active_ = false;
  if (e.send_interrupt) {
    this->drop_until_ = now + this->config_.interrupt_guard_ms;
    this->send_text_("{\"type\":\"interrupt\"}");
  }
  if (e.clear_playback) {
    xSemaphoreTake(this->lock_, portMAX_DELAY);
    this->rx_.clear();
    this->carry_has_ = false;
    xSemaphoreGive(this->lock_);
    this->play_len_ = this->play_off_ = 0;
    this->playing_ = false;
    if (this->speaker_ != nullptr && !this->speaker_->is_stopped()) this->speaker_->stop();
  }
  if (e.fire_connected) this->fire_(T_CONNECTED);
  if (e.fire_ready) this->fire_(T_READY);
  if (e.fire_thinking) this->fire_(T_THINKING);
  if (e.fire_replying) this->fire_(T_REPLYING);
  if (e.fire_searching) this->fire_(T_SEARCHING);
  if (e.fire_listening) this->fire_(T_LISTENING);
  if (e.fire_quota) this->fire_(T_QUOTA);
  if (e.fire_error) this->fire_(T_ERROR);
  if (e.fire_disconnected) this->fire_(T_DISCONNECTED);
  if (e.fire_stopped) this->fire_(T_STOPPED);
  this->bot_speaking_ = this->machine_.bot_speaking();
  if (e.fire_stopped || e.fire_error || e.fire_disconnected) this->log_summary_();
}

void LeylaVoice::log_summary_() {
  xSemaphoreTake(this->lock_, portMAX_DELAY);
  uint64_t rx_drop = this->rx_.dropped(), tx_drop = this->tx_.dropped();
  xSemaphoreGive(this->lock_);
  ESP_LOGI(TAG, "Conversation over: ready after %u ms, first reply audio after %u ms, %u mic blocks sent, "
                "mic bytes dropped %llu, reply bytes dropped %llu, free heap %u",
           (unsigned) this->ready_ms_, (unsigned) this->first_reply_ms_, (unsigned) this->sent_frames_,
           (unsigned long long) tx_drop, (unsigned long long) rx_drop, (unsigned) esp_get_free_heap_size());
}

// ---------- socket ----------

void LeylaVoice::open_socket_() {
  if (this->socket_ != nullptr) return;
  esp_websocket_client_config_t cfg = {};
  cfg.uri = this->url_.c_str();
  cfg.buffer_size = 4096;
  cfg.task_stack = 6144;
  cfg.disable_auto_reconnect = true;
  cfg.network_timeout_ms = 5000;
  this->socket_ = esp_websocket_client_init(&cfg);
  if (this->socket_ == nullptr) {
    ESP_LOGE(TAG, "Could not create the WebSocket client");
    this->ev_closed_ = true;
    return;
  }
  esp_websocket_register_events(this->socket_, WEBSOCKET_EVENT_ANY, &LeylaVoice::socket_event_, this);
  if (esp_websocket_client_start(this->socket_) != ESP_OK) {
    ESP_LOGE(TAG, "Could not start the WebSocket client");
    this->close_socket_();
    this->ev_closed_ = true;
  }
}

void LeylaVoice::close_socket_() {
  if (this->socket_ == nullptr) return;
  esp_websocket_client_handle_t handle = this->socket_;
  this->socket_ = nullptr;
  esp_websocket_unregister_events(handle, WEBSOCKET_EVENT_ANY, &LeylaVoice::socket_event_);
  // Closing and destroying waits for the client task, so it is done off the main loop
  if (xTaskCreate(&LeylaVoice::cleanup_task_, "leyla_ws_end", 4096, handle, 1, nullptr) != pdPASS) {
    esp_websocket_client_destroy(handle);
  }
}

void LeylaVoice::cleanup_task_(void *handle) {
  auto h = static_cast<esp_websocket_client_handle_t>(handle);
  esp_websocket_client_close(h, pdMS_TO_TICKS(1000));
  esp_websocket_client_destroy(h);
  vTaskDelete(nullptr);
}

void LeylaVoice::send_text_(const char *text) {
  if (this->socket_ != nullptr && esp_websocket_client_is_connected(this->socket_))
    esp_websocket_client_send_text(this->socket_, text, strlen(text), pdMS_TO_TICKS(200));
}

void LeylaVoice::socket_event_(void *args, esp_event_base_t, int32_t id, void *data) {
  static_cast<LeylaVoice *>(args)->on_socket_event_(id, static_cast<esp_websocket_event_data_t *>(data));
}

// Runs in the socket task: only copies, never decides.
void LeylaVoice::on_socket_event_(int32_t id, esp_websocket_event_data_t *d) {
  switch (id) {
    case WEBSOCKET_EVENT_CONNECTED:
      this->ev_connected_ = true;
      break;
    case WEBSOCKET_EVENT_DISCONNECTED:
    case WEBSOCKET_EVENT_CLOSED:
      this->ev_closed_ = true;
      break;
    case WEBSOCKET_EVENT_ERROR:
      this->ev_error_ = true;
      break;
    case WEBSOCKET_EVENT_DATA: {
      if (d == nullptr || d->data_len <= 0) break;
      if (d->op_code == 0x2) {  // binary: reply audio
        if ((int32_t) (this->drop_until_.load() - millis()) > 0) break;
        const uint8_t *p = reinterpret_cast<const uint8_t *>(d->data_ptr);
        size_t len = (size_t) d->data_len;
        if (xSemaphoreTake(this->lock_, pdMS_TO_TICKS(20)) != pdTRUE) break;
        if (this->carry_has_) {  // keep whole 16 bit samples when a frame arrives in pieces
          uint8_t pair[2] = {this->carry_, p[0]};
          this->rx_.write(pair, 2);
          p++;
          len--;
          this->carry_has_ = false;
        }
        if (len & 1) {
          this->carry_ = p[len - 1];
          this->carry_has_ = true;
          len--;
        }
        this->rx_.write(p, len);
        xSemaphoreGive(this->lock_);
        this->last_rx_ms_ = millis();
      } else if (d->op_code == 0x1) {  // text: control message, may come in pieces
        if (xSemaphoreTake(this->lock_, pdMS_TO_TICKS(20)) != pdTRUE) break;
        if (d->payload_offset == 0) this->text_part_.clear();
        this->text_part_.append(d->data_ptr, (size_t) d->data_len);
        if (d->payload_offset + d->data_len >= d->payload_len) {
          if (this->texts_.size() < 16) this->texts_.push_back(this->text_part_);
          this->text_part_.clear();
        }
        xSemaphoreGive(this->lock_);
      }
      break;
    }
    default:
      break;
  }
}

void LeylaVoice::handle_text_(const std::string &text, uint32_t now) {
  leyla::Message m = leyla::parse_message(text.data(), text.size());
  switch (m.kind) {
    case leyla::Kind::Ready: this->apply_(this->machine_.ready(now), now); break;
    case leyla::Kind::Phase: this->apply_(this->machine_.phase(m.phase, now), now); break;
    case leyla::Kind::Disconnect: this->apply_(this->machine_.server_disconnect(now), now); break;
    case leyla::Kind::QuotaError: this->apply_(this->machine_.quota_error(now), now); break;
    case leyla::Kind::OtherError: ESP_LOGW(TAG, "Server error: %s", text.c_str()); break;
    case leyla::Kind::Unknown: break;
  }
}

// ---------- microphone ----------

// Runs in the microphone task. Never blocks: when the socket side is slow the newest audio is dropped.
void LeylaVoice::on_mic_data_(const std::vector<uint8_t> &data) {
  if (!this->mic_active_.load()) return;
  if (!this->full_duplex_ && this->bot_speaking_.load()) return;
  auto info = this->mic_->get_audio_stream_info();
  size_t bytes = info.get_bits_per_sample() / 8, channels = info.get_channels();
  if ((bytes != 2 && bytes != 4) || channels == 0) return;
  size_t frames = data.size() / (bytes * channels);
  if (frames == 0) return;
  this->mono_.resize(frames);
  for (size_t i = 0; i < frames; i++) {  // first channel only
    const uint8_t *src = data.data() + i * channels * bytes;
    if (bytes == 4) {
      int32_t v;
      memcpy(&v, src, 4);
      this->mono_[i] = (int16_t) (v >> 16);
    } else {
      int16_t v;
      memcpy(&v, src, 2);
      this->mono_[i] = v;
    }
  }
  this->gain_.process(this->mono_.data(), frames, (float) info.get_sample_rate());
  size_t cap = frames * kWireRate / (info.get_sample_rate() ? info.get_sample_rate() : kMicRate) + 4;
  this->wire_.resize(cap);
  size_t n = this->mic_resampler_.process(this->mono_.data(), frames, this->wire_.data(), cap);
  if (xSemaphoreTake(this->lock_, pdMS_TO_TICKS(5)) != pdTRUE) return;
  this->tx_.write(reinterpret_cast<const uint8_t *>(this->wire_.data()), n * 2);
  xSemaphoreGive(this->lock_);
}

void LeylaVoice::pump_mic_tx_() {
  if (this->socket_ == nullptr || !esp_websocket_client_is_connected(this->socket_)) return;
  uint8_t buf[2400];
  for (int i = 0; i < 2; i++) {
    xSemaphoreTake(this->lock_, portMAX_DELAY);
    size_t n = this->tx_.read(buf, sizeof(buf));
    xSemaphoreGive(this->lock_);
    if (n == 0) return;
    if (esp_websocket_client_send_bin(this->socket_, reinterpret_cast<const char *>(buf), n, pdMS_TO_TICKS(100)) > 0)
      this->sent_frames_++;
  }
}

// ---------- speaker ----------

void LeylaVoice::pump_speaker_(uint32_t now) {
  if (this->speaker_ == nullptr) return;
  size_t queued;
  xSemaphoreTake(this->lock_, portMAX_DELAY);
  queued = this->rx_.size();
  xSemaphoreGive(this->lock_);
  size_t pending = this->play_len_ - this->play_off_;

  if (queued == 0 && pending == 0) {
    this->wait_since_ = 0;
    // Quiet for a moment and the speaker has played everything: the reply is over
    if (this->playing_ && now - this->last_rx_ms_.load() > kDrainGapMs && !this->speaker_->has_buffered_data()) {
      this->playing_ = false;
      this->speaker_->finish();
      this->apply_(this->machine_.speaker_drained(now), now);
    }
    return;
  }
  if (!this->playing_) {
    // Collect a little first so the start does not stutter; short clips go after a short wait
    if (this->wait_since_ == 0) this->wait_since_ = now;
    size_t need = (size_t) kPrebufferMs * (kWireRate * 2 / 1000);
    if (queued + pending < need && now - this->wait_since_ < 150) return;
    this->speaker_->set_audio_stream_info(audio::AudioStreamInfo(16, 1, kWireRate));
    this->speaker_->start();
    this->playing_ = true;
    if (this->first_reply_ms_ == 0) this->first_reply_ms_ = now - this->started_ms_;
  }
  for (int i = 0; i < 4; i++) {
    if (this->play_off_ >= this->play_len_) {
      xSemaphoreTake(this->lock_, portMAX_DELAY);
      this->play_len_ = this->rx_.read(this->play_buf_, sizeof(this->play_buf_));
      xSemaphoreGive(this->lock_);
      this->play_off_ = 0;
      if (this->play_len_ == 0) break;
    }
    size_t written = this->speaker_->play(this->play_buf_ + this->play_off_, this->play_len_ - this->play_off_, 0);
    this->play_off_ += written;
    if (written == 0) break;  // the speaker is full, try again next loop
  }
}

// ---------- main loop ----------

void LeylaVoice::loop() {
  uint32_t now = millis();

  if (this->ev_connected_.exchange(false)) this->apply_(this->machine_.socket_open(now), now);

  std::vector<std::string> texts;
  xSemaphoreTake(this->lock_, portMAX_DELAY);
  texts.swap(this->texts_);
  xSemaphoreGive(this->lock_);
  for (const auto &t : texts) this->handle_text_(t, now);

  uint32_t last_rx = this->last_rx_ms_.load();
  if (last_rx != this->seen_rx_ms_) {
    this->seen_rx_ms_ = last_rx;
    this->machine_.audio_from_server(last_rx);
  }

  if (this->ev_error_.exchange(false)) ESP_LOGW(TAG, "WebSocket error");
  if (this->ev_closed_.exchange(false) && this->machine_.running()) {
    this->apply_(this->machine_.socket_closed(now), now);
    this->close_socket_();
  }

  this->pump_speaker_(now);
  this->pump_mic_tx_();
  this->apply_(this->machine_.tick(now), now);
}

}  // namespace leyla_voice
}  // namespace esphome

#endif  // USE_ESP32
