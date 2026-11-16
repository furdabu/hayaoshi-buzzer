// PC 上で実行するユニットテスト:  pio test -e native
#include <unity.h>

#include "arbiter.h"
#include "battery_level.h"
#include "clock_sync.h"
#include "pc_json.h"
#include "state_tracker.h"

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

// ---------------------------------------------------------------------------
//  PC 連携: 状態の変化を出来事に直す (state_tracker.h)
// ---------------------------------------------------------------------------
using buzzer::MasterState;
using buzzer::StateTracker;
using buzzer::TrackerEvent;
typedef TrackerEvent::Type Ev;

// 親機のまねをして、受信機に届く状態を作る
struct FakeMaster {
  MasterState s;
  FakeMaster() {
    s.bootId = 0x1234;
    s.round = 1;
  }
  MasterState beacon() {
    ++s.seq;
    return s;
  }
  MasterState lock(const uint8_t mac[6], uint8_t id) {
    s.locked = true;
    s.winnerId = id;
    memcpy(s.winnerMac, mac, 6);
    return beacon();
  }
  MasterState judge(uint8_t result) {
    s.lastResult = result;
    memcpy(s.lastWinnerMac, s.winnerMac, 6);
    ++s.judgeSeq;
    ++s.round;
    if (s.round == 0) s.round = 1;
    s.locked = false;
    s.winnerId = 0;
    memset(s.winnerMac, 0, 6);
    return beacon();
  }
};

static void test_tracker_first_state_only_reports_master() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  TEST_ASSERT_FALSE(t.hasState());
  TEST_ASSERT_EQUAL(1, t.update(m.beacon(), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::MasterFound);
  TEST_ASSERT_TRUE(t.hasState());
  TEST_ASSERT_EQUAL(0, t.update(m.beacon(), ev));  // 変化がなければ何も出ない
}

static void test_tracker_buzz_judge_open() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);

  TEST_ASSERT_EQUAL(1, t.update(m.lock(B, 2), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::Buzz);
  TEST_ASSERT_EQUAL(1, ev[0].round);
  TEST_ASSERT_EQUAL(2, ev[0].id);
  TEST_ASSERT_TRUE(ev[0].idKnown);
  TEST_ASSERT_EQUAL(0, t.update(m.beacon(), ev));  // 同じ回答者を 2 回知らせない

  TEST_ASSERT_EQUAL(2, t.update(m.judge(1), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::Judge);
  TEST_ASSERT_EQUAL(1, ev[0].round);
  TEST_ASSERT_EQUAL(2, ev[0].id);
  TEST_ASSERT_EQUAL(1, ev[0].result);
  TEST_ASSERT_TRUE(ev[1].type == Ev::Open);
  TEST_ASSERT_EQUAL(2, ev[1].round);

  uint8_t result = 0, id = 0;
  bool known = false;
  TEST_ASSERT_TRUE(t.lastJudge(&result, &id, &known));
  TEST_ASSERT_EQUAL(1, result);
  TEST_ASSERT_EQUAL(2, id);
  TEST_ASSERT_TRUE(known);
}

static void test_tracker_missed_lock_still_reports_buzz_first() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);
  t.learn(C, 3);  // 番号は Assign パケットで知っていた

  m.lock(C, 3);  // この状態は届かなかった
  TEST_ASSERT_EQUAL(3, t.update(m.judge(2), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::Buzz);
  TEST_ASSERT_EQUAL(1, ev[0].round);
  TEST_ASSERT_EQUAL(3, ev[0].id);
  TEST_ASSERT_TRUE(ev[1].type == Ev::Judge);
  TEST_ASSERT_EQUAL(3, ev[1].id);
  TEST_ASSERT_EQUAL(2, ev[1].result);
  TEST_ASSERT_TRUE(ev[2].type == Ev::Open);
}

static void test_tracker_missed_lock_with_unknown_id() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);

  m.lock(A, 1);  // 届かなかった。番号も知らない
  TEST_ASSERT_EQUAL(3, t.update(m.judge(1), ev));
  TEST_ASSERT_TRUE(ev[1].type == Ev::Judge);
  TEST_ASSERT_FALSE(ev[1].idKnown);
  TEST_ASSERT_EQUAL(0, ev[1].id);
}

static void test_tracker_judge_without_answerer() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);

  // だれも押していないのに判定ボタンが押された
  TEST_ASSERT_EQUAL(2, t.update(m.judge(2), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::Judge);
  TEST_ASSERT_EQUAL(0, ev[0].id);
  TEST_ASSERT_TRUE(ev[0].idKnown);
  TEST_ASSERT_TRUE(ev[1].type == Ev::Open);
}

