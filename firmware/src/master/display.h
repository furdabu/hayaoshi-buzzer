// 親機の 4 桁 7 セグ表示 (TM1637)。USE_DISPLAY=0 なら何もしない。
#pragma once

namespace display {

void begin();
void showBoot();                 // "----"
void showConnected(int count);   // "c 12"  … 接続中の子機の台数
void showWinner(int id);         // "  12"  … 回答権を得た子機の番号
void showRegister(int nextId);   // "P 12"  … 番号登録モード (次に登録される番号)
void showBattery(int percent);   // "b 87"  … 親機の電池残量 (%)
void showLowChild(int id);       // "L 12"  … 12 番の子機の電池残量がわずか
void blank();                    // 全部消す

}  // namespace display
