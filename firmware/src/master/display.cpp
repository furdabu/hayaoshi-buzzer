#include "display.h"

#include <Arduino.h>

#include "config.h"

#if USE_DISPLAY

namespace display {
namespace {

// ---------------------------------------------------------------------------
//  TM1637 の最小ドライバ (外部ライブラリ不要)
//  CLK/DIO はオープンドレインとして扱う: LOW = 出力, HIGH = 入力 (モジュールのプルアップ)
// ---------------------------------------------------------------------------
class Tm1637 {
 public:
  Tm1637(int clk, int dio) : clk_(clk), dio_(dio) {}

  void begin() {
    pinMode(clk_, INPUT_PULLUP);
    pinMode(dio_, INPUT_PULLUP);
    digitalWrite(clk_, LOW);
    digitalWrite(dio_, LOW);
  }

  void setBrightness(uint8_t level) { control_ = 0x88 | (level & 0x07); }

  void setSegments(const uint8_t segs[4]) {
    start();
    writeByte(0x40);  // データ書き込み, アドレス自動インクリメント
    stop();
    start();
    writeByte(0xC0);  // 先頭アドレス
    for (int i = 0; i < 4; ++i) writeByte(segs[i]);
    stop();
    start();
    writeByte(control_);  // 表示 ON + 明るさ
    stop();
  }

 private:
  static void bitDelay() { delayMicroseconds(50); }
  void low(int pin) { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
  void release(int pin) { pinMode(pin, INPUT_PULLUP); }

  void start() {
    low(dio_);
    bitDelay();
  }

  void stop() {
    low(dio_);
    bitDelay();
    release(clk_);
    bitDelay();
    release(dio_);
    bitDelay();
  }

  void writeByte(uint8_t b) {
    for (int i = 0; i < 8; ++i) {
      low(clk_);
      bitDelay();
      if (b & 0x01) {
        release(dio_);
      } else {
        low(dio_);
      }
      bitDelay();
      release(clk_);
      bitDelay();
      b >>= 1;
    }
    // ACK
    low(clk_);
    release(dio_);
    bitDelay();
    release(clk_);
    bitDelay();
    if (digitalRead(dio_) == LOW) low(dio_);
    bitDelay();
    low(clk_);
    bitDelay();
  }

  int clk_;
  int dio_;
  uint8_t control_ = 0x8F;
};

// 7 セグの各セグメント
constexpr uint8_t SEG_A = 0x01, SEG_B = 0x02, SEG_C = 0x04, SEG_D = 0x08;
constexpr uint8_t SEG_E = 0x10, SEG_F = 0x20, SEG_G = 0x40;

constexpr uint8_t kDigits[10] = {
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F,          // 0
    SEG_B | SEG_C,                                          // 1
    SEG_A | SEG_B | SEG_D | SEG_E | SEG_G,                  // 2
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_G,                  // 3
    SEG_B | SEG_C | SEG_F | SEG_G,                          // 4
    SEG_A | SEG_C | SEG_D | SEG_F | SEG_G,                  // 5
    SEG_A | SEG_C | SEG_D | SEG_E | SEG_F | SEG_G,          // 6
    SEG_A | SEG_B | SEG_C,                                  // 7
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_E | SEG_F | SEG_G,  // 8
    SEG_A | SEG_B | SEG_C | SEG_D | SEG_F | SEG_G,          // 9
};
constexpr uint8_t kBlank = 0;
constexpr uint8_t kDash = SEG_G;
constexpr uint8_t kLowerC = SEG_D | SEG_E | SEG_G;
constexpr uint8_t kUpperP = SEG_A | SEG_B | SEG_E | SEG_F | SEG_G;
constexpr uint8_t kLowerB = SEG_C | SEG_D | SEG_E | SEG_F | SEG_G;
constexpr uint8_t kUpperL = SEG_D | SEG_E | SEG_F;

Tm1637 g_tm(PIN_TM_CLK, PIN_TM_DIO);
uint8_t g_shown[4] = {0xFF, 0xFF, 0xFF, 0xFF};

void write(const uint8_t segs[4]) {
  if (memcmp(segs, g_shown, 4) == 0) return;
  memcpy(g_shown, segs, 4);
  g_tm.setSegments(segs);
}

// 先頭に文字 prefix、右寄せで数字 (最大 3 桁)
void prefixed(uint8_t prefix, int value) {
  uint8_t s[4] = {prefix, kBlank, kBlank, kBlank};
  if (value < 0) value = 0;
  if (value > 999) value = 999;
  int pos = 3;
  do {
    s[pos--] = kDigits[value % 10];
    value /= 10;
  } while (value > 0 && pos >= 1);
  write(s);
}

}  // namespace

void begin() {
  g_tm.begin();
  g_tm.setBrightness(DISPLAY_BRIGHTNESS);
}

void showBoot() {
  const uint8_t s[4] = {kDash, kDash, kDash, kDash};
  write(s);
}

void showConnected(int count) { prefixed(kLowerC, count); }

void showWinner(int id) {
  if (id <= 0) {
    showBoot();
    return;
  }
  prefixed(kBlank, id);
}

void showRegister(int nextId) { prefixed(kUpperP, nextId); }

void showBattery(int percent) { prefixed(kLowerB, percent); }

void showLowChild(int id) { prefixed(kUpperL, id); }

}  // namespace display

#else

namespace display {
void begin() {}
void showBoot() {}
void showConnected(int) {}
void showWinner(int) {}
void showRegister(int) {}
void showBattery(int) {}
void showLowChild(int) {}
}  // namespace display

#endif