static void test_tracker_quick_next_buzz_in_one_update() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);
  t.update(m.lock(A, 1), ev);

  // 判定のあと、次の回答者が決まるまでの状態が全部届かなかった
  m.judge(2);
  TEST_ASSERT_EQUAL(3, t.update(m.lock(B, 2), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::Judge);
  TEST_ASSERT_EQUAL(1, ev[0].round);
  TEST_ASSERT_EQUAL(1, ev[0].id);
  TEST_ASSERT_TRUE(ev[1].type == Ev::Open);
  TEST_ASSERT_EQUAL(2, ev[1].round);
  TEST_ASSERT_TRUE(ev[2].type == Ev::Buzz);
  TEST_ASSERT_EQUAL(2, ev[2].round);
  TEST_ASSERT_EQUAL(2, ev[2].id);
}

static void test_tracker_ignores_old_packets() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  const MasterState before = m.beacon();
  t.update(before, ev);
  t.update(m.lock(A, 1), ev);
  TEST_ASSERT_EQUAL(0, t.update(before, ev));  // 順番が入れかわった古い状態
  TEST_ASSERT_TRUE(t.state().locked);
}

static void test_tracker_master_restart() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  t.update(m.beacon(), ev);
  t.update(m.lock(A, 1), ev);

  FakeMaster again;
  again.s.bootId = 0x9999;
  TEST_ASSERT_EQUAL(1, t.update(again.beacon(), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::MasterRestarted);
  TEST_ASSERT_FALSE(t.state().locked);
  TEST_ASSERT_EQUAL(1, t.idOf(A));  // 番号は親機が保存しているので、覚えたままでよい
}

static void test_tracker_joining_while_locked_does_not_repeat_buzz() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  // 受信機を、回答中につないだ
  TEST_ASSERT_EQUAL(1, t.update(m.lock(A, 1), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::MasterFound);
  TEST_ASSERT_EQUAL(0, t.update(m.beacon(), ev));
  TEST_ASSERT_EQUAL(2, t.update(m.judge(1), ev));  // Buzz を出し直さない
  TEST_ASSERT_TRUE(ev[0].type == Ev::Judge);
  TEST_ASSERT_EQUAL(1, ev[0].id);
}

static void test_tracker_register_mode() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  m.s.registerMode = true;
  t.update(m.beacon(), ev);
  t.learn(A, 1);
  t.learn(B, 2);
  t.learn(A, 2);  // 番号を付け直した: A が 2 番になり、B は消える
  TEST_ASSERT_EQUAL(2, t.idOf(A));
  TEST_ASSERT_EQUAL(0, t.idOf(B));

  // 番号登録モードが終わると、次のラウンドが始まる
  m.s.registerMode = false;
  ++m.s.round;
  TEST_ASSERT_EQUAL(2, t.update(m.beacon(), ev));
  TEST_ASSERT_TRUE(ev[0].type == Ev::RegisterOff);
  TEST_ASSERT_TRUE(ev[1].type == Ev::Open);
  TEST_ASSERT_EQUAL(2, ev[1].round);
}

static void test_tracker_round_wraps_past_zero() {
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];
  m.s.round = 65535;
  t.update(m.beacon(), ev);
  t.update(m.lock(A, 1), ev);
  TEST_ASSERT_EQUAL(2, t.update(m.judge(1), ev));
  TEST_ASSERT_EQUAL(65535, ev[0].round);  // 判定されたラウンド
  TEST_ASSERT_EQUAL(1, ev[1].round);      // 0 を飛ばして 1 に戻る
}

// ---------------------------------------------------------------------------
//  PC 連携: PC へ送る JSON (pc_json.h)
// ---------------------------------------------------------------------------
static void test_json_events() {
  char buf[200];
  TrackerEvent e = {Ev::Buzz, 12, 3, true, 0};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"buzz\",\"round\":12,\"id\":3}", buf);

  e = {Ev::Judge, 12, 3, true, 1};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"judge\",\"round\":12,\"id\":3,\"result\":\"correct\"}", buf);

  e = {Ev::Judge, 12, 0, false, 2};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"judge\",\"round\":12,\"id\":null,\"result\":\"incorrect\"}",
                           buf);

  e = {Ev::Open, 13, 0, false, 0};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"open\",\"round\":13}", buf);

  e = {Ev::MasterRestarted, 1, 0, false, 0};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"master\",\"connected\":true,\"restarted\":true}", buf);

  e = {Ev::RegisterOn, 1, 0, false, 0};
  buzzer::pcjson::event(buf, sizeof(buf), e);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"register\",\"active\":true}", buf);

  buzzer::pcjson::master(buf, sizeof(buf), false, false);
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"master\",\"connected\":false}", buf);

  buzzer::pcjson::hello(buf, sizeof(buf), 1, 1, 6, 2);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"hello\",\"device\":\"hayaoshi-receiver\",\"fw\":\"1.1\",\"channel\":6,\"group\":2}",
      buf);
}

