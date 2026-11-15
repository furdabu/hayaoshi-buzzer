// ============================================================================
//  早押しボタン 子機 (child)
//
//  - ボタンが押された瞬間の時刻を割り込みで記録し、親機の時計に換算して送る
//  - ランプは親機が「あなたが回答者」と言ったときだけ点灯する
//    (自分で勝手に点けないので、負けた子機が一瞬光ることもない)
// ============================================================================
#include <Arduino.h>
#include <esp_sleep.h>
#include <esp_timer.h>

#include "battery.h"
#include "clock_sync.h"
#include "config.h"
#include "lamp.h"
#include "protocol.h"
#include "radio.h"
#include "status_led.h"

namespace {

using proto::RoundState;

constexpr uint32_t kWinnerColor = WINNER_COLOR;
constexpr uint32_t kGreen = 0x00FF00;
constexpr uint32_t kRed = 0xFF0000;
constexpr uint32_t kBlue = 0x0030FF;
constexpr uint32_t kPurple = 0x7000FF;
constexpr uint32_t kWhite = 0xFFFFFF;

Lamp g_lamp(PIN_LAMP, CHILD_LAMP_LEDS, LAMP_BRIGHTNESS);
buzzer::ClockSync g_sync;

uint8_t g_myMac[6] = {};
uint8_t g_myId = 0;

// ---- 親機 ----
bool g_haveMaster = false;
uint8_t g_masterMac[6] = {};
uint32_t g_masterBootId = 0;
uint32_t g_lastStateMs = 0;
proto::StatePacket g_state = {};

// ---- 受付 ----
bool g_armed = false;  // 受付中のラウンドを受信済み
uint16_t g_armedRound = 0;

// ---- 押下の送信 ----
bool g_pressSent = false;
uint16_t g_pressRound = 0;
int64_t g_pressMasterUs = 0;
uint8_t g_pressAttempts = 0;
uint32_t g_nextPressMs = 0;

// ---- 保留中の押下 ----
// 親機が次のラウンドを始めた直後で、その知らせがまだ届いていないだけかもしれないので、
// 受付外の押下も少しの間だけ覚えておく。送るかどうかは親機が押した時刻で判断する。
constexpr uint32_t kPendingPressMs = 250;
bool g_pending = false;
int64_t g_pendingEdgeUs = 0;
uint32_t g_pendingSinceMs = 0;
uint16_t g_pendingRound = 0;

// ---- 番号登録モード ----
bool g_prevRegisterMode = false;
bool g_registeredThisMode = false;

// ---- ランプ演出 ----
enum class Fx : uint8_t { None, Correct, Incorrect, Registered };
Fx g_fx = Fx::None;
uint32_t g_fxStartMs = 0;
uint16_t g_seenJudgeSeq = 0;
bool g_judgeSeqKnown = false;
bool g_wasWinner = false;
uint32_t g_winSinceMs = 0;

uint32_t g_nextHelloMs = 0;

// ---- ボタン割り込み ----
volatile bool g_isrArmed = true;
volatile bool g_isrHit = false;
volatile int64_t g_isrEdgeUs = 0;

void IRAM_ATTR onButtonEdge() {
  if (!g_isrArmed) return;
  g_isrEdgeUs = esp_timer_get_time();
  g_isrHit = true;
  g_isrArmed = false;
}

bool connected(uint32_t nowMs) { return g_haveMaster && nowMs - g_lastStateMs < MASTER_TIMEOUT_MS; }

bool registerMode() { return (g_state.flags & proto::kFlagRegisterMode) != 0; }

bool iAmWinner() {
  return static_cast<RoundState>(g_state.state) == RoundState::Locked &&
         proto::macEqual(g_state.winnerMac, g_myMac);
}

void startFx(Fx fx) {
  g_fx = fx;
  g_fxStartMs = millis();
}

void sendPress(uint16_t round, int64_t pressMasterUs, uint8_t attempt) {
  proto::PressPacket p = {};
  proto::fillHeader(p.h, proto::MsgType::Press, GROUP_ID);
  p.round = round;
  p.pressMasterUs = pressMasterUs;
  p.attempt = attempt;
  radio::sendTo(g_masterMac, &p, sizeof(p));
}

// このラウンドの押下を親機に送る (1 ラウンド 1 回)
void submitPress(int64_t edgeUs, uint32_t nowMs) {
  g_pressSent = true;
  g_pressRound = g_armedRound;
  g_pressMasterUs = g_sync.toMaster(edgeUs);
  g_pressAttempts = 0;
  sendPress(g_pressRound, g_pressMasterUs, g_pressAttempts++);
  g_nextPressMs = nowMs + PRESS_RETRY_MS;
  Serial.printf("[press] round %u\n", g_pressRound);
}

void sendHello() {
  proto::HelloPacket p = {};
  proto::fillHeader(p.h, proto::MsgType::Hello, GROUP_ID);
  p.fwMajor = FW_VERSION_MAJOR;
  p.fwMinor = FW_VERSION_MINOR;
  p.knownId = g_myId;
  p.battery20mV = battery::encoded();
  radio::sendTo(g_masterMac, &p, sizeof(p));
}

// ---------------------------------------------------------------------------
//  受信
// ---------------------------------------------------------------------------
void handleState(const RxPacket& rx) {
  proto::StatePacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  const uint32_t nowMs = millis();

  // 同じグループの別の親機が近くにいても、今つながっている親機を優先する
  if (connected(nowMs) && !proto::macEqual(rx.mac, g_masterMac)) return;
  if (!g_haveMaster || !proto::macEqual(rx.mac, g_masterMac)) {
    memcpy(g_masterMac, rx.mac, 6);
    g_haveMaster = true;
    g_nextHelloMs = nowMs;  // すぐに名乗る
    Serial.printf("[link] 親機 %s に接続\n", radio::macToString(rx.mac).c_str());
  }
  if (p.bootId != g_masterBootId) {
    // 親機が再起動した: 時計もラウンド番号もリセットされている
    g_masterBootId = p.bootId;
    g_sync.reset();
    g_armed = false;
    g_pressSent = false;
    g_pending = false;
    g_judgeSeqKnown = false;
    g_prevRegisterMode = false;
    g_registeredThisMode = false;
  }

  g_sync.onBeacon(p.masterTimeUs, rx.rxUs);
  g_lastStateMs = nowMs;

  const bool reg = (p.flags & proto::kFlagRegisterMode) != 0;
  if (reg && !g_prevRegisterMode) g_registeredThisMode = false;
  g_prevRegisterMode = reg;

  const RoundState st = static_cast<RoundState>(p.state);
  if (st == RoundState::Open && !reg) {
    g_armed = true;
    g_armedRound = p.round;
  } else {
    g_armed = false;
  }

  // 受付開始の直前・直後に押されていた押下を送る (受付開始より前なら親機が捨てる)
  if (g_pending) {
    if (nowMs - g_pendingSinceMs > kPendingPressMs || reg) {
      g_pending = false;
    } else if (g_armed && p.round != g_pendingRound &&
               !(g_pressSent && g_pressRound == p.round)) {
      g_pending = false;
      submitPress(g_pendingEdgeUs, nowMs);
    }
  }

  if (!g_judgeSeqKnown) {
    g_seenJudgeSeq = p.judgeSeq;
    g_judgeSeqKnown = true;
  } else if (p.judgeSeq != g_seenJudgeSeq) {
    g_seenJudgeSeq = p.judgeSeq;
    if (proto::macEqual(p.lastWinnerMac, g_myMac)) {
      startFx(p.lastResult == static_cast<uint8_t>(proto::Result::Correct) ? Fx::Correct
                                                                           : Fx::Incorrect);
    }
  }

  g_state = p;

  const bool winner = iAmWinner();
  if (winner && !g_wasWinner) {
    g_winSinceMs = nowMs;
    Serial.println(F("[buzz] 回答権を獲得!"));
  }
  g_wasWinner = winner;
}

void handleAssign(const RxPacket& rx) {
  proto::AssignPacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  if (!g_haveMaster || !proto::macEqual(rx.mac, g_masterMac)) return;
  if (!proto::macEqual(p.targetMac, g_myMac)) return;
  if (g_myId != p.id) Serial.printf("[id] この子機は #%u です\n", p.id);
  g_myId = p.id;
  if (p.flags & proto::kAssignFlash) {
    g_registeredThisMode = true;
    startFx(Fx::Registered);
  }
}

void processRadio() {
  RxPacket rx;
  while (radio::receive(&rx)) {
    proto::MsgType type;
    if (!proto::peekType(rx.data, rx.len, GROUP_ID, &type)) continue;
    switch (type) {
      case proto::MsgType::State:
        handleState(rx);
        break;
      case proto::MsgType::Assign:
        handleAssign(rx);
        break;
      default:
        break;
    }
  }
}

// ---------------------------------------------------------------------------
//  ボタン
// ---------------------------------------------------------------------------
void onPress(int64_t edgeUs) {
  const uint32_t nowMs = millis();
  if (!connected(nowMs)) return;
  if (!g_sync.synced(esp_timer_get_time(), static_cast<int64_t>(MASTER_TIMEOUT_MS) * 1000)) return;

  if (registerMode()) {
    sendPress(0, g_sync.toMaster(edgeUs), 0);
    Serial.println(F("[register] 登録を要求"));
    return;
  }

  const bool open = static_cast<RoundState>(g_state.state) == RoundState::Open && g_armed;
  if (open && !(g_pressSent && g_pressRound == g_armedRound)) {
    submitPress(edgeUs, nowMs);
    return;
  }

  // 他の子機が回答中 / このラウンドでは押下済み → ランプは点けず、少しの間だけ覚えておく
  g_pending = true;
  g_pendingEdgeUs = edgeUs;
  g_pendingSinceMs = nowMs;
  g_pendingRound = g_state.round;
}

void processButton() {
  static bool candidate = false;
  static int64_t candidateUs = 0;
  static uint32_t releasedSinceMs = 0;

  if (g_isrHit) {
    g_isrHit = false;
    candidate = true;
    candidateUs = g_isrEdgeUs;
  }
  // 押された瞬間の時刻は割り込みで記録済み。ノイズでないことを少し待って確かめる。
  // (チャタリングでたまたま HIGH を読んでも、DEBOUNCE_GIVEUP_US までは押下の可能性を残す)
  if (candidate) {
    const int64_t age = esp_timer_get_time() - candidateUs;
    if (age >= DEBOUNCE_CONFIRM_US) {
      if (digitalRead(PIN_BUTTON) == LOW) {
        candidate = false;
        onPress(candidateUs);
      } else if (age >= DEBOUNCE_GIVEUP_US) {
        candidate = false;
        g_isrArmed = true;  // ノイズだった: すぐ次の押下を受け付ける
      }
    }
  }
  // ボタンが離されて安定したら、次の押下を受け付ける
  if (!g_isrArmed && !candidate) {
    if (digitalRead(PIN_BUTTON) == HIGH) {
      if (releasedSinceMs == 0) {
        releasedSinceMs = millis() | 1;
      } else if (millis() - releasedSinceMs >= RELEASE_STABLE_MS) {
        releasedSinceMs = 0;
        g_isrArmed = true;
      }
    } else {
      releasedSinceMs = 0;
    }
  }
}

// 押下パケットの再送 (親機が受け取って状態が変わるまで)
void processPressRetry(uint32_t nowMs) {
  if (!g_pressSent || g_pressAttempts > PRESS_RETRIES) return;
  if (static_cast<int32_t>(nowMs - g_nextPressMs) < 0) return;
  if (static_cast<RoundState>(g_state.state) != RoundState::Open || g_state.round != g_pressRound) {
    g_pressAttempts = PRESS_RETRIES + 1;  // 決着がついたので終了
    return;
  }
  sendPress(g_pressRound, g_pressMasterUs, g_pressAttempts++);
  g_nextPressMs = nowMs + PRESS_RETRY_MS;
}

void processHello(uint32_t nowMs) {
  if (!connected(nowMs) || static_cast<int32_t>(nowMs - g_nextHelloMs) < 0) return;
  sendHello();
  // 全員が同時に送らないように少しばらつかせる
  g_nextHelloMs = nowMs + HELLO_INTERVAL_MS - 200 + random(400);
}

// ---------------------------------------------------------------------------
//  表示
// ---------------------------------------------------------------------------
uint32_t blink(uint32_t elapsed, uint32_t color, uint32_t halfPeriodMs) {
  return ((elapsed / halfPeriodMs) % 2 == 0) ? color : 0;
}

void renderLamp(uint32_t nowMs) {
  uint32_t color = 0;
  const bool conn = connected(nowMs);

  if (g_fx != Fx::None) {
    const uint32_t e = nowMs - g_fxStartMs;
    switch (g_fx) {
      case Fx::Correct:
        if (e < 1200) color = blink(e, kGreen, 150);
        else g_fx = Fx::None;
        break;
      case Fx::Incorrect:
        if (e < 1200) color = blink(e, kRed, 150);
        else g_fx = Fx::None;
        break;
      case Fx::Registered:
        if (e < 480) color = blink(e, kWhite, 120);
        else g_fx = Fx::None;
        break;
      case Fx::None:
        break;
    }
  }

  if (g_fx == Fx::None) {
    if (!conn) {
      // 親機が見つからない: 青く短く点滅
      color = (nowMs % 1500) < 120 ? Lamp::scale(kBlue, 70) : 0;
    } else if (registerMode()) {
      // 登録済み: 白く点灯 / 未登録: 紫でゆっくり明滅
      color = g_registeredThisMode ? Lamp::scale(kWhite, 40)
                                   : Lamp::scale(kPurple, Lamp::breathe(nowMs, 2000, 5, 80));
    } else if (iAmWinner()) {
      // 回答権: 最初に 3 回点滅して目立たせ、その後は点灯
      const uint32_t e = nowMs - g_winSinceMs;
      color = e < 450 ? blink(e, kWinnerColor, 75) : kWinnerColor;
    }
  }

  // 電池残量わずか: 何も表示していないときに 4 秒ごとに赤く短く光る
  if (color == 0 && battery::low() && (nowMs % 4000) < 150) {
    color = Lamp::scale(kRed, 80);
  }

  g_lamp.fill(color);
  g_lamp.show();

  // ボタン内蔵 LED: 押せるとき / 回答権があるときに点灯
  // ボタン内蔵 LED: 「今押せる」ときだけ点灯
  //   点灯: 受付中でまだこのラウンドで押していない / 番号登録モードで未登録
  //   消灯: 他の人が回答中・自分が回答中・このラウンドで押した後・親機につながっていない
  if (PIN_BUTTON_LED >= 0) {
    static int shownLevel = -1;
    const bool pressable =
        conn && ((registerMode() && !g_registeredThisMode) ||
                 (g_armed && !(g_pressSent && g_pressRound == g_armedRound)));
    const int level = pressable ? BUTTON_LED_LEVEL : 0;
    if (level != shownLevel) {
      analogWrite(PIN_BUTTON_LED, level);
      shownLevel = level;
    }
  }
  status_led::set(conn ? true : (nowMs / 500) % 2 == 0);
}

// 電池切れ寸前: 電池を守るため、LED と無線を止めて休止する (電源ボタンの入れ直しで復帰)
void shutdownForLowBattery() {
  Serial.println(F("[battery] 電池切れ寸前のため停止します。充電してから電源を入れ直してください"));
  if (PIN_BUTTON_LED >= 0) analogWrite(PIN_BUTTON_LED, 0);
  for (int i = 0; i < 3; ++i) {
    g_lamp.fill(Lamp::scale(kRed, 120));
    g_lamp.show();
    delay(150);
    g_lamp.clear();
    g_lamp.show();
    delay(150);
  }
  status_led::set(false);
  Serial.flush();
  esp_deep_sleep_start();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(50);
  status_led::begin();
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  if (PIN_BUTTON_LED >= 0) {
    pinMode(PIN_BUTTON_LED, OUTPUT);
    digitalWrite(PIN_BUTTON_LED, LOW);
  }
  g_lamp.begin();

  if (!radio::begin(WIFI_CHANNEL, 16)) {
    Serial.println(F("[radio] ESP-NOW の初期化に失敗しました"));
    while (true) {
      g_lamp.fill((millis() / 300) % 2 ? kRed : 0);
      g_lamp.show();
      delay(10);
    }
  }
  radio::ownMac(g_myMac);
  attachInterrupt(digitalPinToInterrupt(PIN_BUTTON), onButtonEdge, FALLING);

  Serial.println();
  Serial.println(F("=== 早押しボタン 子機 ==="));
  Serial.printf("FW %d.%d  MAC %s  CH %d  GROUP %d\n", FW_VERSION_MAJOR, FW_VERSION_MINOR,
                radio::macToString(g_myMac).c_str(), WIFI_CHANNEL, GROUP_ID);

  // 起動確認。電池があれば残量の色 (緑: 半分以上 / 黄: 少なめ / 赤: 要充電) で 0.6 秒光る
  battery::begin();
  uint32_t bootColor = kWinnerColor;
  uint32_t bootMs = 200;
  if (battery::present()) {
    const int pct = battery::percent();
    bootColor = pct >= 50 ? kGreen : (pct >= 15 ? 0xFFC000 : kRed);
    bootMs = 600;
    Serial.printf("[battery] %d mV (%d%%)\n", battery::millivolts(), pct);
  }
  g_lamp.fill(bootColor);
  g_lamp.show();
  delay(bootMs);
  g_lamp.clear();
  g_lamp.show();
}

void loop() {
  processRadio();
  processButton();
  // 上の処理の中で millis() を記録することがあるので、時刻はここで取る
  // (古い時刻との差を取ると負になり、uint32_t で巨大な値になってしまう)
  const uint32_t nowMs = millis();
  processPressRetry(nowMs);
  processHello(nowMs);
  battery::update(nowMs);
  if (battery::critical()) shutdownForLowBattery();
  renderLamp(nowMs);
  delay(1);
}
