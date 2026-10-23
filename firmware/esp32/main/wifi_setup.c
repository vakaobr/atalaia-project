/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Captive-portal implementation. The ESP32 path uses SoftAP + DNS + HTTP.
 * The stub path is a no-op for testing.
 *
 * parse_form_field is platform-independent so it can be tested on Linux.
 */
#include "wifi_setup.h"

#include <stdbool.h>
#include <string.h>

#include "admin_pin.h"

/* ------------------------------------------------------------------ */
/* URL-encoded form parsing (platform-independent)                     */
/* ------------------------------------------------------------------ */

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
    if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
    return -1;
}

bool parse_form_field(const char *body, const char *key, char *out, int out_sz)
{
    if (!body || !key || !out || out_sz <= 0) return false;
    out[0] = '\0';

    size_t key_len = strlen(key);
    if (key_len == 0) return false;

    const char *p = body;
    while (p) {
        /* p points to the start of a key=value pair. */
        if (strncmp(p, key, key_len) == 0 && p[key_len] == '=') {
            p += key_len + 1; /* skip past "key=" */
            int i = 0;
            while (*p && *p != '&' && i < out_sz - 1) {
                if (*p == '%' && p[1] && p[2]) {
                    int hi = hex_digit(p[1]);
                    int lo = hex_digit(p[2]);
                    if (hi >= 0 && lo >= 0) {
                        out[i++] = (char)(hi * 16 + lo);
                        p += 3;
                        continue;
                    }
                }
                if (*p == '+') {
                    out[i++] = ' ';
                    p++;
                    continue;
                }
                out[i++] = *p++;
            }
            out[i] = '\0';
            return true;
        }
        /* Skip to the next '&' separator. */
        p = strchr(p, '&');
        if (p) p++; /* advance past '&' */
    }
    return false;
}

const char *wifi_setup_pin_problem(const char *pin)
{
    const char *why = admin_pin_weak(pin);
    if (why == NULL) return NULL;
    if (strcmp(why, "length") == 0 || strcmp(why, "digits") == 0) return "PIN must be 4-8 digits";
    /* No default admin PIN on a Field Box (decision AD-29): 1234 and the like are refused. */
    return "Choose another admin PIN: 1234, 0000, a sequence or a repeated pair is too easy to "
           "guess";
}

/* ------------------------------------------------------------------ */
/* ESP32: SoftAP + HTTP captive portal                                 */
/* ------------------------------------------------------------------ */

#ifdef ESP_PLATFORM

#include <stdio.h>

#include "config_store.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

static const char *TAG = "wifi_setup";
static httpd_handle_t server = NULL;
static char ap_ssid[32];
static bool (*join_key_handler)(const char *hex);

void wifi_setup_set_join_key_handler(bool (*handler)(const char *hex))
{
    join_key_handler = handler;
}

/* The HTML page is embedded via CMakeLists.txt EMBED_FILES. */
extern const uint8_t setup_html_start[] asm("_binary_wifi_setup_html_start");
extern const uint8_t setup_html_end[] asm("_binary_wifi_setup_html_end");

static esp_err_t root_get_handler(httpd_req_t *req)
{
    size_t len = (size_t)(setup_html_end - setup_html_start);
    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, (const char *)setup_html_start, (ssize_t)len);
    return ESP_OK;
}

/* Validation helpers. */

/* The setup page's region is the firmware's own (Kconfig ATALAIA_RADIO_REGION, RF-AS923-11):
 * the radio uses only its build's region, so the page may not offer another. Before regions it
 * listed US915, AU915 and others that the radio never used. */
#if defined(CONFIG_ATALAIA_RADIO_REGION_AS923_TW)
#define SETUP_REGION "AS923-TW"
#else
#define SETUP_REGION "EU868"
#endif

static bool is_valid_region(const char *r)
{
    return strcmp(r, SETUP_REGION) == 0;
}

static int parse_int_clamped(const char *s, int lo, int hi, int fallback)
{
    if (!s || !*s) return fallback;
    int v = 0;
    for (const char *p = s; *p >= '0' && *p <= '9'; p++) {
        v = v * 10 + (*p - '0');
    }
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return v;
}

