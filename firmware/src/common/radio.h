// ESP-NOW の送受信を薄く包んだもの (親機・子機共通)
#pragma once

#include <Arduino.h>

#include "protocol.h"

struct RxPacket {
  uint8_t mac[6];   // 送信元
  int64_t rxUs;     // 受信した瞬間の自分の時刻 (esp_timer_get_time)
  uint8_t len;
  uint8_t data[proto::kMaxPacketSize + 8];
};

namespace radio {

// Wi-Fi を STA モード・指定チャンネルにして ESP-NOW を開始する
bool begin(uint8_t channel, size_t queueDepth);

// 受信キューから 1 つ取り出す (無ければ false)。loop() から呼ぶ。
bool receive(RxPacket* out);

bool sendBroadcast(const void* data, size_t len);

// 1 対 1 送信 (ESP-NOW の自動再送あり)。必要なら相手を peer 登録する。
bool sendTo(const uint8_t mac[6], const void* data, size_t len);

void ownMac(uint8_t out[6]);

// "AA:BB:CC:DD:EE:FF" 形式
String macToString(const uint8_t mac[6]);

}  // namespace radio
