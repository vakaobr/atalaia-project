/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_nfc.h"

#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <string.h>

static const char *TAG = "hal_nfc";

/* ---- Kconfig pins ---- */

#ifndef CONFIG_ATALAIA_NFC_SDA_PIN
#define CONFIG_ATALAIA_NFC_SDA_PIN 17
#endif
#ifndef CONFIG_ATALAIA_NFC_SCL_PIN
#define CONFIG_ATALAIA_NFC_SCL_PIN 18
#endif
#ifndef CONFIG_ATALAIA_NFC_I2C_PORT
#define CONFIG_ATALAIA_NFC_I2C_PORT I2C_NUM_0
#endif

#define PN532_I2C_ADDR                0x24
#define PN532_READY_BIT               0x01
#define PN532_CMD_INLISTPASSIVETARGET 0x4A

/* ---- helpers ---- */

static esp_err_t pn532_write_command(const uint8_t *cmd, size_t len)
{
    /*
     * PN532 I2C frame:
     * [0x00] [0x00] [0xFF] [LEN] [LCS] [TFI=0xD4] [CMD] ... [DCS] [0x00]
     */
    uint8_t frame[64];
    if (len + 8 > sizeof(frame)) return ESP_ERR_INVALID_SIZE;

    size_t data_len = len + 1; /* TFI + command bytes */
    uint8_t lcs = (uint8_t)(~data_len + 1);

    frame[0] = 0x00; /* preamble */
    frame[1] = 0x00; /* start code 1 */
    frame[2] = 0xFF; /* start code 2 */
    frame[3] = (uint8_t)data_len;
    frame[4] = lcs;
    frame[5] = 0xD4; /* TFI: host to PN532 */

    uint8_t dcs = 0xD4;
    for (size_t i = 0; i < len; i++) {
        frame[6 + i] = cmd[i];
        dcs += cmd[i];
    }
    dcs = (uint8_t)(~dcs + 1);
    frame[6 + len] = dcs;
    frame[7 + len] = 0x00; /* postamble */

    return i2c_master_write_to_device(CONFIG_ATALAIA_NFC_I2C_PORT, PN532_I2C_ADDR, frame, 8 + len,
                                      pdMS_TO_TICKS(100));
}

static esp_err_t pn532_read_response(uint8_t *buf, size_t buf_len, size_t *out_len)
{
    /* First byte is the ready status */
    uint8_t status;
    esp_err_t err = i2c_master_read_from_device(CONFIG_ATALAIA_NFC_I2C_PORT, PN532_I2C_ADDR,
                                                &status, 1, pdMS_TO_TICKS(100));
    if (err != ESP_OK) return err;
    if (!(status & PN532_READY_BIT)) return ESP_ERR_NOT_FINISHED;

    /* Read the response frame */
    uint8_t frame[64];
    size_t read_len = buf_len + 9;
    if (read_len > sizeof(frame)) read_len = sizeof(frame);

    err = i2c_master_read_from_device(CONFIG_ATALAIA_NFC_I2C_PORT, PN532_I2C_ADDR, frame, read_len,
                                      pdMS_TO_TICKS(100));
    if (err != ESP_OK) return err;

    /*
     * Frame: [RDY] [0x00] [0x00] [0xFF] [LEN] [LCS] [TFI=0xD5] [CMD+1] ... [DCS] [0x00]
     * Data starts at offset 7 (after RDY + preamble + start + LEN + LCS + TFI)
     */
    size_t payload_len = frame[4];
    if (payload_len < 2) return ESP_ERR_INVALID_RESPONSE;
    payload_len -= 1; /* subtract TFI */

    if (payload_len > buf_len) payload_len = buf_len;
    memcpy(buf, &frame[7], payload_len);
    *out_len = payload_len;

    return ESP_OK;
}

/* ---- ops implementation ---- */

static int esp_nfc_init(void)
{
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = CONFIG_ATALAIA_NFC_SDA_PIN,
        .scl_io_num = CONFIG_ATALAIA_NFC_SCL_PIN,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000, /* 100 kHz */
    };

    esp_err_t err = i2c_param_config(CONFIG_ATALAIA_NFC_I2C_PORT, &conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C param config failed: %s", esp_err_to_name(err));
        return -1;
    }

    err = i2c_driver_install(CONFIG_ATALAIA_NFC_I2C_PORT, conf.mode, 0, 0, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C driver install failed: %s", esp_err_to_name(err));
        return -1;
    }

    ESP_LOGI(TAG, "PN532 NFC reader initialised on I2C%d", CONFIG_ATALAIA_NFC_I2C_PORT);
    return 0;
}

static bool esp_nfc_poll(hal_nfc_tag_t *tag)
{
    /* InListPassiveTarget: 1 target, 106 kbps type A */
    uint8_t cmd[] = {PN532_CMD_INLISTPASSIVETARGET, 0x01, 0x00};
    esp_err_t err = pn532_write_command(cmd, sizeof(cmd));
    if (err != ESP_OK) return false;

    /* Wait for response */
    vTaskDelay(pdMS_TO_TICKS(50));

    uint8_t resp[32];
    size_t resp_len = 0;
    err = pn532_read_response(resp, sizeof(resp), &resp_len);
    if (err != ESP_OK) return false;

    /*
     * Response: [CMD+1=0x4B] [NbTg] [Tg] [SENS_RES...] [SEL_RES] [NFCIDLength] [NFCID1...]
     * resp[0] = 0x4B (InListPassiveTarget response)
     * resp[1] = number of targets found
     */
    if (resp_len < 2 || resp[0] != 0x4B || resp[1] == 0) {
        return false;
    }

    /* Parse UID from the response */
    if (resp_len >= 7) {
        uint8_t uid_len = resp[6];
        if (uid_len > sizeof(tag->uid)) uid_len = sizeof(tag->uid);

        memset(tag, 0, sizeof(*tag));
        tag->uid_len = uid_len;
        if (resp_len >= 7 + uid_len) {
            memcpy(tag->uid, &resp[7], uid_len);
        }
    }

    return true;
}

static void esp_nfc_deinit(void)
{
    i2c_driver_delete(CONFIG_ATALAIA_NFC_I2C_PORT);
}

const hal_nfc_ops_t hal_esp_nfc_ops = {
    .init = esp_nfc_init,
    .poll = esp_nfc_poll,
    .deinit = esp_nfc_deinit,
};

#endif /* ESP_PLATFORM */
