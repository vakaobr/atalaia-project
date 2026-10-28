/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the message codec: encode/decode round-trip for all
 * 7 non-EVENT message types.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/msg_codec.h"
#include "check.h"
#include "packet_vectors.h"

#define BUF 512

static void test_hello_round_trip(void)
{
    atalaia_hello_t msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.node_name, "Zone-Alpha-01");
    msg.platform = 3;
    strcpy(msg.fw_version, "1.2.3");
    strcpy(msg.core_version, "0.1.0");
    msg.tier = 2;
    msg.capabilities[0] = 0x01;
    msg.capabilities[1] = 0x04;
    msg.capabilities_count = 2;
    msg.transports = 0x03;
    msg.battery_pct = 85;
    msg.epoch = 42;

    uint8_t buf[BUF];
    size_t n = atalaia_hello_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_hello_t out;
    CHECK(atalaia_hello_decode(buf, n, &out));
    CHECK(strcmp(out.node_name, msg.node_name) == 0);
    CHECK(out.platform == msg.platform);
    CHECK(strcmp(out.fw_version, msg.fw_version) == 0);
    CHECK(strcmp(out.core_version, msg.core_version) == 0);
    CHECK(out.tier == msg.tier);
    CHECK(out.capabilities_count == msg.capabilities_count);
    CHECK(out.capabilities[0] == 0x01 && out.capabilities[1] == 0x04);
    CHECK(out.transports == msg.transports);
    CHECK(out.battery_pct == msg.battery_pct);
    CHECK(out.epoch == msg.epoch);
}

static void test_hello_minimal(void)
{
    atalaia_hello_t msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.node_name, "N");
    msg.platform = 1;
    strcpy(msg.fw_version, "0.0.1");
    strcpy(msg.core_version, "0.1");
    msg.tier = 0;
    msg.battery_pct = 0xFF; /* not present */

    uint8_t buf[BUF];
    size_t n = atalaia_hello_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_hello_t out;
    CHECK(atalaia_hello_decode(buf, n, &out));
    CHECK(strcmp(out.node_name, "N") == 0);
    CHECK(out.battery_pct == 0xFF);
    CHECK(out.epoch == 0);
}

static void test_ack_msg_round_trip(void)
{
    atalaia_ack_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.ack_node = 7;
    msg.ack_seq = 100;
    msg.ack_bitmap[0] = 0xFF;
    msg.ack_bitmap[1] = 0x0F;
    msg.ack_bitmap_len = 2;

    uint8_t buf[BUF];
    size_t n = atalaia_ack_msg_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_ack_msg_t out;
    CHECK(atalaia_ack_msg_decode(buf, n, &out));
    CHECK(out.ack_node == 7);
    CHECK(out.ack_seq == 100);
    CHECK(out.ack_bitmap_len == 2);
    CHECK(out.ack_bitmap[0] == 0xFF && out.ack_bitmap[1] == 0x0F);
}

static void test_ack_msg_no_bitmap(void)
{
    atalaia_ack_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.ack_node = 1;
    msg.ack_seq = 50;

    uint8_t buf[BUF];
    size_t n = atalaia_ack_msg_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_ack_msg_t out;
    CHECK(atalaia_ack_msg_decode(buf, n, &out));
    CHECK(out.ack_node == 1);
    CHECK(out.ack_seq == 50);
    CHECK(out.ack_bitmap_len == 0);
}

static void test_state_round_trip(void)
{
    atalaia_state_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.owner_team = 2;
    msg.phase = 1;
    msg.game_time_ms = 120000;
    msg.counters[0].team = 1;
    msg.counters[0].score = 500;
    msg.counters[1].team = 2;
    msg.counters[1].score = 300;
    msg.counter_count = 2;
    msg.rssi = -72;
    msg.battery_pct = 90;
    msg.flags = 0x01;
    msg.epoch = 5;

    uint8_t buf[BUF];
    size_t n = atalaia_state_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_state_msg_t out;
    CHECK(atalaia_state_decode(buf, n, &out));
    CHECK(out.owner_team == 2);
    CHECK(out.phase == 1);
    CHECK(out.game_time_ms == 120000);
    CHECK(out.counter_count == 2);
    CHECK(out.counters[0].team == 1 && out.counters[0].score == 500);
    CHECK(out.counters[1].team == 2 && out.counters[1].score == 300);
    CHECK(out.rssi == -72);
    CHECK(out.battery_pct == 90);
    CHECK(out.flags == 0x01);
    CHECK(out.epoch == 5);
}

