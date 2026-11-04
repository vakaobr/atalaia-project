/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's task (see pod_task.h).
 *
 * USB: the Heltec V4 has no USB-UART bridge; its USB-C port is the
 * ESP32-S3's own USB-Serial-JTAG controller, which a phone sees as a CDC ACM
 * serial device (as the USB radio modem does, protocol/usb-modem.md). The
 * log console stays on UART0 (sdkconfig.pod), so log text never mixes with
 * frames; the boot ROM's text on the port is skipped by the framing.
 *
 * The simple outputs (CONFIG_ATALAIA_SIMPLE_OUT; pod_outputs.h, increment 9 of the expansion
 * port): their RMT bursts are renewed by this task's loop, so a hung loop stops them within
 * 0.5 s (and the task watchdog reboots the pod).
 *
 * The expansion port (CONFIG_ATALAIA_POD_PORT; pod_port.h, the port half of increment 9): the
 * box's port driver on the board's I2C bus (GPIO 17 and 18, shared with the keypad's expander,
 * the NFC reader and the gauge, EXP-2), ticked by this task's loop with the parts, so a module's
 * lease stops being refreshed when the loop stops.
 */
#include "pod_task.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/packet.h"
#include "atalaia/version.h"
#include "driver/gpio.h"
#include "driver/usb_serial_jtag.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "pod.h"
#include "pod_ble.h"
#include "nvs.h"
#include "pod_config.h"
#include "pod_outputs.h"
#include "pod_port.h"
#include "pod_settings.h"
#include "radio/radio_task.h"
#include "simple_out_esp.h"
#include "sound_esp.h"
#if CONFIG_ATALAIA_POD_PORT
#include "expansion_esp.h"
#endif

#if CONFIG_ATALAIA_POD_MODULE_OUTPUTS
#define POD_MODULE_OUTPUTS  true
#define POD_MODULE_MAX_ON_S CONFIG_ATALAIA_POD_MODULE_MAX_ON_S
#else
#define POD_MODULE_OUTPUTS  false
#define POD_MODULE_MAX_ON_S OUT_MAX_ON_DEFAULT_S
#endif

#if POD_BLE_ENABLED
#include "pod_ble_nimble.h"
#else
/* USB only (CONFIG_ATALAIA_POD_BLE off): no Bluetooth stack in the image. */
static const pod_ble_stack_t pod_ble_nimble_stack = {.notify = NULL, .ctx = NULL};
static void pod_ble_nimble_poll(pod_ble_t *b)
{
    (void)b;
}
static void pod_ble_nimble_set_status(const uint8_t status[3])
{
    (void)status;
}
#endif

static const char *TAG = "pod";

#define POD_TASK_STACK  8192
#define POD_TASK_PRIO   5
#define AUDIO_TASK_PRIO 2
#define USB_BUF_SIZE    1024
#define AUDIO_QUEUE_LEN 16

static const hal_t *hw;
static pod_t pod;
static pod_caps_t caps;
static pod_caps_config_t build_cfg; /* what the Kconfig and the boot gave (pod_settings_apply) */
static pod_settings_t settings;     /* what the field controller pushed (NVS "pod"/"settings") */
static pod_outputs_t outs; /* the simple outputs (none without CONFIG_ATALAIA_SIMPLE_OUT) */
static pod_port_t port;    /* the expansion port (no bus without CONFIG_ATALAIA_POD_PORT) */
static pod_ble_t ble;
static bool ble_on;
static QueueHandle_t audio_q;
static char fw_version[ATALAIA_PROXY_TEXT_MAX + 1];

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* ---- Audio: tones on their own task ---------------------------------------------- */

typedef enum { AUDIO_TONE, AUDIO_STOP, AUDIO_VOLUME } audio_op_t;

typedef struct {
    uint8_t op;
    uint8_t volume;
    uint16_t hz;
    uint16_t ms;
} audio_req_t;

/* On the speaker and the piezo buzzer, whichever are fitted (sound.c, decision BZR-3). */
static void audio_task(void *arg)
{
    (void)arg;
    audio_req_t r;
    sound_out_t out = sound_esp_out(hw, hw->audio != NULL);
    for (;;) {
        if (xQueueReceive(audio_q, &r, portMAX_DELAY) != pdTRUE) continue;
        switch (r.op) {
        case AUDIO_TONE: sound_tone(&out, r.hz, r.ms); break;
        case AUDIO_STOP: sound_stop(&out); break;
        case AUDIO_VOLUME:
            if (hw->audio != NULL) hw->audio->set_volume(r.volume);
            if (hw->buzzer != NULL) hw->buzzer->set_volume(r.volume);
            break;
        default: break;
        }
    }
}

