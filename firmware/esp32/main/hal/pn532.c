/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The PN532's frames and commands (pn532.h), from the PN532 User Manual (UM0701-02): every
 * command is answered first by an ACK frame and then, when the chip is ready again, by the
 * response frame; every I2C read starts with a status byte whose bit 0 says "ready".
 */
#include "pn532.h"

#include <string.h>

/* ---- frames (UM0701-02 6.2.1) ---- */

size_t pn532_build_frame(const uint8_t *cmd, size_t len, uint8_t *out, size_t cap)
{
    /* [00] [00 FF] [LEN] [LCS] [D4 CMD ...] [DCS] [00] */
    if (len == 0 || len > 254 || len + 8 > cap) return 0;
    size_t data_len = len + 1; /* TFI + command bytes */
    out[0] = 0x00;
    out[1] = 0x00;
    out[2] = 0xFF;
    out[3] = (uint8_t)data_len;
    out[4] = (uint8_t)(~data_len + 1);
    out[5] = PN532_TFI_HOST;
    uint8_t dcs = PN532_TFI_HOST;
    for (size_t i = 0; i < len; i++) {
        out[6 + i] = cmd[i];
        dcs += cmd[i];
    }
    out[6 + len] = (uint8_t)(~dcs + 1);
    out[7 + len] = 0x00;
    return 8 + len;
}

bool pn532_is_ack(const uint8_t *rd, size_t len)
{
    static const uint8_t ack[] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
    return len >= 1 + sizeof(ack) && memcmp(rd + 1, ack, sizeof(ack)) == 0;
}

int pn532_parse_response(const uint8_t *rd, size_t len, uint8_t *resp, size_t cap)
{
    /* [RDY] [00] [00 FF] [LEN] [LCS] [D5] [CMD+1 data...] [DCS] [00] */
    if (len < 8) return PN532_ERR_LENGTH;
    if (rd[2] != 0x00 || rd[3] != 0xFF) return PN532_ERR_FRAME;
    if ((uint8_t)(rd[4] + rd[5]) != 0) return PN532_ERR_CHECKSUM;
    /* The error frame 00 00 FF 01 FF 7F 81 00 (6.2.1.5): a syntax error in the command. */
    if (rd[4] == 1 && rd[6] == PN532_TFI_ERROR) return PN532_ERR_ERROR_FRAME;
    if (rd[6] != PN532_TFI_PN532 || rd[4] < 2) return PN532_ERR_FRAME;
    size_t n = (size_t)rd[4] - 1; /* without the TFI */
    if (n > cap || 7 + n + 1 > len) return PN532_ERR_LENGTH;
    uint8_t dcs = PN532_TFI_PN532;
    for (size_t i = 0; i < n; i++) dcs += rd[7 + i];
    if ((uint8_t)(dcs + rd[7 + n]) != 0) return PN532_ERR_CHECKSUM;
    memcpy(resp, rd + 7, n);
    return (int)n;
}

/* ---- the exchange (UM0701-02 6.2.2, 6.2.4) ---- */

static bool wait_ready(pn532_t *p, int timeout_ms)
{
    for (int waited = 0; waited <= timeout_ms; waited += 5) {
        uint8_t status = 0;
        if (p->io.read(p->io.ctx, &status, 1, true) == 0 && (status & PN532_READY_BIT)) {
            return true;
        }
        p->io.delay_ms(p->io.ctx, 5);
    }
    return false;
}

int pn532_transceive(pn532_t *p, const uint8_t *cmd, size_t len, uint8_t *resp, size_t cap)
{
    uint8_t frame[PN532_FRAME_MAX];
    size_t flen = pn532_build_frame(cmd, len, frame, sizeof(frame));
    if (flen == 0) return PN532_ERR_ARG;
    if (p->io.write(p->io.ctx, frame, flen) != 0) return PN532_ERR_IO;
    if (!wait_ready(p, PN532_TIMEOUT_MS)) return PN532_ERR_TIMEOUT;
    if (p->io.read(p->io.ctx, frame, 7, false) != 0) return PN532_ERR_IO;
    if (!pn532_is_ack(frame, 7)) return PN532_ERR_NO_ACK;
    if (!wait_ready(p, PN532_TIMEOUT_MS)) return PN532_ERR_TIMEOUT;
    size_t want = cap + 9; /* RDY, 00 00 FF LEN LCS D5, the data, DCS 00 */
    if (want > sizeof(frame)) want = sizeof(frame);
    if (p->io.read(p->io.ctx, frame, want, false) != 0) return PN532_ERR_IO;
    int n = pn532_parse_response(frame, want, resp, cap);
    if (n < 0) return n;
    if (n < 1 || resp[0] != (uint8_t)(cmd[0] + 1)) return PN532_ERR_CODE;
    return n;
}

/* ---- commands ---- */

