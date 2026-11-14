// Tests for the pure logic of leyla_voice. Build and run: make -C tests
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "../esphome/components/leyla_voice/edge.h"
#include "../esphome/components/leyla_voice/gain.h"
#include "../esphome/components/leyla_voice/message.h"
#include "../esphome/components/leyla_voice/resample.h"
#include "../esphome/components/leyla_voice/ring_buffer.h"
#include "../esphome/components/leyla_voice/state_machine.h"

static int failures = 0, checks = 0;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #c); } } while (0)

using namespace leyla;

static std::vector<int16_t> sine(size_t n, float amp, float hz = 300, float rate = 16000, size_t off = 0) {
  std::vector<int16_t> v(n);
  for (size_t i = 0; i < n; i++) v[i] = (int16_t) (amp * std::sin(2 * M_PI * hz * (i + off) / rate));
  return v;
}
static float rms_of(const std::vector<int16_t> &v) {
  double s = 0;
  for (auto x : v) s += (double) x * x;
  return (float) std::sqrt(s / v.size());
}

static void test_gain() {
  GainStage g;
  g.configure(1.0f, 3000, 150);
  auto q = sine(1600, 700);
  auto copy = q;
  g.process(q.data(), q.size(), 16000);
  CHECK(!g.enabled() && q == copy);  // max gain 1 means off

  g.configure(6.0f, 3000, 150);
  float first = 0, last = 0;
  for (int block = 0; block < 100; block++) {  // 100 blocks of 100 ms of a quiet voice, rms about 350
    auto b = sine(1600, 500, 300, 16000, block * 1600);
    g.process(b.data(), b.size(), 16000);
    if (block == 0) first = rms_of(b);
    last = rms_of(b);
  }
  CHECK(last > first * 1.5f);          // quiet voice is lifted
  CHECK(g.gain() > 4.0f && g.gain() <= 6.0f);

  g.configure(6.0f, 3000, 150);
  for (int block = 0; block < 50; block++) {  // loud voice stays untouched
    auto b = sine(1600, 28000);
    g.process(b.data(), b.size(), 16000);
  }
  CHECK(g.gain() >= 1.0f && g.gain() < 1.2f);

  g.configure(6.0f, 3000, 150);
  float before = g.gain();
  for (int block = 0; block < 20; block++) {  // noise below the floor holds the gain
    auto b = sine(1600, 100);
    g.process(b.data(), b.size(), 16000);
  }
  CHECK(std::fabs(g.gain() - before) < 1e-6f);

  g.configure(12.0f, 12000, 0);
  auto loud = sine(1600, 30000);
  for (int block = 0; block < 5; block++) g.process(loud.data(), loud.size(), 16000);
  auto hot = sine(1600, 30000);
  g.process(hot.data(), hot.size(), 16000);
  int near_full = 0;
  for (auto x : hot) if (x >= 32700 || x <= -32700) near_full++;
  CHECK(near_full < 16);  // soft limiter: no flat hard clipped tops
  CHECK(GainStage::limit(40000.0f) <= 32767 && GainStage::limit(-40000.0f) >= -32767);
  CHECK(GainStage::limit(1000.0f) == 1000);
  CHECK(GainStage::limit(30000.0f) > GainStage::limit(25000.0f));  // still rising above the knee
}

static void test_resample() {
  Resampler r(16000, 24000);
  std::vector<int16_t> in(1600, 1000), out(1600 * 3 / 2 + 2);
  size_t n = r.process(in.data(), in.size(), out.data(), out.size());
  CHECK(n >= 2399 && n <= 2401);
  CHECK(out[10] == 1000 && out[n - 1] == 1000);  // constant stays constant (after the first sample)

  // Splitting into blocks gives the same output as one call
  auto s = sine(3200, 8000);
  Resampler a(16000, 24000), b(16000, 24000);
  std::vector<int16_t> one(5000), many;
  size_t n1 = a.process(s.data(), s.size(), one.data(), one.size());
  std::vector<int16_t> tmp(300);
  for (size_t i = 0; i < s.size(); i += 160) {
    size_t k = b.process(s.data() + i, 160, tmp.data(), tmp.size());
    many.insert(many.end(), tmp.begin(), tmp.begin() + k);
  }
  CHECK(many.size() == n1);
  CHECK(std::equal(many.begin(), many.end(), one.begin()));

  Resampler up(24000, 48000);
  std::vector<int16_t> ramp(100), o2(210);
  for (int i = 0; i < 100; i++) ramp[i] = (int16_t) (i * 100);
  size_t m = up.process(ramp.data(), ramp.size(), o2.data(), o2.size());
  CHECK(m == 200);
  bool mono = true;
  for (size_t i = 1; i < m; i++) if (o2[i] < o2[i - 1]) mono = false;
  CHECK(mono);

  Resampler small(16000, 24000);
  std::vector<int16_t> tiny(10);
  small.process(in.data(), 100, tiny.data(), tiny.size());
  CHECK(small.dropped() > 0);  // too small output buffer is counted, no overflow
}

