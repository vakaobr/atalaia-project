/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Firmware updates on the ESP32-S3 (fw_update_esp.h): the operations fw_update_run
 * needs, over ESP-IDF's Wi-Fi station, esp_http_client and esp_ota_*.
 *
 * HTTPS trusts exactly one certificate authority: the field CA whose SHA-256 the
 * signed join payload carries (key 13). The controller sends it after its own
 * certificate (controller/atalaia_controller/tls.py); the verify callback clears
 * "not trusted" on that certificate alone, so the chain must end at it, the
 * controller's certificate must be signed by it and carry the host name of the
 * address (key 14), as mbedTLS checks. The same pattern as ESP-IDF's own
 * certificate bundle (a placeholder CA list and a verify callback).
 */
#include "fw_update_esp.h"

#include <stdio.h>
#include <string.h>

#include "box_text.h"
#include "config_store.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "fw_update.h"
#include "mbedtls/md.h"
#include "mbedtls/pk.h"
#include "mbedtls/sha256.h"
#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"
#include "sdkconfig.h"

static const char *TAG = "fw_update";

#define WIFI_GOT_IP  BIT0
#define WIFI_FAILED  BIT1
#define WIFI_RETRIES 5

static box_game_t *s_box;
static void (*s_screen)(const char *tmpl, const char *data_json);
static int (*s_battery)(void);
static volatile bool s_busy;
/* A failure the controller did not take over HTTPS: the update task sets it, the game task
 * sends it over LoRa (fw_update_esp_poll) and clears it. */
static volatile bool s_failed_due;
static fw_result_t s_failed;
static fw_job_t s_job;
static atalaia_join_t s_join; /* a copy: the game task keeps its own */
static uint8_t s_keys[FW_KEYS_MAX][32];
static int s_key_count = -1;

/* ---- release keys -------------------------------------------------------------------- */

static size_t release_keys(void)
{
    if (s_key_count < 0) {
        s_key_count = fw_keys_parse(CONFIG_ATALAIA_OTA_RELEASE_KEYS, s_keys, FW_KEYS_MAX);
        if (s_key_count < 0) {
            ESP_LOGE(TAG, "CONFIG_ATALAIA_OTA_RELEASE_KEYS is malformed: no update is accepted");
            s_key_count = 0;
        }
    }
    return (size_t)s_key_count;
}

/* ---- the field CA ------------------------------------------------------------------- */

static uint8_t s_pin[32];
static mbedtls_x509_crt s_placeholder_ca; /* never matches: the callback decides */

static bool is_field_ca(const mbedtls_x509_crt *crt)
{
    uint8_t h[32];
    return mbedtls_sha256(crt->raw.p, crt->raw.len, h, 0) == 0 && memcmp(h, s_pin, 32) == 0;
}

/* Whether ca (a certificate the server sent) issued and signed child. */
static bool signed_by(const mbedtls_x509_crt *child, mbedtls_x509_crt *ca)
{
    if (!ca->MBEDTLS_PRIVATE(ca_istrue)) {
        ESP_LOGW(TAG, "the field CA is not marked as a CA");
        return false;
    }
    if (child->issuer_raw.len != ca->subject_raw.len ||
        memcmp(child->issuer_raw.p, ca->subject_raw.p, ca->subject_raw.len) != 0) {
        ESP_LOGW(TAG, "the certificate's issuer is not the field CA's name");
        return false;
    }
    if (!mbedtls_pk_can_do(&ca->pk, child->MBEDTLS_PRIVATE(sig_pk))) {
        ESP_LOGW(TAG, "the field CA's key cannot check this signature type");
        return false;
    }
    const mbedtls_md_info_t *md = mbedtls_md_info_from_type(child->MBEDTLS_PRIVATE(sig_md));
    unsigned char hash[MBEDTLS_MD_MAX_SIZE];
    int ret = md == NULL ? -1 : mbedtls_md(md, child->tbs.p, child->tbs.len, hash);
    if (ret != 0) {
        ESP_LOGW(TAG, "hashing the certificate failed (-0x%04x)", (unsigned)-ret);
        return false;
    }
    ret = mbedtls_pk_verify_ext(child->MBEDTLS_PRIVATE(sig_pk), child->MBEDTLS_PRIVATE(sig_opts),
                                &ca->pk, child->MBEDTLS_PRIVATE(sig_md), hash,
                                mbedtls_md_get_size(md), child->MBEDTLS_PRIVATE(sig).p,
                                child->MBEDTLS_PRIVATE(sig).len);
    if (ret != 0)
        ESP_LOGW(TAG, "the field CA's signature does not verify (-0x%04x)", (unsigned)-ret);
    return ret == 0;
}