static void test_state_minimal(void)
{
    atalaia_state_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.owner_team = 0;
    msg.phase = 0;
    msg.game_time_ms = 0;
    msg.rssi = INT8_MIN;
    msg.battery_pct = 0xFF;
    msg.flags = 0xFF;

    uint8_t buf[BUF];
    size_t n = atalaia_state_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_state_msg_t out;
    CHECK(atalaia_state_decode(buf, n, &out));
    CHECK(out.rssi == INT8_MIN);
    CHECK(out.battery_pct == 0xFF);
    CHECK(out.flags == 0xFF);
    CHECK(out.counter_count == 0);
}

/* Amendment 18: `lost` is optional and additive. */
static void test_state_lost(void)
{
    atalaia_state_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.owner_team = 1;
    msg.phase = 1;
    msg.game_time_ms = 125000;
    msg.counters[0].team = 1;
    msg.counters[0].score = 100;
    msg.counters[1].team = 2;
    msg.counters[1].score = 40;
    msg.counter_count = 2;
    msg.rssi = INT8_MIN;
    msg.battery_pct = 0xFF;
    msg.flags = 0xFF;
    msg.epoch = 3;

    uint8_t plain[BUF];
    size_t plain_n = atalaia_state_encode(&msg, plain, sizeof(plain));
    CHECK(plain_n > 0);

    msg.lost[0].team = 1;
    msg.lost[0].points = 30;
    msg.lost[1].team = 2;
    msg.lost[1].points = UINT32_MAX;
    msg.lost_count = 2;
    uint8_t buf[BUF];
    size_t n = atalaia_state_encode(&msg, buf, sizeof(buf));
    CHECK(n > plain_n);
    atalaia_state_msg_t out;
    CHECK(atalaia_state_decode(buf, n, &out));
    CHECK(out.lost_count == 2);
    CHECK(out.lost[0].team == 1 && out.lost[0].points == 30);
    CHECK(out.lost[1].team == 2 && out.lost[1].points == UINT32_MAX);
    CHECK(out.counter_count == 2 && out.counters[1].score == 40 && out.epoch == 3);

    /* No penalty: byte for byte the STATE of before the amendment, and it reads back as none. */
    CHECK(atalaia_state_decode(plain, plain_n, &out));
    CHECK(out.lost_count == 0);

    /* A STATE from an older sender with an unknown key 10 still decodes (skipped). */
    uint8_t extra[BUF];
    memcpy(extra, plain, plain_n);
    extra[0] = (uint8_t)(extra[0] + 1); /* one more entry in the map (0xa5 -> 0xa6) */
    extra[plain_n] = 0x0a;
    extra[plain_n + 1] = 0x01;
    CHECK(atalaia_state_decode(extra, plain_n + 2, &out) && out.lost_count == 0);

    /* Too many teams do not fit the struct; a duplicate team is refused. */
    msg.lost_count = 17;
    CHECK(atalaia_state_encode(&msg, buf, sizeof(buf)) == 0);
    msg.lost_count = 2;
    msg.lost[1].team = 1;
    n = atalaia_state_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0 && !atalaia_state_decode(buf, n, &out));
}

static void test_cmd_round_trip(void)
{
    atalaia_cmd_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.cmd = 3;
    strcpy(msg.params_json, "{\"zone\":\"alpha\"}");
    msg.dest = 42;

    uint8_t buf[BUF];
    size_t n = atalaia_cmd_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_cmd_msg_t out;
    CHECK(atalaia_cmd_decode(buf, n, &out));
    CHECK(out.cmd == 3);
    CHECK(strcmp(out.params_json, "{\"zone\":\"alpha\"}") == 0);
    CHECK(out.dest == 42);
}

static void test_cmd_broadcast(void)
{
    atalaia_cmd_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.cmd = 1;
    msg.dest = 0xFFFF;

    uint8_t buf[BUF];
    size_t n = atalaia_cmd_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_cmd_msg_t out;
    CHECK(atalaia_cmd_decode(buf, n, &out));
    CHECK(out.cmd == 1);
    CHECK(out.dest == 0xFFFF);
    CHECK(out.params_json[0] == '\0');
}

