/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem task: serial link <-> modem logic <-> radio task.
 *
 * The serial link is the ESP32-S3's built-in USB-Serial-JTAG port by
 * default, or UART0 for boards that put a USB-UART bridge on GPIO 43/44
 * (CONFIG_ATALAIA_MODEM_LINK_UART0). Both paths are compiled in every
 * build so neither can rot; the unused one is dropped by the linker.
 *
 * The radio task owns the SPI bus, so channel changes, duty-cycle readings
 * and noise measurements go through it (radio_task_set_channel,
 * radio_task_duty_*, radio_task_measure_*).
 */
#include "modem_task.h"

#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "driver/usb_serial_jtag.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "atalaia/duty_cycle.h"
#include "modem.h"
#include "radio/radio_task.h"
#include "sdkconfig.h"

#ifdef CONFIG_ATALAIA_MODEM_LINK_UART0
#define MODEM_LINK_UART 1
#else
#define MODEM_LINK_UART 0
#endif

#ifndef CONFIG_ATALAIA_MODEM_UART_BAUD
#define CONFIG_ATALAIA_MODEM_UART_BAUD 921600
#endif

#ifndef CONFIG_ATALAIA_MODEM_EPOCH_WINDOW
#define CONFIG_ATALAIA_MODEM_EPOCH_WINDOW 16
#endif

#ifndef CONFIG_ATALAIA_MODEM_LINK_TIMEOUT_S
#define CONFIG_ATALAIA_MODEM_LINK_TIMEOUT_S 12
#endif

#if MODEM_LINK_UART && defined(CONFIG_ESP_CONSOLE_UART)
#error                                                                                             \
    "The modem link uses UART0: move the console off it (CONFIG_ESP_CONSOLE_NONE or USB_SERIAL_JTAG)"
#endif

#define MODEM_UART       UART_NUM_0
#define MODEM_BUF_SIZE   1024
#define MODEM_TASK_STACK 6144
#define MODEM_TASK_PRIO  4

/* How often the loop publishes its state for the OLED (modem_display.c). */
#define SCREEN_PUBLISH_MS 200

static const char *TAG = "modem";

static modem_t modem;

/* What the OLED task reads: only the modem task touches `modem`, and it
 * publishes the screen's state here, so the display never races it. */
static portMUX_TYPE screen_lock = portMUX_INITIALIZER_UNLOCKED;
static modem_screen_state_t screen_state;
static uint32_t idle_channel_hz;

static int link_write(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    int n;
    if (MODEM_LINK_UART) {
        n = uart_write_bytes(MODEM_UART, buf, len);
    } else {
        /* Bounded wait: with no host attached the frames are simply lost. */
        n = usb_serial_jtag_write_bytes(buf, len, pdMS_TO_TICKS(20));
    }
    return n == (int)len ? 0 : -1;
}

static int link_read(uint8_t *buf, size_t cap)
{
    if (MODEM_LINK_UART) {
        return uart_read_bytes(MODEM_UART, buf, (uint32_t)cap, pdMS_TO_TICKS(5));
    }
    return usb_serial_jtag_read_bytes(buf, (uint32_t)cap, pdMS_TO_TICKS(5));
}

static bool link_start(void)
{
    if (MODEM_LINK_UART) {
        uart_config_t cfg = {
            .baud_rate = CONFIG_ATALAIA_MODEM_UART_BAUD,
            .data_bits = UART_DATA_8_BITS,
            .parity = UART_PARITY_DISABLE,
            .stop_bits = UART_STOP_BITS_1,
            .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
            .source_clk = UART_SCLK_DEFAULT,
        };
        if (uart_driver_install(MODEM_UART, MODEM_BUF_SIZE, MODEM_BUF_SIZE, 0, NULL, 0) != ESP_OK) {
            return false;
        }
        return uart_param_config(MODEM_UART, &cfg) == ESP_OK;
    }
    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = MODEM_BUF_SIZE,
        .rx_buffer_size = MODEM_BUF_SIZE,
    };
    return usb_serial_jtag_driver_install(&cfg) == ESP_OK;
}

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

