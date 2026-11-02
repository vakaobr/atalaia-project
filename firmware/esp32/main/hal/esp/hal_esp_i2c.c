/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "hal_esp_i2c.h"

#include <string.h>

#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "hal_i2c";

#ifndef CONFIG_ATALAIA_NFC_SDA_PIN
#define CONFIG_ATALAIA_NFC_SDA_PIN 17
#endif
#ifndef CONFIG_ATALAIA_NFC_SCL_PIN
#define CONFIG_ATALAIA_NFC_SCL_PIN 18
#endif

#define BUS_HZ 100000 /* 100 kHz: the PN532 is the slowest device */
/* Pulses shorter than this many I2C clock cycles on SDA/SCL are ignored (the driver's typical
 * value): noise on a poor joint is filtered by the hardware, not seen as a start/stop. */
#define GLITCH_CYCLES 7
/* The most parts on the bus: OLED, keypad (any of 16 addresses, one used), NFC, gauge. */
#define MAX_DEVICES 8

typedef struct {
    uint8_t addr;
    i2c_master_dev_handle_t dev;
    i2c_health_t health;
} device_t;

static int init_result = 1; /* 1 = not tried yet */
static i2c_master_bus_handle_t bus;
static SemaphoreHandle_t lock; /* the table and the health records, never held in a transaction */
static SemaphoreHandle_t xfer; /* one transaction (or reset, or probe) on the bus at a time */
static device_t devices[MAX_DEVICES];
static size_t device_count;
static i2c_bus_health_t bus_health;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

int hal_esp_i2c_init(void)
{
    if (init_result != 1) return init_result;

    lock = xSemaphoreCreateMutex();
    xfer = xSemaphoreCreateMutex();
    i2c_bus_health_init(&bus_health);
    i2c_master_bus_config_t conf = {
        .i2c_port = HAL_ESP_I2C_PORT,
        .sda_io_num = CONFIG_ATALAIA_NFC_SDA_PIN,
        .scl_io_num = CONFIG_ATALAIA_NFC_SCL_PIN,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = GLITCH_CYCLES,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = (lock && xfer) ? i2c_new_master_bus(&conf, &bus) : ESP_ERR_NO_MEM;
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C bus init failed: %s", esp_err_to_name(err));
        init_result = -1;
    } else {
        ESP_LOGI(TAG, "I2C bus on SDA %d, SCL %d", CONFIG_ATALAIA_NFC_SDA_PIN,
                 CONFIG_ATALAIA_NFC_SCL_PIN);
        init_result = 0;
    }
    return init_result;
}

/* The device's record, made on first use; NULL when the table is full or the driver refuses.
 * Call with the lock held. */
static device_t *device_for(uint8_t addr)
{
    for (size_t i = 0; i < device_count; i++) {
        if (devices[i].addr == addr) return &devices[i];
    }
    if (device_count >= MAX_DEVICES) return NULL;
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = BUS_HZ,
    };
    device_t *d = &devices[device_count];
    if (i2c_master_bus_add_device(bus, &cfg, &d->dev) != ESP_OK) return NULL;
    d->addr = addr;
    i2c_health_init(&d->health);
    device_count++;
    return d;
}

bool hal_esp_i2c_probe(uint8_t addr)
{
    if (init_result != 0) return false;
    xSemaphoreTake(xfer, portMAX_DELAY);
    esp_err_t err = i2c_master_probe(bus, addr, 50);
    if (err == ESP_ERR_TIMEOUT) i2c_master_bus_reset(bus); /* bus stuck: let go of it */
    xSemaphoreGive(xfer);
    return err == ESP_OK;
}

bool hal_esp_i2c_usable(uint8_t addr)
{
    if (init_result != 0) return false;
    bool usable = true;
    xSemaphoreTake(lock, portMAX_DELAY);
    for (size_t i = 0; i < device_count; i++) {
        if (devices[i].addr == addr) {
            i2c_health_t copy = devices[i].health; /* allow() counts a skip: do not on a peek */
            usable = i2c_health_allow(&copy, now_ms());
            break;
        }
    }
    xSemaphoreGive(lock);
    return usable;
}

typedef enum { OP_WRITE, OP_READ, OP_WRITE_READ } op_t;