static void test_ring() {
  RingBuffer rb(8);
  uint8_t a[6] = {1, 2, 3, 4, 5, 6}, o[8];
  CHECK(rb.write(a, 6) == 6 && rb.size() == 6);
  CHECK(rb.read(o, 4) == 4 && o[0] == 1 && o[3] == 4);
  CHECK(rb.write(a, 6) == 6);  // wraps around
  CHECK(rb.size() == 8);
  CHECK(rb.read(o, 8) == 8 && o[0] == 5 && o[1] == 6 && o[2] == 1 && o[7] == 6);
  CHECK(rb.size() == 0);
  uint8_t big[20] = {0};
  CHECK(rb.write(big, 20) == 8 && rb.dropped() == 12);
  rb.clear();
  CHECK(rb.size() == 0 && rb.read(o, 4) == 0);
  // memory only held while in use: released buffer is safe to touch, acquire gives it back
  rb.release();
  CHECK(rb.capacity() == 0 && rb.write(a, 4) == 0 && rb.read(o, 4) == 0 && rb.size() == 0);
  rb.acquire(8);
  CHECK(rb.capacity() == 8 && rb.write(a, 6) == 6 && rb.read(o, 6) == 6 && o[5] == 6);
}

static void test_messages() {
  auto p = [](const char *s) { return parse_message(s, std::char_traits<char>::length(s)); };
  CHECK(p("{\"type\":\"ready\"}").kind == Kind::Ready);
  CHECK(p("{ \"type\" : \"ready\" }").kind == Kind::Ready);
  Message m = p("{\"type\":\"phase\",\"phase\":\"searching\"}");
  CHECK(m.kind == Kind::Phase && m.phase == Phase::Searching);
  m = p("{\"phase\":\"replying\",\"type\":\"phase\"}");
  CHECK(m.kind == Kind::Phase && m.phase == Phase::Replying);
  CHECK(p("{\"type\":\"phase\",\"phase\":\"dancing\"}").kind == Kind::Unknown);
  CHECK(p("{\"type\":\"disconnect\",\"message\":\"bye\",\"reason\":\"x\"}").kind == Kind::Disconnect);
  CHECK(p("{\"type\":\"error\",\"code\":\"insufficient_quota\"}").kind == Kind::QuotaError);
  CHECK(p("{\"type\":\"error\",\"code\":\"other\"}").kind == Kind::OtherError);
  CHECK(p("{\"type\":\"surprise\"}").kind == Kind::Unknown);
  CHECK(p("not json at all").kind == Kind::Unknown);
  CHECK(p("").kind == Kind::Unknown);
  CHECK(p("{\"type\":").kind == Kind::Unknown);
}

static void test_machine() {
  Machine m;
  uint32_t t = 1000;
  CHECK(m.state() == State::Idle && !m.running());
  Effects e = m.start(t, 100000);
  CHECK(e.open_socket && m.state() == State::Connecting);
  CHECK(!m.start(t, 100000).open_socket);  // already running
  e = m.socket_open(t += 300);
  CHECK(e.fire_connected && m.state() == State::WaitingReady);
  e = m.ready(t += 1100);
  CHECK(e.fire_ready && e.start_mic && m.state() == State::Listening);
  e = m.phase(Phase::Thinking, t += 2000);
  CHECK(e.fire_thinking && m.state() == State::Thinking);
  e = m.phase(Phase::Replying, t += 500);
  CHECK(e.fire_replying && m.bot_speaking() && m.state() == State::Replying);
  e = m.speaker_drained(t += 3000);
  CHECK(e.fire_listening && m.state() == State::Listening && !m.bot_speaking());

  // Search extends the inactivity limit to 60 s
  e = m.phase(Phase::Searching, t += 100);
  CHECK(e.fire_searching);
  CHECK(!m.tick(t + 30000).fire_stopped);
  CHECK(m.tick(t + 60000).fire_stopped && !m.running());

  // Plain inactivity stops after 20 s
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  CHECK(!m.tick(t + 19999).fire_stopped);
  m.audio_from_server(t + 15000);
  CHECK(!m.tick(t + 30000).fire_stopped);
  e = m.tick(t + 35000);
  CHECK(e.fire_stopped && e.close_socket && e.stop_mic && !m.running());
}

