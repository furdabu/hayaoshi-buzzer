// PC 上で実行するユニットテスト:  pio test -e native
#include <unity.h>

#include "arbiter.h"
#include "battery_level.h"
#include "clock_sync.h"

using buzzer::Arbiter;
using buzzer::Candidate;
using buzzer::ClockSync;

static const uint8_t A[6] = {1, 1, 1, 1, 1, 1};
static const uint8_t B[6] = {2, 2, 2, 2, 2, 2};
static const uint8_t C[6] = {3, 3, 3, 3, 3, 3};

void setUp() {}
void tearDown() {}

static void test_single_press_wins_after_window() {
  Arbiter arb(50000, 5000);
  arb.reset(1000000);
  TEST_ASSERT_TRUE(arb.offer(A, 1100000, 1102000) == Arbiter::Offer::Accepted);
  Candidate w;
  TEST_ASSERT_FALSE(arb.poll(1102000 + 49999, &w));  // まだ待ち時間中
  TEST_ASSERT_TRUE(arb.poll(1102000 + 50000, &w));
  TEST_ASSERT_EQUAL_MEMORY(A, w.mac, 6);
  TEST_ASSERT_FALSE(arb.poll(1200000, &w));  // 決定は一度だけ
}

static void test_earlier_press_wins_even_if_it_arrives_later() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  // B が先に届いたが、押した時刻は A の方が 3ms 早い
  TEST_ASSERT_TRUE(arb.offer(B, 500000, 501000) == Arbiter::Offer::Accepted);
  TEST_ASSERT_TRUE(arb.offer(A, 497000, 520000) == Arbiter::Offer::Accepted);
  TEST_ASSERT_TRUE(arb.offer(C, 499000, 530000) == Arbiter::Offer::Accepted);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(551000, &w));
  TEST_ASSERT_EQUAL_MEMORY(A, w.mac, 6);
}

static void test_tie_goes_to_first_arrival() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  arb.offer(C, 400000, 401000);
  arb.offer(B, 400000, 402000);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(500000, &w));
  TEST_ASSERT_EQUAL_MEMORY(C, w.mac, 6);
}

static void test_duplicate_and_closed() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  TEST_ASSERT_TRUE(arb.offer(A, 100000, 101000) == Arbiter::Offer::Accepted);
  TEST_ASSERT_TRUE(arb.offer(A, 100000, 116000) == Arbiter::Offer::Duplicate);
  TEST_ASSERT_EQUAL(1, arb.candidateCount());
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(200000, &w));
  TEST_ASSERT_TRUE(arb.offer(B, 90000, 201000) == Arbiter::Offer::Closed);  // 決定後は無視
}

static void test_press_before_open_is_rejected() {
  Arbiter arb(50000, 5000);
  arb.reset(1000000);
  TEST_ASSERT_TRUE(arb.offer(A, 990000, 1001000) == Arbiter::Offer::TooEarly);
  // 許容誤差内なら受付開始時刻に丸めて受け付ける
  TEST_ASSERT_TRUE(arb.offer(B, 997000, 1001000) == Arbiter::Offer::Accepted);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(2000000, &w));
  TEST_ASSERT_EQUAL_MEMORY(B, w.mac, 6);
  TEST_ASSERT_EQUAL_INT64(1000000, w.pressUs);
}

static void test_future_timestamp_is_clamped_to_arrival() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  // C の時計がずれていて、届いた時刻より後の時刻を主張している
  arb.offer(C, 900000, 300000);
  arb.offer(A, 310000, 310000);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(400000, &w));
  TEST_ASSERT_EQUAL_MEMORY(C, w.mac, 6);  // 300000 に丸められて最速
  TEST_ASSERT_EQUAL_INT64(300000, w.pressUs);
}

static void test_reset_starts_new_round() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  arb.offer(A, 10000, 11000);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(100000, &w));
  arb.reset(200000);
  TEST_ASSERT_FALSE(arb.decided());
  TEST_ASSERT_TRUE(arb.offer(A, 250000, 251000) == Arbiter::Offer::Accepted);
}

static void test_capacity_limit() {
  Arbiter arb(50000, 5000);
  arb.reset(0);
  uint8_t mac[6] = {0};
  for (size_t i = 0; i < Arbiter::kMaxCandidates; ++i) {
    mac[5] = static_cast<uint8_t>(i);
    TEST_ASSERT_TRUE(arb.offer(mac, 1000 + i, 2000) == Arbiter::Offer::Accepted);
  }
  mac[4] = 1;
  TEST_ASSERT_TRUE(arb.offer(mac, 1, 2000) == Arbiter::Offer::Full);
}

static void test_clock_sync_uses_least_delayed_beacon() {
  ClockSync s;
  TEST_ASSERT_FALSE(s.synced(0, 1000000));
  // 本当の offset は +5,000,000 us。受信処理の遅れが 300 / 50 / 900 us
  s.onBeacon(10000000, 5000300);
  s.onBeacon(10100000, 5100050);
  s.onBeacon(10200000, 5200900);
  TEST_ASSERT_EQUAL_INT64(4999950, s.offset());
  TEST_ASSERT_EQUAL_INT64(10249950, s.toMaster(5250000));
  TEST_ASSERT_TRUE(s.synced(5300000, 1500000));
  TEST_ASSERT_FALSE(s.synced(5200900 + 1500001, 1500000));
}

