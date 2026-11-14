#include "radio.h"

#include <WiFi.h>
#include <esp_arduino_version.h>
#include <esp_now.h>
#include <esp_timer.h>
#include <esp_wifi.h>

namespace radio {
namespace {

QueueHandle_t g_queue = nullptr;
const uint8_t kBroadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

// Wi-Fi タスクから呼ばれるので、時刻だけ取ってすぐキューに積む
void enqueue(const uint8_t* mac, const uint8_t* data, int len) {
  const int64_t now = esp_timer_get_time();
  if (g_queue == nullptr || len <= 0 || len > static_cast<int>(sizeof(RxPacket::data))) return;
  RxPacket p;
  memcpy(p.mac, mac, 6);
  p.rxUs = now;
  p.len = static_cast<uint8_t>(len);
  memcpy(p.data, data, len);
  xQueueSend(g_queue, &p, 0);
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onReceive(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  enqueue(info->src_addr, data, len);
}
#else
void onReceive(const uint8_t* mac, const uint8_t* data, int len) { enqueue(mac, data, len); }
#endif

bool ensurePeer(const uint8_t mac[6]) {
  if (esp_now_is_peer_exist(mac)) return true;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, mac, 6);
  peer.channel = 0;  // 0 = 現在のチャンネル
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  return esp_now_add_peer(&peer) == ESP_OK;
}

}  // namespace

bool begin(uint8_t channel, size_t queueDepth) {
  g_queue = xQueueCreate(queueDepth, sizeof(RxPacket));
  if (g_queue == nullptr) return false;

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_ps(WIFI_PS_NONE);  // 省電力を切って遅延を減らす
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  if (esp_now_init() != ESP_OK) return false;
  esp_now_register_recv_cb(onReceive);
  return ensurePeer(kBroadcast);
}

bool receive(RxPacket* out) {
  if (g_queue == nullptr) return false;
  return xQueueReceive(g_queue, out, 0) == pdTRUE;
}

bool sendBroadcast(const void* data, size_t len) {
  return esp_now_send(kBroadcast, static_cast<const uint8_t*>(data), len) == ESP_OK;
}

bool sendTo(const uint8_t mac[6], const void* data, size_t len) {
  if (!ensurePeer(mac)) return false;
  return esp_now_send(mac, static_cast<const uint8_t*>(data), len) == ESP_OK;
}

void ownMac(uint8_t out[6]) { WiFi.macAddress(out); }

String macToString(const uint8_t mac[6]) {
  char buf[18];
  snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3],
           mac[4], mac[5]);
  return String(buf);
}

}  // namespace radio
