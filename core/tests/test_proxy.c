/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Capability proxy payloads (atalaia/proxy.h) against the shared vectors
 * (protocol/vectors/capability_proxy.yaml, also checked by
 * simulator/tests/test_capability_proxy.py; the frames around them by
 * firmware/esp32/test/test_proxy_codec.c). Every vector is checked.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/proxy.h"
#include "check.h"
#include "proxy_vectors.h"

static bool same_ident(const atalaia_proxy_ident_t *a, const atalaia_proxy_ident_t *b)
{
    return strcmp(a->fw_version, b->fw_version) == 0 && strcmp(a->caps_json, b->caps_json) == 0 &&
           a->has_battery == b->has_battery && a->battery_pct == b->battery_pct &&
           a->has_radio == b->has_radio && a->protocol_version == b->protocol_version;
}

static bool same_msg(const atalaia_proxy_msg_t *a, const atalaia_proxy_msg_t *b)
{
    return strcmp(a->cap_id, b->cap_id) == 0 && strcmp(a->name, b->name) == 0 &&
           strcmp(a->data_json, b->data_json) == 0 && a->seq == b->seq;
}

static void test_ident_vectors(void)
{
    CHECK(PROXY_IDENT_VECTOR_COUNT >= 3);
    for (size_t i = 0; i < PROXY_IDENT_VECTOR_COUNT; i++) {
        const proxy_ident_vector_t *v = &proxy_ident_vectors[i];
        int before = check_failures;
        uint8_t buf[ATALAIA_PROXY_PAYLOAD_MAX];
        size_t n = atalaia_proxy_ident_encode(&v->fields, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        atalaia_proxy_ident_t got;
        CHECK(atalaia_proxy_ident_decode(v->payload, v->payload_len, &got));
        CHECK(same_ident(&got, &v->fields));
        /* Re-encoding the decoded fields gives the same bytes. */
        n = atalaia_proxy_ident_encode(&got, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        CHECK(atalaia_proxy_ident_encode(&v->fields, buf, v->payload_len - 1) == 0);
        if (check_failures != before) fprintf(stderr, "  in ident vector %s\n", v->name);
    }
}

static void test_msg_vectors(void)
{
    CHECK(PROXY_MSG_VECTOR_COUNT >= 7);
    for (size_t i = 0; i < PROXY_MSG_VECTOR_COUNT; i++) {
        const proxy_msg_vector_t *v = &proxy_msg_vectors[i];
        int before = check_failures;
        uint8_t buf[ATALAIA_PROXY_PAYLOAD_MAX];
        size_t n = atalaia_proxy_msg_encode(&v->fields, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        atalaia_proxy_msg_t got;
        CHECK(atalaia_proxy_msg_decode(v->payload, v->payload_len, &got));
        CHECK(same_msg(&got, &v->fields));
        n = atalaia_proxy_msg_encode(&got, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        if (check_failures != before) {
            fprintf(stderr, "  in msg vector %s (decoded %s %s %s %u)\n", v->name, got.cap_id,
                    got.name, got.data_json, got.seq);
        }
    }
}

static void test_ack_vectors(void)
{
    CHECK(PROXY_ACK_VECTOR_COUNT >= 3);
    for (size_t i = 0; i < PROXY_ACK_VECTOR_COUNT; i++) {
        uint8_t buf[2];
        CHECK(atalaia_proxy_ack_encode(proxy_ack_vectors[i].seq, buf, sizeof(buf)) == 2);
        uint16_t seq = 0;
        CHECK(atalaia_proxy_ack_decode(buf, 2, &seq) && seq == proxy_ack_vectors[i].seq);
    }
    /* The ack payloads are also among the frame vectors (type 4). */
    size_t acks = 0;
    for (size_t i = 0; i < PROXY_FRAME_VECTOR_COUNT; i++) {
        const proxy_frame_vector_t *f = &proxy_frame_vectors[i];
        if (f->type != ATALAIA_PROXY_ACK) continue;
        uint16_t seq;
        CHECK(atalaia_proxy_ack_decode(f->payload, f->payload_len, &seq));
        CHECK(seq == proxy_ack_vectors[acks].seq);
        acks++;
    }
    CHECK(acks == PROXY_ACK_VECTOR_COUNT);
}

static void test_invalid_vectors(void)
{
    CHECK(PROXY_BAD_VECTOR_COUNT >= 20);
    for (size_t i = 0; i < PROXY_BAD_VECTOR_COUNT; i++) {
        const proxy_bad_vector_t *v = &proxy_bad_vectors[i];
        bool accepted;
        if (v->type == ATALAIA_PROXY_IDENT) {
            atalaia_proxy_ident_t got;
            memset(&got, 0x5A, sizeof(got));
            accepted = atalaia_proxy_ident_decode(v->payload, v->payload_len, &got);
            CHECK(got.fw_version[0] == '\0' && got.protocol_version == 0); /* zeroed */
        } else if (v->type == ATALAIA_PROXY_ACK) {
            uint16_t seq;
            accepted = atalaia_proxy_ack_decode(v->payload, v->payload_len, &seq);
        } else {
            atalaia_proxy_msg_t got;
            accepted = atalaia_proxy_msg_decode(v->payload, v->payload_len, &got);
            CHECK(got.cap_id[0] == '\0' && got.seq == 0);
        }
        if (accepted) {
            fprintf(stderr, "FAIL proxy bad vector %s accepted (%s)\n", v->name, v->why);
            check_failures++;
        }
    }
}

static void test_skipped_keys(void)
{
    atalaia_proxy_ident_t ident;
    CHECK(atalaia_proxy_ident_decode(proxy_skipped_ident, proxy_skipped_ident_len, &ident));
    CHECK(strcmp(ident.fw_version, "0.3.0") == 0 && strcmp(ident.caps_json, "[]") == 0);
    atalaia_proxy_msg_t msg;
    CHECK(atalaia_proxy_msg_decode(proxy_skipped_evt, proxy_skipped_evt_len, &msg));
    CHECK(same_msg(&msg, &proxy_msg_vectors[0].fields));
}

static void test_encode_refuses(void)
{
    uint8_t buf[ATALAIA_PROXY_PAYLOAD_MAX];
    atalaia_proxy_msg_t m = proxy_msg_vectors[0].fields;
    snprintf(m.cap_id, sizeof(m.cap_id), "Btn");
    CHECK(atalaia_proxy_msg_encode(&m, buf, sizeof(buf)) == 0);
    m = proxy_msg_vectors[0].fields;
    snprintf(m.data_json, sizeof(m.data_json), "[1,2]"); /* not an object */
    CHECK(atalaia_proxy_msg_encode(&m, buf, sizeof(buf)) == 0);
    m = proxy_msg_vectors[0].fields;
    m.data_json[0] = '\0'; /* no data: left out */
    size_t n = atalaia_proxy_msg_encode(&m, buf, sizeof(buf));
    CHECK(n > 0 && buf[0] == 0xA3);

    atalaia_proxy_ident_t id = proxy_ident_vectors[0].fields;
    id.battery_pct = 101;
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) == 0);
    id = proxy_ident_vectors[0].fields;
    snprintf(id.caps_json, sizeof(id.caps_json), "[{\"id\":\"x\"}]"); /* no type */
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) == 0);
    snprintf(id.caps_json, sizeof(id.caps_json), "[{\"id\":\"x\",\"type\":\"y\"} junk");
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) == 0);
    snprintf(id.caps_json, sizeof(id.caps_json), " [ ] ");
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) > 0);
    id.protocol_version = 2;
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) == 0);
    /* 17 capabilities: one too many. */
    id = proxy_ident_vectors[0].fields;
    size_t o = (size_t)snprintf(id.caps_json, sizeof(id.caps_json), "[");
    for (int i = 0; i < 17; i++) {
        o += (size_t)snprintf(id.caps_json + o, sizeof(id.caps_json) - o,
                              "%s{\"id\":\"b\",\"type\":\"t\"}", i ? "," : "");
    }
    snprintf(id.caps_json + o, sizeof(id.caps_json) - o, "]");
    CHECK(atalaia_proxy_ident_encode(&id, buf, sizeof(buf)) == 0);

    CHECK(atalaia_proxy_modem_type(ATALAIA_PROXY_RADIO_RX) == 0x02);
    CHECK(atalaia_proxy_modem_type(ATALAIA_PROXY_RADIO_ERROR) == 0x07);
    CHECK(atalaia_proxy_modem_type(ATALAIA_PROXY_ACK) == 0);
    CHECK(atalaia_proxy_ack_encode(1, buf, 1) == 0);
}

void run_proxy_tests(void)
{
    test_ident_vectors();
    test_msg_vectors();
    test_ack_vectors();
    test_invalid_vectors();
    test_skipped_keys();
    test_encode_refuses();
}