static esp_err_t config_post_handler(httpd_req_t *req)
{
    /* With the field Wi-Fi's name and password URL-encoded, the form can pass 512 bytes. */
    static char buf[1024];
    if (req->content_len == 0 || req->content_len >= sizeof(buf)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Empty or too long");
        return ESP_FAIL;
    }
    int ret = 0;
    while (ret < (int)req->content_len) {
        int n = httpd_req_recv(req, buf + ret, req->content_len - (size_t)ret);
        if (n <= 0) {
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Empty body");
            return ESP_FAIL;
        }
        ret += n;
    }
    buf[ret] = '\0';

    /* Parse fields. */
    char name[33], region[10], pin[9], bri_s[4], vol_s[4];

    if (!parse_form_field(buf, "name", name, sizeof(name)) || name[0] == '\0') {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Name is required (1-32 chars)");
        return ESP_FAIL;
    }

    if (!parse_form_field(buf, "region", region, sizeof(region))) {
        snprintf(region, sizeof(region), "%s", SETUP_REGION);
    }
    if (!is_valid_region(region)) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                            "This box is built for the " SETUP_REGION " radio region only");
        return ESP_FAIL;
    }

    if (!parse_form_field(buf, "pin", pin, sizeof(pin))) pin[0] = '\0';
    const char *pin_problem = wifi_setup_pin_problem(pin);
    if (pin_problem != NULL) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, pin_problem);
        return ESP_FAIL;
    }

    uint32_t brightness = 80;
    if (parse_form_field(buf, "brightness", bri_s, sizeof(bri_s))) {
        brightness = (uint32_t)parse_int_clamped(bri_s, 0, 100, 80);
    }

    uint32_t volume = 80;
    if (parse_form_field(buf, "volume", vol_s, sizeof(vol_s))) {
        volume = (uint32_t)parse_int_clamped(vol_s, 0, 100, 80);
    }

    /* The field join key is optional here (it can also be set on the console). */
    char join_key[80];
    if (parse_form_field(buf, "joinkey", join_key, sizeof(join_key)) && join_key[0] != '\0') {
        if (join_key_handler == NULL || !join_key_handler(join_key)) {
            httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "The field join key is 64 hex digits");
            return ESP_FAIL;
        }
    }

    /* The field Wi-Fi a firmware update uses (protocol/firmware-update.md), optional. */
    char wifi_ssid[33], wifi_pass[65];
    bool have_wifi =
        parse_form_field(buf, "wifissid", wifi_ssid, sizeof(wifi_ssid)) && wifi_ssid[0] != '\0';
    if (!parse_form_field(buf, "wifipass", wifi_pass, sizeof(wifi_pass))) wifi_pass[0] = '\0';
    size_t np = strlen(wifi_pass);
    if (have_wifi && np > 0 && np < 8) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST,
                            "The field Wi-Fi password is 8-64 characters, or none");
        return ESP_FAIL;
    }

    /* Write to config store. */
    if (have_wifi) {
        config_store_set_str("wifi_ssid", wifi_ssid);
        config_store_set_str("wifi_pass", wifi_pass);
    }
    config_store_set_str("node_name", name);
    config_store_set_str("region", region);
    config_store_set_str("admin_pin", pin);
    config_store_set_u32("brightness", brightness);
    config_store_set_u32("volume", volume);
    config_store_set_configured(true);

    ESP_LOGI(TAG, "Config saved: name=%s region=%s", name, region);

    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr(req, "<html><body><h1>Saved. Rebooting...</h1></body></html>");

    /* Schedule reboot after the HTTP response flushes. */
    const esp_timer_create_args_t timer_args = {
        .callback = (esp_timer_cb_t)esp_restart,
        .name = "reboot",
    };
    esp_timer_handle_t reboot_timer;
    esp_timer_create(&timer_args, &reboot_timer);
    esp_timer_start_once(reboot_timer, 500000); /* 500 ms */

    return ESP_OK;
}

int wifi_setup_start(void)
{
    /* Get MAC for SSID suffix. */
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    char *ssid = ap_ssid;
    snprintf(ap_ssid, sizeof(ap_ssid), "atalaia-%02X%02X", mac[4], mac[5]);

    /* The Wi-Fi driver and the AP network interface must exist first. */
    esp_netif_create_default_wifi_ap();
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_err_t err = esp_wifi_init(&init_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi init failed: %s", esp_err_to_name(err));
        return -1;
    }

    /* Start SoftAP. */
    wifi_config_t wifi_cfg = {0};
    strncpy((char *)wifi_cfg.ap.ssid, ssid, sizeof(wifi_cfg.ap.ssid));
    wifi_cfg.ap.ssid_len = (uint8_t)strlen(ssid);
    wifi_cfg.ap.channel = 1;
    wifi_cfg.ap.max_connection = 1;
    wifi_cfg.ap.authmode = WIFI_AUTH_OPEN;

    esp_wifi_set_mode(WIFI_MODE_AP);
    esp_wifi_set_config(WIFI_IF_AP, &wifi_cfg);
    esp_wifi_start();

    ESP_LOGI(TAG, "SoftAP started: %s", ssid);

    /* Start HTTP server. */
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 4;

    if (httpd_start(&server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server");
        return -1;
    }

    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_get_handler};
    httpd_register_uri_handler(server, &root);

    /* Captive portal: respond to all GET requests with the config page. */
    httpd_uri_t captive = {.uri = "/generate_204", .method = HTTP_GET, .handler = root_get_handler};
    httpd_register_uri_handler(server, &captive);

    httpd_uri_t config_post = {
        .uri = "/config", .method = HTTP_POST, .handler = config_post_handler};
    httpd_register_uri_handler(server, &config_post);

    return 0;
}

const char *wifi_setup_ssid(void)
{
    return ap_ssid;
}

void wifi_setup_stop(void)
{
    if (server) {
        httpd_stop(server);
        server = NULL;
    }
    esp_wifi_stop();
}

#else /* stub build */

int wifi_setup_start(void)
{
    return 0;
}

const char *wifi_setup_ssid(void)
{
    return "";
}

void wifi_setup_stop(void)
{
}

void wifi_setup_set_join_key_handler(bool (*handler)(const char *hex))
{
    (void)handler;
}

#endif
