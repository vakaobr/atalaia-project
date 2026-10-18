/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Capability proxy frames (protocol/capability-proxy.md) with the USB
 * modem's framing (main/modem/modem_framing.c), which the I/O pod shares:
 * every vector of protocol/vectors/capability_proxy.yaml becomes exactly
 * its frame, the decoder gives every frame back (also one byte at a time),
 * and a stream with boot text, a bad CRC and an impossible length yields
 * just its good frames. The payloads themselves: core/tests/test_proxy.c.
 *
 * Its own executable, so that `ctest -R proxy_codec` runs it alone.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/proxy.h"
#include "modem/modem_framing.h"
#include "proxy_vectors.h"

static int failures;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

#define GOT_MAX 8

typedef struct {
    int count;
    uint8_t type[GOT_MAX];
    uint8_t payload[GOT_MAX][MODEM_FRAME_PAYLOAD_MAX];
    size_t len[GOT_MAX];
} got_t;

static void on_frame(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    got_t *g = ctx;
    if (g->count < GOT_MAX) {
        g->type[g->count] = type;
        memcpy(g->payload[g->count], payload, len);
        g->len[g->count] = len;
    }
    g->count++;
}

static void test_crc(void)
{
    CHECK(modem_crc16(proxy_crc_data, proxy_crc_data_len) == PROXY_CRC_CHECK);
}

static void test_frames(void)
{
    CHECK(PROXY_FRAME_VECTOR_COUNT >= 20);
    for (size_t i = 0; i < PROXY_FRAME_VECTOR_COUNT; i++) {
        const proxy_frame_vector_t *v = &proxy_frame_vectors[i];
        int before = failures;
        uint8_t frame[MODEM_FRAME_MAX];
        size_t n = modem_frame_encode(v->type, v->payload, v->payload_len, frame, sizeof(frame));
        CHECK(n == v->frame_len && memcmp(frame, v->frame, n) == 0);

        /* Back through the decoder, whole and one byte at a time. */
        for (int bytewise = 0; bytewise < 2; bytewise++) {
            modem_decoder_t d;
            modem_decoder_init(&d);
            got_t got = {0};
            if (bytewise) {
                for (size_t k = 0; k < v->frame_len; k++) {
                    modem_decoder_feed(&d, v->frame + k, 1, on_frame, &got);
                }
            } else {
                modem_decoder_feed(&d, v->frame, v->frame_len, on_frame, &got);
            }
            CHECK(got.count == 1 && got.type[0] == v->type && got.len[0] == v->payload_len);
            CHECK(got.count == 1 && memcmp(got.payload[0], v->payload, v->payload_len) == 0);
        }
        /* Radio frames carry the modem's payloads: the modem type is 3 lower. */
        if (v->type >= ATALAIA_PROXY_RADIO_RX) {
            CHECK(atalaia_proxy_modem_type(v->type) == v->type - 3);
        }
        if (failures != before) fprintf(stderr, "  in frame vector %s\n", v->name);
    }
}

static void test_stream(void)
{
    modem_decoder_t d;
    modem_decoder_init(&d);
    got_t got = {0};
    /* In two pieces, cut inside the boot text's line. */
    modem_decoder_feed(&d, proxy_stream, 10, on_frame, &got);
    modem_decoder_feed(&d, proxy_stream + 10, proxy_stream_len - 10, on_frame, &got);
    CHECK(got.count == (int)PROXY_STREAM_FRAME_COUNT);
    for (size_t i = 0; i < PROXY_STREAM_FRAME_COUNT && (int)i < got.count; i++) {
        const proxy_frame_vector_t *f = &proxy_stream_frames[i];
        CHECK(got.type[i] == f->type && got.len[i] == f->payload_len);
        CHECK(memcmp(got.payload[i], f->payload, f->payload_len) == 0);
    }
    CHECK(d.crc_errors == PROXY_STREAM_CRC_ERRORS);
    CHECK(d.length_errors == PROXY_STREAM_LENGTH_ERRORS);

    /* The EVT it holds decodes to the button vector. */
    atalaia_proxy_msg_t m;
    CHECK(got.count >= 1 && atalaia_proxy_msg_decode(got.payload[0], got.len[0], &m));
    CHECK(strcmp(m.cap_id, "btn.red") == 0 && m.seq == 7);
}

int main(void)
{
    test_crc();
    test_frames();
    test_stream();
    if (failures) {
        fprintf(stderr, "proxy_codec: %d check(s) failed\n", failures);
        return 1;
    }
    printf("proxy_codec: %d frame vectors and the stream match\n", (int)PROXY_FRAME_VECTOR_COUNT);
    return 0;
}
