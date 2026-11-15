// 効果音 (DFPlayer Mini + スピーカー)
#pragma once

#include <stdint.h>

namespace audio {

// microSD の /mp3/0001.mp3 〜 0004.mp3 に対応
enum class Sound : uint8_t {
  Correct = 1,    // 正解   (ピンポーン)
  Incorrect = 2,  // 不正解 (ブッブー)
  BuzzIn = 3,     // 回答者が決まった (ピコーン)
  Startup = 4,    // 起動音
};

void begin();
void play(Sound sound);
void update();  // loop() から毎回呼ぶ
bool dfplayerReady();

}  // namespace audio