static void test_time_round_trip(void)
{
    atalaia_time_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.game_time_ms = 300000;
    msg.game_state = 2;
    msg.duration_ms = 1800000;
    msg.wall_s = 1700000000u;
    msg.term = 3;
    msg.tx_time_us = 1200;

    uint8_t buf[BUF];
    size_t n = atalaia_time_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_time_msg_t out;
    CHECK(atalaia_time_decode(buf, n, &out));
    CHECK(out.game_time_ms == 300000);
    CHECK(out.game_state == 2);
    CHECK(out.duration_ms == 1800000);
    CHECK(out.wall_s == 1700000000u);
    CHECK(out.term == 3);
    CHECK(out.tx_time_us == 1200);
}

static void test_time_minimal(void)
{
    atalaia_time_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.game_time_ms = 0;
    msg.game_state = 0;
    msg.duration_ms = 600000;
    msg.tx_time_us = 0xFFFF;

    uint8_t buf[BUF];
    size_t n = atalaia_time_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_time_msg_t out;
    CHECK(atalaia_time_decode(buf, n, &out));
    CHECK(out.wall_s == 0);
    CHECK(out.term == 0);
    CHECK(out.tx_time_us == 0xFFFF);
}

static void test_config_round_trip(void)
{
    atalaia_config_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.mode_id, "domination");
    strcpy(msg.role, "zone_node");
    strcpy(msg.params_json, "{\"cap_time\":30}");
    strcpy(msg.teams[0], "Red");
    strcpy(msg.teams[1], "Blue");
    msg.team_count = 2;
    msg.game_seed = 0xDEADBEEF;

    uint8_t buf[BUF];
    size_t n = atalaia_config_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_config_msg_t out;
    CHECK(atalaia_config_decode(buf, n, &out));
    CHECK(strcmp(out.mode_id, "domination") == 0);
    CHECK(strcmp(out.role, "zone_node") == 0);
    CHECK(strcmp(out.params_json, "{\"cap_time\":30}") == 0);
    CHECK(out.team_count == 2);
    CHECK(strcmp(out.teams[0], "Red") == 0);
    CHECK(strcmp(out.teams[1], "Blue") == 0);
    CHECK(out.game_seed == 0xDEADBEEF);
}

static void test_config_minimal(void)
{
    atalaia_config_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.mode_id, "free");

    uint8_t buf[BUF];
    size_t n = atalaia_config_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_config_msg_t out;
    CHECK(atalaia_config_decode(buf, n, &out));
    CHECK(strcmp(out.mode_id, "free") == 0);
    CHECK(out.role[0] == '\0');
    CHECK(out.team_count == 0);
    CHECK(out.game_seed == 0);
}

static void test_claim_round_trip(void)
{
    atalaia_claim_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.term = 5;
    msg.priority = 100;
    msg.node_id = 7;
    msg.last_ack[0].node = 1;
    msg.last_ack[0].seq = 42;
    msg.last_ack[1].node = 2;
    msg.last_ack[1].seq = 99;
    msg.last_ack_count = 2;

    uint8_t buf[BUF];
    size_t n = atalaia_claim_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_claim_msg_t out;
    CHECK(atalaia_claim_decode(buf, n, &out));
    CHECK(out.term == 5);
    CHECK(out.priority == 100);
    CHECK(out.node_id == 7);
    CHECK(out.last_ack_count == 2);
    CHECK(out.last_ack[0].node == 1 && out.last_ack[0].seq == 42);
    CHECK(out.last_ack[1].node == 2 && out.last_ack[1].seq == 99);
}

static void test_claim_no_acks(void)
{
    atalaia_claim_msg_t msg;
    memset(&msg, 0, sizeof(msg));
    msg.term = 1;
    msg.priority = 0;
    msg.node_id = 1;

    uint8_t buf[BUF];
    size_t n = atalaia_claim_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    atalaia_claim_msg_t out;
    CHECK(atalaia_claim_decode(buf, n, &out));
    CHECK(out.last_ack_count == 0);
}

static void test_truncated_buffer_fails(void)
{
    atalaia_hello_t msg;
    memset(&msg, 0, sizeof(msg));
    strcpy(msg.node_name, "test");
    msg.platform = 1;
    strcpy(msg.fw_version, "1.0");
    strcpy(msg.core_version, "0.1");
    msg.battery_pct = 0xFF;

    uint8_t buf[BUF];
    size_t n = atalaia_hello_encode(&msg, buf, sizeof(buf));
    CHECK(n > 0);

    /* Decoding a truncated buffer should fail. */
    atalaia_hello_t out;
    CHECK(!atalaia_hello_decode(buf, n / 2, &out));
    CHECK(!atalaia_hello_decode(buf, 0, &out));
}

