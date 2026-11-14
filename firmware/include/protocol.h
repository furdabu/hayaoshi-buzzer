// 親機・子機で共有する ESP-NOW パケット定義
// Packet definitions shared by master (親機) and child (子機).
//
// 通信の流れ (詳細は docs/protocol.md):
//   親機 -> 全子機 (broadcast) : StatePacket を 100ms ごと + 状態変化時に連続送信
//   子機 -> 親機   (unicast)   : PressPacket (ボタン押下), HelloPacket (生存通知)
//   親機 -> 全子機 (broadcast) : AssignPacket (子機番号の通知)
#pragma once

#include <stdint.h>
#include <string.h>

namespace proto {

constexpr uint32_t kMagic = 0x315A4251;  // "QBZ1" (little endian)
constexpr uint8_t kVersion = 1;

enum class MsgType : uint8_t {
  State = 1,
  Press = 2,
  Hello = 3,
  Assign = 4,
};

enum class RoundState : uint8_t {
  Open = 0,    // 受付中: 子機のボタンを受け付ける
  Locked = 1,  // 回答者決定: winner 以外は反応しない
};

enum class Result : uint8_t {
  None = 0,
  Correct = 1,
  Incorrect = 2,
};

// StatePacket.flags
constexpr uint8_t kFlagRegisterMode = 0x01;  // 番号登録モード中

// AssignPacket.flags
constexpr uint8_t kAssignFlash = 0x01;  // 子機のランプを光らせて登録完了を知らせる

struct __attribute__((packed)) Header {
  uint32_t magic;
  uint8_t version;
  uint8_t type;   // MsgType
  uint8_t group;  // GROUP_ID: 同じ部屋で複数セットを使うときに分ける
  uint8_t reserved;
};

// 親機 -> 全子機。状態そのものを毎回送るので、取りこぼしても次の送信で回復する。
struct __attribute__((packed)) StatePacket {
  Header h;
  uint32_t bootId;       // 親機の起動ごとに変わる乱数 (再起動検出用)
  uint32_t seq;          // 送信ごとに +1
  int64_t masterTimeUs;  // 送信直前の親機時刻 (esp_timer_get_time)。子機の時刻同期に使う
  uint16_t round;        // 正解/不正解でリセットされるたびに +1
  uint8_t state;         // RoundState
  uint8_t winnerId;      // 回答権を得た子機の番号 (0 = なし)
  uint8_t winnerMac[6];  // 回答権を得た子機の MAC
  uint16_t judgeSeq;     // 判定(正解/不正解)ボタンが押されるたびに +1
  uint8_t lastResult;    // 直近の判定 Result
  uint8_t lastWinnerMac[6];  // 直近の判定対象だった子機
  uint8_t flags;
};

// 子機 -> 親機。
struct __attribute__((packed)) PressPacket {
  Header h;
  uint16_t round;          // 子機が受付中だと認識していたラウンド
  int64_t pressMasterUs;   // ボタンが押された時刻を「親機の時計」に換算した値
  uint8_t attempt;         // 再送回数 (0 = 初回)
};

// 子機 -> 親機。1 秒ごとの生存通知。
struct __attribute__((packed)) HelloPacket {
  Header h;
  uint8_t fwMajor;
  uint8_t fwMinor;
  uint8_t knownId;  // 子機が覚えている自分の番号 (0 = 未割り当て)
  uint8_t reserved;
};

// 親機 -> 全子機。targetMac の子機に番号を伝える。
struct __attribute__((packed)) AssignPacket {
  Header h;
  uint8_t targetMac[6];
  uint8_t id;
  uint8_t flags;
};

constexpr size_t kMaxPacketSize = sizeof(StatePacket);

inline void fillHeader(Header& h, MsgType type, uint8_t group) {
  h.magic = kMagic;
  h.version = kVersion;
  h.type = static_cast<uint8_t>(type);
  h.group = group;
  h.reserved = 0;
}

// 受信データの種類を調べる。プロトコル外のデータなら false。
inline bool peekType(const uint8_t* data, size_t len, uint8_t group, MsgType* out) {
  if (len < sizeof(Header)) return false;
  Header h;
  memcpy(&h, data, sizeof(h));
  if (h.magic != kMagic || h.version != kVersion || h.group != group) return false;
  *out = static_cast<MsgType>(h.type);
  return true;
}

// 受信データを構造体にコピーする (長さが足りなければ false)。
template <typename T>
inline bool parse(const uint8_t* data, size_t len, T* out) {
  if (len < sizeof(T)) return false;
  memcpy(out, data, sizeof(T));
  return true;
}

inline bool macEqual(const uint8_t* a, const uint8_t* b) { return memcmp(a, b, 6) == 0; }

inline bool macIsZero(const uint8_t* a) {
  static const uint8_t kZero[6] = {0, 0, 0, 0, 0, 0};
  return memcmp(a, kZero, 6) == 0;
}

}  // namespace proto
