// 親機の判定ボタン (チャタリング除去つき)
#pragma once

#include <Arduino.h>

#include "config.h"

class Button {
 public:
  explicit Button(int pin) : pin_(pin) {}

  void begin() {
    pinMode(pin_, INPUT_PULLUP);
    lastRaw_ = stable_ = raw();
    rawSince_ = millis();
  }

  // 押された瞬間に一度だけ true を返す
  bool update(uint32_t nowMs) {
    const bool r = raw();
    if (r != lastRaw_) {
      lastRaw_ = r;
      rawSince_ = nowMs;
    }
    // 押すときは素早く (8ms)、離すときは慎重に判定する
    const uint32_t need = r ? 8 : BUTTON_DEBOUNCE_MS;
    if (r != stable_ && nowMs - rawSince_ >= need) {
      stable_ = r;
      return stable_;
    }
    return false;
  }

  bool isDown() const { return stable_; }
  bool raw() const { return digitalRead(pin_) == LOW; }

 private:
  int pin_;
  bool lastRaw_ = false;
  bool stable_ = false;
  uint32_t rawSince_ = 0;
};
