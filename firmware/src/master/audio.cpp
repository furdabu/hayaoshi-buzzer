#include "audio.h"

#include <Arduino.h>
#include <DFRobotDFPlayerMini.h>

#include "config.h"

// 互換品の DFPlayer で応答が返ってこない場合は 1 にする (応答確認を省略)
#ifndef DFPLAYER_SKIP_CHECK
#define DFPLAYER_SKIP_CHECK 0
#endif

// 1: DFPlayer が見つからないときだけブザーを鳴らす / 0: 常にブザーも鳴らす
#ifndef BUZZER_FALLBACK_ONLY
#define BUZZER_FALLBACK_ONLY 1
#endif

namespace audio {
namespace {

DFRobotDFPlayerMini g_df;
bool g_dfReady = false;

struct Note {
  uint16_t freq;  // 0 = 休符
  uint16_t ms;
};

const Note kCorrect[] = {{988, 140}, {0, 30}, {784, 600}};      // ピン・ポーン
const Note kIncorrect[] = {{170, 180}, {0, 70}, {170, 600}};    // ブッ・ブー
const Note kBuzzIn[] = {{1760, 70}, {2349, 280}};               // ピコーン
const Note kStartup[] = {{1047, 90}, {1319, 90}, {1568, 160}};  // ドミソ

const Note* g_seq = nullptr;
size_t g_len = 0;
size_t g_index = 0;
uint32_t g_noteEndMs = 0;

bool buzzerEnabled() {
  if (PIN_BUZZER < 0) return false;
  return !(BUZZER_FALLBACK_ONLY && g_dfReady);
}

void startNote(uint32_t nowMs) {
  const Note& n = g_seq[g_index];
  if (n.freq == 0) {
    noTone(PIN_BUZZER);
  } else {
    tone(PIN_BUZZER, n.freq);
  }
  g_noteEndMs = nowMs + n.ms;
}

template <size_t N>
void startSequence(const Note (&notes)[N]) {
  g_seq = notes;
  g_len = N;
  g_index = 0;
  startNote(millis());
}

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
  if (g_dfReady) {
    g_df.playMp3Folder(static_cast<int>(sound));
  }
  if (buzzerEnabled()) {
    switch (sound) {
      case Sound::Correct:
        startSequence(kCorrect);
        break;
      case Sound::Incorrect:
        startSequence(kIncorrect);
        break;
      case Sound::BuzzIn:
        startSequence(kBuzzIn);
        break;
      case Sound::Startup:
        startSequence(kStartup);
        break;
    }
  }
}

void update() {
  // DFPlayer からの通知 (再生終了など) は使わないので読み捨てる
  while (Serial2.available()) Serial2.read();

  if (g_seq == nullptr) return;
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - g_noteEndMs) < 0) return;
  ++g_index;
  if (g_index >= g_len) {
    noTone(PIN_BUZZER);
    g_seq = nullptr;
    return;
  }
  startNote(now);
}

bool dfplayerReady() { return g_dfReady; }

}  // namespace audio
