// 電池の残量 (親機・子機共通)
#pragma once

#include <stdint.h>

namespace battery {

void begin();
void update(uint32_t nowMs);  // loop() から呼ぶ (1 秒ごとに測定)

bool present();       // 電池の電圧らしい値が測れているか (配線が外れていると false)
int millivolts();     // 電池電圧 (mV)。測れていなければ 0
int percent();        // 残量 (%)。測れていなければ 0
bool low();           // 残量わずか
bool critical();      // 電池切れ寸前 (BATTERY_CUTOFF_MV を 10 秒下回った)。電池を守るため停止する
uint8_t encoded();    // 無線で送る 1 バイト表現 (20mV 単位, 0 = 不明)

}  // namespace battery