static uint32_t io_now_ms(void *ctx)
{
    (void)ctx;
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* The screen's state now (the link timeout counted from this moment). */
static void publish_screen_state(void)
{
    uint32_t duty = modem.radio_present ? radio_task_duty_remaining_ms() : 0;
    modem_screen_state_t s;
    modem_screen_state(&modem, io_now_ms(NULL), CONFIG_ATALAIA_MODEM_LINK_TIMEOUT_S * 1000u,
                       idle_channel_hz, duty, NULL, &s);
    taskENTER_CRITICAL(&screen_lock);
    screen_state = s;
    taskEXIT_CRITICAL(&screen_lock);
}

void modem_task_screen_state(modem_screen_state_t *out, const char *fault)
{
    taskENTER_CRITICAL(&screen_lock);
    *out = screen_state;
    taskEXIT_CRITICAL(&screen_lock);
    if (!out->radio_ok && fault && fault[0]) {
        snprintf(out->fault, sizeof(out->fault), "%s", fault);
    }
}

static modem_tx_status_t map_status(radio_tx_status_t status)
{
    switch (status) {
    case RADIO_TX_RESULT_OK: return MODEM_TX_OK;
    case RADIO_TX_RESULT_DUTY_CYCLE: return MODEM_TX_DUTY_CYCLE;
    default: return MODEM_TX_TIMEOUT;
    }
}

static void modem_loop(void *arg)
{
    (void)arg;
    /* The task watchdog reboots the modem if this loop hangs
     * (CONFIG_ESP_TASK_WDT_PANIC in sdkconfig.modem). */
    esp_task_wdt_add(NULL);
    modem_send_ident(&modem);

    uint8_t buf[256];
    uint32_t last_publish = io_now_ms(NULL);
    for (;;) {
        esp_task_wdt_reset();
        uint32_t t = io_now_ms(NULL);
        if (t - last_publish >= SCREEN_PUBLISH_MS) {
            publish_screen_state();
            last_publish = t;
        }
        int n = link_read(buf, sizeof(buf));
        if (n > 0) {
            modem_feed_serial(&modem, buf, (size_t)n);
        }
        radio_rx_msg_t rx;
        while (radio_task_recv(&rx)) {
            /* The HAL does not report SNR yet: sent as 0. */
            modem_on_air_rx(&modem, rx.data, rx.len, rx.rssi, 0);
        }
        radio_tx_result_t result;
        while (radio_task_tx_result(&result)) {
            modem_on_tx_result(&modem, result.tag, map_status(result.status));
        }
        noise_result_t noise;
        int noise_rc;
        if (radio_task_measure_result(&noise, &noise_rc)) {
            modem_on_measure_result(&modem, noise_rc, &noise);
        }
    }
}

bool modem_task_start(const hal_t *hal)
{
    if (!link_start()) {
        ESP_LOGE(TAG, "serial link driver failed to start");
        return false;
    }
    modem_io_t io = {
        .serial_write = link_write,
        .radio_send = io_radio_send,
        .set_channel = io_set_channel,
        .duty_cycle_remaining_ms = io_duty_remaining,
        .now_ms = io_now_ms,
        .measure_start = io_measure_start,
        .ctx = NULL,
    };
    const esp_app_desc_t *app = esp_app_get_description();
    modem_init(&modem, &io, &atalaia_crypto_mbedtls, app->version, hal->radio != NULL,
               CONFIG_ATALAIA_MODEM_EPOCH_WINDOW);
    /* The radio's boot channel (hal_esp_radio.c), shown until the controller sets one. */
    idle_channel_hz = atalaia_channel_ok(CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ)
                          ? CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ
                          : 869525000u;
    publish_screen_state();
    ESP_LOGI(TAG, "modem ready on %s (radio %s, epoch window %d)",
             MODEM_LINK_UART ? "UART0" : "USB-Serial-JTAG", hal->radio != NULL ? "on" : "absent",
             CONFIG_ATALAIA_MODEM_EPOCH_WINDOW);
    return xTaskCreatePinnedToCore(modem_loop, "modem", MODEM_TASK_STACK, NULL, MODEM_TASK_PRIO,
                                   NULL, 1) == pdPASS;
}
