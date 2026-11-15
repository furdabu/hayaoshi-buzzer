#include "audio.h"

#include <Arduino.h>
#include <DFRobotDFPlayerMini.h>

#include "config.h"

// 互換品の DFPlayer で応答が返ってこない場合は 1 にする (応答確認を省略)
#ifndef DFPLAYER_SKIP_CHECK
#define DFPLAYER_SKIP_CHECK 0
#endif

namespace audio {
namespace {

DFRobotDFPlayerMini g_df;
bool g_dfReady = false;

}  // namespace

void begin() {
  Serial2.begin(9600, SERIAL_8N1, PIN_DF_RX, PIN_DF_TX);
#if DFPLAYER_SKIP_CHECK
  g_df.begin(Serial2, /*isACK=*/false, /*doReset=*/true);
  delay(1000);
  g_dfReady = true;
#else
  g_dfReady = g_df.begin(Serial2, /*isACK=*/true, /*doReset=*/true);
  if (g_dfReady) {
    // 以降は応答待ちでループが止まらないように ACK なしで再設定する (リセットはしない)
    g_df.begin(Serial2, /*isACK=*/false, /*doReset=*/false);
  } else {
    Serial.println(F("[audio] DFPlayer が応答しません。配線と microSD を確認してください。"));
    Serial.println(F("[audio] 互換品の場合は config で DFPLAYER_SKIP_CHECK=1 を試してください。"));
  }
#endif
  if (g_dfReady) {
    g_df.volume(AUDIO_VOLUME);
    Serial.println(F("[audio] DFPlayer OK"));
  }
}

void play(Sound sound) {
  if (g_dfReady) g_df.playMp3Folder(static_cast<int>(sound));
}

void update() {
  // DFPlayer からの通知 (再生終了など) は使わないので読み捨てる
  while (Serial2.available()) Serial2.read();
}

bool dfplayerReady() { return g_dfReady; }

}  // namespace audio
