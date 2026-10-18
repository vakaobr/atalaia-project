/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB modem framing: CRC known answer, round trips at the size limits,
 * and resynchronisation after junk, bad CRCs and impossible lengths.
 */
#include <string.h>

#include "check.h"
#include "modem/modem_framing.h"

#define MAX_FRAMES 16

typedef struct {
    int count;
    uint8_t type[MAX_FRAMES];
    size_t len[MAX_FRAMES];
    uint8_t payload[MAX_FRAMES][MODEM_FRAME_PAYLOAD_MAX];
} sink_t;

static void sink_cb(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    sink_t *s = (sink_t *)ctx;
    if (s->count >= MAX_FRAMES) return;
    s->type[s->count] = type;
    s->len[s->count] = len;
    memcpy(s->payload[s->count], payload, len);
    s->count++;
}

static void test_crc_known_answer(void)
{
    /* CRC-16/CCITT-FALSE check value from the CRC catalogue. */
    const char *check = "123456789";
    CHECK(modem_crc16((const uint8_t *)check, strlen(check)) == 0x29B1);
    CHECK(modem_crc16(NULL, 0) == 0xFFFF);
}

static void test_encode_layout(void)
{
    uint8_t payload[3] = {0x01, 0x02, 0x03};
    uint8_t out[16];
    size_t n = modem_frame_encode(MODEM_FRAME_CMD, payload, 3, out, sizeof(out));
    CHECK(n == 9);
    CHECK(out[0] == MODEM_SYNC);
    CHECK(out[1] == MODEM_FRAME_CMD);
    CHECK(out[2] == 0x00 && out[3] == 0x03);
    CHECK(memcmp(out + 4, payload, 3) == 0);
    uint16_t crc = modem_crc16(out + 1, 6);
    CHECK(out[7] == (crc >> 8) && out[8] == (crc & 0xFF));

    /* Too long, or no room. */
    uint8_t big[MODEM_FRAME_PAYLOAD_MAX + 1] = {0};
    uint8_t buf[MODEM_FRAME_MAX + 8];
    CHECK(modem_frame_encode(MODEM_FRAME_TX, big, sizeof(big), buf, sizeof(buf)) == 0);
    CHECK(modem_frame_encode(MODEM_FRAME_TX, payload, 3, out, 8) == 0);
}

static void test_round_trip_sizes(void)
{
    static const size_t sizes[] = {0, 1, 200, MODEM_FRAME_PAYLOAD_MAX};
    for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
        uint8_t payload[MODEM_FRAME_PAYLOAD_MAX];
        for (size_t j = 0; j < sizes[i]; j++) payload[j] = (uint8_t)(j * 7 + i);
        uint8_t frame[MODEM_FRAME_MAX];
        size_t n = modem_frame_encode(MODEM_FRAME_RX, payload, sizes[i], frame, sizeof(frame));
        CHECK(n == sizes[i] + MODEM_FRAME_OVERHEAD);

        modem_decoder_t d;
        sink_t s = {0};
        modem_decoder_init(&d);
        modem_decoder_feed(&d, frame, n, sink_cb, &s);
        CHECK(s.count == 1);
        CHECK(s.type[0] == MODEM_FRAME_RX);
        CHECK(s.len[0] == sizes[i]);
        CHECK(memcmp(s.payload[0], payload, sizes[i]) == 0);
        CHECK(d.dropped_bytes == 0 && d.crc_errors == 0);
    }
}

static void test_byte_by_byte_and_back_to_back(void)
{
    uint8_t a[] = {0xAA, 0xBB};
    uint8_t b[] = {0xA5, 0xA5, 0xA5}; /* sync bytes inside a payload are fine */
    uint8_t stream[64];
    size_t n = modem_frame_encode(MODEM_FRAME_STATUS, a, sizeof(a), stream, sizeof(stream));
    n += modem_frame_encode(MODEM_FRAME_ERROR, b, sizeof(b), stream + n, sizeof(stream) - n);

    modem_decoder_t d;
    sink_t s = {0};
    modem_decoder_init(&d);
    for (size_t i = 0; i < n; i++) {
        modem_decoder_feed(&d, stream + i, 1, sink_cb, &s);
    }
    CHECK(s.count == 2);
    CHECK(s.type[0] == MODEM_FRAME_STATUS && s.len[0] == 2);
    CHECK(s.type[1] == MODEM_FRAME_ERROR && s.len[1] == 3);
    CHECK(memcmp(s.payload[1], b, 3) == 0);
}