static void test_clock_sync_window_forgets_old_samples() {
  ClockSync s;
  s.onBeacon(1000, 0);  // offset 1000 (古い値)
  for (int i = 1; i <= ClockSync::kWindow; ++i) {
    s.onBeacon(100000 * i + 500, 100000 * i);  // offset 500
  }
  TEST_ASSERT_EQUAL_INT64(500, s.offset());
  s.reset();
  TEST_ASSERT_EQUAL(0, s.sampleCount());
}

// 2 台の子機が同じビーコンで同期したとき、押した順番が正しく判定される
static void test_end_to_end_two_children() {
  ClockSync c1, c2;
  // 親機時刻 1,000,000 のビーコンを、時計の違う 2 台が受信 (受信遅れも違う)
  c1.onBeacon(1000000, 40000 + 120);
  c2.onBeacon(1000000, 9000000 + 380);
  // 子機1 は自分の時計で 40000+120+30000 に押した → 親機時刻で約 1,030,000
  // 子機2 は自分の時計で 9000000+380+29000 に押した → 親機時刻で約 1,029,000 (こちらが速い)
  const int64_t p1 = c1.toMaster(40000 + 120 + 30000);
  const int64_t p2 = c2.toMaster(9000000 + 380 + 29000);
  Arbiter arb(50000, 5000);
  arb.reset(1000000);
  arb.offer(A, p1, 1031000);  // 子機1 の方が先に届く
  arb.offer(B, p2, 1036000);
  Candidate w;
  TEST_ASSERT_TRUE(arb.poll(1090000, &w));
  TEST_ASSERT_EQUAL_MEMORY(B, w.mac, 6);
}

static void test_battery_percent() {
  TEST_ASSERT_EQUAL(0, buzzer::batteryPercent(3000));
  TEST_ASSERT_EQUAL(0, buzzer::batteryPercent(3300));
  TEST_ASSERT_EQUAL(50, buzzer::batteryPercent(3800));
  TEST_ASSERT_EQUAL(40, buzzer::batteryPercent(3750));  // 30 と 50 の中間
  TEST_ASSERT_EQUAL(100, buzzer::batteryPercent(4150));
  TEST_ASSERT_EQUAL(100, buzzer::batteryPercent(4300));
  // 電圧が上がれば残量は減らない
  int prev = 0;
  for (int mv = 3200; mv <= 4300; mv += 5) {
    const int p = buzzer::batteryPercent(mv);
    TEST_ASSERT_TRUE(p >= prev);
    prev = p;
  }
}

static void test_battery_low_hysteresis() {
  bool low = false;
  low = buzzer::batteryLow(low, 3460, 3450, 100);
  TEST_ASSERT_FALSE(low);
  low = buzzer::batteryLow(low, 3440, 3450, 100);
  TEST_ASSERT_TRUE(low);
  low = buzzer::batteryLow(low, 3500, 3450, 100);  // 少し戻っただけでは解除しない
  TEST_ASSERT_TRUE(low);
  low = buzzer::batteryLow(low, 3560, 3450, 100);  // 充電されたら解除
  TEST_ASSERT_FALSE(low);
}

static void test_battery_encoding() {
  TEST_ASSERT_EQUAL(0, buzzer::encodeBattery20mV(0));
  TEST_ASSERT_EQUAL(3700, buzzer::decodeBattery20mV(buzzer::encodeBattery20mV(3700)));
  TEST_ASSERT_EQUAL(4200, buzzer::decodeBattery20mV(buzzer::encodeBattery20mV(4195)));
  TEST_ASSERT_EQUAL(255, buzzer::encodeBattery20mV(9000));
}

static void test_battery_cutoff_needs_sustained_low() {
  buzzer::CutoffDetector cut(3200, 3);
  TEST_ASSERT_FALSE(cut.update(3100));
  TEST_ASSERT_FALSE(cut.update(3150));
  TEST_ASSERT_FALSE(cut.update(3300));  // 一度戻ったらやり直し
  TEST_ASSERT_FALSE(cut.update(3100));
  TEST_ASSERT_FALSE(cut.update(3100));
  TEST_ASSERT_TRUE(cut.update(3100));
  TEST_ASSERT_FALSE(cut.update(0));  // 測れていない値では反応しない
}

int main(int, char**) {
  UNITY_BEGIN();
  RUN_TEST(test_single_press_wins_after_window);
  RUN_TEST(test_earlier_press_wins_even_if_it_arrives_later);
  RUN_TEST(test_tie_goes_to_first_arrival);
  RUN_TEST(test_duplicate_and_closed);
  RUN_TEST(test_press_before_open_is_rejected);
  RUN_TEST(test_future_timestamp_is_clamped_to_arrival);
  RUN_TEST(test_reset_starts_new_round);
  RUN_TEST(test_capacity_limit);
  RUN_TEST(test_clock_sync_uses_least_delayed_beacon);
  RUN_TEST(test_clock_sync_window_forgets_old_samples);
  RUN_TEST(test_end_to_end_two_children);
  RUN_TEST(test_battery_percent);
  RUN_TEST(test_battery_low_hysteresis);
  RUN_TEST(test_battery_encoding);
  RUN_TEST(test_battery_cutoff_needs_sustained_low);
  return UNITY_END();
}