static void test_json_state() {
  char buf[200];
  StateTracker t;
  FakeMaster m;
  TrackerEvent ev[StateTracker::kMaxEvents];

  buzzer::pcjson::state(buf, sizeof(buf), true, t);  // まだ何も届いていない
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"state\",\"master\":false}", buf);

  t.update(m.beacon(), ev);
  buzzer::pcjson::state(buf, sizeof(buf), true, t);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"state\",\"master\":true,\"phase\":\"open\",\"round\":1,\"winner\":0,"
      "\"judgeSeq\":0,\"last\":null}",
      buf);

  t.update(m.lock(B, 2), ev);
  buzzer::pcjson::state(buf, sizeof(buf), true, t);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"state\",\"master\":true,\"phase\":\"locked\",\"round\":1,\"winner\":2,"
      "\"judgeSeq\":0,\"last\":null}",
      buf);

  t.update(m.judge(2), ev);
  buzzer::pcjson::state(buf, sizeof(buf), true, t);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"state\",\"master\":true,\"phase\":\"open\",\"round\":2,\"winner\":0,"
      "\"judgeSeq\":1,\"last\":{\"result\":\"incorrect\",\"id\":2}}",
      buf);

  buzzer::pcjson::state(buf, sizeof(buf), false, t);  // 親機を見失った
  TEST_ASSERT_EQUAL_STRING("{\"type\":\"state\",\"master\":false}", buf);
}

static void test_json_info() {
  char buf[640];
  buzzer::MasterInfo v;
  buzzer::pcjson::info(buf, sizeof(buf), v);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"info\",\"registered\":0,\"connected\":0,\"ids\":[],\"lowBattery\":[],"
      "\"masterBattery\":null,\"buzz\":null}",
      buf);

  v.registered = 8;
  v.connected = 3;
  v.connectedMask = 0x13;  // 1, 2, 5 番
  v.lowBatteryMask = 0x10;  // 5 番
  v.masterBatteryMv = 3980;
  v.buzzRound = 12;
  v.buzzId = 5;
  v.buzzCandidates = 2;
  v.buzzElapsedMs = 1234;
  buzzer::pcjson::info(buf, sizeof(buf), v);
  TEST_ASSERT_EQUAL_STRING(
      "{\"type\":\"info\",\"registered\":8,\"connected\":3,\"ids\":[1,2,5],\"lowBattery\":[5],"
      "\"masterBattery\":{\"mv\":3980,\"low\":false},"
      "\"buzz\":{\"round\":12,\"id\":5,\"elapsedMs\":1234,\"candidates\":2}}",
      buf);
}

static void test_json_longest_info_fits_and_overflow_gives_empty_line() {
  char buf[640];
  buzzer::MasterInfo v;
  v.registered = 64;
  v.connected = 64;
  v.connectedMask = ~0ULL;
  v.lowBatteryMask = ~0ULL;
  v.masterBatteryMv = 4200;
  v.masterBatteryLow = true;
  v.buzzRound = 65535;
  v.buzzId = 64;
  v.buzzCandidates = 64;
  v.buzzElapsedMs = 4000000000UL;
  const size_t len = buzzer::pcjson::info(buf, sizeof(buf), v);
  TEST_ASSERT_TRUE(len > 0);  // 受信機のバッファ (640 バイト) に、一番長い行が入る
  TEST_ASSERT_EQUAL(len, strlen(buf));
  TEST_ASSERT_EQUAL('}', buf[len - 1]);

  char small[40];
  TEST_ASSERT_EQUAL(0, buzzer::pcjson::info(small, sizeof(small), v));  // 途中で切れた行は送らない
  TEST_ASSERT_EQUAL_STRING("", small);
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
  RUN_TEST(test_tracker_first_state_only_reports_master);
  RUN_TEST(test_tracker_buzz_judge_open);
  RUN_TEST(test_tracker_missed_lock_still_reports_buzz_first);
  RUN_TEST(test_tracker_missed_lock_with_unknown_id);
  RUN_TEST(test_tracker_judge_without_answerer);
  RUN_TEST(test_tracker_quick_next_buzz_in_one_update);
  RUN_TEST(test_tracker_ignores_old_packets);
  RUN_TEST(test_tracker_master_restart);
  RUN_TEST(test_tracker_joining_while_locked_does_not_repeat_buzz);
  RUN_TEST(test_tracker_register_mode);
  RUN_TEST(test_tracker_round_wraps_past_zero);
  RUN_TEST(test_json_events);
  RUN_TEST(test_json_state);
  RUN_TEST(test_json_info);
  RUN_TEST(test_json_longest_info_fits_and_overflow_gives_empty_line);
  return UNITY_END();
}
