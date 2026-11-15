#include "battery.h"

#include <Arduino.h>

#include "battery_level.h"
#include "config.h"

namespace battery {

#if USE_BATTERY

namespace {

// この範囲外の値は「電池がつながっていない (分圧回路が無い)」とみなす
constexpr int kPresentMinMv = 2800;
constexpr int kPresentMaxMv = 4600;
constexpr int kHysteresisMv = 100;
constexpr uint32_t kIntervalMs = 1000;

int g_mv = 0;
bool g_low = false;
uint32_t g_lastMs = 0;

int measure() {
  uint32_t sum = 0;
  for (int i = 0; i < 16; ++i) sum += analogReadMilliVolts(PIN_BATTERY);
  return static_cast<int>(static_cast<float>(sum) / 16.0f * BATTERY_DIVIDER);
}

}  // namespace

void begin() {
  g_mv = measure();
  g_low = present() && g_mv < BATTERY_LOW_MV;
  g_lastMs = millis();
}

void update(uint32_t nowMs) {
  if (static_cast<int32_t>(nowMs - g_lastMs) < static_cast<int32_t>(kIntervalMs)) return;
  g_lastMs = nowMs;
  // 無線の送信などで値がぶれるので、ゆっくり追従させる
  g_mv = (g_mv * 3 + measure()) / 4;
  g_low = present() && buzzer::batteryLow(g_low, g_mv, BATTERY_LOW_MV, kHysteresisMv);
}

bool present() { return g_mv >= kPresentMinMv && g_mv <= kPresentMaxMv; }
int millivolts() { return present() ? g_mv : 0; }
int percent() { return present() ? buzzer::batteryPercent(g_mv) : 0; }
bool low() { return g_low; }
uint8_t encoded() { return buzzer::encodeBattery20mV(millivolts()); }

#else

void begin() {}
void update(uint32_t) {}
bool present() { return false; }
int millivolts() { return 0; }
int percent() { return 0; }
bool low() { return false; }
uint8_t encoded() { return 0; }

#endif

}  // namespace battery
