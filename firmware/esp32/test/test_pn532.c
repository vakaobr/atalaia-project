/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The PN532 driver (hal/pn532.c) and the USB console's NTAG writer (nfc_card.c) against a fake
 * PN532 on a fake I2C bus, before either meets a real chip. The expected bytes are written out
 * by hand from the PN532 User Manual (NXP UM0701-02): the normal information frame (6.2.1.1:
 * 00, 00 FF, LEN, LCS with LEN + LCS = 0, TFI, data, DCS with TFI + data + DCS = 0, 00), the ACK
 * frame (6.2.1.3: 00 00 FF 00 FF 00), the error frame (6.2.1.5: 00 00 FF 01 FF 7F 81 00), the
 * I2C status byte (6.2.4: bit 0 ready) and the commands (7.2.10 SAMConfiguration, 7.3.1
 * RFConfiguration, 7.3.5 InListPassiveTarget, 7.3.8 InDataExchange, 7.3.9 InCommunicateThru).
 * The fake holds an NTAG213/215/216 laid out as NXP's datasheet says, and fails the test if
 * anything writes outside its user pages.
 */
#include "adoption.h"
#include "check.h"
#include "field_card_vectors.h"
#include "hal/pn532.h"
#include "nfc_card.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

/* ---- the fake PN532 with its NTAG ---- */

enum {
    F_NONE = 0,
    F_WRITE_IO,     /* the I2C write fails */
    F_NEVER_READY,  /* the status byte never says ready */
    F_NACK_FOR_ACK, /* a NACK frame where the ACK should be */
    F_BAD_LCS,      /* the response's LCS is wrong */
    F_BAD_DCS,      /* the response's DCS is wrong */
    F_ERROR_FRAME,  /* the error frame instead of the response */
    F_WRONG_TFI,    /* the response comes back with the host's TFI (D4) */
    F_WRONG_CODE,   /* the response code is not the command's + 1 */
    F_LONG_LEN,     /* LEN says more bytes than the host reads */
    F_BAD_START,    /* 00 FF FF instead of 00 00 FF */
};

typedef struct {
    /* what the host wrote */
    uint8_t frames[600][PN532_FRAME_MAX];
    size_t frame_len[600];
    int nframes;
    int status_reads, other_reads, delays;
    size_t read_lens[8]; /* the lengths of the first non-status reads */
    int busy;            /* status reads that still say "busy" */
    int fault;
    int fault_after; /* commands to answer well before the fault */
    /* the pending answer */
    uint8_t ack_or_resp[80];
    size_t pending_len;
    int pending; /* 0 none, 1 the ACK, 2 the response */
    uint8_t resp[80];
    size_t resp_len;
    /* the tag */
    bool tag_present;
    bool tag_idle; /* after a NAK: only InListPassiveTarget wakes it */
    bool has_version;
    int pages;
    uint8_t last_user_page;
    uint8_t mem[231 * 4];
    uint8_t version[8];
    int writes_left;  /* -1: no limit; 0: the next WRITE fails (the card taken away) */
    int corrupt_page; /* a WRITE to this page stores something else (0: none) */
    int bad_writes;   /* WRITEs outside the user pages: must stay 0 */
    int writes;       /* WRITEs that reached the tag */
    uint8_t uid[7];
    int uid_len_reply; /* NFCIDLength to send (7, or something odd) */
    int cut_uid;       /* send fewer UID bytes than NFCIDLength says */
} fake_t;

static fake_t fk;

/* A PN532-to-host normal information frame, built here independently of pn532.c. */
static size_t mk_frame(uint8_t tfi, const uint8_t *data, size_t n, uint8_t *out)
{
    out[0] = 0x00;
    out[1] = 0x00;
    out[2] = 0xFF;
    out[3] = (uint8_t)(n + 1);
    out[4] = (uint8_t)(0x100 - (n + 1));
    out[5] = tfi;
    unsigned sum = tfi;
    for (size_t i = 0; i < n; i++) {
        out[6 + i] = data[i];
        sum += data[i];
    }
    out[6 + n] = (uint8_t)(0x100 - (sum & 0xFF));
    out[7 + n] = 0x00;
    return n + 8;
}

/* The host's frame, checked against 6.2.1.1 byte by byte. Returns the data after the TFI. */
static size_t host_frame_data(const uint8_t *f, size_t len, const uint8_t **data)
{
    CHECK(len >= 8);
    CHECK(f[0] == 0x00);                 /* preamble */
    CHECK(f[1] == 0x00 && f[2] == 0xFF); /* start code */
    CHECK(f[3] == len - 7);              /* LEN: TFI + data */
    CHECK((uint8_t)(f[3] + f[4]) == 0);  /* LCS */
    CHECK(f[5] == 0xD4);                 /* TFI: host to PN532 */
    unsigned sum = 0;
    for (size_t i = 5; i < len - 1; i++) sum += f[i];
    CHECK((sum & 0xFF) == 0);  /* DCS */
    CHECK(f[len - 1] == 0x00); /* postamble */
    *data = f + 6;
    return len - 8;
}

static void tag_reply(uint8_t code, uint8_t status, const uint8_t *data, size_t n)
{
    fk.resp[0] = code;
    fk.resp[1] = status;
    if (n) memcpy(fk.resp + 2, data, n);
    fk.resp_len = 2 + n;
}

