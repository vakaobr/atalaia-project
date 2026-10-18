/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * PN532 NFC reader over I2C (address 0x24), from the public PN532 user
 * manual: every command is answered first by an ACK frame and then, when
 * the chip is ready again, by the response frame; every I2C read starts
 * with a status byte whose bit 0 says "ready".
 *
 * Two operations: poll for an ISO 14443A tag (InListPassiveTarget), and
 * read a Type 2 tag's user memory (NTAG215/216, pages from 4) with the
 * tag's READ command through InDataExchange, for join cards
 * (protocol/join.md) and player tags (protocol/nfc-tag.md). Since the box
 * also polls during games, init sets the chip to normal mode
 * (SAMConfiguration) and to one passive activation attempt
 * (RFConfiguration MaxRetries), so a poll with no tag in the field returns
 * at once instead of waiting out the timeout, and a read stops as soon as
 * the NDEF message is complete. Not yet run against a real PN532: the
 * boards and readers have not arrived (plan phase F); BRING_UP.md step 7
 * checks it.
 */

#ifdef ESP_PLATFORM

#include "../hal_nfc.h"
#include "hal_esp_i2c.h"

#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <string.h>

static const char *TAG = "hal_nfc";

/* The PN532 sits on the shared board bus (hal_esp_i2c.c). */
#define NFC_I2C_PORT HAL_ESP_I2C_PORT

#define PN532_I2C_ADDR                0x24
#define PN532_READY_BIT               0x01
#define PN532_CMD_SAMCONFIGURATION    0x14
#define PN532_CMD_RFCONFIGURATION     0x32
#define PN532_CMD_INLISTPASSIVETARGET 0x4A
#define PN532_CMD_INDATAEXCHANGE      0x40
#define NTAG_CMD_READ                 0x30
#define NTAG_FIRST_USER_PAGE          4
#define NTAG_LAST_PAGE                231 /* NTAG216; NTAG215 stops earlier and errors */
#define PN532_TIMEOUT_MS              100

static bool present;
static bool have_target; /* the last poll found a tag (target 1) */

/* ---- frames ---- */

static esp_err_t pn532_write_command(const uint8_t *cmd, size_t len)
{
    /* [00] [00 FF] [LEN] [LCS] [D4 CMD ...] [DCS] [00] */
    uint8_t frame[64];
    if (len + 8 > sizeof(frame)) return ESP_ERR_INVALID_SIZE;
    size_t data_len = len + 1; /* TFI + command bytes */
    frame[0] = 0x00;
    frame[1] = 0x00;
    frame[2] = 0xFF;
    frame[3] = (uint8_t)data_len;
    frame[4] = (uint8_t)(~data_len + 1);
    frame[5] = 0xD4;
    uint8_t dcs = 0xD4;
    for (size_t i = 0; i < len; i++) {
        frame[6 + i] = cmd[i];
        dcs += cmd[i];
    }
    frame[6 + len] = (uint8_t)(~dcs + 1);
    frame[7 + len] = 0x00;
    return i2c_master_write_to_device(NFC_I2C_PORT, PN532_I2C_ADDR, frame, 8 + len,
                                      pdMS_TO_TICKS(PN532_TIMEOUT_MS));
}