int pn532_configure(pn532_t *p)
{
    /* SAMConfiguration (7.2.10): Mode 1 normal (no SAM), Timeout 0x14 (20 x 50 ms, only used in
     * virtual card mode), IRQ 1. */
    static const uint8_t sam[] = {PN532_CMD_SAMCONFIGURATION, 0x01, 0x14, 0x01};
    /* RFConfiguration (7.3.1) CfgItem 5 MaxRetries: MxRtyATR 0xFF (the default), MxRtyPSL 1 (the
     * default), MxRtyPassiveActivation 1: one retry, so two activation attempts per
     * InListPassiveTarget instead of the default 0xFF (forever), and a poll with no tag in the
     * field returns at once. (0x00 would be a single attempt.) */
    static const uint8_t retries[] = {PN532_CMD_RFCONFIGURATION, 0x05, 0xFF, 0x01, 0x01};
    uint8_t resp[8];
    int r = pn532_transceive(p, sam, sizeof(sam), resp, sizeof(resp));
    if (r < 0) return r;
    r = pn532_transceive(p, retries, sizeof(retries), resp, sizeof(resp));
    return r < 0 ? r : 0;
}

bool pn532_poll(pn532_t *p, hal_nfc_tag_t *tag)
{
    p->have_target = false;
    /* InListPassiveTarget (7.3.5): MaxTg 1, BrTy 0x00 (106 kbps type A). */
    static const uint8_t cmd[] = {PN532_CMD_INLISTPASSIVETARGET, 0x01, 0x00};
    uint8_t resp[32];
    int n = pn532_transceive(p, cmd, sizeof(cmd), resp, sizeof(resp));
    /* [4B] [NbTg] [Tg] [SENS_RES 2] [SEL_RES] [NFCIDLength] [NFCID1...] */
    if (n < 7 || resp[1] == 0) return false;
    uint8_t uid_len = resp[6];
    if (uid_len == 0 || n < 7 + uid_len) return false; /* cut short: not a tag to trust */
    memset(tag, 0, sizeof(*tag));
    if (uid_len > sizeof(tag->uid)) uid_len = sizeof(tag->uid);
    memcpy(tag->uid, &resp[7], uid_len);
    tag->uid_len = uid_len;
    p->have_target = true;
    return true;
}

/* InDataExchange (7.3.8) to target 1: [40] [Tg 01] [tag command...] -> [41] [Status] [data...]. */
static int data_exchange(pn532_t *p, const uint8_t *tcmd, size_t tlen, uint8_t *resp, size_t cap)
{
    uint8_t cmd[16];
    if (tlen + 2 > sizeof(cmd)) return PN532_ERR_ARG;
    cmd[0] = PN532_CMD_INDATAEXCHANGE;
    cmd[1] = 0x01;
    memcpy(cmd + 2, tcmd, tlen);
    int n = pn532_transceive(p, cmd, tlen + 2, resp, cap);
    if (n < 0) return n;
    if (n < 2 || resp[1] != 0x00) return PN532_ERR_STATUS; /* the tag's NAK, a timeout, gone */
    return n;
}

int pn532_t2_read(pn532_t *p, uint8_t page, uint8_t out[16])
{
    if (!p->have_target) return PN532_ERR_STATUS;
    const uint8_t tcmd[] = {T2_CMD_READ, page};
    uint8_t resp[24];
    int n = data_exchange(p, tcmd, sizeof(tcmd), resp, sizeof(resp));
    if (n < 0) return n;
    if (n < 18) return PN532_ERR_LENGTH;
    memcpy(out, resp + 2, 16);
    return 0;
}

int pn532_t2_write(pn532_t *p, uint8_t page, const uint8_t data[4])
{
    if (!p->have_target) return PN532_ERR_STATUS;
    /* The tag's 4-bit ACK (0xA) is taken by the PN532: success is Status 0x00. */
    const uint8_t tcmd[] = {T2_CMD_WRITE, page, data[0], data[1], data[2], data[3]};
    uint8_t resp[8];
    int n = data_exchange(p, tcmd, sizeof(tcmd), resp, sizeof(resp));
    return n < 0 ? n : 0;
}

int pn532_t2_get_version(pn532_t *p, uint8_t out[8])
{
    if (!p->have_target) return PN532_ERR_STATUS;
    /* InCommunicateThru (7.3.9): the bytes go to the tag as they are, the PN532 adding the CRC:
     * [42] [60] -> [43] [Status] [8 bytes]. */
    static const uint8_t cmd[] = {PN532_CMD_INCOMMUNICATETHRU, T2_CMD_GET_VERSION};
    uint8_t resp[16];
    int n = pn532_transceive(p, cmd, sizeof(cmd), resp, sizeof(resp));
    if (n < 0) return n;
    if (n < 2 || resp[1] != 0x00) return PN532_ERR_STATUS;
    if (n < 10) return PN532_ERR_LENGTH;
    memcpy(out, resp + 2, 8);
    return 0;
}

bool t2_ndef_complete(const uint8_t *m, size_t len)
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

#define T2_FIRST_USER_PAGE 4
#define T2_LAST_PAGE       231 /* past NTAG216's last page (230): the READ fails there */

int pn532_read_user_memory(pn532_t *p, uint8_t *buf, size_t cap)
{
    if (!p->have_target) return -1;
    size_t got = 0;
    for (unsigned page = T2_FIRST_USER_PAGE; got < cap && page <= T2_LAST_PAGE; page += 4) {
        uint8_t block[16];
        if (pn532_t2_read(p, (uint8_t)page, block) != 0) break; /* past the end, or gone */
        size_t take = cap - got < 16 ? cap - got : 16;
        memcpy(buf + got, block, take);
        got += take;
        /* Stop as soon as the NDEF message is complete (a join card, a player tag). */
        if (t2_ndef_complete(buf, got)) break;
    }
    return got > 0 ? (int)got : -1;
}