static void fake_command(const uint8_t *c, size_t n)
{
    switch (c[0]) {
    case 0x14: /* SAMConfiguration */
    case 0x32: /* RFConfiguration */
        fk.resp[0] = (uint8_t)(c[0] + 1);
        fk.resp_len = 1;
        break;
    case 0x4A: { /* InListPassiveTarget */
        CHECK(n == 3 && c[1] == 0x01 && c[2] == 0x00);
        fk.resp[0] = 0x4B;
        if (!fk.tag_present) {
            fk.resp[1] = 0x00; /* NbTg 0 */
            fk.resp_len = 2;
            break;
        }
        fk.tag_idle = false;
        /* NbTg 1, Tg 1, SENS_RES 00 44, SEL_RES 00 (an NTAG21x), NFCIDLength, NFCID1 */
        const uint8_t head[] = {0x4B, 0x01, 0x01, 0x00, 0x44, 0x00, (uint8_t)fk.uid_len_reply};
        memcpy(fk.resp, head, sizeof(head));
        size_t u = fk.cut_uid ? 3 : 7;
        memcpy(fk.resp + sizeof(head), fk.uid, u);
        fk.resp_len = sizeof(head) + u;
        break;
    }
    case 0x40: {                       /* InDataExchange */
        CHECK(n >= 3 && c[1] == 0x01); /* target 1 */
        if (!fk.tag_present || fk.tag_idle) {
            tag_reply(0x41, 0x01, NULL, 0); /* time-out: no answer from the tag */
            break;
        }
        if (c[2] == 0x30 && n == 4) { /* READ: 16 bytes, rolling over past the last page */
            if (c[3] >= fk.pages) {
                fk.tag_idle = true;
                tag_reply(0x41, 0x14, NULL, 0); /* NAK */
                break;
            }
            uint8_t out[16];
            for (int i = 0; i < 4; i++)
                memcpy(out + 4 * i, fk.mem + 4 * ((c[3] + i) % fk.pages), 4);
            tag_reply(0x41, 0x00, out, 16);
        } else if (c[2] == 0xA2 && n == 8) { /* WRITE: one page */
            uint8_t p = c[3];
            if (p < 4 || p > fk.last_user_page) fk.bad_writes++;
            if (fk.writes_left == 0) {
                fk.tag_present = false;
                tag_reply(0x41, 0x01, NULL, 0);
                break;
            }
            if (fk.writes_left > 0) fk.writes_left--;
            if (p >= fk.pages || p < 2) {
                fk.tag_idle = true;
                tag_reply(0x41, 0x14, NULL, 0);
                break;
            }
            fk.writes++;
            memcpy(fk.mem + 4 * p, c + 4, 4);
            if (p == fk.corrupt_page) fk.mem[4 * p] ^= 0x55;
            tag_reply(0x41, 0x00, NULL, 0);
        } else {
            CHECK(false); /* nothing else goes to the tag this way */
        }
        break;
    }
    case 0x42:                         /* InCommunicateThru */
        CHECK(n == 2 && c[1] == 0x60); /* GET_VERSION */
        if (!fk.tag_present || fk.tag_idle || !fk.has_version) {
            fk.tag_idle = fk.tag_present;
            tag_reply(0x43, 0x01, NULL, 0);
            break;
        }
        tag_reply(0x43, 0x00, fk.version, 8);
        break;
    default: CHECK(false);
    }
}

