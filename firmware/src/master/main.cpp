// ============================================================================
//  早押しボタン 親機 (master)
//
//  - 子機からの押下を受け取り、最も早く押した 1 台に回答権を与える
//  - 正解 / 不正解ボタンで判定 → 効果音 + ランプ → 次のラウンドへリセット
//  - 起動時に「正解ボタン」を押したままにすると番号登録モード
// ============================================================================
#include <Arduino.h>
#include <esp_timer.h>
#if __has_include(<esp_random.h>)
#include <esp_random.h>
#endif

#include "arbiter.h"
#include "audio.h"
#include "button.h"
#include "config.h"
#include "display.h"
#include "lamp.h"
#include "protocol.h"
#include "radio.h"
#include "registry.h"
#include "status_led.h"

namespace {

using proto::Result;
using proto::RoundState;

constexpr uint32_t kGreen = 0x00FF00;
constexpr uint32_t kRed = 0xFF0000;
constexpr uint32_t kPurple = 0x7000FF;
constexpr uint16_t kLedsPerLamp = MASTER_LEDS_PER_LAMP;  // 0〜N-1: 緑, N〜2N-1: 赤

Lamp g_lamp(PIN_LAMP, kLedsPerLamp * 2, LAMP_BRIGHTNESS);
Registry g_registry;
buzzer::Arbiter g_arbiter(static_cast<int64_t>(ARBITRATION_WINDOW_MS) * 1000,
                          static_cast<int64_t>(EARLY_TOLERANCE_MS) * 1000);
Button g_btnCorrect(PIN_BTN_CORRECT);
Button g_btnIncorrect(PIN_BTN_INCORRECT);

// ---- ゲームの状態 ----
bool g_registerMode = false;
uint32_t g_bootId = 0;
uint32_t g_seq = 0;
uint16_t g_round = 1;
RoundState g_state = RoundState::Open;
uint8_t g_winnerMac[6] = {};
uint8_t g_winnerId = 0;
uint16_t g_judgeSeq = 0;
Result g_lastResult = Result::None;
uint8_t g_lastWinnerMac[6] = {};

// ---- 送信スケジュール ----
uint32_t g_lastBeaconMs = 0;
uint8_t g_burstLeft = 0;
uint32_t g_nextBurstMs = 0;

// ---- ランプ演出 ----
Result g_lampResult = Result::None;
uint32_t g_lampResultSinceMs = 0;

void sendState() {
  proto::StatePacket p = {};
  proto::fillHeader(p.h, proto::MsgType::State, GROUP_ID);
  p.bootId = g_bootId;
  p.seq = ++g_seq;
  p.round = g_round;
  p.state = static_cast<uint8_t>(g_state);
  p.winnerId = g_winnerId;
  memcpy(p.winnerMac, g_winnerMac, 6);
  p.judgeSeq = g_judgeSeq;
  p.lastResult = static_cast<uint8_t>(g_lastResult);
  memcpy(p.lastWinnerMac, g_lastWinnerMac, 6);
  p.flags = g_registerMode ? proto::kFlagRegisterMode : 0;
  p.masterTimeUs = esp_timer_get_time();  // 送信直前に時刻を入れる
  radio::sendBroadcast(&p, sizeof(p));
}

// 状態が変わったら、取りこぼし対策で数回続けて送る
void requestBurst() {
  g_burstLeft = STATE_BURST_COUNT;
  g_nextBurstMs = millis();
}

void sendAssign(const uint8_t mac[6], uint8_t id, bool flash) {
  proto::AssignPacket p = {};
  proto::fillHeader(p.h, proto::MsgType::Assign, GROUP_ID);
  memcpy(p.targetMac, mac, 6);
  p.id = id;
  p.flags = flash ? proto::kAssignFlash : 0;
  // 子機は最大 64 台で ESP-NOW の peer 上限 (20) を超えるので、宛先を中に書いて一斉送信する
  radio::sendBroadcast(&p, sizeof(p));
}

void openRound() {
  ++g_round;
  if (g_round == 0) g_round = 1;
  g_state = RoundState::Open;
  memset(g_winnerMac, 0, 6);
  g_winnerId = 0;
  g_arbiter.reset(esp_timer_get_time());
  requestBurst();
}

void judge(Result result) {
  g_lastResult = result;
  memcpy(g_lastWinnerMac, g_winnerMac, 6);
  ++g_judgeSeq;
  audio::play(result == Result::Correct ? audio::Sound::Correct : audio::Sound::Incorrect);
  g_lampResult = result;
  g_lampResultSinceMs = millis();
  Serial.printf("[judge] %s  (回答者 #%u)\n", result == Result::Correct ? "正解" : "不正解",
                g_winnerId);
  openRound();
}

void exitRegisterMode() {
  g_registerMode = false;
  Serial.printf("[register] 終了: %u 台登録済み\n", g_registry.count());
  audio::play(audio::Sound::Startup);
  openRound();
}

void handlePress(const RxPacket& rx) {
  proto::PressPacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  const uint32_t nowMs = millis();
  g_registry.touch(rx.mac, nowMs);

  if (g_registerMode) {
    const bool isNew = g_registry.idOf(rx.mac) == 0;
    const uint8_t id = g_registry.assign(rx.mac, nowMs);
    if (id == 0) {
      Serial.println(F("[register] 登録数が上限に達しています"));
      return;
    }
    if (isNew) {
      Serial.printf("[register] #%u = %s\n", id, radio::macToString(rx.mac).c_str());
      audio::play(audio::Sound::BuzzIn);
    }
    sendAssign(rx.mac, id, /*flash=*/true);
    return;
  }

  if (g_state != RoundState::Open || p.round != g_round) return;

  uint8_t id = g_registry.idOf(rx.mac);
  if (id == 0) {
    id = g_registry.assign(rx.mac, nowMs);
    if (id != 0) sendAssign(rx.mac, id, false);
  }
  if (g_arbiter.offer(rx.mac, p.pressMasterUs, rx.rxUs) == buzzer::Arbiter::Offer::Accepted) {
    Serial.printf("[press] #%u  +%.1f ms\n", id,
                  static_cast<double>(p.pressMasterUs - g_arbiter.openUs()) / 1000.0);
  }
}

void handleHello(const RxPacket& rx) {
  proto::HelloPacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  const uint32_t nowMs = millis();
  g_registry.touch(rx.mac, nowMs);

  uint8_t id = g_registry.idOf(rx.mac);
  if (id == 0 && !g_registerMode) {
    // 未登録の子機には空いている番号を自動で割り当てる
    id = g_registry.assign(rx.mac, nowMs);
    if (id != 0) {
      Serial.printf("[join] #%u = %s\n", id, radio::macToString(rx.mac).c_str());
    }
  }
  if (id != 0 && p.knownId != id) sendAssign(rx.mac, id, false);
}

void processRadio() {
  RxPacket rx;
  while (radio::receive(&rx)) {
    proto::MsgType type;
    if (!proto::peekType(rx.data, rx.len, GROUP_ID, &type)) continue;
    switch (type) {
      case proto::MsgType::Press:
        handlePress(rx);
        break;
      case proto::MsgType::Hello:
        handleHello(rx);
        break;
      default:
        break;
    }
  }
}

void processArbiter() {
  if (g_registerMode || g_state != RoundState::Open) return;
  buzzer::Candidate winner;
  if (!g_arbiter.poll(esp_timer_get_time(), &winner)) return;

  g_state = RoundState::Locked;
  memcpy(g_winnerMac, winner.mac, 6);
  g_winnerId = g_registry.idOf(winner.mac);
  g_lampResult = Result::None;  // 前の判定ランプを消す
  requestBurst();
  audio::play(audio::Sound::BuzzIn);
  Serial.printf("[buzz] 回答権: #%u  (+%.1f ms, 候補 %u 台)\n", g_winnerId,
                static_cast<double>(winner.pressUs - g_arbiter.openUs()) / 1000.0,
                static_cast<unsigned>(g_arbiter.candidateCount()));
}

void processButtons(uint32_t nowMs) {
  if (g_btnCorrect.update(nowMs)) {
    if (g_registerMode) {
      exitRegisterMode();
    } else {
      judge(Result::Correct);
    }
  }
  if (g_btnIncorrect.update(nowMs)) {
    if (g_registerMode) {
      exitRegisterMode();
    } else {
      judge(Result::Incorrect);
    }
  }
}

void processBroadcast(uint32_t nowMs) {
  if (g_burstLeft > 0 && static_cast<int32_t>(nowMs - g_nextBurstMs) >= 0) {
    sendState();
    --g_burstLeft;
    g_nextBurstMs = nowMs + STATE_BURST_GAP_MS;
    g_lastBeaconMs = nowMs;
  } else if (nowMs - g_lastBeaconMs >= BEACON_INTERVAL_MS) {
    sendState();
    g_lastBeaconMs = nowMs;
  }
}

void renderLamps(uint32_t nowMs) {
  uint32_t green = 0;
  uint32_t red = 0;

  if (g_registerMode) {
    const uint8_t level = Lamp::breathe(nowMs, 2000, 10, 140);
    green = red = Lamp::scale(kPurple, level);
  } else if (g_lampResult != Result::None) {
    const uint32_t elapsed = nowMs - g_lampResultSinceMs;
    if (JUDGE_LAMP_MS > 0 && elapsed >= static_cast<uint32_t>(JUDGE_LAMP_MS)) {
      g_lampResult = Result::None;
    } else {
      // 最初の 0.6 秒は点滅、その後は点灯
      const bool on = elapsed >= 600 || (elapsed / 100) % 2 == 0;
      if (on) {
        if (g_lampResult == Result::Correct) {
          green = kGreen;
        } else {
          red = kRed;
        }
      }
    }
  }

  g_lamp.fill(green, 0, kLedsPerLamp);
  g_lamp.fill(red, kLedsPerLamp, kLedsPerLamp);
  g_lamp.show();
}

void renderDisplay(uint32_t nowMs) {
  if (g_registerMode) {
    display::showRegister(g_registry.count() + 1);
  } else if (g_state == RoundState::Locked) {
    display::showWinner(g_winnerId);
  } else {
    display::showConnected(g_registry.connected(nowMs, CHILD_TIMEOUT_MS));
  }
  status_led::set(g_registerMode ? (nowMs / 250) % 2 == 0 : true);
}

// 起動時に正解ボタンが押されていたら番号登録モードに入る
bool checkRegisterModeAtBoot() {
  if (!g_btnCorrect.raw()) return false;
  const uint32_t start = millis();
  while (millis() - start < REGISTER_HOLD_MS) {
    if (!g_btnCorrect.raw()) return false;
    delay(10);
  }
  return true;
}

void lampTest() {
  g_lamp.fill(kGreen, 0, kLedsPerLamp);
  g_lamp.show();
  delay(300);
  g_lamp.clear();
  g_lamp.fill(kRed, kLedsPerLamp, kLedsPerLamp);
  g_lamp.show();
  delay(300);
  g_lamp.clear();
  g_lamp.show();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(50);
  status_led::begin();
  g_btnCorrect.begin();
  g_btnIncorrect.begin();
  g_lamp.begin();
  display::begin();
  display::showBoot();
  g_registry.begin();
  g_bootId = esp_random();

  if (checkRegisterModeAtBoot()) {
    g_registerMode = true;
    g_registry.clear();
    Serial.println(F("[register] 番号登録モード: 子機のボタンを番号順に押してください"));
    Serial.println(F("[register] 終わったら正解/不正解ボタンのどちらかを押すと通常モードに戻ります"));
  }

  if (!radio::begin(WIFI_CHANNEL, 64)) {
    Serial.println(F("[radio] ESP-NOW の初期化に失敗しました"));
    while (true) {
      g_lamp.fill((millis() / 300) % 2 ? kRed : 0);
      g_lamp.show();
      delay(10);
    }
  }

  uint8_t mac[6];
  radio::ownMac(mac);
  Serial.println();
  Serial.println(F("=== 早押しボタン 親機 ==="));
  Serial.printf("FW %d.%d  MAC %s  CH %d  GROUP %d  登録済み子機 %u 台\n", FW_VERSION_MAJOR,
                FW_VERSION_MINOR, radio::macToString(mac).c_str(), WIFI_CHANNEL, GROUP_ID,
                g_registry.count());

  audio::begin();
  lampTest();
  audio::play(audio::Sound::Startup);

  g_arbiter.reset(esp_timer_get_time());
  requestBurst();
}

void loop() {
  processRadio();
  processArbiter();
  processButtons(millis());
  // 上の処理の中で millis() を記録することがあるので、時刻はここで取り直す
  // (古い時刻との差を取ると負になり、uint32_t で巨大な値になってしまう)
  const uint32_t nowMs = millis();
  processBroadcast(nowMs);
  audio::update();
  renderLamps(nowMs);
  renderDisplay(nowMs);
  delay(1);
}