/* As ESP-IDF's certificate bundle does: mbedTLS marks "not trusted" on the
 * certificate it could not chain to a trusted CA (on the bench, the
 * controller's own certificate, though the server sent the field CA after
 * it). Clear it only where the field CA of the join, found among the
 * certificates the server sent, is that certificate itself or issued and
 * signed it; every other flag stays. */
static int pin_verify(void *ctx, mbedtls_x509_crt *crt, int depth, uint32_t *flags)
{
    (void)ctx;
    if (*flags & MBEDTLS_X509_BADCERT_NOT_TRUSTED) {
        bool anchored = is_field_ca(crt);
        for (mbedtls_x509_crt *ca = crt->next; !anchored && ca != NULL; ca = ca->next) {
            anchored = is_field_ca(ca) && signed_by(crt, ca);
        }
        if (anchored) {
            *flags &= ~(uint32_t)MBEDTLS_X509_BADCERT_NOT_TRUSTED;
        } else {
            ESP_LOGW(TAG, "certificate at depth %d: not the field CA of the join, nor signed by it",
                     depth);
        }
    }
    if (depth == 0 && *flags != 0) {
        /* Say why a handshake is refused (name, usage, signature...). */
        char why[160];
        mbedtls_x509_crt_verify_info(why, sizeof(why), "", *flags);
        ESP_LOGW(TAG, "the controller's certificate: %s", why);
    }
    return 0;
}

static esp_err_t pin_attach(void *conf)
{
    mbedtls_ssl_config *c = (mbedtls_ssl_config *)conf;
    mbedtls_ssl_conf_authmode(c, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(c, &s_placeholder_ca, NULL);
    mbedtls_ssl_conf_verify(c, pin_verify, NULL);
    return ESP_OK;
}

/* ---- Wi-Fi ---------------------------------------------------------------------------- */

static EventGroupHandle_t s_wifi_events;
static esp_netif_t *s_sta;
static esp_event_handler_instance_t s_on_wifi, s_on_ip;
static int s_retries;
static bool s_wifi_on;

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (++s_retries <= WIFI_RETRIES) {
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(s_wifi_events, WIFI_FAILED);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_events, WIFI_GOT_IP);
    }
}

static void net_down(void *ctx)
{
    (void)ctx;
    if (!s_wifi_on) return;
    s_retries = WIFI_RETRIES + 1; /* the disconnection below is not a reason to reconnect */
    esp_wifi_disconnect();
    esp_wifi_stop();
    esp_event_handler_instance_unregister(WIFI_EVENT, ESP_EVENT_ANY_ID, s_on_wifi);
    esp_event_handler_instance_unregister(IP_EVENT, IP_EVENT_STA_GOT_IP, s_on_ip);
    esp_wifi_deinit();
    s_wifi_on = false;
}

static bool net_up(void *ctx)
{
    (void)ctx;
    char ssid[33] = "", pass[65] = "";
    if (!config_store_get_str("wifi_ssid", ssid, sizeof(ssid)) || ssid[0] == '\0') {
        ESP_LOGW(TAG, "no field Wi-Fi set (the setup portal, or \"@wifi <ssid> <password>\")");
        return false;
    }
    config_store_get_str("wifi_pass", pass, sizeof(pass));
    if (s_wifi_events == NULL) s_wifi_events = xEventGroupCreate();
    if (s_sta == NULL) s_sta = esp_netif_create_default_wifi_sta();
    xEventGroupClearBits(s_wifi_events, WIFI_GOT_IP | WIFI_FAILED);
    s_retries = 0;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    /* The Wi-Fi driver's RX buffers need DMA-capable internal RAM: log the
     * headroom before it starts, the figure that decides whether it can. */
    ESP_LOGI(TAG, "Wi-Fi starting: DMA-capable RAM %u bytes free (largest %u), internal %u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    esp_err_t err = esp_wifi_init(&init);
    if (err != ESP_OK) {
        /* Reported as no_wifi; say here that the driver itself did not start. */
        ESP_LOGE(TAG, "Wi-Fi driver did not start: %s", esp_err_to_name(err));
        return false;
    }
    s_wifi_on = true;
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL, &s_on_wifi);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL, &s_on_ip);
    wifi_config_t wc;
    memset(&wc, 0, sizeof(wc));
    memcpy(wc.sta.ssid, ssid, strlen(ssid));
    memcpy(wc.sta.password, pass, strlen(pass));
    wc.sta.threshold.authmode = pass[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    if (esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK ||
        esp_wifi_set_config(WIFI_IF_STA, &wc) != ESP_OK || esp_wifi_start() != ESP_OK) {
        return false;
    }
    esp_wifi_set_ps(WIFI_PS_NONE); /* full speed for the few seconds of the download */
    EventBits_t bits =
        xEventGroupWaitBits(s_wifi_events, WIFI_GOT_IP | WIFI_FAILED, pdFALSE, pdFALSE,
                            pdMS_TO_TICKS(CONFIG_ATALAIA_OTA_WIFI_TIMEOUT_S * 1000));
    if (!(bits & WIFI_GOT_IP)) {
        ESP_LOGW(TAG, "the field Wi-Fi \"%s\" did not connect", ssid);
        return false;
    }
    return true;
}

