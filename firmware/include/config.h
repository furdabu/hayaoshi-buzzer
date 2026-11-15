// ============================================================================
//  早押しボタン 設定ファイル
//  ピン番号や動作パラメータはここで変更できます。
//  platformio.ini の build_flags で -DNAME=値 を指定しても上書きできます。
// ============================================================================
#pragma once

#define FW_VERSION_MAJOR 1
#define FW_VERSION_MINOR 0

// ---------------------------------------------------------------------------
//  無線 (ESP-NOW)
// ---------------------------------------------------------------------------
// 親機と子機で同じ値にすること。近くの Wi-Fi と干渉する場合は 1 / 6 / 11 などに変更。
#ifndef WIFI_CHANNEL
#define WIFI_CHANNEL 1
#endif

// 同じ部屋で 2 セット以上使う場合はセットごとに別の値 (1〜255) にする。
#ifndef GROUP_ID
#define GROUP_ID 1
#endif

// ---------------------------------------------------------------------------
//  ゲーム動作
// ---------------------------------------------------------------------------
// 子機の最大台数 (番号は 1〜MAX_CHILDREN)
#ifndef MAX_CHILDREN
#define MAX_CHILDREN 64
#endif

// 最初の押下が届いてから、他の押下を待つ時間 (ms)。
// この間に届いた押下の中から「押した時刻」が最も早い子機を選ぶ。
#ifndef ARBITRATION_WINDOW_MS
#define ARBITRATION_WINDOW_MS 50
#endif

// 判定ランプ (正解=緑 / 不正解=赤) を点灯しておく時間 (ms)。
// 0 にすると次に誰かがボタンを押すまで点灯し続ける。
#ifndef JUDGE_LAMP_MS
#define JUDGE_LAMP_MS 3000
#endif

// 子機の回答ランプの色 (0xRRGGBB)
#ifndef WINNER_COLOR
#define WINNER_COLOR 0xFF7800
#endif

// ランプ全体の明るさ (0〜255)。USB 給電なら 160 程度まで。
#ifndef LAMP_BRIGHTNESS
#define LAMP_BRIGHTNESS 160
#endif

// ボタン内蔵 LED の明るさ (0〜255)。下げると電池が長持ちする
//   子機: 今押せるときに点灯 / 親機: 判定待ち (回答者が決まった) のときに点灯
#ifndef BUTTON_LED_LEVEL
#define BUTTON_LED_LEVEL 255
#endif

// DFPlayer の音量 (0〜30)
#ifndef AUDIO_VOLUME
#define AUDIO_VOLUME 24
#endif

// 親機のディスプレイ (TM1637 4桁7セグ) を使うか (1 = 使う)
#ifndef USE_DISPLAY
#define USE_DISPLAY 1
#endif

#ifndef DISPLAY_BRIGHTNESS
#define DISPLAY_BRIGHTNESS 5  // 0〜7
#endif

// ---------------------------------------------------------------------------
//  バッテリー (18650 + TP4056 充電モジュール + 昇圧モジュール)
// ---------------------------------------------------------------------------
// 電池の電圧を測って残量を表示する。USB 給電だけで作る場合は 0 にする。
#ifndef USE_BATTERY
#define USE_BATTERY 1
#endif

// 電池の電圧を ADC で測るための分圧比 (100kΩ + 100kΩ なら 2.0)
#ifndef BATTERY_DIVIDER
#define BATTERY_DIVIDER 2.0f
#endif

// これより低くなったら「電池残量わずか」として知らせる (mV)
#ifndef BATTERY_LOW_MV
#define BATTERY_LOW_MV 3450
#endif

// ---------------------------------------------------------------------------
//  ランプ (WS2812B) の LED 数
// ---------------------------------------------------------------------------
// 親機: 緑ランプ → 赤ランプ の順に 1 本のデータ線でつなぐ
#ifndef MASTER_LEDS_PER_LAMP
#define MASTER_LEDS_PER_LAMP 16
#endif

#ifndef CHILD_LAMP_LEDS
#define CHILD_LAMP_LEDS 16
#endif