static bool pn532_wait_ready(int timeout_ms)
{
    for (int waited = 0; waited <= timeout_ms; waited += 5) {
        uint8_t status = 0;
        if (i2c_master_read_from_device(NFC_I2C_PORT, PN532_I2C_ADDR, &status, 1,
                                        pdMS_TO_TICKS(20)) == ESP_OK &&
            (status & PN532_READY_BIT)) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    return false;
}

/*
 * Sends a command, checks the ACK frame, waits for the response and copies
 * its data (from the command code + 1 on) into resp. Returns the length, or -1.
 */
static int pn532_transceive(const uint8_t *cmd, size_t len, uint8_t *resp, size_t cap)
{
    if (pn532_write_command(cmd, len) != ESP_OK) return -1;
    if (!pn532_wait_ready(PN532_TIMEOUT_MS)) return -1;
    static const uint8_t ack[] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
    uint8_t frame[64];
    if (i2c_master_read_from_device(NFC_I2C_PORT, PN532_I2C_ADDR, frame, 1 + sizeof(ack),
                                    pdMS_TO_TICKS(PN532_TIMEOUT_MS)) != ESP_OK ||
        memcmp(frame + 1, ack, sizeof(ack)) != 0) {
        return -1;
    }
    if (!pn532_wait_ready(PN532_TIMEOUT_MS)) return -1;
    /* [RDY] [00] [00 FF] [LEN] [LCS] [D5] [CMD+1 data...] [DCS] [00] */
    size_t want = cap + 9;
    if (want > sizeof(frame)) want = sizeof(frame);
    if (i2c_master_read_from_device(NFC_I2C_PORT, PN532_I2C_ADDR, frame, want,
                                    pdMS_TO_TICKS(PN532_TIMEOUT_MS)) != ESP_OK) {
        return -1;
    }
    if (frame[2] != 0x00 || frame[3] != 0xFF || (uint8_t)(frame[4] + frame[5]) != 0 ||
        frame[6] != 0xD5 || frame[4] < 2) {
        return -1;
    }
    size_t n = (size_t)frame[4] - 1; /* without the TFI */
    if (n > cap || 7 + n + 1 > want) return -1;
    uint8_t dcs = 0xD5;
    for (size_t i = 0; i < n; i++) dcs += frame[7 + i];
    if ((uint8_t)(dcs + frame[7 + n]) != 0) return -1;
    memcpy(resp, frame + 7, n);
    return (int)n;
}

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
    /* Normal mode (no SAM), and one passive activation attempt per poll
     * (MxRtyATR 0xFF, MxRtyPSL 1, MxRtyPassiveActivation 1). */
    static const uint8_t sam[] = {PN532_CMD_SAMCONFIGURATION, 0x01, 0x14, 0x01};
    static const uint8_t retries[] = {PN532_CMD_RFCONFIGURATION, 0x05, 0xFF, 0x01, 0x01};
    uint8_t resp[8];
    if (pn532_transceive(sam, sizeof(sam), resp, sizeof(resp)) < 1 ||
        pn532_transceive(retries, sizeof(retries), resp, sizeof(resp)) < 1) {
        ESP_LOGW(TAG, "PN532: configuration not acknowledged; polls may block for %d ms",
                 PN532_TIMEOUT_MS);
    }
    return 0;
}

static bool esp_nfc_poll(hal_nfc_tag_t *tag)
{
    have_target = false;
    if (!present) return false;
    /* InListPassiveTarget: 1 target, 106 kbps type A. */
    static const uint8_t cmd[] = {PN532_CMD_INLISTPASSIVETARGET, 0x01, 0x00};
    uint8_t resp[32];
    int n = pn532_transceive(cmd, sizeof(cmd), resp, sizeof(resp));
    /* [4B] [NbTg] [Tg] [SENS_RES 2] [SEL_RES] [NFCIDLength] [NFCID1...] */
    if (n < 7 || resp[0] != 0x4B || resp[1] == 0) return false;
    memset(tag, 0, sizeof(*tag));
    uint8_t uid_len = resp[6];
    if (uid_len > sizeof(tag->uid)) uid_len = sizeof(tag->uid);
    if (n >= 7 + uid_len) {
        memcpy(tag->uid, &resp[7], uid_len);
        tag->uid_len = uid_len;
    }
    have_target = true;
    return true;
}

/* True once the TLVs read so far hold a complete NDEF message, or the terminator. */
static bool ndef_complete(const uint8_t *m, size_t len)
{
    size_t i = 0;
    while (i < len) {
        uint8_t t = m[i++];
        if (t == 0x00) continue; /* NULL TLV */
        if (t == 0xFE) return true;
        if (i >= len) return false;
        size_t l = m[i++];
        if (l == 0xFF) {
            if (len - i < 2) return false;
            l = (size_t)m[i] << 8 | m[i + 1];
            i += 2;
        }
        if (t == 0x03) return l <= len - i;
        if (l > len - i) return false;
        i += l;
    }
    return false;
}

static int esp_nfc_read_user_memory(uint8_t *buf, size_t cap)
{
    if (!present || !have_target) return -1;
    size_t got = 0;
    for (unsigned page = NTAG_FIRST_USER_PAGE; got < cap && page <= NTAG_LAST_PAGE; page += 4) {
        /* InDataExchange to target 1: the tag's READ returns 16 bytes (4 pages). */
        uint8_t cmd[] = {PN532_CMD_INDATAEXCHANGE, 0x01, NTAG_CMD_READ, (uint8_t)page};
        uint8_t resp[24];
        int n = pn532_transceive(cmd, sizeof(cmd), resp, sizeof(resp));
        if (n < 18 || resp[0] != 0x41 || resp[1] != 0x00) break; /* past the end, or gone */
        size_t take = cap - got < 16 ? cap - got : 16;
        memcpy(buf + got, resp + 2, take);
        got += take;
        /* Stop as soon as the NDEF message is complete (a join card, a player tag). */
        if (ndef_complete(buf, got)) break;
    }
    return got > 0 ? (int)got : -1;
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
    .deinit = esp_nfc_deinit,
};

#endif /* ESP_PLATFORM */
