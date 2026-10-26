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

/* ------------------------------------------------------------------ */
/* The portal's languages (platform-independent)                       */
/* ------------------------------------------------------------------ */

/* European Portuguese addresses the player as "tu"; German as "du" (decisions BN-14, P5H-4,
 * P5K-2: the box's own wording). The German and Chinese are drafted by an AI model and wait
 * for a native-speaking player's review (docs/translations/status.yaml). */
static const char *const messages[WS_MSG_COUNT][BOX_LANG_COUNT] = {
    [WS_MSG_BAD_BODY] = {"The form is empty or too long",
                         "O formulário está vazio ou é demasiado longo",
                         "Das Formular ist leer oder zu lang", "表單是空的，或內容太長"},
    [WS_MSG_NAME] = {"Name is required (1-32 chars)", "O nome é obrigatório (1 a 32 caracteres)",
                     "Der Name ist nötig (1-32 Zeichen)", "請輸入名稱（1 到 32 個字元）"},
    [WS_MSG_REGION] = {"This box is built for the %s radio region only",
                       "Esta caixa foi feita só para a região de rádio %s",
                       "Diese Box ist nur für die Funkregion %s gebaut",
                       "這個盒子只支援 %s 無線電區域"},
    [WS_MSG_PIN_DIGITS] = {"PIN must be 4-8 digits", "O PIN tem de ter 4 a 8 algarismos",
                           "Die PIN muss 4-8 Ziffern haben", "PIN 碼必須是 4 到 8 位數字"},
    [WS_MSG_PIN_WEAK] =
        {"Choose another admin PIN: 1234, 0000, a sequence or a repeated pair is too easy to "
         "guess",
         "Escolhe outro PIN de administração: 1234, 0000, uma sequência ou um "
         "par repetido são fáceis de adivinhar",
         "Wähle eine andere Admin-PIN: 1234, 0000, eine Zahlenfolge oder ein wiederholtes "
         "Paar sind zu leicht zu erraten",
         "請換一組管理 PIN 碼：1234、0000、連號數字或重複的兩位數太容易被猜到"},
    [WS_MSG_JOIN_KEY] = {"The field join key is 64 hex digits",
                         "A chave de ligação ao campo tem 64 algarismos hexadecimais",
                         "Der Feld-Join-Schlüssel hat 64 Hex-Ziffern",
                         "場地加入金鑰是 64 位十六進位數字"},
    [WS_MSG_WIFI_PASS] = {"The field Wi-Fi password is 8-64 characters, or none",
                          "A palavra-passe do Wi-Fi do campo tem 8 a 64 caracteres, ou nenhuma",
                          "Das WLAN-Passwort des Felds hat 8-64 Zeichen, oder keins",
                          "場地 Wi-Fi 密碼需為 8 到 64 個字元，或不設密碼"},
    [WS_MSG_SAVED] = {"Saved. Rebooting...", "Guardado. A reiniciar...", "Gespeichert. Neustart...",
                      "已儲存，正在重新啟動..."},
};

const char *wifi_setup_msg(box_lang_t lang, wifi_setup_msg_t msg)
{
    if ((unsigned)msg >= (unsigned)WS_MSG_COUNT) return "";
    if ((unsigned)lang >= (unsigned)BOX_LANG_COUNT) lang = BOX_LANG_EN;
    return messages[msg][lang];
}

const char *wifi_setup_pin_problem_in(box_lang_t lang, const char *pin)
{
    const char *why = admin_pin_weak(pin);
    if (why == NULL) return NULL;
    if (strcmp(why, "length") == 0 || strcmp(why, "digits") == 0) {
        return wifi_setup_msg(lang, WS_MSG_PIN_DIGITS);
    }
    /* No default admin PIN on a Field Box (decision AD-29): 1234 and the like are refused. */
    return wifi_setup_msg(lang, WS_MSG_PIN_WEAK);
}

const char *wifi_setup_pin_problem(const char *pin)
{
    return wifi_setup_pin_problem_in(BOX_LANG_EN, pin);
}

/* A tag of Accept-Language ("pt-PT", "zh-TW", "en;q=0.8"): its language if the box has it
 * (English included), and its q value in thousandths; false for a language it has not. */