static void audio_tone(void *ctx, uint32_t hz, uint32_t ms)
{
    (void)ctx;
    audio_req_t r = {.op = AUDIO_TONE, .hz = (uint16_t)hz, .ms = (uint16_t)ms};
    if (audio_q != NULL) xQueueSend(audio_q, &r, 0);
}

static void audio_stop(void *ctx)
{
    (void)ctx;
    if (audio_q == NULL) return;
    xQueueReset(audio_q); /* the tones still waiting are dropped too */
    audio_req_t r = {.op = AUDIO_STOP};
    xQueueSend(audio_q, &r, 0);
}

static void audio_volume(void *ctx, uint8_t pct)
{
    (void)ctx;
    audio_req_t r = {.op = AUDIO_VOLUME, .volume = pct};
    if (audio_q != NULL) xQueueSend(audio_q, &r, 0);
}

/* ---- The proxy's I/O ---------------------------------------------------------------- */

static int link_write(void *ctx, pod_link_t link, const uint8_t *frame, size_t len)
{
    (void)ctx;
    if (link == POD_LINK_BLE) return ble_on ? pod_ble_send_frame(&ble, frame, len) : -1;
    /* Bounded wait: with no phone reading, the frames are lost (and resent). */
    int n = usb_serial_jtag_write_bytes(frame, len, pdMS_TO_TICKS(20));
    return n == (int)len ? 0 : -1;
}

static uint32_t io_now(void *ctx)
{
    (void)ctx;
    return now_ms();
}

static bool io_command(void *ctx, const atalaia_proxy_msg_t *cmd)
{
    (void)ctx;
    if (pod_outputs_owns(&outs, cmd->cap_id)) return pod_outputs_command(&outs, cmd);
    if (pod_port_owns(&port, cmd->cap_id)) return pod_port_command(&port, cmd);
    return pod_caps_command(&caps, cmd);
}

/* ---- The settings pushed over the radio (pod_settings.h), kept in NVS ---------------- */

#define SETTINGS_NS  "pod"
#define SETTINGS_KEY "settings"

static void settings_save(void)
{
    char json[POD_SETTINGS_JSON_MAX];
    nvs_handle_t h;
    if (pod_settings_to_json(&settings, json, sizeof(json)) == 0) return;
    if (nvs_open(SETTINGS_NS, NVS_READWRITE, &h) != ESP_OK) return;
    if (nvs_set_str(h, SETTINGS_KEY, json) == ESP_OK) nvs_commit(h);
    nvs_close(h);
}

static void settings_load(void)
{
    char json[POD_SETTINGS_JSON_MAX] = "";
    nvs_handle_t h;
    if (nvs_open(SETTINGS_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t len = sizeof(json);
        if (nvs_get_str(h, SETTINGS_KEY, json, &len) != ESP_OK) json[0] = '\0';
        nvs_close(h);
    }
    pod_settings_load(&settings, json);
}

static pod_config_result_t io_config(void *ctx, const char *params_json, uint32_t *rev)
{
    (void)ctx;
    pod_config_result_t r = pod_settings_handle(&settings, params_json, &caps, &build_cfg, rev);
    if (r == POD_CONFIG_APPLIED) settings_save();
    return r;
}

static int battery_pct(void)
{
    if (hw->battery == NULL) return -1;
    hal_battery_info_t b = hw->battery->read();
    return b.voltage_mv > 0 ? (int)b.percent : -1;
}

static void io_ident(void *ctx, atalaia_proxy_ident_t *out, pod_ident_level_t level)
{
    (void)ctx;
    memcpy(out->fw_version, fw_version, sizeof(out->fw_version));
    pod_port_ident_caps(&port, &caps, level, out->caps_json, sizeof(out->caps_json));
    int pct = battery_pct();
    out->has_battery = pct >= 0;
    out->battery_pct = pct >= 0 ? (uint8_t)pct : 0;
}

static bool emit(void *ctx, const char *cap_id, const char *event, const char *data_json)
{
    (void)ctx;
    return pod_event(&pod, cap_id, event, data_json);
}

static void io_link_active(void *ctx, pod_link_t link)
{
    (void)ctx;
    ESP_LOGI(TAG, "phone on the %s link", link == POD_LINK_USB ? "USB" : "Bluetooth");
    pod_caps_report(&caps, emit, NULL);
}

static void io_log(void *ctx, const char *line)
{
    (void)ctx;
    ESP_LOGI(TAG, "%s", line);
}

static void outputs_log(void *ctx, const char *line)
{
    (void)ctx;
    ESP_LOGI(TAG, "output: %s", line);
}

static void port_ident_changed(void *ctx)
{
    (void)ctx;
    pod_send_ident_all(&pod);
}

static void port_log(void *ctx, const char *line)
{
    (void)ctx;
    ESP_LOGI(TAG, "%s", line);
}

/* ---- The radio through the radio task ------------------------------------------------ */

static bool io_radio_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    (void)ctx;
    return radio_task_send_tagged(pkt, len, tag);
}