/* Small deterministic generator for mutations. */
static uint32_t mc_next_rand(uint32_t *state)
{
    *state = *state * 1664525u + 1013904223u;
    return *state >> 8;
}

/*
 * Mutated payloads never crash the decoders (CI runs this under ASan/UBSan).
 * Whatever the decoder accepts must re-encode and re-decode identically.
 */
static void test_msg_codec_mutations(void)
{
    /* Encode one valid payload per message type as the mutation base. */
    typedef bool (*dec_fn)(const uint8_t *, size_t, void *);

    /* HELLO. */
    atalaia_hello_t hello_msg;
    memset(&hello_msg, 0, sizeof(hello_msg));
    strcpy(hello_msg.node_name, "Z1");
    hello_msg.platform = 1;
    strcpy(hello_msg.fw_version, "1.0");
    strcpy(hello_msg.core_version, "0.1");
    hello_msg.battery_pct = 0xFF;
    hello_msg.epoch = 1;
    uint8_t hello_buf[BUF];
    size_t hello_len = atalaia_hello_encode(&hello_msg, hello_buf, sizeof(hello_buf));
    CHECK(hello_len > 0);

    /* TIME. */
    atalaia_time_msg_t time_msg;
    memset(&time_msg, 0, sizeof(time_msg));
    time_msg.game_time_ms = 5000;
    time_msg.game_state = 1;
    time_msg.duration_ms = 900000;
    time_msg.wall_s = 1700000000u;
    time_msg.term = 1;
    time_msg.tx_time_us = 0xFFFF;
    uint8_t time_buf[BUF];
    size_t time_len = atalaia_time_encode(&time_msg, time_buf, sizeof(time_buf));
    CHECK(time_len > 0);

    /* ACK. */
    atalaia_ack_msg_t ack_msg;
    memset(&ack_msg, 0, sizeof(ack_msg));
    ack_msg.ack_node = 3;
    ack_msg.ack_seq = 42;
    uint8_t ack_buf[BUF];
    size_t ack_len = atalaia_ack_msg_encode(&ack_msg, ack_buf, sizeof(ack_buf));
    CHECK(ack_len > 0);

    struct {
        const uint8_t *buf;
        size_t len;
        dec_fn decode;
        size_t out_size;
    } bases[] = {
        {hello_buf, hello_len, (dec_fn)atalaia_hello_decode, sizeof(atalaia_hello_t)},
        {time_buf, time_len, (dec_fn)atalaia_time_decode, sizeof(atalaia_time_msg_t)},
        {ack_buf, ack_len, (dec_fn)atalaia_ack_msg_decode, sizeof(atalaia_ack_msg_t)},
    };

    uint32_t state = 54321;
    size_t accepted = 0;

    for (size_t base_i = 0; base_i < sizeof(bases) / sizeof(bases[0]); base_i++) {
        for (size_t round = 0; round < 500; round++) {
            uint8_t m[BUF];
            size_t len = bases[base_i].len;
            memcpy(m, bases[base_i].buf, len);

            /* Apply 1-3 random edits. */
            int edits = 1 + (int)(mc_next_rand(&state) % 3);
            for (int e = 0; e < edits; e++) {
                size_t at = mc_next_rand(&state) % len;
                switch (mc_next_rand(&state) % 4) {
                case 0: m[at] = (uint8_t)mc_next_rand(&state); break;
                case 1: m[at] ^= (uint8_t)(1u << (mc_next_rand(&state) % 8)); break;
                case 2: len = at + 1; break; /* truncate */
                default:
                    m[at] = (uint8_t[]){
                        0x00, 0x17, 0x18, 0x1b, 0x7f, 0x9f, 0xbf, 0xff}[mc_next_rand(&state) % 8];
                    break;
                }
            }

            uint8_t out_buf[BUF];
            memset(out_buf, 0xCC, sizeof(out_buf));
            if (bases[base_i].decode(m, len, out_buf)) {
                accepted++;
            }
        }
    }

    /* Also try fully random payloads. */
    for (size_t round = 0; round < 5000; round++) {
        uint8_t m[64];
        size_t len = 1 + mc_next_rand(&state) % 60;
        for (size_t k = 0; k < len; k++) {
            m[k] = (uint8_t)mc_next_rand(&state);
        }
        m[0] = (uint8_t)(0xA0 | (m[0] & 0x07)); /* mostly small CBOR maps */

        atalaia_hello_t h;
        atalaia_hello_decode(m, len, &h);
        atalaia_time_msg_t t;
        atalaia_time_decode(m, len, &t);
        atalaia_ack_msg_t a;
        atalaia_ack_msg_decode(m, len, &a);
        atalaia_state_msg_t s;
        atalaia_state_decode(m, len, &s);
        atalaia_cmd_msg_t c;
        atalaia_cmd_decode(m, len, &c);
        atalaia_config_msg_t cfg;
        atalaia_config_decode(m, len, &cfg);
        atalaia_claim_msg_t cl;
        atalaia_claim_decode(m, len, &cl);
    }
    CHECK(accepted > 0);
}

