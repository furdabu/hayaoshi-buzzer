// 子機の時計を親機の時計に合わせるロジック (子機側)。
// Arduino に依存しないので PC 上でユニットテストできる (firmware/test)。
//
// 考え方:
//   親機は送信直前の自分の時刻 masterUs を入れて全子機に一斉送信する。
//   同じ電波は全子機にほぼ同時に届くので、各子機は
//     offset = masterUs - (受信した瞬間の自分の時刻)
//   を求めれば、全子機がほぼ同じ基準で親機の時計を推定できる。
//   受信処理の遅れ (latency) は offset を小さくする方向にしか働かないので、
//   直近数回分の最大値を使うと遅れの影響を最小にできる。
#pragma once

#include <stdint.h>

namespace buzzer {

class ClockSync {
 public:
  static constexpr int kWindow = 8;  // 100ms 間隔なら直近 0.8 秒分

  void reset() {
    count_ = 0;
    head_ = 0;
    lastRxUs_ = 0;
  }

  // 親機からの時刻付きパケットを受信したときに呼ぶ
  void onBeacon(int64_t masterUs, int64_t localRxUs) {
    samples_[head_] = masterUs - localRxUs;
    head_ = (head_ + 1) % kWindow;
    if (count_ < kWindow) ++count_;
    lastRxUs_ = localRxUs;
  }

  // 最後の受信から maxAgeUs 以内なら同期済みとみなす
  bool synced(int64_t localNowUs, int64_t maxAgeUs) const {
    return count_ > 0 && (localNowUs - lastRxUs_) <= maxAgeUs;
  }

  // 子機の時計 → 親機の時計
  int64_t toMaster(int64_t localUs) const { return localUs + offset(); }

  int64_t offset() const {
    if (count_ == 0) return 0;
    int64_t best = samples_[(head_ + kWindow - 1) % kWindow];
    for (int i = 1; i < count_; ++i) {
      const int64_t s = samples_[(head_ + kWindow - 1 - i) % kWindow];
      if (s > best) best = s;
    }
    return best;
  }

  int sampleCount() const { return count_; }

 private:
  int64_t samples_[kWindow] = {};
  int count_ = 0;
  int head_ = 0;
  int64_t lastRxUs_ = 0;
};

}  // namespace buzzer