static int io_set_channel(void *ctx, uint32_t freq_hz)
{
    (void)ctx;
    return radio_task_set_channel(freq_hz) ? 0 : -1;
}

static uint32_t io_duty_remaining(void *ctx)
{
    (void)ctx;
    return radio_task_duty_remaining_ms();
}

static int io_measure_start(void *ctx, uint32_t freq_hz, uint16_t dwell_ms, bool cad)
{
    (void)ctx;
    return radio_task_measure_start(freq_hz, dwell_ms, cad) ? 0 : -1;
}

static modem_tx_status_t map_status(radio_tx_status_t status)
{
    switch (status) {
    case RADIO_TX_RESULT_OK: return MODEM_TX_OK;
    case RADIO_TX_RESULT_DUTY_CYCLE: return MODEM_TX_DUTY_CYCLE;
    default: return MODEM_TX_TIMEOUT;
    }
}

/* ---- The enclosure switch -------------------------------------------------------------- */

static int tamper_raw(void)
{
#if CONFIG_ATALAIA_POD_TAMPER_PIN >= 0
    return gpio_get_level(CONFIG_ATALAIA_POD_TAMPER_PIN) == POD_TAMPER_OPEN_LEVEL ? 1 : 0;
#else
    return -1;
#endif
}

static void tamper_start(void)
{
#if CONFIG_ATALAIA_POD_TAMPER_PIN >= 0
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << CONFIG_ATALAIA_POD_TAMPER_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
#endif
}

/* ---- The loop ---------------------------------------------------------------------------- */

static void pod_loop(void *arg)
{
    (void)arg;
    /* The task watchdog reboots a hung pod (sdkconfig.pod); the phone notices
     * the missing ACKs, links again and configures the radio again. */
    esp_task_wdt_add(NULL);
    uint8_t buf[256];
    uint32_t last_usb_check = 0, last_status = 0, last_battery = 0;
    int battery = battery_pct();
    for (;;) {
        esp_task_wdt_reset();
        int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), pdMS_TO_TICKS(5));
        if (n > 0) pod_feed(&pod, POD_LINK_USB, buf, (size_t)n);
        if (ble_on) pod_ble_nimble_poll(&ble);

        uint32_t t = now_ms();
        pod_caps_poll(&caps, t, tamper_raw(), emit, NULL);

        radio_rx_msg_t rx;
        while (radio_task_recv(&rx)) pod_on_air_rx(&pod, rx.data, rx.len, rx.rssi, 0);
        radio_tx_result_t result;
        while (radio_task_tx_result(&result)) {
            pod_on_tx_result(&pod, result.tag, map_status(result.status));
        }
        noise_result_t noise;
        int noise_rc;
        if (radio_task_measure_result(&noise, &noise_rc)) {
            pod_on_measure_result(&pod, noise_rc, &noise);
        }

        pod_tick(&pod);
        if (ble_on) pod_ble_flush(&ble);
        /* The outputs' link and lease rules, and their bursts renewed (every 200 ms). */
        pod_outputs_tick(&outs, pod_phone_on(&pod), pod_heard_ms(&pod), now_ms());
        /* The expansion port: hot-plug, polls, hits to the phone, the modules' lease. */
        pod_port_tick(&port, pod_phone_on(&pod), now_ms());

        bool usb_host = usb_serial_jtag_is_connected();
        if (t - last_usb_check >= 100) {
            last_usb_check = t;
            pod_set_link_up(&pod, POD_LINK_USB, usb_host);
        }
        if (t - last_battery >= 10000) {
            last_battery = t;
            battery = battery_pct();
        }
        if (t - last_status >= 500) {
            last_status = t;
            uint8_t status[3];
            pod_status_bytes(&pod, battery, usb_host, status);
            if (ble_on) {
                pod_ble_nimble_set_status(status);
                pod_ble_set_status(&ble, status);
            }
        }
    }
}

