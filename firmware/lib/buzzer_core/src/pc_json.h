// 受信機が PC へ送る 1 行ずつの JSON (JSON Lines) を作る。形式の説明は docs/pc-link.md。
// Arduino に依存しないので PC 上でユニットテストできる (firmware/test)。
//
// どの関数も buf に 1 行分 (改行なし) を書いて、その長さを返す。
// buf に入りきらないときは、こわれた行を送らないように 0 を返す (buf は空文字列になる)。
#pragma once

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "state_tracker.h"

namespace buzzer {

// 親機の Info パケットから、表示に使う所だけ写したもの
struct MasterInfo {
  uint8_t registered = 0;       // 登録済みの子機の台数
  uint8_t connected = 0;        // 接続中の台数
  uint64_t connectedMask = 0;   // ビット (番号 - 1) が 1 = 接続中
  uint64_t lowBatteryMask = 0;  // ビット (番号 - 1) が 1 = 電池残量わずか
  int masterBatteryMv = 0;      // 親機の電池電圧 (0 = 分からない)
  bool masterBatteryLow = false;
  uint16_t buzzRound = 0;       // 直近に回答者が決まったラウンド (0 = まだない)
  uint8_t buzzId = 0;
  uint8_t buzzCandidates = 0;   // ほぼ同時に押していた子機の数 (回答者を含む)
  uint32_t buzzElapsedMs = 0;   // 受付開始から回答者が押すまでの時間
};

namespace pcjson {

// buf の後ろへ書き足していく小さな道具
class Line {
 public:
  Line(char* buf, size_t cap) : buf_(buf), cap_(cap) {
    if (cap_ > 0) buf_[0] = '\0';
  }

  void add(const char* fmt, ...) __attribute__((format(printf, 2, 3))) {
    if (overflow_ || cap_ == 0) return;
    va_list ap;
    va_start(ap, fmt);
    const int n = vsnprintf(buf_ + len_, cap_ - len_, fmt, ap);
    va_end(ap);
    if (n < 0 || static_cast<size_t>(n) >= cap_ - len_) {
      overflow_ = true;
      return;
    }
    len_ += static_cast<size_t>(n);
  }

  // 番号の一覧: [1,2,5]
  void idList(uint64_t mask) {
    add("[");
    bool first = true;
    for (int id = 1; id <= 64; ++id) {
      if (((mask >> (id - 1)) & 1) == 0) continue;
      add(first ? "%d" : ",%d", id);
      first = false;
    }
    add("]");
  }

  // 番号。分からないときは null
  void idOrNull(uint8_t id, bool known) {
    if (known) {
      add("%u", static_cast<unsigned>(id));
    } else {
      add("null");
    }
  }

  size_t finish() {
    if (overflow_ || cap_ == 0) {
      if (cap_ > 0) buf_[0] = '\0';
      return 0;
    }
    return len_;
  }

