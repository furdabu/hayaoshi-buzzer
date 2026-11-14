#include "lamp.h"

#include <math.h>

Lamp::Lamp(uint8_t pin, uint16_t count, uint8_t brightness)
    : strip_(count > kMaxLeds ? kMaxLeds : count, pin, NEO_GRB + NEO_KHZ800),
      count_(count > kMaxLeds ? kMaxLeds : count),
      brightness_(brightness) {
  memset(frame_, 0, sizeof(frame_));
}

void Lamp::begin() {
  strip_.begin();
  strip_.setBrightness(brightness_);
  strip_.clear();
  strip_.show();
  dirty_ = false;
}

void Lamp::fill(uint32_t color, uint16_t first, uint16_t n) {
  if (first >= count_) return;
  const uint16_t last = (n == 0 || first + n > count_) ? count_ : first + n;
  for (uint16_t i = first; i < last; ++i) {
    if (frame_[i] != color) {
      frame_[i] = color;
      dirty_ = true;
    }
  }
}

void Lamp::show() {
  if (!dirty_) return;
  for (uint16_t i = 0; i < count_; ++i) strip_.setPixelColor(i, frame_[i]);
  strip_.show();
  dirty_ = false;
}

uint32_t Lamp::scale(uint32_t color, uint8_t level) {
  const uint32_t r = ((color >> 16) & 0xFF) * level / 255;
  const uint32_t g = ((color >> 8) & 0xFF) * level / 255;
  const uint32_t b = (color & 0xFF) * level / 255;
  return (r << 16) | (g << 8) | b;
}

uint8_t Lamp::breathe(uint32_t nowMs, uint32_t periodMs, uint8_t minLevel, uint8_t maxLevel) {
  const float phase = static_cast<float>(nowMs % periodMs) / periodMs;
  const float wave = 0.5f - 0.5f * cosf(phase * 2.0f * static_cast<float>(M_PI));
  return static_cast<uint8_t>(minLevel + (maxLevel - minLevel) * wave);
}