static bool accept_tag(const char *p, size_t n, box_lang_t *lang, int *q)
{
    char tag[16];
    size_t t = strcspn(p, ";");
    if (t > n) t = n;
    if (t == 0 || t >= sizeof(tag)) return false;
    for (size_t i = 0; i < t; i++) tag[i] = (char)((p[i] >= 'A' && p[i] <= 'Z') ? p[i] + 32 : p[i]);
    tag[t] = '\0';
    *q = 1000;
    const char *qp = memchr(p, ';', n);
    if (qp != NULL) {
        qp++;
        while (qp < p + n && *qp == ' ') qp++;
        if (qp + 2 <= p + n && qp[0] == 'q' && qp[1] == '=') {
            qp += 2;
            int whole = 0, frac = 0, digits = 0;
            bool number = qp < p + n && *qp >= '0' && *qp <= '9';
            if (number) whole = *qp++ - '0';
            if (qp < p + n && *qp == '.') {
                qp++;
                for (; qp < p + n && *qp >= '0' && *qp <= '9' && digits < 3; qp++, digits++) {
                    frac = frac * 10 + (*qp - '0');
                }
                for (; digits < 3; digits++) frac *= 10;
            }
            if (number) *q = whole * 1000 + frac; /* "q=x" is no q value: the default 1 */
        }
    }
    if (*q <= 0) return false;
    box_lang_t l = box_lang_from_code(tag);
    bool english = tag[0] == 'e' && tag[1] == 'n' && (tag[2] == '\0' || tag[2] == '-');
    if (l == BOX_LANG_EN && !english) return false;
    *lang = l;
    return true;
}

box_lang_t wifi_setup_pick_lang(const char *query_lang, const char *accept_language)
{
    if (query_lang != NULL && query_lang[0] != '\0') return box_lang_from_code(query_lang);
    if (box_lang_given()) return box_lang();
    box_lang_t best = BOX_LANG_EN;
    int best_q = 0;
    for (const char *p = accept_language; p != NULL && *p != '\0';) {
        while (*p == ' ' || *p == ',') p++;
        size_t n = strcspn(p, ",");
        box_lang_t l;
        int q;
        if (n > 0 && accept_tag(p, n, &l, &q) && q > best_q) {
            best = l;
            best_q = q;
        }
        p += n;
    }
    return best;
}

/* ------------------------------------------------------------------ */
/* The captive portal's DNS (platform-independent)                     */
/* ------------------------------------------------------------------ */