static void test_resync_after_junk(void)
{
    /* Boot-log text, a stray sync byte and a fake header before a frame. */
    uint8_t stream[128];
    const char *junk = "ESP-ROM:esp32s3\r\n";
    size_t n = strlen(junk);
    memcpy(stream, junk, n);
    stream[n++] = MODEM_SYNC;
    stream[n++] = 0x02;
    uint8_t payload[] = {1, 2, 3, 4};
    n += modem_frame_encode(MODEM_FRAME_IDENT, payload, sizeof(payload), stream + n,
                            sizeof(stream) - n);

    modem_decoder_t d;
    sink_t s = {0};
    modem_decoder_init(&d);
    modem_decoder_feed(&d, stream, n, sink_cb, &s);
    CHECK(s.count == 1);
    CHECK(s.type[0] == MODEM_FRAME_IDENT);
    CHECK(s.len[0] == 4);
    CHECK(d.dropped_bytes > strlen(junk));
}

static void test_bad_crc_then_good_frame(void)
{
    uint8_t stream[64];
    uint8_t p1[] = {9, 9, 9};
    size_t n = modem_frame_encode(MODEM_FRAME_TX, p1, sizeof(p1), stream, sizeof(stream));
    stream[5] ^= 0xFF; /* corrupt the payload */
    uint8_t p2[] = {7};
    n += modem_frame_encode(MODEM_FRAME_CMD, p2, sizeof(p2), stream + n, sizeof(stream) - n);

    modem_decoder_t d;
    sink_t s = {0};
    modem_decoder_init(&d);
    modem_decoder_feed(&d, stream, n, sink_cb, &s);
    CHECK(s.count == 1);
    CHECK(s.type[0] == MODEM_FRAME_CMD && s.len[0] == 1 && s.payload[0][0] == 7);
    CHECK(d.crc_errors == 1);
}

static void test_frame_hidden_in_rejected_bytes(void)
{
    /* A sync byte with a huge length, then a real frame: the decoder must
     * not swallow the real frame while "waiting" for 0xFFFF bytes. */
    uint8_t stream[64] = {MODEM_SYNC, MODEM_FRAME_RX, 0xFF, 0xFF};
    size_t n = 4;
    uint8_t p[] = {0x42};
    n += modem_frame_encode(MODEM_FRAME_STATUS, p, sizeof(p), stream + n, sizeof(stream) - n);

    modem_decoder_t d;
    sink_t s = {0};
    modem_decoder_init(&d);
    modem_decoder_feed(&d, stream, n, sink_cb, &s);
    CHECK(s.count == 1);
    CHECK(s.type[0] == MODEM_FRAME_STATUS && s.payload[0][0] == 0x42);
    CHECK(d.length_errors == 1);

    /* A truncated frame whose CRC fails because a real frame starts inside
     * its "payload": the real frame is still delivered. */
    uint8_t inner[16];
    uint8_t q[] = {1, 2};
    size_t inner_len = modem_frame_encode(MODEM_FRAME_TX_ACK, q, sizeof(q), inner, sizeof(inner));
    uint8_t stream2[64] = {MODEM_SYNC, MODEM_FRAME_RX, 0x00, (uint8_t)inner_len};
    memcpy(stream2 + 4, inner, inner_len);
    size_t n2 = 4 + inner_len;
    stream2[n2++] = 0x00; /* wrong CRC for the outer frame */
    stream2[n2++] = 0x00;
    sink_t s2 = {0};
    modem_decoder_init(&d);
    modem_decoder_feed(&d, stream2, n2, sink_cb, &s2);
    CHECK(s2.count == 1);
    CHECK(s2.type[0] == MODEM_FRAME_TX_ACK && s2.len[0] == 2);
    CHECK(d.crc_errors == 1);
}

void run_modem_framing_tests(void)
{
    test_crc_known_answer();
    test_encode_layout();
    test_round_trip_sizes();
    test_byte_by_byte_and_back_to_back();
    test_resync_after_junk();
    test_bad_crc_then_good_frame();
    test_frame_hidden_in_rejected_bytes();
}
