// 子機の MAC アドレス → 番号 (1〜MAX_CHILDREN) の対応表。
// 親機のフラッシュ (NVS) に保存されるので、電源を切っても番号は変わらない。
#pragma once

#include <stdint.h>

#include "config.h"

class Registry {
 public:
  void begin();  // 保存済みの対応表を読み込む

  uint8_t idOf(const uint8_t mac[6]) const;  // 未登録なら 0
  uint8_t assign(const uint8_t mac[6], uint32_t nowMs);  // 登録済みならその番号、満杯なら 0
  void clear();

  void touch(const uint8_t mac[6], uint32_t nowMs);
  int connected(uint32_t nowMs, uint32_t timeoutMs) const;
  uint8_t count() const { return count_; }

 private:
  void save();

  uint8_t macs_[MAX_CHILDREN][6] = {};
  uint32_t lastSeen_[MAX_CHILDREN] = {};
  uint8_t count_ = 0;
};