 private:
  char* buf_;
  size_t cap_;
  size_t len_ = 0;
  bool overflow_ = false;
};

inline const char* resultName(uint8_t result) {
  return result == 1 ? "correct" : result == 2 ? "incorrect" : "none";
}

// 受信機の自己紹介
inline size_t hello(char* buf, size_t cap, int fwMajor, int fwMinor, int channel, int group) {
  Line l(buf, cap);
  l.add("{\"type\":\"hello\",\"device\":\"hayaoshi-receiver\",\"fw\":\"%d.%d\",\"channel\":%d,"
        "\"group\":%d}",
        fwMajor, fwMinor, channel, group);
  return l.finish();
}

// 親機が見つかった / 見失った
inline size_t master(char* buf, size_t cap, bool connected, bool restarted) {
  Line l(buf, cap);
  if (connected) {
    l.add("{\"type\":\"master\",\"connected\":true,\"restarted\":%s}", restarted ? "true" : "false");
  } else {
    l.add("{\"type\":\"master\",\"connected\":false}");
  }
  return l.finish();
}

// 出来事 1 つ
inline size_t event(char* buf, size_t cap, const TrackerEvent& e) {
  Line l(buf, cap);
  switch (e.type) {
    case TrackerEvent::Type::MasterFound:
      return master(buf, cap, true, false);
    case TrackerEvent::Type::MasterRestarted:
      return master(buf, cap, true, true);
    case TrackerEvent::Type::RegisterOn:
      l.add("{\"type\":\"register\",\"active\":true}");
      break;
    case TrackerEvent::Type::RegisterOff:
      l.add("{\"type\":\"register\",\"active\":false}");
      break;
    case TrackerEvent::Type::Buzz:
      l.add("{\"type\":\"buzz\",\"round\":%u,\"id\":", static_cast<unsigned>(e.round));
      l.idOrNull(e.id, e.idKnown);
      l.add("}");
      break;
    case TrackerEvent::Type::Judge:
      l.add("{\"type\":\"judge\",\"round\":%u,\"id\":", static_cast<unsigned>(e.round));
      l.idOrNull(e.id, e.idKnown);
      l.add(",\"result\":\"%s\"}", resultName(e.result));
      break;
    case TrackerEvent::Type::Open:
      l.add("{\"type\":\"open\",\"round\":%u}", static_cast<unsigned>(e.round));
      break;
  }
  return l.finish();
}

// 今の状態 (1 秒ごと、と出来事のたびに送る)
inline size_t state(char* buf, size_t cap, bool masterConnected, const StateTracker& t) {
  Line l(buf, cap);
  if (!masterConnected || !t.hasState()) {
    l.add("{\"type\":\"state\",\"master\":false}");
    return l.finish();
  }
  const MasterState& s = t.state();
  const char* phase = s.registerMode ? "register" : s.locked ? "locked" : "open";
  l.add("{\"type\":\"state\",\"master\":true,\"phase\":\"%s\",\"round\":%u,\"winner\":", phase,
        static_cast<unsigned>(s.round));
  if (s.locked) {
    l.idOrNull(s.winnerId, s.winnerId != 0);
  } else {
    l.add("0");
  }
  l.add(",\"judgeSeq\":%u,\"last\":", static_cast<unsigned>(s.judgeSeq));
  uint8_t result = 0;
  uint8_t id = 0;
  bool known = false;
  if (t.lastJudge(&result, &id, &known)) {
    l.add("{\"result\":\"%s\",\"id\":", resultName(result));
    l.idOrNull(id, known);
    l.add("}");
  } else {
    l.add("null");
  }
  l.add("}");
  return l.finish();
}

// 子機の接続や電池など (変わったとき、と 5 秒ごとに送る)
inline size_t info(char* buf, size_t cap, const MasterInfo& v) {
  Line l(buf, cap);
  l.add("{\"type\":\"info\",\"registered\":%u,\"connected\":%u,\"ids\":",
        static_cast<unsigned>(v.registered), static_cast<unsigned>(v.connected));
  l.idList(v.connectedMask);
  l.add(",\"lowBattery\":");
  l.idList(v.lowBatteryMask);
  if (v.masterBatteryMv > 0) {
    l.add(",\"masterBattery\":{\"mv\":%d,\"low\":%s}", v.masterBatteryMv,
          v.masterBatteryLow ? "true" : "false");
  } else {
    l.add(",\"masterBattery\":null");
  }
  if (v.buzzRound != 0) {
    l.add(",\"buzz\":{\"round\":%u,\"id\":%u,\"elapsedMs\":%lu,\"candidates\":%u}",
          static_cast<unsigned>(v.buzzRound), static_cast<unsigned>(v.buzzId),
          static_cast<unsigned long>(v.buzzElapsedMs), static_cast<unsigned>(v.buzzCandidates));
  } else {
    l.add(",\"buzz\":null");
  }
  l.add("}");
  return l.finish();
}

}  // namespace pcjson
}  // namespace buzzer
