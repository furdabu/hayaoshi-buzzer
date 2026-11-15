// リチウムイオン電池 (1 セル) の電圧から残量を見積もる。Arduino 非依存 (PC でテスト可能)。
#pragma once

namespace buzzer {

// 電圧 (mV) → 残量 (%)。放電カーブを折れ線で近似したおおよその値。
inline int batteryPercent(int mv) {
  static const int kMv[] = {3300, 3500, 3600, 3700, 3800, 3900, 4000, 4100, 4150};
  static const int kPct[] = {0, 5, 12, 30, 50, 65, 80, 93, 100};
  constexpr int n = sizeof(kMv) / sizeof(kMv[0]);
  if (mv <= kMv[0]) return 0;
  for (int i = 1; i < n; ++i) {
    if (mv < kMv[i]) {
      return kPct[i - 1] + (kPct[i] - kPct[i - 1]) * (mv - kMv[i - 1]) / (kMv[i] - kMv[i - 1]);
    }
  }
  return 100;
}

// 「電池残量わずか」の判定。境目でちらつかないように、戻るときは hysteresisMv だけ余分に要求する。
inline bool batteryLow(bool wasLow, int mv, int lowMv, int hysteresisMv) {
  return wasLow ? mv < lowMv + hysteresisMv : mv < lowMv;
}

// 無線で送るための 1 バイト表現 (20mV 単位, 0 = 不明)
inline unsigned char encodeBattery20mV(int mv) {
  if (mv <= 0) return 0;
  const int v = (mv + 10) / 20;
  return static_cast<unsigned char>(v < 1 ? 1 : (v > 255 ? 255 : v));
}

inline int decodeBattery20mV(unsigned char v) { return v * 20; }

}  // namespace buzzer