/* ---- HTTPS ---------------------------------------------------------------------------- */

static esp_http_client_handle_t s_http;

static esp_http_client_handle_t http_open(const char *base, const char *path)
{
    char url[ATALAIA_JOIN_URL_MAX + 64];
    snprintf(url, sizeof(url), "%s%s", base, path);
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = 15000,
        .buffer_size = 2048,
        .crt_bundle_attach = pin_attach,
        .disable_auto_redirect = true, /* the pinned controller answers itself */
    };
    esp_http_client_handle_t h = esp_http_client_init(&cfg);
    if (h == NULL) return NULL;
    if (esp_http_client_open(h, 0) != ESP_OK) {
        esp_http_client_cleanup(h);
        return NULL;
    }
    return h;
}

static bool http_answer(esp_http_client_handle_t h, int64_t *length)
{
    int64_t n = esp_http_client_fetch_headers(h);
    if (n < 0 || esp_http_client_get_status_code(h) != 200) return false;
    *length = esp_http_client_is_chunked_response(h) ? -1 : n;
    return true;
}

static int get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    int64_t length = -1;
    esp_http_client_handle_t h = http_open(base, path);
    if (h == NULL) return -1;
    int got = -1;
    int64_t headers = esp_http_client_fetch_headers(h);
    if (headers >= 0 && esp_http_client_get_status_code(h) != 200) {
        got = -2; /* the controller answered: not this (404, 409) */
    } else if (headers >= 0) {
        length = esp_http_client_is_chunked_response(h) ? -1 : headers;
        if (length <= 0 || (size_t)length >= cap) got = -3; /* longer than such a text may be */
    }
    if (got == -1 && headers >= 0 && length > 0) {
        got = 0;
        while (got < (int)length) {
            int n = esp_http_client_read(h, buf + got, (int)length - got);
            if (n <= 0) break;
            got += n;
        }
        if (got != (int)length) got = -1;
    }
    if (got >= 0) buf[got] = '\0';
    esp_http_client_close(h);
    esp_http_client_cleanup(h);
    return got;
}

static bool open_stream(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    s_http = http_open(base, path);
    if (s_http == NULL) return false;
    if (!http_answer(s_http, length)) {
        /* An answer other than 200 (the controller does not offer it): *length -2. */
        *length = esp_http_client_get_status_code(s_http) > 0 ? -2 : -1;
        esp_http_client_close(s_http);
        esp_http_client_cleanup(s_http);
        s_http = NULL;
        return false;
    }
    return true;
}

static int read_stream(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    if (s_http == NULL) return -1;
    int n = esp_http_client_read(s_http, (char *)buf, (int)cap);
    if (n == 0 && !esp_http_client_is_complete_data_received(s_http)) return -1;
    return n;
}

static void close_stream(void *ctx)
{
    (void)ctx;
    if (s_http == NULL) return;
    esp_http_client_close(s_http);
    esp_http_client_cleanup(s_http);
    s_http = NULL;
}

static bool post(void *ctx, const char *base, const char *path, const char *body,
                 const char *mac_hex)
{
    (void)ctx;
    char url[ATALAIA_JOIN_URL_MAX + 64];
    snprintf(url, sizeof(url), "%s%s", base, path);
    esp_http_client_config_t cfg = {
        .url = url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 10000,
        .crt_bundle_attach = pin_attach,
        .disable_auto_redirect = true,
    };
    esp_http_client_handle_t h = esp_http_client_init(&cfg);
    if (h == NULL) return false;
    esp_http_client_set_header(h, "Content-Type", "text/plain");
    esp_http_client_set_header(h, "X-Atalaia-Mac", mac_hex);
    esp_http_client_set_post_field(h, body, (int)strlen(body));
    bool ok = esp_http_client_perform(h) == ESP_OK && esp_http_client_get_status_code(h) == 200;
    if (!ok) ESP_LOGW(TAG, "the report did not reach the controller: over LoRa instead");
    esp_http_client_cleanup(h);
    return ok;
}

