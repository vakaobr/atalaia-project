/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * PN532 NFC reader over I2C (address 0x24) on the shared board bus. The frames and commands are
 * platform-free in hal/pn532.c (checked byte by byte by the host tests, test/test_pn532.c); this
 * file gives them the ESP32's I2C bus and FreeRTOS's delay.
 *
 * Poll for an ISO 14443A tag (InListPassiveTarget), read a Type 2 tag's user memory (NTAG215/216,
 * pages from 4) with the tag's READ command through InDataExchange, for join cards
 * (protocol/join.md) and player tags (protocol/nfc-tag.md), and the tag's READ, WRITE and
 * GET_VERSION for the USB console's card writer ("@nfcwrite", nfc_card.h). Since the box also
 * polls during games, init sets the chip to normal mode (SAMConfiguration) and to few passive
 * activation attempts (RFConfiguration MaxRetries), so a poll with no tag in the field returns at
 * once instead of waiting out the timeout, and a read stops as soon as the NDEF message is
 * complete. Not yet run against a real PN532; BRING_UP.md step 7 checks it.
 */

#ifdef ESP_PLATFORM

#include "../hal_nfc.h"
#include "../pn532.h"
#include "hal_esp_i2c.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "hal_nfc";

static bool present;

/* ---- the bus ---- */

static int i2c_write(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    return hal_esp_i2c_write(PN532_I2C_ADDR, data, len, PN532_TIMEOUT_MS) == HAL_ESP_I2C_OK ? 0
                                                                                            : -1;
}

static int i2c_read(void *ctx, uint8_t *data, size_t len, bool quiet)
{
    (void)ctx;
    /* Quiet: the PN532 NACKs while it is busy, which says nothing about the bus. */
    int r = quiet ? hal_esp_i2c_read_quiet(PN532_I2C_ADDR, data, len, 20)
                  : hal_esp_i2c_read(PN532_I2C_ADDR, data, len, PN532_TIMEOUT_MS);
    return r == HAL_ESP_I2C_OK ? 0 : -1;
}

static void rtos_delay(void *ctx, unsigned ms)
{
    (void)ctx;
    vTaskDelay(pdMS_TO_TICKS(ms));
}

static pn532_t pn532 = {.io = {.write = i2c_write, .read = i2c_read, .delay_ms = rtos_delay}};

/* ---- ops ---- */

static int esp_nfc_init(void)
{
    present = hal_esp_i2c_init() == 0 && hal_esp_i2c_probe(PN532_I2C_ADDR);
    if (!present) {
        /* Not fatal: the box runs without NFC (and Wokwi has no PN532). */
        ESP_LOGW(TAG, "PN532 NFC reader not found at 0x%02X: NFC disabled", PN532_I2C_ADDR);
        return -1;
    }
    ESP_LOGI(TAG, "PN532 NFC reader at 0x%02X", PN532_I2C_ADDR);
    int r = pn532_configure(&pn532);
    if (r < 0) {
        ESP_LOGW(TAG, "PN532: configuration not acknowledged (%d); polls may block for %d ms", r,
                 PN532_TIMEOUT_MS);
    }
    return 0;
}

static bool esp_nfc_poll(hal_nfc_tag_t *tag)
{
    if (!present) {
        pn532.have_target = false;
        return false;
    }
    return pn532_poll(&pn532, tag);
}

static int esp_nfc_read_user_memory(uint8_t *buf, size_t cap)
{
    if (!present) return -1;
    return pn532_read_user_memory(&pn532, buf, cap);
}

static int esp_nfc_t2_read(uint8_t page, uint8_t out[16])
{
    return present ? pn532_t2_read(&pn532, page, out) : -1;
}

static int esp_nfc_t2_write(uint8_t page, const uint8_t data[4])
{
    return present ? pn532_t2_write(&pn532, page, data) : -1;
}

static int esp_nfc_t2_get_version(uint8_t out[8])
{
    return present ? pn532_t2_get_version(&pn532, out) : -1;
}

static void esp_nfc_deinit(void)
{
    /* The bus is shared; it stays installed. */
    present = false;
}

const hal_nfc_ops_t hal_esp_nfc_ops = {
    .init = esp_nfc_init,
    .poll = esp_nfc_poll,
    .read_user_memory = esp_nfc_read_user_memory,
    .t2_read = esp_nfc_t2_read,
    .t2_write = esp_nfc_t2_write,
    .t2_get_version = esp_nfc_t2_get_version,
    .deinit = esp_nfc_deinit,
};

#endif /* ESP_PLATFORM */