static int transact(uint8_t addr, op_t op, const uint8_t *out, size_t out_len, uint8_t *in,
                    size_t in_len, int timeout_ms, bool tracked)
{
    if (init_result != 0) return HAL_ESP_I2C_FAIL;

    xSemaphoreTake(lock, portMAX_DELAY);
    device_t *d = device_for(addr);
    bool go = d != NULL && (!tracked || i2c_health_allow(&d->health, now_ms()));
    i2c_master_dev_handle_t dev = d ? d->dev : NULL;
    xSemaphoreGive(lock);
    if (d == NULL) return HAL_ESP_I2C_FAIL;
    if (!go) return HAL_ESP_I2C_SUSPENDED;

    esp_err_t err;
    xSemaphoreTake(xfer, portMAX_DELAY);
    switch (op) {
    case OP_WRITE: err = i2c_master_transmit(dev, out, out_len, timeout_ms); break;
    case OP_READ: err = i2c_master_receive(dev, in, in_len, timeout_ms); break;
    default: err = i2c_master_transmit_receive(dev, out, out_len, in, in_len, timeout_ms); break;
    }
    if (!tracked) {
        xSemaphoreGive(xfer);
        return err == ESP_OK ? HAL_ESP_I2C_OK : HAL_ESP_I2C_FAIL;
    }

    bool reset;
    i2c_health_event_t ev;
    uint32_t t = now_ms();
    xSemaphoreTake(lock, portMAX_DELAY);
    ev = i2c_health_report(&d->health, t, err == ESP_OK);
    reset = i2c_bus_health_report(&bus_health, t, err == ESP_OK);
    uint32_t errors = d->health.errors, backoff = d->health.backoff_ms;
    xSemaphoreGive(lock);

    if (reset) {
        /* A run of failures on the bus: the driver already reset the controller after each one;
         * this also clocks out a slave holding SDA low. */
        i2c_master_bus_reset(bus);
    }
    xSemaphoreGive(xfer);
    if (reset) ESP_LOGW(TAG, "bus reset after a run of failed transactions");
    if (ev == I2C_HEALTH_SUSPENDED) {
        ESP_LOGW(TAG, "device 0x%02X suspended after %d failures (last: %s): retry in %lu ms", addr,
                 I2C_HEALTH_FAIL_LIMIT, esp_err_to_name(err), (unsigned long)backoff);
    } else if (ev == I2C_HEALTH_STILL_DOWN) {
        ESP_LOGW(TAG, "device 0x%02X still failing (%lu errors): next try in %lu ms", addr,
                 (unsigned long)errors, (unsigned long)backoff);
    } else if (ev == I2C_HEALTH_RECOVERED) {
        ESP_LOGI(TAG, "device 0x%02X answers again", addr);
    }
    return err == ESP_OK ? HAL_ESP_I2C_OK : HAL_ESP_I2C_FAIL;
}

int hal_esp_i2c_write(uint8_t addr, const uint8_t *data, size_t len, int timeout_ms)
{
    return transact(addr, OP_WRITE, data, len, NULL, 0, timeout_ms, true);
}

int hal_esp_i2c_read(uint8_t addr, uint8_t *data, size_t len, int timeout_ms)
{
    return transact(addr, OP_READ, NULL, 0, data, len, timeout_ms, true);
}

int hal_esp_i2c_write_read(uint8_t addr, const uint8_t *out, size_t out_len, uint8_t *in,
                           size_t in_len, int timeout_ms)
{
    return transact(addr, OP_WRITE_READ, out, out_len, in, in_len, timeout_ms, true);
}

int hal_esp_i2c_read_quiet(uint8_t addr, uint8_t *data, size_t len, int timeout_ms)
{
    return transact(addr, OP_READ, NULL, 0, data, len, timeout_ms, false);
}

void hal_esp_i2c_stats(uint8_t addr, i2c_health_t *out, uint32_t *bus_resets)
{
    memset(out, 0, sizeof(*out));
    if (init_result != 0) return;
    xSemaphoreTake(lock, portMAX_DELAY);
    for (size_t i = 0; i < device_count; i++) {
        if (devices[i].addr == addr) *out = devices[i].health;
    }
    if (bus_resets) *bus_resets = bus_health.resets;
    xSemaphoreGive(lock);
}

#endif /* ESP_PLATFORM */