static int fake_write(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    if (fk.fault == F_WRITE_IO) return -1;
    CHECK(len <= PN532_FRAME_MAX);
    if (fk.nframes < 600) {
        memcpy(fk.frames[fk.nframes], data, len);
        fk.frame_len[fk.nframes] = len;
    }
    fk.nframes++;
    const uint8_t *cmd;
    size_t n = host_frame_data(data, len, &cmd);
    fake_command(cmd, n);
    bool fault = fk.fault != F_NONE && fk.fault_after-- <= 0;
    /* The ACK (or a NACK in its place). */
    static const uint8_t ack[] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
    static const uint8_t nack[] = {0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
    memcpy(fk.ack_or_resp, fault && fk.fault == F_NACK_FOR_ACK ? nack : ack, 6);
    fk.pending_len = 6;
    fk.pending = 1;
    /* The response, spoilt as asked. */
    uint8_t r[80];
    size_t rl;
    if (fault && fk.fault == F_ERROR_FRAME) {
        static const uint8_t err[] = {0x00, 0x00, 0xFF, 0x01, 0xFF, 0x7F, 0x81, 0x00};
        memcpy(r, err, sizeof(err));
        rl = sizeof(err);
    } else {
        if (fault && fk.fault == F_WRONG_CODE) fk.resp[0] ^= 0x10;
        rl = mk_frame(fault && fk.fault == F_WRONG_TFI ? 0xD4 : 0xD5, fk.resp, fk.resp_len, r);
        if (fault && fk.fault == F_BAD_LCS) r[4] ^= 0x01;
        if (fault && fk.fault == F_BAD_DCS) r[rl - 2] ^= 0x01;
        if (fault && fk.fault == F_LONG_LEN) {
            r[3] = 0x30; /* 47 data bytes said; the host reads fewer */
            r[4] = (uint8_t)(0x100 - 0x30);
        }
        if (fault && fk.fault == F_BAD_START) r[1] = 0xFF;
    }
    memcpy(fk.ack_or_resp + 6, r, rl);
    fk.resp_len = rl; /* now the frame's length, after the ACK's 6 bytes */
    return 0;
}

static int fake_read(void *ctx, uint8_t *data, size_t len, bool quiet)
{
    (void)ctx;
    if (quiet) {
        /* The ready poll: one status byte (6.2.4). */
        CHECK(len == 1);
        fk.status_reads++;
        if (fk.fault == F_NEVER_READY || fk.busy > 0) {
            if (fk.busy > 0) fk.busy--;
            data[0] = 0x00;
        } else {
            data[0] = fk.pending ? 0x01 : 0x00;
        }
        return 0;
    }
    if (fk.other_reads < 8) fk.read_lens[fk.other_reads] = len;
    fk.other_reads++;
    memset(data, 0, len); /* past the frame the PN532 sends zeros */
    data[0] = 0x01;       /* ready */
    if (fk.pending == 1) {
        memcpy(data + 1, fk.ack_or_resp, len - 1 < 6 ? len - 1 : 6);
        fk.pending = 2;
    } else if (fk.pending == 2) {
        size_t n = fk.resp_len < len - 1 ? fk.resp_len : len - 1;
        memcpy(data + 1, fk.ack_or_resp + 6, n);
        fk.pending = 0;
    }
    return 0;
}

static void fake_delay(void *ctx, unsigned ms)
{
    (void)ctx;
    CHECK(ms == 5);
    fk.delays++;
}

static pn532_t chip;

/* An NTAG of the given kind as the datasheet lays it out (8.5), blank but NDEF-formatted. */
static void fake_reset(nfc_t2_kind_t kind)
{
    memset(&fk, 0, sizeof(fk));
    memset(&chip, 0, sizeof(chip));
    chip.io =
        (pn532_io_t){.ctx = &fk, .write = fake_write, .read = fake_read, .delay_ms = fake_delay};
    fk.tag_present = true;
    fk.has_version = true;
    fk.writes_left = -1;
    fk.uid_len_reply = 7;
    const uint8_t uid[7] = {0x04, 0xA1, 0xB2, 0xC3, 0xD4, 0xE5, 0x80};
    memcpy(fk.uid, uid, 7);
    uint8_t size_cc = 0x3E, size_v = 0x11;
    switch (kind) {
    case NFC_T2_NTAG213:
        fk.pages = 45;
        fk.last_user_page = 39;
        size_cc = 0x12;
        size_v = 0x0F;
        break;
    case NFC_T2_NTAG216:
        fk.pages = 231;
        fk.last_user_page = 225;
        size_cc = 0x6D;
        size_v = 0x13;
        break;
    default:
        fk.pages = 135;
        fk.last_user_page = 129;
        break;
    }
    memcpy(fk.mem, uid, 3); /* UID0-2, BCC0 */
    fk.mem[3] = 0x88 ^ 0x04 ^ 0xA1 ^ 0xB2;
    memcpy(fk.mem + 4, uid + 3, 4); /* UID3-6 */
    const uint8_t cc[4] = {0xE1, 0x10, size_cc, 0x00};
    memcpy(fk.mem + 12, cc, 4);
    fk.mem[16] = 0x03; /* an empty NDEF message, then the terminator */
    fk.mem[18] = 0xFE;
    /* The dynamic lock page (no bit set; byte 3 RFUI reads BDh) and the configuration pages,
     * with markers that must survive. */
    const uint8_t dyn[4] = {0x00, 0x00, 0x00, 0xBD};
    memcpy(fk.mem + 4 * (fk.last_user_page + 1), dyn, 4);
    for (int p = fk.last_user_page + 2; p < fk.pages; p++)
        memset(fk.mem + 4 * p, 0xC0 + (p & 0x0F), 4);
    const uint8_t v[8] = {0x00, 0x04, 0x04, 0x02, 0x01, 0x00, size_v, 0x03};
    memcpy(fk.version, v, 8);
}

/* hal_nfc_ops_t over the chip, as hal_esp_nfc.c does over the ESP32's bus. */
static bool op_poll(hal_nfc_tag_t *t)
{
    return pn532_poll(&chip, t);
}
static int op_read_mem(uint8_t *b, size_t cap)
{
    return pn532_read_user_memory(&chip, b, cap);
}
static int op_t2_read(uint8_t page, uint8_t out[16])
{
    return pn532_t2_read(&chip, page, out);
}
static int op_t2_write(uint8_t page, const uint8_t d[4])
{
    return pn532_t2_write(&chip, page, d);
}
static int op_t2_version(uint8_t out[8])
{
    return pn532_t2_get_version(&chip, out);
}
static const hal_nfc_ops_t ops = {.poll = op_poll,
                                  .read_user_memory = op_read_mem,
                                  .t2_read = op_t2_read,
                                  .t2_write = op_t2_write,
                                  .t2_get_version = op_t2_version};

static bool frame_is(int i, const uint8_t *want, size_t n)
{
    return i < fk.nframes && fk.frame_len[i] == n && memcmp(fk.frames[i], want, n) == 0;
}

/* ---- frames, by hand from the manual ---- */

static void test_build_frame(void)
{
    uint8_t f[PN532_FRAME_MAX];
    /* UM0701-02's own example (GetFirmwareVersion): 00 00 FF 02 FE D4 02 2A 00. */
    const uint8_t gfv[] = {0x00, 0x00, 0xFF, 0x02, 0xFE, 0xD4, 0x02, 0x2A, 0x00};
    const uint8_t gfv_cmd[] = {0x02};
    CHECK(pn532_build_frame(gfv_cmd, 1, f, sizeof(f)) == sizeof(gfv));
    CHECK(memcmp(f, gfv, sizeof(gfv)) == 0);
    /* SAMConfiguration normal mode: LEN 5, LCS FB, DCS 0x100 - (D4+14+01+14+01 = 0xFE) = 02. */
    const uint8_t sam[] = {0x00, 0x00, 0xFF, 0x05, 0xFB, 0xD4, 0x14, 0x01, 0x14, 0x01, 0x02, 0x00};
    const uint8_t sam_cmd[] = {0x14, 0x01, 0x14, 0x01};
    CHECK(pn532_build_frame(sam_cmd, 4, f, sizeof(f)) == sizeof(sam) && memcmp(f, sam, 12) == 0);
    /* Room for the frame, or nothing. */
    CHECK(pn532_build_frame(sam_cmd, 4, f, 11) == 0);
    CHECK(pn532_build_frame(sam_cmd, 0, f, sizeof(f)) == 0);
    CHECK(pn532_build_frame(sam_cmd, 4, f, 12) == 12);
}

static void test_ack(void)
{
    const uint8_t ack[] = {0x01, 0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00};
    CHECK(pn532_is_ack(ack, sizeof(ack)));
    const uint8_t nack[] = {0x01, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00};
    CHECK(!pn532_is_ack(nack, sizeof(nack)));
    CHECK(!pn532_is_ack(ack, sizeof(ack) - 1));                           /* a short read */
    const uint8_t shifted[] = {0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0x00}; /* no status byte */
    CHECK(!pn532_is_ack(shifted, sizeof(shifted)));
}

static void test_parse_response(void)
{
    uint8_t resp[16];
    /* SAMConfiguration's answer: D5 15, DCS 0x100 - 0xEA = 16. */
    const uint8_t sam[] = {0x01, 0x00, 0x00, 0xFF, 0x02, 0xFE, 0xD5, 0x15, 0x16, 0x00, 0x00};
    CHECK(pn532_parse_response(sam, sizeof(sam), resp, sizeof(resp)) == 1 && resp[0] == 0x15);
    /* InListPassiveTarget with no tag: D5 4B 00, LEN 3, LCS FD, DCS E0. */
    const uint8_t none[] = {0x01, 0x00, 0x00, 0xFF, 0x03, 0xFD, 0xD5, 0x4B, 0x00, 0xE0, 0x00};
    CHECK(pn532_parse_response(none, sizeof(none), resp, sizeof(resp)) == 2);
    CHECK(resp[0] == 0x4B && resp[1] == 0x00);
    /* The error frame. */
    const uint8_t err[] = {0x01, 0x00, 0x00, 0xFF, 0x01, 0xFF, 0x7F, 0x81, 0x00};
    CHECK(pn532_parse_response(err, sizeof(err), resp, sizeof(resp)) == PN532_ERR_ERROR_FRAME);
    /* A wrong LCS, a wrong DCS. */
    uint8_t bad[sizeof(none)];
    memcpy(bad, none, sizeof(none));
    bad[5] = 0xFC;
    CHECK(pn532_parse_response(bad, sizeof(bad), resp, sizeof(resp)) == PN532_ERR_CHECKSUM);
    memcpy(bad, none, sizeof(none));
    bad[9] = 0xE1;
    CHECK(pn532_parse_response(bad, sizeof(bad), resp, sizeof(resp)) == PN532_ERR_CHECKSUM);
    /* The host's TFI, a wrong start code. */
    memcpy(bad, none, sizeof(none));
    bad[6] = 0xD4;
    bad[9] = (uint8_t)(bad[9] + 1);
    CHECK(pn532_parse_response(bad, sizeof(bad), resp, sizeof(resp)) == PN532_ERR_FRAME);
    memcpy(bad, none, sizeof(none));
    bad[2] = 0xFF;
    CHECK(pn532_parse_response(bad, sizeof(bad), resp, sizeof(resp)) == PN532_ERR_FRAME);
    /* A short read: the frame does not fit in what was read. */
    CHECK(pn532_parse_response(none, 9, resp, sizeof(resp)) == PN532_ERR_LENGTH);
    CHECK(pn532_parse_response(none, 4, resp, sizeof(resp)) == PN532_ERR_LENGTH);
    /* More data than the caller's buffer. */
    CHECK(pn532_parse_response(none, sizeof(none), resp, 1) == PN532_ERR_LENGTH);
    /* A NACK or an extended frame (LEN FF, LCS FF) is not a normal information frame. */
    const uint8_t nack[] = {0x01, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x00};
    CHECK(pn532_parse_response(nack, sizeof(nack), resp, sizeof(resp)) < 0);
    const uint8_t ext[] = {0x01, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00,
                           0x02, 0xFE, 0xD5, 0x15, 0x16, 0x00};
    CHECK(pn532_parse_response(ext, sizeof(ext), resp, sizeof(resp)) < 0);
    /* An ACK is not a response (its LEN 00 + LCS FF is not 0: a frame of its own, 6.2.1.3). */
    const uint8_t ack[] = {0x01, 0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0x00, 0x00};
    CHECK(pn532_parse_response(ack, sizeof(ack), resp, sizeof(resp)) == PN532_ERR_CHECKSUM);
}

/* ---- the exchange with the fake chip ---- */

static void test_configure(void)
{
    fake_reset(NFC_T2_NTAG215);
    CHECK(pn532_configure(&chip) == 0);
    const uint8_t sam[] = {0x00, 0x00, 0xFF, 0x05, 0xFB, 0xD4, 0x14, 0x01, 0x14, 0x01, 0x02, 0x00};
    /* RFConfiguration MaxRetries FF 01 01: LEN 6, LCS FA, DCS 0x100 - 0x0C = F4. */
    const uint8_t rf[] = {0x00, 0x00, 0xFF, 0x06, 0xFA, 0xD4, 0x32,
                          0x05, 0xFF, 0x01, 0x01, 0xF4, 0x00};
    CHECK(fk.nframes == 2 && frame_is(0, sam, sizeof(sam)) && frame_is(1, rf, sizeof(rf)));
    /* Each command: the status byte, the ACK (status + 6 bytes), the status, the response. */
    CHECK(fk.status_reads == 4 && fk.other_reads == 4);
    CHECK(fk.read_lens[0] == 7 && fk.read_lens[1] == 8 + 9); /* resp[8] + 9 */
    CHECK(fk.delays == 0);
}

static void test_busy_and_timeout(void)
{
    fake_reset(NFC_T2_NTAG215);
    fk.busy = 3; /* busy for three status reads, 5 ms apart */
    CHECK(pn532_configure(&chip) == 0);
    CHECK(fk.delays == 3);
    fake_reset(NFC_T2_NTAG215);
    fk.fault = F_NEVER_READY;
    CHECK(pn532_configure(&chip) == PN532_ERR_TIMEOUT);
    CHECK(fk.status_reads == PN532_TIMEOUT_MS / 5 + 1 && fk.other_reads == 0);
    fake_reset(NFC_T2_NTAG215);
    fk.fault = F_WRITE_IO;
    CHECK(pn532_configure(&chip) == PN532_ERR_IO);
}

static void test_faults(void)
{
    static const struct {
        int fault;
        int err;
    } cases[] = {
        {F_NACK_FOR_ACK, PN532_ERR_NO_ACK}, {F_BAD_LCS, PN532_ERR_CHECKSUM},
        {F_BAD_DCS, PN532_ERR_CHECKSUM},    {F_ERROR_FRAME, PN532_ERR_ERROR_FRAME},
        {F_WRONG_TFI, PN532_ERR_FRAME},     {F_WRONG_CODE, PN532_ERR_CODE},
        {F_LONG_LEN, PN532_ERR_LENGTH},     {F_BAD_START, PN532_ERR_FRAME},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        fake_reset(NFC_T2_NTAG215);
        fk.fault = cases[i].fault;
        CHECK(pn532_configure(&chip) == cases[i].err);
        /* A poll through the same fault finds no tag. */
        fake_reset(NFC_T2_NTAG215);
        fk.fault = cases[i].fault;
        hal_nfc_tag_t t;
        CHECK(!pn532_poll(&chip, &t) && !chip.have_target);
    }
}

static void test_poll(void)
{
    fake_reset(NFC_T2_NTAG215);
    hal_nfc_tag_t t;
    CHECK(pn532_poll(&chip, &t) && chip.have_target);
    /* InListPassiveTarget 1 target 106 kbps type A: 00 00 FF 04 FC D4 4A 01 00 E1 00. */
    const uint8_t ilpt[] = {0x00, 0x00, 0xFF, 0x04, 0xFC, 0xD4, 0x4A, 0x01, 0x00, 0xE1, 0x00};
    CHECK(frame_is(0, ilpt, sizeof(ilpt)));
    CHECK(t.uid_len == 7 && memcmp(t.uid, fk.uid, 7) == 0);
    /* No tag in the field. */
    fake_reset(NFC_T2_NTAG215);
    fk.tag_present = false;
    CHECK(!pn532_poll(&chip, &t) && !chip.have_target);
    /* A UID cut short (NFCIDLength 7, 3 bytes sent): not a tag to trust. */
    fake_reset(NFC_T2_NTAG215);
    fk.cut_uid = 1;
    CHECK(!pn532_poll(&chip, &t));
    /* A 4-byte UID (NFCIDLength 4). */
    fake_reset(NFC_T2_NTAG215);
    fk.uid_len_reply = 4;
    CHECK(pn532_poll(&chip, &t) && t.uid_len == 4 && memcmp(t.uid, fk.uid, 4) == 0);
}

static void test_tag_frames(void)
{
    fake_reset(NFC_T2_NTAG215);
    hal_nfc_tag_t t;
    uint8_t b[16];
    /* Before a poll found a tag, nothing goes to the chip. */
    CHECK(pn532_t2_read(&chip, 4, b) == PN532_ERR_STATUS && fk.nframes == 0);
    CHECK(pn532_poll(&chip, &t));
    /* InDataExchange Tg 1 READ page 4: LEN 5, LCS FB, DCS 0x100 - 0x49 = B7. */
    CHECK(pn532_t2_read(&chip, 4, b) == 0);
    const uint8_t rd[] = {0x00, 0x00, 0xFF, 0x05, 0xFB, 0xD4, 0x40, 0x01, 0x30, 0x04, 0xB7, 0x00};
    CHECK(frame_is(1, rd, sizeof(rd)));
    CHECK(memcmp(b, fk.mem + 16, 16) == 0);
    /* WRITE page 5 DE AD BE EF: LEN 9, LCS F7, DCS 0x100 - 0xF4 = 0C. */
    const uint8_t d[4] = {0xDE, 0xAD, 0xBE, 0xEF};
    CHECK(pn532_t2_write(&chip, 5, d) == 0);
    const uint8_t wr[] = {0x00, 0x00, 0xFF, 0x09, 0xF7, 0xD4, 0x40, 0x01,
                          0xA2, 0x05, 0xDE, 0xAD, 0xBE, 0xEF, 0x0C, 0x00};
    CHECK(frame_is(2, wr, sizeof(wr)));
    CHECK(memcmp(fk.mem + 20, d, 4) == 0);
    /* InCommunicateThru GET_VERSION: LEN 3, LCS FD, DCS 0x100 - 0x76 = 8A. */
    uint8_t v[8];
    CHECK(pn532_t2_get_version(&chip, v) == 0 && memcmp(v, fk.version, 8) == 0);
    const uint8_t gv[] = {0x00, 0x00, 0xFF, 0x03, 0xFD, 0xD4, 0x42, 0x60, 0x8A, 0x00};
    CHECK(frame_is(3, gv, sizeof(gv)));
    /* A READ past the end: the tag's NAK, status not 00. */
    CHECK(pn532_t2_read(&chip, 200, b) == PN532_ERR_STATUS);
    /* The tag goes away. */
    fk.tag_present = false;
    CHECK(pn532_t2_write(&chip, 6, d) == PN532_ERR_STATUS);
}

static void test_read_user_memory(void)
{
    const field_card_vector_t *v = &field_card_vectors[0];
    fake_reset(NFC_T2_NTAG215);
    memcpy(fk.mem + 16, v->ndef_tag, v->ndef_tag_len);
    hal_nfc_tag_t t;
    uint8_t buf[888];
    CHECK(pn532_read_user_memory(&chip, buf, sizeof(buf)) == -1); /* no poll yet */
    CHECK(pn532_poll(&chip, &t));
    int before = fk.nframes;
    int n = pn532_read_user_memory(&chip, buf, sizeof(buf));
    /* 93 bytes: six READs of 16, then the message is whole. */
    CHECK(n == 96 && memcmp(buf, v->ndef_tag, v->ndef_tag_len) == 0);
    CHECK(fk.nframes - before == 6);
    const uint8_t *card = NULL;
    CHECK(adoption_card_from_ndef_tag(buf, (size_t)n, &card) > 0);
    CHECK(t2_ndef_complete(v->ndef_tag, v->ndef_tag_len));
    CHECK(!t2_ndef_complete(v->ndef_tag, 40));
    /* cap stops it. */
    CHECK(pn532_poll(&chip, &t));
    CHECK(pn532_read_user_memory(&chip, buf, 20) == 20);
}

/* ---- the NTAG writer ---- */

static void test_kinds(void)
{
    const uint8_t cc213[4] = {0xE1, 0x10, 0x12, 0x00}, cc215[4] = {0xE1, 0x10, 0x3E, 0x00};
    const uint8_t cc216[4] = {0xE1, 0x10, 0x6D, 0x00}, ccbad[4] = {0xE1, 0x10, 0x06, 0x00};
    const uint8_t ccmagic[4] = {0x00, 0x10, 0x3E, 0x00};
    CHECK(nfc_card_kind_from_cc(cc213) == NFC_T2_NTAG213);
    CHECK(nfc_card_kind_from_cc(cc215) == NFC_T2_NTAG215);
    CHECK(nfc_card_kind_from_cc(cc216) == NFC_T2_NTAG216);
    CHECK(nfc_card_kind_from_cc(ccbad) == NFC_T2_UNKNOWN);   /* a MIFARE Ultralight's 48 bytes */
    CHECK(nfc_card_kind_from_cc(ccmagic) == NFC_T2_UNKNOWN); /* not NDEF-formatted */
    const uint8_t v213[8] = {0x00, 0x04, 0x04, 0x02, 0x01, 0x00, 0x0F, 0x03};
    const uint8_t v216[8] = {0x00, 0x04, 0x04, 0x02, 0x01, 0x00, 0x13, 0x03};
    const uint8_t vul[8] = {0x00, 0x04, 0x03, 0x01, 0x01, 0x00, 0x0B, 0x03}; /* Ultralight EV1 */
    CHECK(nfc_card_kind_from_version(v213) == NFC_T2_NTAG213);
    CHECK(nfc_card_kind_from_version(v216) == NFC_T2_NTAG216);
    CHECK(nfc_card_kind_from_version(vul) == NFC_T2_UNKNOWN);
    CHECK(nfc_card_last_user_page(NFC_T2_NTAG213) == 39);
    CHECK(nfc_card_last_user_page(NFC_T2_NTAG215) == 129);
    CHECK(nfc_card_last_user_page(NFC_T2_NTAG216) == 225);
    CHECK(nfc_card_last_user_page(NFC_T2_UNKNOWN) == 0);
    CHECK(strcmp(nfc_t2_kind_name(NFC_T2_NTAG216), "NTAG216") == 0);
    CHECK(strcmp(nfc_card_result_code(NFC_CARD_TOO_BIG), "too_big") == 0);
}

/* The bytes outside the user pages are as the fake made them. */
static bool outside_untouched(const uint8_t before[231 * 4])
{
    return memcmp(fk.mem, before, 16) == 0 &&
           memcmp(fk.mem + 4 * (fk.last_user_page + 1), before + 4 * (fk.last_user_page + 1),
                  (size_t)(fk.pages - fk.last_user_page - 1) * 4) == 0;
}

static void test_write_field_cards(void)
{
    static const nfc_t2_kind_t kinds[] = {NFC_T2_NTAG213, NFC_T2_NTAG215, NFC_T2_NTAG216};
    for (size_t k = 0; k < 3; k++) {
        for (size_t i = 0; i < FIELD_CARD_VECTOR_COUNT; i++) {
            const field_card_vector_t *v = &field_card_vectors[i];
            fake_reset(kinds[k]);
            uint8_t before[231 * 4];
            memcpy(before, fk.mem, sizeof(before));
            hal_nfc_tag_t t;
            CHECK(op_poll(&t));
            nfc_card_info_t info;
            CHECK(nfc_card_write(&ops, v->ndef_tag, v->ndef_tag_len, &info) == NFC_CARD_OK);
            CHECK(info.kind == kinds[k] && info.cc_known && info.version_known);
            CHECK(info.pages_written == (v->ndef_tag_len + 3) / 4);
            CHECK(fk.writes == (int)info.pages_written && fk.bad_writes == 0);
            CHECK(memcmp(fk.mem + 16, v->ndef_tag, v->ndef_tag_len) == 0);
            CHECK(outside_untouched(before));
            /* The box reads it back as a field card (to the message's end; the terminator TLV
             * may be left unread). */
            uint8_t buf[888];
            size_t got = 0;
            CHECK(nfc_card_read(&ops, buf, sizeof(buf), false, &got, &info) == NFC_CARD_OK);
            const uint8_t *card = NULL;
            CHECK(got >= v->ndef_tag_len - 1 && adoption_card_from_ndef_tag(buf, got, &card) > 0);
        }
    }
}

static void test_write_sizes(void)
{
    static uint8_t data[888];
    for (size_t i = 0; i < sizeof(data); i++) data[i] = (uint8_t)(i * 7 + 1);
    static const struct {
        nfc_t2_kind_t kind;
        size_t fits;
    } sizes[] = {{NFC_T2_NTAG213, 144}, {NFC_T2_NTAG215, 504}, {NFC_T2_NTAG216, 888}};
    for (size_t k = 0; k < 3; k++) {
        /* The whole user memory: the last user page written, nothing after it. */
        fake_reset(sizes[k].kind);
        uint8_t before[231 * 4];
        memcpy(before, fk.mem, sizeof(before));
        hal_nfc_tag_t t;
        CHECK(op_poll(&t));
        nfc_card_info_t info;
        CHECK(nfc_card_write(&ops, data, sizes[k].fits, &info) == NFC_CARD_OK);
        CHECK(info.pages_written == sizes[k].fits / 4 && fk.bad_writes == 0);
        CHECK(memcmp(fk.mem + 16, data, sizes[k].fits) == 0 && outside_untouched(before));
        /* One byte more would reach the dynamic lock page: refused before any WRITE. */
        fake_reset(sizes[k].kind);
        CHECK(op_poll(&t));
        CHECK(nfc_card_write(&ops, data, sizes[k].fits + (k < 2 ? 1 : 0), &info) ==
              (k < 2 ? NFC_CARD_TOO_BIG : NFC_CARD_OK));
        if (k < 2) CHECK(fk.writes == 0 && info.kind == sizes[k].kind);
    }
    /* A length not a multiple of 4: the last page padded with zeros. */
    fake_reset(NFC_T2_NTAG213);
    hal_nfc_tag_t t;
    nfc_card_info_t info;
    CHECK(op_poll(&t));
    memset(fk.mem + 16, 0xEE, 8);
    CHECK(nfc_card_write(&ops, data, 5, &info) == NFC_CARD_OK && info.pages_written == 2);
    CHECK(memcmp(fk.mem + 16, data, 5) == 0 && fk.mem[21] == 0 && fk.mem[23] == 0);
    /* Nothing, or more than any NTAG. */
    CHECK(nfc_card_write(&ops, data, 0, &info) == NFC_CARD_EMPTY);
    CHECK(nfc_card_write(&ops, data, 889, &info) == NFC_CARD_TOO_BIG);
}

static void test_write_size_sources(void)
{
    static uint8_t data[300];
    memset(data, 0x5A, sizeof(data));
    hal_nfc_tag_t t;
    nfc_card_info_t info;
    /* The CC says NTAG216 but GET_VERSION says NTAG213: the smaller wins. */
    fake_reset(NFC_T2_NTAG213);
    fk.mem[14] = 0x6D;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 200, &info) == NFC_CARD_TOO_BIG && fk.writes == 0);
    CHECK(info.kind == NFC_T2_NTAG213);
    /* No GET_VERSION (its NAK leaves the tag idle): polled again, the CC decides. */
    fake_reset(NFC_T2_NTAG215);
    fk.has_version = false;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 300, &info) == NFC_CARD_OK);
    CHECK(info.kind == NFC_T2_NTAG215 && info.cc_known && !info.version_known);
    /* A CC naming no size, GET_VERSION does. */
    fake_reset(NFC_T2_NTAG216);
    fk.mem[14] = 0x00;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 300, &info) == NFC_CARD_OK && info.kind == NFC_T2_NTAG216);
    /* Neither: refused. */
    fake_reset(NFC_T2_NTAG216);
    fk.mem[14] = 0x06;
    fk.has_version = false;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 16, &info) == NFC_CARD_UNKNOWN_TAG && fk.writes == 0);
}