/* ---- the OTA slot ----------------------------------------------------------------------- */

static const esp_partition_t *s_slot;
static esp_ota_handle_t s_ota;

static int slot_begin(void *ctx, uint32_t size)
{
    (void)ctx;
    s_slot = esp_ota_get_next_update_partition(NULL);
    if (s_slot == NULL || size > s_slot->size) return -1;
    return esp_ota_begin(s_slot, size, &s_ota) == ESP_OK ? 0 : -1;
}

static int slot_write(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    return esp_ota_write(s_ota, data, len) == ESP_OK ? 0 : -1;
}

static int slot_end(void *ctx)
{
    (void)ctx;
    esp_err_t err = esp_ota_end(s_ota);
    if (err != ESP_OK) ESP_LOGE(TAG, "the image is not valid: %s", esp_err_to_name(err));
    return err == ESP_OK ? 0 : -1;
}

static int slot_activate(void *ctx)
{
    (void)ctx;
    return esp_ota_set_boot_partition(s_slot) == ESP_OK ? 0 : -1;
}

static void slot_abort(void *ctx)
{
    (void)ctx;
    esp_ota_abort(s_ota);
}

/* ---- the task ----------------------------------------------------------------------------- */

static bool cancelled(void *ctx)
{
    (void)ctx;
    return s_box != NULL && box_game_playing(s_box);
}

static void show(const char *title, const char *text)
{
    char data[96];
    snprintf(data, sizeof(data), "{\"title\":\"%s\",\"mode\":\"%.40s\"}", title, text);
    if (s_screen != NULL) s_screen("status", data);
}

static void progress(void *ctx, uint32_t done, uint32_t total)
{
    (void)ctx;
    static unsigned last = 101;
    unsigned pct = total ? (unsigned)((uint64_t)done * 100u / total) : 0;
    if (pct / 10 == last / 10 && last != 101) return;
    last = pct;
    char text[48];
    snprintf(text, sizeof(text), "%s %u%%", s_job.version, pct);
    show(box_text(TX_UPDATING), text);
}

static const fw_io_t IO = {
    .net_up = net_up,
    .net_down = net_down,
    .get_text = get_text,
    .open = open_stream,
    .read = read_stream,
    .close = close_stream,
    .post = post,
    .cancelled = cancelled,
    .progress = progress,
    .flash = {slot_begin, slot_write, slot_end, slot_activate, slot_abort},
    .ctx = NULL,
};

static void update_task(void *arg)
{
    (void)arg;
    ESP_LOGW(TAG, "update to %s (release %s) started", s_job.version, s_job.id);
    show(box_text(TX_UPDATING), s_job.version);
    fw_result_t r = fw_update_run(&s_job, &IO);
    memset(s_join.game_key, 0, sizeof(s_join.game_key));
    if (r == FW_INSTALLED) {
        ESP_LOGW(TAG, "%s installed (%lu bytes): rebooting into it", s_job.version,
                 (unsigned long)s_job.written);
        show(box_text(TX_RESTARTING), s_job.version);
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
    }
    ESP_LOGW(TAG, "update to %s failed: %s; the running image is unchanged", s_job.version,
             fw_result_name(r));
    show(box_text(TX_UPDATE_FAILED), fw_result_name(r));
    if (!s_job.reported && s_job.join != NULL) {
        /* The game task tells the controller over LoRa (fw_update_esp_poll). */
        s_failed = r;
        __atomic_store_n(&s_failed_due, true, __ATOMIC_RELEASE);
    }
    __atomic_store_n(&s_busy, false, __ATOMIC_RELEASE);
    vTaskDelete(NULL);
}

const fw_io_t *fw_update_esp_net(const uint8_t ca_sha256[32])
{
    memcpy(s_pin, ca_sha256, sizeof(s_pin));
    return &IO;
}

bool fw_update_esp_net_claim(void)
{
    bool idle = false;
    return __atomic_compare_exchange_n(&s_busy, &idle, true, false, __ATOMIC_ACQ_REL,
                                       __ATOMIC_ACQUIRE);
}

void fw_update_esp_net_release(void)
{
    __atomic_store_n(&s_busy, false, __ATOMIC_RELEASE);
}