size_t wifi_setup_dns_reply(const uint8_t *q, size_t len, uint8_t *out, size_t cap,
                            const uint8_t ip[4])
{
    enum { HEADER = 12, TYPE_A = 1, TYPE_ANY = 255, CLASS_IN = 1 };
    if (q == NULL || out == NULL || ip == NULL || len < HEADER + 5 || len > 512) return 0;
    if ((q[2] & 0x80) != 0) return 0;        /* a response */
    if (((q[2] >> 3) & 0x0F) != 0) return 0; /* only the standard query */
    if (q[4] != 0 || q[5] != 1) return 0;    /* exactly one question */
    size_t i = HEADER;
    for (;;) { /* the name: labels, no compression in a question */
        if (i >= len) return 0;
        uint8_t l = q[i];
        if (l == 0) {
            i++;
            break;
        }
        if ((l & 0xC0) != 0 || i + 1 + l >= len) return 0;
        i += 1 + (size_t)l;
        if (i - HEADER > 255) return 0;
    }
    if (i + 4 > len) return 0;
    unsigned qtype = (unsigned)(q[i] << 8 | q[i + 1]);
    unsigned qclass = (unsigned)(q[i + 2] << 8 | q[i + 3]);
    size_t end = i + 4;
    bool answer = (qtype == TYPE_A || qtype == TYPE_ANY) && qclass == CLASS_IN;
    if (end + (answer ? 16 : 0) > cap) return 0;
    memcpy(out, q, end);
    out[2] = (uint8_t)(0x80 | 0x04 | (q[2] & 0x01)); /* response, authoritative, RD as asked */
    out[3] = 0x80;                                   /* recursion available, NOERROR */
    out[4] = 0, out[5] = 1;                          /* one question, */
    out[6] = 0, out[7] = answer ? 1 : 0;             /* its answer, */
    out[8] = out[9] = out[10] = out[11] = 0;         /* nothing else (EDNS is dropped) */
    if (!answer) return end;
    uint8_t *a = out + end;
    a[0] = 0xC0, a[1] = HEADER; /* the name, as the question's */
    a[2] = 0, a[3] = TYPE_A;
    a[4] = 0, a[5] = CLASS_IN;
    a[6] = a[7] = a[8] = 0, a[9] = 30; /* TTL */
    a[10] = 0, a[11] = 4;
    memcpy(a + 12, ip, 4);
    return end + 16;
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
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "dhcpserver/dhcpserver.h"
#include "lwip/sockets.h"
#include "nvs_flash.h"

static const char *TAG = "wifi_setup";
static httpd_handle_t server = NULL;
static char ap_ssid[32];
static bool (*join_key_handler)(const char *hex);
static esp_netif_t *ap_netif;
static char ap_ip_text[16] = "192.168.4.1"; /* the SoftAP's address (esp_netif's default) */
static uint8_t ap_ip[4] = {192, 168, 4, 1};
static int dns_sock = -1;
static volatile bool dns_run;

void wifi_setup_set_join_key_handler(bool (*handler)(const char *hex))
{
    join_key_handler = handler;
}

/* The HTML page is embedded via CMakeLists.txt EMBED_FILES. */
extern const uint8_t setup_html_start[] asm("_binary_wifi_setup_html_start");
extern const uint8_t setup_html_end[] asm("_binary_wifi_setup_html_end");

/* The page's language: "?lang=" (the links at its foot), the box's, the browser's. */
static box_lang_t request_lang(httpd_req_t *req)
{
    char query[24] = "", code[8] = "", accept[96] = "";
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        httpd_query_key_value(query, "lang", code, sizeof(code));
    }
    size_t n = httpd_req_get_hdr_value_len(req, "Accept-Language");
    if (n > 0 && n < sizeof(accept))
        httpd_req_get_hdr_value_str(req, "Accept-Language", accept, sizeof(accept));
    return wifi_setup_pick_lang(code, accept);
}

/* The embedded page, with its "@LANG@" replaced by the language code (the page's script puts
 * the texts in; without a script it stays English). */
static esp_err_t root_get_handler(httpd_req_t *req)
{
    static const char marker[] = "@LANG@";
    const char *html = (const char *)setup_html_start;
    size_t len = (size_t)(setup_html_end - setup_html_start);
    size_t at = 0;
    while (at + sizeof(marker) - 1 <= len && memcmp(html + at, marker, sizeof(marker) - 1) != 0)
        at++;
    httpd_resp_set_type(req, "text/html");
    if (at + sizeof(marker) - 1 > len) return httpd_resp_send(req, html, (ssize_t)len);
    const char *code = box_lang_code(request_lang(req));
    httpd_resp_send_chunk(req, html, (ssize_t)at);
    httpd_resp_send_chunk(req, code, HTTPD_RESP_USE_STRLEN);
    httpd_resp_send_chunk(req, html + at + sizeof(marker) - 1,
                          (ssize_t)(len - at - (sizeof(marker) - 1)));
    return httpd_resp_send_chunk(req, NULL, 0);
}

/* Everything else a phone asks for is the operating system checking for the internet
 * (Android /generate_204, Apple /hotspot-detect.html, Windows /connecttest.txt, ...): not the
 * answer it expects, so it opens the sign-in page, which is this page. */
static esp_err_t captive_get_handler(httpd_req_t *req)
{
    char where[40];
    snprintf(where, sizeof(where), "http://%s/", ap_ip_text);
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", where);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, "", 0);
}

