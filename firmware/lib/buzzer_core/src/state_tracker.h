// 親機が送ってくる「今の状態」を見続けて、変化を出来事に直すロジック (PC 連携の受信機側)。
// Arduino に依存しないので PC 上でユニットテストできる (firmware/test)。
//
// 考え方:
//   親機は「今の状態そのもの」を 100ms ごとに送ってくる (docs/protocol.md)。
//   PC 側のプログラムが欲しいのは「回答者が決まった」「正解だった」といった出来事なので、
//   前回の状態とくらべて、変わった所を出来事として取り出す。
//   何回か取りこぼしても、次に届いた状態から「回答者決定 → 判定 → 次の受付」の順で出し直す。
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace buzzer {

// 親機の状態 (StatePacket から必要な所だけ写したもの)
struct MasterState {
  uint32_t bootId = 0;         // 親機の起動ごとに変わる
  uint32_t seq = 0;            // 送信ごとに +1
  uint16_t round = 0;          // 正解/不正解のたびに +1 (0 は使わない)
  bool locked = false;         // 回答者が決まっている
  bool registerMode = false;   // 番号登録モード中
  uint8_t winnerId = 0;        // 回答者の番号 (0 = なし / 番号なし)
  uint8_t winnerMac[6] = {};
  uint16_t judgeSeq = 0;       // 判定のたびに +1
  uint8_t lastResult = 0;      // 直近の判定: 0 = まだない, 1 = 正解, 2 = 不正解
  uint8_t lastWinnerMac[6] = {};  // 直近に判定された子機 (全部 0 = 回答者なしで判定)
};

struct TrackerEvent {
  enum class Type : uint8_t {
    MasterFound,      // 親機を見つけた (受信機の起動後はじめて、または別の親機)
    MasterRestarted,  // 親機が再起動した
    RegisterOn,       // 番号登録モードに入った
    RegisterOff,      // 番号登録モードが終わった
    Buzz,             // 回答者が決まった
    Judge,            // 正解 / 不正解が押された
    Open,             // 次の受付が始まった
  };
  Type type;
  uint16_t round;  // Buzz / Judge: そのラウンド, Open: 新しいラウンド
  uint8_t id;      // Buzz: 回答者, Judge: 判定された子機 (0 = 回答者なし)
  bool idKnown;    // false = 番号が分からない (id は 0)
  uint8_t result;  // Judge: 1 = 正解, 2 = 不正解
};

class StateTracker {
 public:
  static constexpr size_t kMaxEvents = 6;  // 1 回の update() で出る出来事の上限
  static constexpr size_t kMaxIds = 64;

  StateTracker() { reset(); }

  // 親機が別のものに変わったときなどに、覚えていることを全部忘れる
  void reset() {
    have_ = false;
    last_ = MasterState();
    buzzRound_ = 0;
    forgetIds();
  }

  // 新しく届いた状態を渡す。出来事を out に順番どおりに入れて、その数を返す。
  size_t update(const MasterState& s, TrackerEvent out[kMaxEvents]) {
    size_t n = 0;

    if (!have_ || s.bootId != last_.bootId) {
      // 途中から見始めたので、それまでの出来事は分からない。今の状態だけを覚える
      out[n++] = make(have_ ? TrackerEvent::Type::MasterRestarted : TrackerEvent::Type::MasterFound,
                      s.round);
      have_ = true;
      if (s.registerMode) forgetIds();
      learnWinner(s);
      buzzRound_ = s.locked ? s.round : 0;  // すでに決まっている回答者は、あらためて知らせない
      last_ = s;
      return n;
    }

    // 順番が入れかわって届いた古い状態は捨てる
    if (static_cast<int32_t>(s.seq - last_.seq) <= 0) return 0;

    if (s.registerMode != last_.registerMode) {
      if (s.registerMode) forgetIds();  // 番号を付け直すので、古い対応表は使えない
      out[n++] = make(s.registerMode ? TrackerEvent::Type::RegisterOn
                                     : TrackerEvent::Type::RegisterOff,
                      s.round);
    }
    learnWinner(s);

    if (s.judgeSeq != last_.judgeSeq) {
      // 親機は判定のすぐあとに次のラウンドへ進むので、判定されたのは 1 つ前のラウンド
      const uint16_t judged = s.round != last_.round ? prevRound(s.round) : s.round;
      const bool nobody = isZero(s.lastWinnerMac);
      const uint8_t id = nobody ? 0 : idOf(s.lastWinnerMac);
      const bool known = nobody || id != 0;
      if (!nobody && buzzRound_ != judged) {
        // 回答者が決まった知らせを取りこぼしていた: 先にそれを出す
        TrackerEvent e = make(TrackerEvent::Type::Buzz, judged);
        e.id = id;
        e.idKnown = known;
        out[n++] = e;
      }
      TrackerEvent e = make(TrackerEvent::Type::Judge, judged);
      e.id = id;
      e.idKnown = known;
      e.result = s.lastResult;
      out[n++] = e;
    }

    if (s.round != last_.round && !s.registerMode) {
      out[n++] = make(TrackerEvent::Type::Open, s.round);
    }

    if (s.locked && buzzRound_ != s.round) {
      TrackerEvent e = make(TrackerEvent::Type::Buzz, s.round);
      e.id = s.winnerId;
      e.idKnown = s.winnerId != 0;
      out[n++] = e;
      buzzRound_ = s.round;
    }

    last_ = s;
    return n;
  }

  // 子機の MAC アドレスと番号の対応を覚える (親機の Assign パケットから)
  void learn(const uint8_t mac[6], uint8_t id) {
    if (id == 0 || id > kMaxIds || isZero(mac)) return;
    for (size_t i = 0; i < kMaxIds; ++i) {
      if (memcmp(macs_[i], mac, 6) == 0) memset(macs_[i], 0, 6);  // 番号が変わった子機
    }
    memcpy(macs_[id - 1], mac, 6);
  }

  // 分からなければ 0
  uint8_t idOf(const uint8_t mac[6]) const {
    if (isZero(mac)) return 0;
    for (size_t i = 0; i < kMaxIds; ++i) {
      if (memcmp(macs_[i], mac, 6) == 0) return static_cast<uint8_t>(i + 1);
    }
    return 0;
  }

  bool hasState() const { return have_; }
  const MasterState& state() const { return last_; }

  // 直近の判定。まだ一度も判定されていなければ false。
  // *id = 判定された子機 (0 = 回答者なし), *idKnown = false なら番号が分からない
  bool lastJudge(uint8_t* result, uint8_t* id, bool* idKnown) const {
    if (!have_ || last_.lastResult == 0) return false;
    const bool nobody = isZero(last_.lastWinnerMac);
    *result = last_.lastResult;
    *id = nobody ? 0 : idOf(last_.lastWinnerMac);
    *idKnown = nobody || *id != 0;
    return true;
  }

 private:
  static bool isZero(const uint8_t mac[6]) {
    static const uint8_t kZero[6] = {0, 0, 0, 0, 0, 0};
    return memcmp(mac, kZero, 6) == 0;
  }

  // ラウンド番号は 1〜65535 を回る (0 は使わない)
  static uint16_t prevRound(uint16_t round) {
    return round <= 1 ? 65535 : static_cast<uint16_t>(round - 1);
  }

  static TrackerEvent make(TrackerEvent::Type type, uint16_t round) {
    TrackerEvent e;
    e.type = type;
    e.round = round;
    e.id = 0;
    e.idKnown = false;
    e.result = 0;
    return e;
  }

  void learnWinner(const MasterState& s) {
    if (s.locked) learn(s.winnerMac, s.winnerId);
  }

  void forgetIds() { memset(macs_, 0, sizeof(macs_)); }

  bool have_ = false;
  MasterState last_;
  uint16_t buzzRound_ = 0;  // 回答者決定を知らせ終わったラウンド (0 = なし)
  uint8_t macs_[kMaxIds][6];
};

}  // namespace buzzer
