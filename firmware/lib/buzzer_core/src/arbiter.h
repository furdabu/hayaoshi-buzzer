// 「誰が一番早く押したか」を決めるロジック (親機側)。
// Arduino に依存しないので PC 上でユニットテストできる (firmware/test)。
//
// 考え方:
//   無線は届く順番が押した順番と一致するとは限らない (再送・混雑)。
//   そこで子機は「押した瞬間の時刻」を親機の時計に換算して送ってくる。
//   親機は最初の押下が届いてから windowUs だけ待ち、その間に届いた
//   押下の中から時刻が最も早いものを勝者にする。
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace buzzer {

struct Candidate {
  uint8_t mac[6];
  int64_t pressUs;    // 押した時刻 (親機の時計, 補正後)
  int64_t arrivalUs;  // 親機に届いた時刻
};

class Arbiter {
 public:
  static constexpr size_t kMaxCandidates = 64;

  enum class Offer : uint8_t {
    Accepted,   // 候補として受け付けた
    Duplicate,  // 同じ子機からの再送
    TooEarly,   // 受付開始より前に押されている
    Closed,     // すでに勝者が決まっている
    Full,       // 候補数の上限
  };

  explicit Arbiter(int64_t windowUs = 50000, int64_t earlyToleranceUs = 5000)
      : windowUs_(windowUs), earlyToleranceUs_(earlyToleranceUs) {
    reset(0);
  }

  // 新しいラウンドを開始する。roundOpenUs = 受付開始時刻 (親機の時計)
  void reset(int64_t roundOpenUs) {
    openUs_ = roundOpenUs;
    count_ = 0;
    firstArrivalUs_ = 0;
    collecting_ = false;
    decided_ = false;
  }

  // 押下を候補に加える。nowUs = その押下が届いた時刻 (親機の時計)
  Offer offer(const uint8_t mac[6], int64_t pressUs, int64_t nowUs) {
    if (decided_) return Offer::Closed;
    if (pressUs < openUs_ - earlyToleranceUs_) return Offer::TooEarly;
    for (size_t i = 0; i < count_; ++i) {
      if (memcmp(candidates_[i].mac, mac, 6) == 0) return Offer::Duplicate;
    }
    if (count_ >= kMaxCandidates) return Offer::Full;

    // 時刻同期の誤差で「受付開始より少し前」や「届いた時刻より後」に
    // なることがあるので、ありえる範囲に丸める。
    if (pressUs < openUs_) pressUs = openUs_;
    if (pressUs > nowUs) pressUs = nowUs;

    Candidate& c = candidates_[count_++];
    memcpy(c.mac, mac, 6);
    c.pressUs = pressUs;
    c.arrivalUs = nowUs;
    if (!collecting_) {
      collecting_ = true;
      firstArrivalUs_ = nowUs;
    }
    return Offer::Accepted;
  }

  // 定期的に呼ぶ。勝者が決まった瞬間に一度だけ true を返す。
  bool poll(int64_t nowUs, Candidate* winner) {
    if (!collecting_ || decided_) return false;
    if (nowUs - firstArrivalUs_ < windowUs_) return false;

    size_t best = 0;
    for (size_t i = 1; i < count_; ++i) {
      const Candidate& a = candidates_[i];
      const Candidate& b = candidates_[best];
      if (a.pressUs < b.pressUs || (a.pressUs == b.pressUs && a.arrivalUs < b.arrivalUs)) {
        best = i;
      }
    }
    decided_ = true;
    collecting_ = false;
    if (winner) *winner = candidates_[best];
    return true;
  }

  bool collecting() const { return collecting_; }
  bool decided() const { return decided_; }
  size_t candidateCount() const { return count_; }
  int64_t openUs() const { return openUs_; }

 private:
  int64_t windowUs_;
  int64_t earlyToleranceUs_;
  int64_t openUs_ = 0;
  int64_t firstArrivalUs_ = 0;
  bool collecting_ = false;
  bool decided_ = false;
  size_t count_ = 0;
  Candidate candidates_[kMaxCandidates];
};

}  // namespace buzzer