static void test_write_refused_and_failed(void)
{
    static uint8_t data[200];
    for (size_t i = 0; i < sizeof(data); i++) data[i] = (uint8_t)i;
    hal_nfc_tag_t t;
    nfc_card_info_t info;
    /* No reader, no card. */
    const hal_nfc_ops_t none = {.init = NULL};
    CHECK(nfc_card_write(&none, data, 16, &info) == NFC_CARD_NO_READER);
    fake_reset(NFC_T2_NTAG215);
    CHECK(nfc_card_write(&ops, data, 16, &info) == NFC_CARD_NO_TAG); /* never polled */
    /* The CC says read-only. */
    fake_reset(NFC_T2_NTAG215);
    fk.mem[15] = 0x0F;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 16, &info) == NFC_CARD_LOCKED && fk.writes == 0);
    /* A static lock bit (L6: lock byte 0 bit 6) covers a page to write. */
    fake_reset(NFC_T2_NTAG215);
    fk.mem[10] = 0x40;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 16, &info) == NFC_CARD_LOCKED && info.failed_page == 6);
    CHECK(fk.writes == 0);
    /* ... but not one past what is written (L8 with 16 bytes: pages 4 to 7). */
    fake_reset(NFC_T2_NTAG215);
    fk.mem[11] = 0x01;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 16, &info) == NFC_CARD_OK);
    /* A dynamic lock bit: NTAG215 bit 0 locks pages 16-31; NTAG213 bit 1 pages 18-19. */
    fake_reset(NFC_T2_NTAG215);
    fk.mem[4 * 130] = 0x01;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 200, &info) == NFC_CARD_LOCKED && info.failed_page == 16);
    fake_reset(NFC_T2_NTAG213);
    fk.mem[4 * 40] = 0x02;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 56, &info) == NFC_CARD_OK); /* pages 4 to 17 */
    fake_reset(NFC_T2_NTAG213);
    fk.mem[4 * 40] = 0x02;
    CHECK(op_poll(&t));
    CHECK(nfc_card_write(&ops, data, 60, &info) == NFC_CARD_LOCKED && info.failed_page == 18);
    CHECK(fk.writes == 0);
    /* The card taken away after 5 pages. */
    fake_reset(NFC_T2_NTAG215);
    CHECK(op_poll(&t));
    fk.writes_left = 5;
    CHECK(nfc_card_write(&ops, data, 100, &info) == NFC_CARD_WRITE_FAILED);
    CHECK(info.pages_written == 5 && info.failed_page == 9);
    /* A page that reads back different. */
    fake_reset(NFC_T2_NTAG215);
    CHECK(op_poll(&t));
    fk.corrupt_page = 10;
    CHECK(nfc_card_write(&ops, data, 100, &info) == NFC_CARD_VERIFY_FAILED);
    CHECK(info.failed_page == 10 && info.pages_written == 25);
}

