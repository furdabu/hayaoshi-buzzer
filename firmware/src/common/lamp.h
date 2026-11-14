// WS2812B (NeoPixel) ランプ。変化があったときだけ LED に書き込む。
#pragma once

#include <Adafruit_NeoPixel.h>

class Lamp {
 public:
  static constexpr uint16_t kMaxLeds = 128;

  Lamp(uint8_t pin, uint16_t count, uint8_t brightness);

  void begin();
  // first から n 個を color にする (n = 0 なら最後まで)
  void fill(uint32_t color, uint16_t first = 0, uint16_t n = 0);
  void clear() { fill(0); }
  // 前回から変化があれば LED に送る
  void show();

  uint16_t count() const { return count_; }

  // 色の明るさを level/255 倍にする
  static uint32_t scale(uint32_t color, uint8_t level);
  // ゆっくり明滅する明るさ (minLevel〜maxLevel)
  static uint8_t breathe(uint32_t nowMs, uint32_t periodMs, uint8_t minLevel, uint8_t maxLevel);

 private:
  Adafruit_NeoPixel strip_;
  uint16_t count_;
  uint8_t brightness_;
  uint32_t frame_[kMaxLeds];
  bool dirty_ = true;
};
