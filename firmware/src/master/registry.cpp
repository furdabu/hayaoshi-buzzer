#include "registry.h"

#include <Preferences.h>
#include <string.h>

namespace {
constexpr const char* kNamespace = "hayaoshi";
// MAC アドレス (6 バイト) を番号順に並べた 1 つのデータとして保存する。
// 台数はデータの長さから求めるので、書き込み途中で電源が切れても台数とデータが食い違わない。
constexpr const char* kKeyMacs = "macs";
}  // namespace

void Registry::begin() {
  count_ = 0;
  memset(macs_, 0, sizeof(macs_));
  memset(lastSeen_, 0, sizeof(lastSeen_));

  Preferences prefs;
  if (!prefs.begin(kNamespace, /*readOnly=*/true)) return;  // まだ一度も保存していない
  const size_t len = prefs.getBytesLength(kKeyMacs);
  if (len > 0 && len % 6 == 0 && len <= sizeof(macs_)) {
    if (prefs.getBytes(kKeyMacs, macs_, sizeof(macs_)) == len) {
      count_ = static_cast<uint8_t>(len / 6);
    }
  }
  prefs.end();
}

uint8_t Registry::idOf(const uint8_t mac[6]) const {
  for (uint8_t i = 0; i < count_; ++i) {
    if (memcmp(macs_[i], mac, 6) == 0) return i + 1;
  }
  return 0;
}

uint8_t Registry::assign(const uint8_t mac[6], uint32_t nowMs) {
  uint8_t id = idOf(mac);
  if (id == 0) {
    if (count_ >= MAX_CHILDREN) return 0;
    memcpy(macs_[count_], mac, 6);
    ++count_;
    id = count_;
    save();
  }
  lastSeen_[id - 1] = nowMs == 0 ? 1 : nowMs;
  return id;
}

void Registry::clear() {
  count_ = 0;
  memset(macs_, 0, sizeof(macs_));
  memset(lastSeen_, 0, sizeof(lastSeen_));
  save();
}

void Registry::touch(const uint8_t mac[6], uint32_t nowMs) {
  const uint8_t id = idOf(mac);
  if (id != 0) lastSeen_[id - 1] = nowMs == 0 ? 1 : nowMs;
}

int Registry::connected(uint32_t nowMs, uint32_t timeoutMs) const {
  int n = 0;
  for (uint8_t i = 0; i < count_; ++i) {
    if (lastSeen_[i] != 0 && nowMs - lastSeen_[i] <= timeoutMs) ++n;
  }
  return n;
}

void Registry::save() {
  Preferences prefs;
  if (!prefs.begin(kNamespace, /*readOnly=*/false)) return;
  if (count_ > 0) {
    prefs.putBytes(kKeyMacs, macs_, sizeof(macs_[0]) * count_);
  } else {
    prefs.remove(kKeyMacs);
  }
  prefs.end();
}