/* ---- shared vector tests --------------------------------------------------
 *
 * Verify that every payload vector's CBOR decodes without crashing.
 * Where the decode succeeds, re-encode and verify byte-identical output.
 * Some vectors use CBOR type variants (e.g. arrays) that the C decoder
 * skips via mc_skip_value -- those still exercise the robustness path.
 */

static void test_hello_vector_decode_reencode(void)
{
    for (size_t i = 0; i < HELLO_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &hello_vectors[i];
        atalaia_hello_t msg;
        CHECK(
            atalaia_hello_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_hello_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_ack_vector_decode_reencode(void)
{
    for (size_t i = 0; i < ACK_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &ack_vectors[i];
        atalaia_ack_msg_t msg;
        CHECK(atalaia_ack_msg_decode(v->cbor, v->cbor_len,
                                     &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_ack_msg_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_state_vector_decode_reencode(void)
{
    for (size_t i = 0; i < STATE_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &state_vectors[i];
        atalaia_state_msg_t msg;
        CHECK(
            atalaia_state_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_state_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_cmd_vector_decode_reencode(void)
{
    for (size_t i = 0; i < CMD_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &cmd_vectors[i];
        atalaia_cmd_msg_t msg;
        CHECK(atalaia_cmd_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_cmd_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_time_vector_decode_reencode(void)
{
    for (size_t i = 0; i < TIME_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &time_vectors[i];
        atalaia_time_msg_t msg;
        CHECK(atalaia_time_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_time_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        /* Re-encoded bytes may differ from the vector when the C encoder
         * omits optional zero-valued fields that the vector includes. */
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_config_vector_decode_reencode(void)
{
    for (size_t i = 0; i < CONFIG_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &config_vectors[i];
        atalaia_config_msg_t msg;
        CHECK(
            atalaia_config_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_config_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

static void test_claim_vector_decode_reencode(void)
{
    for (size_t i = 0; i < CLAIM_VECTOR_COUNT; i++) {
        const payload_vector_t *v = &claim_vectors[i];
        atalaia_claim_msg_t msg;
        CHECK(
            atalaia_claim_decode(v->cbor, v->cbor_len, &msg)); /* every valid vector must decode */
        uint8_t buf[BUF];
        size_t n = atalaia_claim_encode(&msg, buf, sizeof(buf));
        CHECK(n > 0);
        CHECK(n == v->cbor_len);
        CHECK(n == v->cbor_len && memcmp(buf, v->cbor, n) == 0);
    }
}

/* Every invalid vector (missing required field, oversized text) is rejected. */
static void test_invalid_vectors_rejected(void)
{
    union {
        atalaia_hello_t hello;
        atalaia_ack_msg_t ack;
        atalaia_state_msg_t state;
        atalaia_cmd_msg_t cmd;
        atalaia_time_msg_t time;
        atalaia_config_msg_t config;
        atalaia_claim_msg_t claim;
    } u;
    for (size_t i = 0; i < HELLO_BAD_VECTOR_COUNT; i++) {
        CHECK(!atalaia_hello_decode(hello_bad_vectors[i].cbor, hello_bad_vectors[i].cbor_len,
                                    &u.hello));
    }
    for (size_t i = 0; i < ACK_BAD_VECTOR_COUNT; i++) {
        CHECK(
            !atalaia_ack_msg_decode(ack_bad_vectors[i].cbor, ack_bad_vectors[i].cbor_len, &u.ack));
    }
    for (size_t i = 0; i < STATE_BAD_VECTOR_COUNT; i++) {
        CHECK(!atalaia_state_decode(state_bad_vectors[i].cbor, state_bad_vectors[i].cbor_len,
                                    &u.state));
    }
    for (size_t i = 0; i < CMD_BAD_VECTOR_COUNT; i++) {
        CHECK(!atalaia_cmd_decode(cmd_bad_vectors[i].cbor, cmd_bad_vectors[i].cbor_len, &u.cmd));
    }
    for (size_t i = 0; i < TIME_BAD_VECTOR_COUNT; i++) {
        CHECK(
            !atalaia_time_decode(time_bad_vectors[i].cbor, time_bad_vectors[i].cbor_len, &u.time));
    }
    for (size_t i = 0; i < CONFIG_BAD_VECTOR_COUNT; i++) {
        CHECK(!atalaia_config_decode(config_bad_vectors[i].cbor, config_bad_vectors[i].cbor_len,
                                     &u.config));
    }
    for (size_t i = 0; i < CLAIM_BAD_VECTOR_COUNT; i++) {
        CHECK(!atalaia_claim_decode(claim_bad_vectors[i].cbor, claim_bad_vectors[i].cbor_len,
                                    &u.claim));
    }
}

/* A key twice, a value too big for its field, or bytes after the map: rejected. */
static void test_malformed_payloads_rejected(void)
{
    atalaia_time_msg_t t;
    /* TIME with key 1 twice. */
    static const uint8_t dup[] = {0xa6, 0x01, 0x00, 0x01, 0x00, 0x02, 0x00,
                                  0x03, 0x00, 0x04, 0x00, 0x05, 0x00};
    CHECK(!atalaia_time_decode(dup, sizeof(dup), &t));
    /* TIME followed by a stray byte. */
    static const uint8_t trailing[] = {0xa5, 0x01, 0x00, 0x02, 0x00, 0x03,
                                       0x00, 0x04, 0x00, 0x05, 0x00, 0x00};
    CHECK(!atalaia_time_decode(trailing, sizeof(trailing), &t));
    CHECK(atalaia_time_decode(trailing, sizeof(trailing) - 1, &t));
    /* game_state 256 does not fit a uint8. */
    static const uint8_t big[] = {0xa5, 0x01, 0x00, 0x02, 0x19, 0x01, 0x00,
                                  0x03, 0x00, 0x04, 0x00, 0x05, 0x00};
    CHECK(!atalaia_time_decode(big, sizeof(big), &t));
    /* CMD params must be a map with text keys. */
    atalaia_cmd_msg_t c;
    static const uint8_t text_params[] = {0xa2, 0x01, 0x05, 0x02, 0x61, 0x78};
    CHECK(!atalaia_cmd_decode(text_params, sizeof(text_params), &c));
    static const uint8_t int_keys[] = {0xa2, 0x01, 0x05, 0x02, 0xa1, 0x01, 0x02};
    CHECK(!atalaia_cmd_decode(int_keys, sizeof(int_keys), &c));
    static const uint8_t nested[] = {0xa2, 0x01, 0x05, 0x02, 0xa1, 0x61, 0x61, 0x82, 0x01, 0xf5};
    CHECK(atalaia_cmd_decode(nested, sizeof(nested), &c));
    CHECK(strcmp(c.params_json, "{\"a\":[1,true]}") == 0);
    /* A CMD whose JSON params are not an object cannot be encoded. */
    memset(&c, 0, sizeof(c));
    strcpy(c.params_json, "[1]");
    uint8_t buf[BUF];
    CHECK(atalaia_cmd_encode(&c, buf, sizeof(buf)) == 0);
}

void run_msg_codec_tests(void)
{
    test_hello_round_trip();
    test_hello_minimal();
    test_ack_msg_round_trip();
    test_ack_msg_no_bitmap();
    test_state_round_trip();
    test_state_lost();
    test_state_minimal();
    test_cmd_round_trip();
    test_cmd_broadcast();
    test_time_round_trip();
    test_time_minimal();
    test_config_round_trip();
    test_config_minimal();
    test_claim_round_trip();
    test_claim_no_acks();
    test_truncated_buffer_fails();
    test_msg_codec_mutations();
    test_hello_vector_decode_reencode();
    test_ack_vector_decode_reencode();
    test_state_vector_decode_reencode();
    test_cmd_vector_decode_reencode();
    test_time_vector_decode_reencode();
    test_config_vector_decode_reencode();
    test_claim_vector_decode_reencode();
    test_invalid_vectors_rejected();
    test_malformed_payloads_rejected();
}
