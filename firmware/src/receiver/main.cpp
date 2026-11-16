// ============================================================================
//  早押しボタン PC 連携の受信機 (receiver)
//
//  - 親機が無線で送っている状態を聞いて、USB から PC へ 1 行ずつの JSON で流す
//  - 聞くだけで、電波は出さない (ゲームの動きには影響しない)
//  - 子機と同じマイコン (XIAO ESP32C6) を USB で PC につなぐだけで使う (配線なし)
//
//  PC へ送る内容は docs/pc-link.md を参照
// ============================================================================
#include <Arduino.h>

#include "battery_level.h"
#include "config.h"
#include "pc_json.h"
#include "protocol.h"
#include "radio.h"
#include "state_tracker.h"
#include "status_led.h"

namespace {

constexpr uint32_t kStateEveryMs = 1000;  // 変化がなくても、今の状態を送る間隔
constexpr uint32_t kInfoEveryMs = 5000;   // 変化がなくても、子機の情報を送る間隔

buzzer::StateTracker g_tracker;

// ---- 親機 ----
bool g_haveMaster = false;  // 一度でも親機を見つけた
bool g_masterUp = false;    // 今、親機からの状態が届いている
uint8_t g_masterMac[6] = {};
uint32_t g_lastStateMs = 0;

// ---- 子機の情報 (親機の Info パケット) ----
bool g_haveInfo = false;
proto::InfoPacket g_info = {};

uint32_t g_lastStateLineMs = 0;
uint32_t g_lastInfoLineMs = 0;

char g_line[640];

void sendLine(size_t len) {
  if (len == 0) return;  // 入りきらなかった行は送らない
  Serial.write(reinterpret_cast<const uint8_t*>(g_line), len);
  Serial.write('\n');
}

void sendHello() {
  sendLine(buzzer::pcjson::hello(g_line, sizeof(g_line), FW_VERSION_MAJOR, FW_VERSION_MINOR,
                                 WIFI_CHANNEL, GROUP_ID));
}

void sendStateLine(uint32_t nowMs) {
  sendLine(buzzer::pcjson::state(g_line, sizeof(g_line), g_masterUp, g_tracker));
  g_lastStateLineMs = nowMs;
}

void sendInfoLine(uint32_t nowMs) {
  if (!g_haveInfo) return;
  buzzer::MasterInfo v;
  v.registered = g_info.registered;
  v.connected = g_info.connected;
  v.connectedMask = g_info.connectedMask;
  v.lowBatteryMask = g_info.lowBatteryMask;
  v.masterBatteryMv = buzzer::decodeBattery20mV(g_info.masterBattery20mV);
  v.masterBatteryLow = (g_info.flags & proto::kInfoMasterBatteryLow) != 0;
  v.buzzRound = g_info.buzzRound;
  v.buzzId = g_info.buzzId;
  v.buzzCandidates = g_info.buzzCandidates;
  v.buzzElapsedMs = g_info.buzzElapsedMs;
  sendLine(buzzer::pcjson::info(g_line, sizeof(g_line), v));
  g_lastInfoLineMs = nowMs;
}

// ---------------------------------------------------------------------------
//  受信
// ---------------------------------------------------------------------------
void handleState(const RxPacket& rx) {
  proto::StatePacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  const uint32_t nowMs = millis();

  // 同じグループの別の親機が近くにいても、今聞いている親機を優先する
  if (g_masterUp && !proto::macEqual(rx.mac, g_masterMac)) return;
  if (!g_haveMaster || !proto::macEqual(rx.mac, g_masterMac)) {
    memcpy(g_masterMac, rx.mac, 6);
    g_haveMaster = true;
    g_tracker.reset();
    g_haveInfo = false;
  }
  const bool wasUp = g_masterUp;
  g_masterUp = true;
  g_lastStateMs = nowMs;

  buzzer::MasterState s;
  s.bootId = p.bootId;
  s.seq = p.seq;
  s.round = p.round;
  s.locked = static_cast<proto::RoundState>(p.state) == proto::RoundState::Locked;
  s.registerMode = (p.flags & proto::kFlagRegisterMode) != 0;
  s.winnerId = p.winnerId;
  memcpy(s.winnerMac, p.winnerMac, 6);
  s.judgeSeq = p.judgeSeq;
  s.lastResult = p.lastResult;
  memcpy(s.lastWinnerMac, p.lastWinnerMac, 6);

  buzzer::TrackerEvent events[buzzer::StateTracker::kMaxEvents];
  const size_t n = g_tracker.update(s, events);

  bool announced = false;  // 「親機が見つかった」を出来事として送ったか
  for (size_t i = 0; i < n; ++i) {
    if (events[i].type == buzzer::TrackerEvent::Type::MasterFound ||
        events[i].type == buzzer::TrackerEvent::Type::MasterRestarted) {
      announced = true;
      g_haveInfo = false;  // 親機が変わった / 再起動したので、古い情報は使わない
    }
  }
  // 電波が途切れていた親機が戻ってきた (再起動ではない)
  if (!wasUp && !announced) sendLine(buzzer::pcjson::master(g_line, sizeof(g_line), true, false));
  for (size_t i = 0; i < n; ++i) {
    sendLine(buzzer::pcjson::event(g_line, sizeof(g_line), events[i]));
  }
  if (n > 0 || !wasUp) sendStateLine(nowMs);
}

void handleAssign(const RxPacket& rx) {
  proto::AssignPacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  if (!g_haveMaster || !proto::macEqual(rx.mac, g_masterMac)) return;
  g_tracker.learn(p.targetMac, p.id);
}

void handleInfo(const RxPacket& rx) {
  proto::InfoPacket p;
  if (!proto::parse(rx.data, rx.len, &p)) return;
  if (!g_masterUp || !proto::macEqual(rx.mac, g_masterMac)) return;
  if (!g_tracker.hasState() || p.bootId != g_tracker.state().bootId) return;
  if (g_haveInfo && memcmp(&p, &g_info, sizeof(p)) == 0) return;  // 変化なし
  g_info = p;
  g_haveInfo = true;
  sendInfoLine(millis());
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
      case proto::MsgType::Info:
        handleInfo(rx);
        break;
      default:
        break;
    }
  }
}