void pod_task_start(const hal_t *hal, const pod_caps_config_t *cfg)
{
    hw = hal;
    const esp_app_desc_t *app = esp_app_get_description();
    /* IDENT's fw_version is 1-23 printable bytes: the image's version, its build metadata
     * shortened if need be (the boot log has all of it). */
    pod_fw_version(app->version, fw_version);

    usb_serial_jtag_driver_config_t usb = {
        .tx_buffer_size = USB_BUF_SIZE,
        .rx_buffer_size = USB_BUF_SIZE,
    };
    if (usb_serial_jtag_driver_install(&usb) != ESP_OK) {
        ESP_LOGE(TAG, "USB-Serial-JTAG driver failed to start: no USB link");
    }

    pod_audio_t audio = {.tone = audio_tone, .stop = audio_stop, .volume = audio_volume};
    if (cfg->audio && (hal->audio != NULL || hal->buzzer != NULL)) {
        audio_q = xQueueCreate(AUDIO_QUEUE_LEN, sizeof(audio_req_t));
        if (audio_q != NULL)
            xTaskCreatePinnedToCore(audio_task, "audio", 4096, NULL, AUDIO_TASK_PRIO, NULL, 0);
    }
    pod_caps_init(&caps, cfg, hal, audio_q != NULL ? &audio : NULL);
    /* The settings pushed over the radio last time, on top of the build's (caps now has the
     * parts that answered at boot). */
    build_cfg = caps.cfg;
    settings_load();
    pod_settings_apply(&settings, &caps, &build_cfg);
    tamper_start();
    /* The simple outputs, off: the loop's first tick ends their signal (the pins low). */
    outputs_ops_t out_ops = {.log = outputs_log};
    pod_outputs_init(&outs, &out_ops);
    int n_outs = simple_out_esp_init(&outs.out);
    /* The expansion port next (EXP-29): ALL_OFF to every module on the socket before anything
     * else, then each one read and added; the loop probes for more every 2 s. */
    pod_port_config_t port_cfg = {.module_outputs = POD_MODULE_OUTPUTS,
                                  .module_max_on_s = POD_MODULE_MAX_ON_S};
    pod_port_ops_t port_ops = {
        .ctx = NULL, .emit = emit, .ident_changed = port_ident_changed, .log = port_log};
    const exp_bus_t *port_bus = NULL;
#if CONFIG_ATALAIA_POD_PORT
    exp_bus_t bus;
    if (expansion_esp_bus(&bus)) {
        port_bus = &bus;
    } else {
        ESP_LOGW(TAG, "expansion port: the I2C bus could not be installed; no modules");
    }
#endif
    pod_port_init(&port, port_bus, &outs, &port_cfg, &port_ops);
    pod_port_start(&port, now_ms());

    pod_io_t io = {
        .link_write = link_write,
        .now_ms = io_now,
        .command = io_command,
        .ident = io_ident,
        .link_active = io_link_active,
        .log = io_log,
        .ctx = NULL,
        .config = io_config,
    };
    modem_io_t radio = {
        .radio_send = io_radio_send,
        .set_channel = io_set_channel,
        .duty_cycle_remaining_ms = io_duty_remaining,
        .now_ms = io_now,
        .measure_start = io_measure_start,
        .ctx = NULL,
    };
    pod_init(&pod, &io, &radio, &atalaia_crypto_mbedtls, fw_version, hal->radio != NULL,
             CONFIG_ATALAIA_MODEM_EPOCH_WINDOW);

    pod_ble_init(&ble, &pod, &pod_ble_nimble_stack, POD_BLE_ENCRYPTED);
    pod_ble_require_mitm(&ble, POD_BLE_PASSKEY); /* a passkey's key only (PODPK-3) */
#if POD_BLE_ENABLED
    ble_on = pod_ble_nimble_start(POD_BLE_ENCRYPTED);
#endif

    char json[ATALAIA_PROXY_JSON_MAX];
    pod_port_ident_caps(&port, &caps, POD_IDENT_FULL, json, sizeof(json));
    ESP_LOGI(TAG,
             "I/O pod %s, core %s: radio %s, Bluetooth %s, %d simple output(s), expansion port %s "
             "(%d module(s)), capabilities %s",
             fw_version, atalaia_version(), hal->radio != NULL ? "on" : "absent",
             ble_on ? "on" : "off", n_outs, port.on ? "on" : "off",
             port.on ? expansion_module_count(&port.xb.exp) : 0, json);
    xTaskCreatePinnedToCore(pod_loop, "pod", POD_TASK_STACK, NULL, POD_TASK_PRIO, NULL, 1);
}