static void test_machine_edges() {
  Machine m;
  uint32_t t = 0;
  // low memory refuses to start
  Effects e = m.start(t, 1000);
  CHECK(e.fire_error && !e.open_socket && !m.running());

  // ready timeout: one retry, then error
  m.start(t, 100000);
  e = m.tick(t + 5000);
  CHECK(e.close_socket && e.open_socket && m.state() == State::Connecting);
  m.socket_open(t + 5100);
  e = m.tick(t + 10200);
  CHECK(e.fire_error && e.close_socket && !m.running());

  // interrupt while she speaks
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  m.phase(Phase::Replying, t + 100);
  e = m.interrupt(t + 1000);
  CHECK(e.send_interrupt && e.clear_playback && e.fire_listening && m.state() == State::Listening);
  CHECK(m.drop_audio(t + 1100) && !m.drop_audio(t + 1400));
  CHECK(!m.interrupt(t + 1500).send_interrupt);  // nothing to interrupt now

  // server disconnect while she speaks: wait for the playback, then stop
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  m.phase(Phase::Replying, t + 100);
  e = m.server_disconnect(t + 2000);
  CHECK(m.state() == State::Stopping && !e.fire_stopped);
  e = m.speaker_drained(t + 3500);
  CHECK(e.fire_stopped && e.close_socket && !m.running());

  // server disconnect while silent: stop at once
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  e = m.server_disconnect(t + 100);
  CHECK(e.fire_stopped && !m.running());

  // quota error: show for 4 s, then stop
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  e = m.quota_error(t + 100);
  CHECK(e.fire_quota && e.stop_mic && m.state() == State::Stopping);
  CHECK(!m.tick(t + 3000).fire_stopped);
  CHECK(m.tick(t + 4200).fire_stopped && !m.running());

  // socket lost
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t);
  e = m.socket_closed(t + 500);
  CHECK(e.fire_disconnected && e.stop_mic && !m.running());

  // stop action clears the playback
  m = Machine(); t = 0;
  m.start(t, 100000); m.socket_open(t); m.ready(t); m.phase(Phase::Replying, t + 10);
  e = m.stop(t + 20);
  CHECK(e.fire_stopped && e.clear_playback && e.close_socket && !m.bot_speaking());
  CHECK(!m.stop(t + 30).fire_stopped);  // second stop does nothing

  // events in the wrong state are ignored
  m = Machine();
  CHECK(!m.ready(0).fire_ready && !m.phase(Phase::Replying, 0).fire_replying);
  CHECK(!m.socket_closed(0).fire_disconnected && !m.tick(100000).fire_stopped);

  // millis() wraps around after 49 days: the guard still works
  m = Machine();
  uint32_t big = 0xFFFFFF00u;
  m.start(big, 100000); m.socket_open(big); m.ready(big);
  m.phase(Phase::Replying, big + 10);
  m.interrupt(big + 20);
  CHECK(m.drop_audio(big + 100) && !m.drop_audio(big + 400));
}

static void test_edge() {
  EdgeSmoother e;
  e.start();
  std::vector<int16_t> a(480, 10000);
  e.on_play(a.data(), a.size());
  CHECK(a[0] < 100 && a[EdgeSmoother::kFadeIn - 1] > 9500 && a[EdgeSmoother::kFadeIn] == 10000);  // faded in once
  std::vector<int16_t> b(480, 10000);
  e.on_play(b.data(), b.size());
  CHECK(b[0] == 10000);  // no second fade in
  int16_t tail[EdgeSmoother::kFadeOut];
  size_t n = e.make_tail(tail);
  CHECK(n == EdgeSmoother::kFadeOut && tail[0] > 9900 && tail[n - 1] == 0);
  bool falling = true;
  for (size_t i = 1; i < n; i++) falling = falling && tail[i] <= tail[i - 1];
  CHECK(falling);
  CHECK(e.make_tail(tail) == 0);  // only once per gap
  std::vector<int16_t> c(480, -8000);
  e.on_play(c.data(), c.size());
  CHECK(c[0] > -100 && c[EdgeSmoother::kFadeIn] == -8000);  // next audio fades in again
  n = e.make_tail(tail);
  CHECK(n > 0 && tail[0] < -7900 && tail[n - 1] == 0);  // negative level ramps up to zero
  e.start();
  CHECK(e.make_tail(tail) == 0);  // silence needs no ramp
  std::vector<int16_t> d(10, 5000);  // shorter than the fade in
  e.on_play(d.data(), d.size());
  CHECK(d[9] < 5000 && d[9] > d[0]);
}

int main() {
  test_gain();
  test_edge();
  test_resample();
  test_ring();
  test_messages();
  test_machine();
  test_machine_edges();
  printf("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