/* A form that cannot be saved: a 400 with the reason in the page's language. */
static esp_err_t send_problem(httpd_req_t *req, box_lang_t lang, const char *text)
{
    (void)lang;
    httpd_resp_set_status(req, "400 Bad Request");
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr_chunk(req, "<!DOCTYPE html><meta charset=\"utf-8\"><meta name=\"viewport\" "
                                  "content=\"width=device-width,initial-scale=1\"><body style=\""
                                  "font-family:system-ui,sans-serif;padding:16px\"><p>");
    httpd_resp_sendstr_chunk(req, text);
    httpd_resp_sendstr_chunk(req, "</p><p><a href=\"javascript:history.back()\">&larr;</a></p>");
    httpd_resp_sendstr_chunk(req, NULL);
    return ESP_FAIL;
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
    box_lang_t lang = request_lang(req);
    /* With the field Wi-Fi's name and password URL-encoded, the form can pass 512 bytes. */
    static char buf[1024];
    if (req->content_len == 0 || req->content_len >= sizeof(buf)) {
        return send_problem(req, lang, wifi_setup_msg(lang, WS_MSG_BAD_BODY));
    }
    int ret = 0;
    while (ret < (int)req->content_len) {
        int n = httpd_req_recv(req, buf + ret, req->content_len - (size_t)ret);
        if (n <= 0) {
            return send_problem(req, lang, wifi_setup_msg(lang, WS_MSG_BAD_BODY));
        }
        ret += n;
    }
    buf[ret] = '\0';

    /* Parse fields. */
    char name[33], region[10], pin[9], bri_s[4], vol_s[4];

    if (!parse_form_field(buf, "name", name, sizeof(name)) || name[0] == '\0') {
        return send_problem(req, lang, wifi_setup_msg(lang, WS_MSG_NAME));
    }

    if (!parse_form_field(buf, "region", region, sizeof(region))) {
        snprintf(region, sizeof(region), "%s", SETUP_REGION);
    }
    if (!is_valid_region(region)) {
        char why[96];
        snprintf(why, sizeof(why), wifi_setup_msg(lang, WS_MSG_REGION), SETUP_REGION);
        return send_problem(req, lang, why);
    }

    if (!parse_form_field(buf, "pin", pin, sizeof(pin))) pin[0] = '\0';
    const char *pin_problem = wifi_setup_pin_problem_in(lang, pin);
    if (pin_problem != NULL) return send_problem(req, lang, pin_problem);

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
            return send_problem(req, lang, wifi_setup_msg(lang, WS_MSG_JOIN_KEY));
        }
    }

    /* The field Wi-Fi a firmware update uses (protocol/firmware-update.md), optional. */
    char wifi_ssid[33], wifi_pass[65];
    bool have_wifi =
        parse_form_field(buf, "wifissid", wifi_ssid, sizeof(wifi_ssid)) && wifi_ssid[0] != '\0';
    if (!parse_form_field(buf, "wifipass", wifi_pass, sizeof(wifi_pass))) wifi_pass[0] = '\0';
    size_t np = strlen(wifi_pass);
    if (have_wifi && np > 0 && np < 8) {
        return send_problem(req, lang, wifi_setup_msg(lang, WS_MSG_WIFI_PASS));
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

    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr_chunk(req, "<!DOCTYPE html><meta charset=\"utf-8\"><meta name=\"viewport\" "
                                  "content=\"width=device-width,initial-scale=1\"><body style=\""
                                  "font-family:system-ui,sans-serif;padding:16px\"><h1>");
    httpd_resp_sendstr_chunk(req, wifi_setup_msg(lang, WS_MSG_SAVED));
    httpd_resp_sendstr_chunk(req, "</h1></body>");
    httpd_resp_sendstr_chunk(req, NULL);

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

/* The captive portal's DNS: every name is the box (wifi_setup_dns_reply), on the SoftAP's
 * address only. */
static void dns_task(void *arg)
{
    (void)arg;
    static uint8_t in[512], out[528];
    while (dns_run) {
        struct sockaddr_in from;
        socklen_t flen = sizeof(from);
        int n = recvfrom(dns_sock, in, sizeof(in), 0, (struct sockaddr *)&from, &flen);
        if (n <= 0) continue; /* the 1 s receive timeout, to look at dns_run */
        size_t m = wifi_setup_dns_reply(in, (size_t)n, out, sizeof(out), ap_ip);
        if (m > 0) sendto(dns_sock, out, m, 0, (struct sockaddr *)&from, flen);
    }
    close(dns_sock);
    dns_sock = -1;
    vTaskDelete(NULL);
}

static void dns_start(void)
{
    dns_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (dns_sock < 0) {
        ESP_LOGW(TAG, "DNS: no socket; phones will not open the page by themselves");
        return;
    }
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(53);
    memcpy(&addr.sin_addr.s_addr, ap_ip, 4); /* the SoftAP's address only */
    struct timeval tv = {.tv_sec = 1};
    setsockopt(dns_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    if (bind(dns_sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        /* The network interface may not hold its address yet: the portal runs on the SoftAP
         * alone (no station), so any address is the AP's. */
        addr.sin_addr.s_addr = htonl(INADDR_ANY);
    }
    if (bind(dns_sock, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        ESP_LOGW(TAG, "DNS: cannot bind port 53; phones will not open the page by themselves");
        close(dns_sock);
        dns_sock = -1;
        return;
    }
    dns_run = true;
    if (xTaskCreate(dns_task, "dns", 3072, NULL, 2, NULL) != pdPASS) {
        ESP_LOGW(TAG, "DNS: no task");
        dns_run = false;
        close(dns_sock);
        dns_sock = -1;
    }
}

int wifi_setup_start(void)
{
    /* Get MAC for SSID suffix. */
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    char *ssid = ap_ssid;
    snprintf(ap_ssid, sizeof(ap_ssid), "atalaia-%02X%02X", mac[4], mac[5]);

    /* The Wi-Fi driver and the AP network interface must exist first. */
    ap_netif = esp_netif_create_default_wifi_ap();
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

    /* The AP's address (192.168.4.1 unless the network interface says another). */
    esp_netif_ip_info_t info;
    if (ap_netif != NULL && esp_netif_get_ip_info(ap_netif, &info) == ESP_OK && info.ip.addr != 0) {
        memcpy(ap_ip, &info.ip.addr, 4);
        snprintf(ap_ip_text, sizeof(ap_ip_text), "%u.%u.%u.%u", ap_ip[0], ap_ip[1], ap_ip[2],
                 ap_ip[3]);
    }
    /* The DHCP server tells phones to ask the box for names (it offers no DNS otherwise, and
     * the phone would ask its mobile network, and never see the portal). */
    if (ap_netif != NULL) {
        esp_netif_dns_info_t dns = {0};
        dns.ip.type = ESP_IPADDR_TYPE_V4;
        memcpy(&dns.ip.u_addr.ip4.addr, ap_ip, 4);
        dhcps_offer_t offer_dns = OFFER_DNS;
        esp_netif_dhcps_stop(ap_netif);
        if (esp_netif_dhcps_option(ap_netif, ESP_NETIF_OP_SET, ESP_NETIF_DOMAIN_NAME_SERVER,
                                   &offer_dns, sizeof(offer_dns)) != ESP_OK ||
            esp_netif_set_dns_info(ap_netif, ESP_NETIF_DNS_MAIN, &dns) != ESP_OK) {
            ESP_LOGW(TAG, "DHCP: cannot offer the box as DNS; phones may not open the page by "
                          "themselves");
        }
        esp_netif_dhcps_start(ap_netif);
    }
    dns_start();

    /* Start HTTP server. A DNS socket and HTTP's (open sockets + 3) share LWIP's ten. */
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 4;
    config.max_open_sockets = 5;
    config.lru_purge_enable = true;
    config.uri_match_fn = httpd_uri_match_wildcard;

    if (httpd_start(&server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server");
        return -1;
    }

    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_get_handler};
    httpd_register_uri_handler(server, &root);

    httpd_uri_t config_post = {
        .uri = "/config", .method = HTTP_POST, .handler = config_post_handler};
    httpd_register_uri_handler(server, &config_post);

    /* Captive portal: any other GET is a phone's connectivity check; it is sent to the page. */
    httpd_uri_t captive = {.uri = "/*", .method = HTTP_GET, .handler = captive_get_handler};
    httpd_register_uri_handler(server, &captive);

    return 0;
}

const char *wifi_setup_ssid(void)
{
    return ap_ssid;
}

void wifi_setup_stop(void)
{
    dns_run = false; /* the DNS task ends within its 1 s receive timeout */
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
