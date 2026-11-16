// ============================================================================
//  早押しボタン 設定ファイル
//  ピン番号や動作パラメータはここで変更できます。
//  #ifndef で囲まれた値は、platformio.ini の build_flags で -DNAME=値 を指定しても上書きできます
//  (末尾の「通信タイミング」とバージョン番号は config.h を直接書き換えてください)。
// ============================================================================
#pragma once

#define FW_VERSION_MAJOR 1
#define FW_VERSION_MINOR 1

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

// 親機の判定ランプ (正解=赤 / 不正解=青) を点灯しておく時間 (ms)。
// 0 にすると次に誰かがボタンを押すまで点灯し続ける。
#ifndef JUDGE_LAMP_MS
#define JUDGE_LAMP_MS 5000
#endif

// 判定の色 (0xRRGGBB)。親機のランプと、判定された子機の点滅に使う。ボタンの色 (正解=赤 / 不正解=青) に合わせている
#ifndef CORRECT_COLOR
#define CORRECT_COLOR 0xFF0000
#endif
#ifndef INCORRECT_COLOR
#define INCORRECT_COLOR 0x0050FF
#endif

// 子機の回答ランプの色 (0xRRGGBB)
#ifndef WINNER_COLOR
#define WINNER_COLOR 0xFF7800
#endif

// ランプ全体の明るさ (0〜255)。7 連基板なら最大 (255) でも 5V で 0.4A 程度
#ifndef LAMP_BRIGHTNESS
#define LAMP_BRIGHTNESS 255
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
// 電池の電圧を ADC で測るための分圧比 (100kΩ + 100kΩ なら 2.0)
#ifndef BATTERY_DIVIDER
#define BATTERY_DIVIDER 2.0f
#endif

// これより低くなったら「電池残量わずか」として知らせる (mV)
#ifndef BATTERY_LOW_MV
#define BATTERY_LOW_MV 3450
#endif

// これを 10 秒続けて下回ったら、電池を守るために LED と無線を止めて休止する (mV)。
// 電源ボタンを入れ直すと復帰する (充電してから)
#ifndef BATTERY_CUTOFF_MV
#define BATTERY_CUTOFF_MV 3200
#endif

// 無線の送信出力。通信が不安定なときに下げて試せる:
// platformio.ini の build_flags に -DWIFI_TX_POWER=WIFI_POWER_8_5dBm などを足す
// (未定義なら最大出力のまま)

// ---------------------------------------------------------------------------
//  ランプ (WS2812B) の LED 数
// ---------------------------------------------------------------------------
// 親機: 中央のランプ 1 個
#ifndef MASTER_LAMP_LEDS
#define MASTER_LAMP_LEDS 7
#endif

#ifndef CHILD_LAMP_LEDS
#define CHILD_LAMP_LEDS 7
#endif

// ---------------------------------------------------------------------------
//  ピン配置
// ---------------------------------------------------------------------------
#if defined(BOARD_XIAO_ESP32C6)
// --- 子機・PC 連携の受信機: Seeed Studio XIAO ESP32C6 ---
// 番号は GPIO 番号。かっこの中は基板のピンの名前 (D0〜D3 は USB を上にして左の列の上から 4 本)
#ifndef PIN_BATTERY
#define PIN_BATTERY 0  // (D0) 電池電圧 (分圧) の入力。アナログ入力ができるのは D0〜D2 だけ
#endif
#ifndef PIN_BUTTON
#define PIN_BUTTON 1  // (D1)
#endif
#ifndef PIN_LAMP
#define PIN_LAMP 2  // (D2)
#endif
#ifndef PIN_BUTTON_LED
#define PIN_BUTTON_LED 21  // (D3) ボタン内蔵 LED (12V, トランジスタ経由)。使わないなら -1
#endif
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED 15  // 基板上の LED (USB 端子の横)
#endif
#ifndef STATUS_LED_ACTIVE_LOW
#define STATUS_LED_ACTIVE_LOW 1  // 点灯と消灯が逆になる場合は 0 にする
#endif
// GPIO3 と GPIO14 は基板の中でアンテナの切り替えに使われている (起動時に基板上のアンテナが選ばれる)。
// GPIO16 (D6) は起動時にメッセージが出るので、LED などの出力には使わないこと

#else
// --- 親機: ESP32-DevKitC-32E (ESP32-WROOM-32E) ---
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
#ifndef PIN_JUDGE_LED
#define PIN_JUDGE_LED 26  // 正解・不正解ボタンの内蔵 LED (12V, 2 個まとめてトランジスタ経由)。使わないなら -1
#endif
#ifndef PIN_LAMP
#define PIN_LAMP 27
#endif
#ifndef PIN_BATTERY
#define PIN_BATTERY 35  // 電池電圧 (分圧) の入力。ADC1 のピンであること (無線使用中は ADC2 が使えない)
#endif
#ifndef PIN_STATUS_LED
#define PIN_STATUS_LED 2  // 純正の ESP32-DevKitC-32E には LED が付いていない (LED を足す場合の出力)
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
#define INFO_INTERVAL_MS 1000      // 親機が PC 連携用の追加情報を送る間隔
#define PRESS_RETRIES 4            // 押下パケットの再送回数
#define PRESS_RETRY_MS 15          // 押下パケットの再送間隔
#define EARLY_TOLERANCE_MS 5       // 受付開始より前の押下として捨てるまでの許容誤差
#define DEBOUNCE_CONFIRM_US 4000   // 押されてからこの時間後にまだ押されていれば押下と判定
#define DEBOUNCE_GIVEUP_US 12000   // この時間までに押されている状態を確認できなければノイズとみなす
#define RELEASE_STABLE_MS 30       // 離したと判定するまでの時間
#define BUTTON_DEBOUNCE_MS 25      // 親機ボタンのチャタリング除去
#define REGISTER_HOLD_MS 1500      // 起動時に正解ボタンをこの時間押していたら番号登録モード