// PC から "?" が届いたら、今わかっていることを全部送り直す (つないだ直後の表示用)
void processSerial(uint32_t nowMs) {
  bool asked = false;
  while (Serial.available() > 0) {
    if (Serial.read() == '?') asked = true;
  }
  if (!asked) return;
  sendHello();
  sendStateLine(nowMs);
  sendInfoLine(nowMs);
}

}  // namespace

void setup() {
#if ARDUINO_USB_MODE && ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxBufferSize(2048);  // 出来事が続いたときに、行が途中で切れないように
#endif
  Serial.begin(115200);
  delay(50);
  status_led::begin();
  status_led::set(false);

  if (!radio::begin(WIFI_CHANNEL, 64)) {
    while (true) {
      Serial.println(F("{\"type\":\"error\",\"message\":\"radio init failed\"}"));
      status_led::set((millis() / 100) % 2 == 0);
      delay(1000);
    }
  }
  sendHello();
}

void loop() {
  processRadio();
  const uint32_t nowMs = millis();

  if (g_masterUp && nowMs - g_lastStateMs >= MASTER_TIMEOUT_MS) {
    g_masterUp = false;
    sendLine(buzzer::pcjson::master(g_line, sizeof(g_line), false, false));
    sendStateLine(nowMs);
  }

  processSerial(nowMs);
  if (nowMs - g_lastStateLineMs >= kStateEveryMs) sendStateLine(nowMs);
  if (g_masterUp && nowMs - g_lastInfoLineMs >= kInfoEveryMs) sendInfoLine(nowMs);

  // 基板の LED: 点灯 = 親機の電波を受信中 / 点滅 = 親機を探している
  status_led::set(g_masterUp ? true : (nowMs / 500) % 2 == 0);
  delay(1);
}