static void test_read_dump(void)
{
    const field_card_vector_t *v = &field_card_vectors[3];
    fake_reset(NFC_T2_NTAG213);
    memcpy(fk.mem + 16, v->ndef_tag, v->ndef_tag_len);
    hal_nfc_tag_t t;
    CHECK(op_poll(&t));
    uint8_t buf[888];
    size_t got = 0;
    nfc_card_info_t info;
    CHECK(nfc_card_read(&ops, buf, sizeof(buf), false, &got, &info) == NFC_CARD_OK);
    CHECK(got == 128 && memcmp(buf, v->ndef_tag, v->ndef_tag_len) == 0); /* to the message's end */
    CHECK(nfc_card_read(&ops, buf, sizeof(buf), true, &got, &info) == NFC_CARD_OK);
    CHECK(got == 144 && info.kind == NFC_T2_NTAG213); /* the whole user memory, no more */
    fk.tag_present = false;
    CHECK(nfc_card_read(&ops, buf, sizeof(buf), true, &got, &info) == NFC_CARD_NO_TAG);
}

static void test_hex(void)
{
    uint8_t out[4];
    size_t len = 0;
    CHECK(nfc_card_hex_append("03aB", out, &len, sizeof(out)) && len == 2);
    CHECK(out[0] == 0x03 && out[1] == 0xAB);
    CHECK(nfc_card_hex_append("FE00", out, &len, sizeof(out)) && len == 4 && out[2] == 0xFE);
    CHECK(!nfc_card_hex_append("00", out, &len, sizeof(out)) && len == 4); /* full */
    len = 0;
    CHECK(!nfc_card_hex_append("0", out, &len, sizeof(out)) && len == 0);
    CHECK(!nfc_card_hex_append("0g", out, &len, sizeof(out)) && len == 0);
    CHECK(!nfc_card_hex_append("03 5a", out, &len, sizeof(out)) && len == 0);
    CHECK(nfc_card_hex_append("", out, &len, sizeof(out)) && len == 0);
}

void run_pn532_tests(void)
{
    test_build_frame();
    test_ack();
    test_parse_response();
    test_configure();
    test_busy_and_timeout();
    test_faults();
    test_poll();
    test_tag_frames();
    test_read_user_memory();
    test_kinds();
    test_write_field_cards();
    test_write_sizes();
    test_write_size_sources();
    test_write_refused_and_failed();
    test_read_dump();
    test_hex();
}
