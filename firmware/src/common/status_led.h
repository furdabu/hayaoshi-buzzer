// 基板上の小さな LED (動作確認用)
#pragma once

#include <Arduino.h>

#include "config.h"

namespace status_led {

inline void begin() {
  if (PIN_STATUS_LED < 0) return;
  pinMode(PIN_STATUS_LED, OUTPUT);
}

inline void set(bool on) {
  if (PIN_STATUS_LED < 0) return;
  digitalWrite(PIN_STATUS_LED, (on != (STATUS_LED_ACTIVE_LOW != 0)) ? HIGH : LOW);
}

}  // namespace status_led