// ---------------------------------------------------------------------------
//  ピン配置
// ---------------------------------------------------------------------------
#if defined(BOARD_C3_SUPERMINI)
// --- 子機: ESP32-C3 SuperMini ---
#ifndef PIN_BUTTON
#define PIN_BUTTON 3
#endif
#ifndef PIN_LAMP
#define PIN_LAMP 4
#endif
#ifndef PIN_BUTTON_LED
#define PIN_BUTTON_LED 5  // ボタン内蔵 LED (12V, トランジスタ経由)。使わないなら -1
#endif
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED 8
#endif
#ifndef PIN_BATTERY
#define PIN_BATTERY 1  // 電池電圧 (分圧) の入力
#endif
#ifndef STATUS_LED_ACTIVE_LOW
#define STATUS_LED_ACTIVE_LOW 1
#endif

#else
// --- ESP32 DevKitC (ESP32-WROOM-32) ---
// 親機
#ifndef PIN_BTN_CORRECT
#define PIN_BTN_CORRECT 32
#endif
#ifndef PIN_BTN_INCORRECT
#define PIN_BTN_INCORRECT 33
#endif
#ifndef PIN_DF_RX
#define PIN_DF_RX 16  // ESP32 の RX ← DFPlayer の TX
#endif
#ifndef PIN_DF_TX
#define PIN_DF_TX 17  // ESP32 の TX → 1kΩ → DFPlayer の RX
#endif
#ifndef PIN_TM_CLK
#define PIN_TM_CLK 18
#endif
#ifndef PIN_TM_DIO
#define PIN_TM_DIO 19
#endif
#ifndef PIN_BUZZER
#define PIN_BUZZER 25  // 任意: 圧電ブザー (DFPlayer が無くても音が出る)。使わないなら -1
#endif
#ifndef PIN_JUDGE_LED
#define PIN_JUDGE_LED 26  // 正解・不正解ボタンの内蔵 LED (12V, 2 個まとめてトランジスタ経由)。使わないなら -1
#endif

// 子機
#ifndef PIN_BUTTON
#define PIN_BUTTON 32
#endif
#ifndef PIN_BUTTON_LED
#define PIN_BUTTON_LED 26  // ボタン内蔵 LED (12V, トランジスタ経由)。使わないなら -1
#endif

// 共通
#ifndef PIN_LAMP
#define PIN_LAMP 27
#endif
#ifndef PIN_BATTERY
#define PIN_BATTERY 35  // 電池電圧 (分圧) の入力。ADC1 のピンであること (無線使用中は ADC2 が使えない)
#endif
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED 2
#endif
#ifndef STATUS_LED_ACTIVE_LOW
#define STATUS_LED_ACTIVE_LOW 0
#endif
#endif

// ---------------------------------------------------------------------------
//  通信タイミング (通常は変更不要)
// ---------------------------------------------------------------------------
#define BEACON_INTERVAL_MS 100     // 親機が状態を送る間隔
#define STATE_BURST_COUNT 3        // 状態が変わったときの連続送信回数
#define STATE_BURST_GAP_MS 8       // 連続送信の間隔
#define MASTER_TIMEOUT_MS 1500     // これだけ親機から届かなければ「未接続」
#define HELLO_INTERVAL_MS 1000     // 子機の生存通知間隔
#define CHILD_TIMEOUT_MS 3500      // これだけ子機から届かなければ接続数から外す
#define PRESS_RETRIES 4            // 押下パケットの再送回数
#define PRESS_RETRY_MS 15          // 押下パケットの再送間隔
#define EARLY_TOLERANCE_MS 5       // 受付開始より前の押下として捨てるまでの許容誤差
#define DEBOUNCE_CONFIRM_US 4000   // 押されてからこの時間後にまだ押されていれば押下と判定
#define DEBOUNCE_GIVEUP_US 12000   // この時間までに押されている状態を確認できなければノイズとみなす
#define RELEASE_STABLE_MS 30       // 離したと判定するまでの時間
#define BUTTON_DEBOUNCE_MS 25      // 親機ボタンのチャタリング除去
#define REGISTER_HOLD_MS 1500      // 起動時に正解ボタンをこの時間押していたら番号登録モード