void fw_update_esp_poll(void)
{
    if (s_box == NULL || !__atomic_load_n(&s_failed_due, __ATOMIC_ACQUIRE)) return;
    box_game_update_failed(s_box, s_job.id, fw_result_name(s_failed), s_job.running_version);
    __atomic_store_n(&s_failed_due, false, __ATOMIC_RELEASE);
}

void fw_update_esp_init(box_game_t *box, void (*screen)(const char *tmpl, const char *data_json),
                        int (*battery_pct)(void))
{
    s_box = box;
    s_screen = screen;
    s_battery = battery_pct;
    size_t keys = release_keys();
    if (keys == 0) {
        ESP_LOGW(TAG, "no release key built in (CONFIG_ATALAIA_OTA_RELEASE_KEYS): firmware "
                      "updates are refused");
    } else {
        ESP_LOGI(TAG, "%u release key(s); version %s, variant %s, board %s", (unsigned)keys,
                 esp_app_get_description()->version, atalaia_fw_desc.variant,
                 atalaia_fw_desc.board);
    }
}

void fw_update_esp_offer(const char *params_json)
{
    if (s_box == NULL) return;
    if (s_busy) {
        ESP_LOGW(TAG, "an update is already running");
        return;
    }
    fw_update_esp_poll(); /* the last failure goes out before s_job is reused */
    const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
    memset(&s_job, 0, sizeof(s_job));
    s_join = s_box->join;
    s_job.platform = CONFIG_IDF_TARGET;
    s_job.running_version = esp_app_get_description()->version;
    s_job.desc = &atalaia_fw_desc;
    s_job.keys = (const uint8_t(*)[32])s_keys;
    s_job.key_count = release_keys();
    s_job.slot_size = next != NULL ? (uint32_t)next->size : 0;
    s_job.playing = box_game_playing(s_box);
    s_job.battery_pct = s_battery != NULL ? s_battery() : -1;
    s_job.min_battery_pct = CONFIG_ATALAIA_OTA_MIN_BATTERY_PCT;
    s_job.join = box_game_active(s_box) ? &s_join : NULL;
    fw_result_t r =
        fw_offer_parse(params_json, s_job.id, s_job.version) ? FW_INSTALLED : FW_BAD_OFFER;
    if (r == FW_INSTALLED) r = fw_update_precheck(&s_job);
    if (r != FW_INSTALLED) {
        ESP_LOGW(TAG, "update refused: %s", fw_result_name(r));
        show(box_text(TX_UPDATE_REFUSED), fw_result_name(r));
        memset(s_join.game_key, 0, sizeof(s_join.game_key));
        /* Refused before any network: the controller hears why over LoRa (in a joined game). */
        if (s_job.join != NULL)
            box_game_update_failed(s_box, s_job.id, fw_result_name(r), s_job.running_version);
        return;
    }
    memcpy(s_pin, s_join.ca_sha256, sizeof(s_pin));
    s_busy = true;
    /* Core 0, below the game task: the game and the radio keep running meanwhile. */
    if (xTaskCreatePinnedToCore(update_task, "fw_update", 8192, NULL, 2, NULL, 0) != pdPASS) {
        ESP_LOGE(TAG, "no memory for the update task");
        s_busy = false;
    }
}

bool fw_update_esp_set_wifi(const char *ssid, const char *password)
{
    size_t ns = strlen(ssid), np = strlen(password);
    if (ns < 1 || ns > 32 || np > 64 || (np > 0 && np < 8)) return false;
    config_store_set_str("wifi_ssid", ssid);
    config_store_set_str("wifi_pass", password);
    return true;
}

void fw_update_esp_boot(bool radio_ok, bool storage_ok)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (running == NULL || esp_ota_get_state_partition(running, &state) != ESP_OK ||
        state != ESP_OTA_IMG_PENDING_VERIFY) {
        return;
    }
    size_t keys = release_keys();
    bool core_ok = fw_update_self_test((const uint8_t(*)[32])s_keys, keys);
    if (radio_ok && storage_ok && core_ok) {
        esp_ota_mark_app_valid_cancel_rollback();
        ESP_LOGW(TAG, "firmware %s confirmed after its self-test",
                 esp_app_get_description()->version);
        return;
    }
    ESP_LOGE(TAG,
             "the new firmware failed its self-test (radio %s, storage %s, core %s): "
             "rolling back",
             radio_ok ? "ok" : "FAILED", storage_ok ? "ok" : "FAILED", core_ok ? "ok" : "FAILED");
    esp_ota_mark_app_invalid_rollback_and_reboot();
}
