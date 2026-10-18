/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the radio protocol layer: epoch persistence (boot, wrap,
 * exhaustion, NVS failure) and receiver-side epoch trial.
 *
 * Uses an in-process NVS stub that records calls and returns
 * configurable results, and the test-stub crypto backend from
 * packet.h (XOR + FNV-1a, NOT cryptographically secure).
 */
#include <string.h>

#include "check.h"
#include "radio/radio_protocol.h"

/* ---- NVS test stub -------------------------------------------------------- */

typedef struct {
    uint16_t stored_epoch;
    bool epoch_present;
    uint8_t stored_key[16];
    bool key_present;
    int write_epoch_result; /* 0 = ok, -1 = fail */
    int write_epoch_calls;
    uint16_t last_written_epoch;
} test_nvs_state_t;

static int test_nvs_read_epoch(void *ctx, uint16_t *epoch)
{
    test_nvs_state_t *st = (test_nvs_state_t *)ctx;
    if (!st->epoch_present) return -1; /* not found */
    *epoch = st->stored_epoch;
    return 0;
}

static int test_nvs_write_epoch(void *ctx, uint16_t epoch)
{
    test_nvs_state_t *st = (test_nvs_state_t *)ctx;
    st->write_epoch_calls++;
    st->last_written_epoch = epoch;
    if (st->write_epoch_result != 0) return st->write_epoch_result;
    st->stored_epoch = epoch;
    st->epoch_present = true;
    return 0;
}

static int test_nvs_read_key(void *ctx, uint8_t key[16])
{
    test_nvs_state_t *st = (test_nvs_state_t *)ctx;
    if (!st->key_present) return -1;
    memcpy(key, st->stored_key, 16);
    return 0;
}

static int test_nvs_write_key(void *ctx, const uint8_t key[16])
{
    test_nvs_state_t *st = (test_nvs_state_t *)ctx;
    memcpy(st->stored_key, key, 16);
    st->key_present = true;
    return 0;
}

static int test_nvs_erase_key(void *ctx)
{
    test_nvs_state_t *st = (test_nvs_state_t *)ctx;
    memset(st->stored_key, 0, 16);
    st->key_present = false;
    return 0;
}

static void test_nvs_reset(test_nvs_state_t *st)
{
    memset(st, 0, sizeof(*st));
}

static const atalaia_radio_nvs_ops_t test_nvs_ops = {
    .read_epoch = test_nvs_read_epoch,
    .write_epoch = test_nvs_write_epoch,
    .read_key = test_nvs_read_key,
    .write_key = test_nvs_write_key,
    .erase_key = test_nvs_erase_key,
    .ctx = NULL, /* overridden per test */
};

/* ---- Helpers -------------------------------------------------------------- */

static const uint8_t test_key[16] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                                     0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10};

/*
 * Build an encrypted packet for the recv tests.
 * Returns the total packet length, or 0 on error.
 */
static size_t build_test_packet(uint16_t game_id, uint16_t source, uint16_t seq, uint16_t epoch,
                                const uint8_t key[16], const uint8_t *payload, size_t payload_len,
                                uint8_t *out, size_t out_cap)
{
    atalaia_header_t hdr;
    hdr.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1);
    hdr.game_id = game_id;
    hdr.source = source;
    hdr.seq = seq;
    hdr.hop_limit = 3;
    hdr.type = ATALAIA_MSG_EVENT;
    return atalaia_packet_encrypt(&hdr, epoch, key, payload, payload_len, out, out_cap,
                                  &atalaia_crypto_test_stub);
}

/*
 * Make a valid event for the send-path tests.
 * The event type is "test.ping" which encodes as a custom event by name.
 */
static void make_test_event(atalaia_event_t *ev)
{
    atalaia_event_init(ev, 1, 0, 0, "test.ping", 0, 0, 0);
}

/* ---- Epoch persistence tests ---------------------------------------------- */

static void test_boot_epoch(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    nvs.stored_epoch = 5;
    nvs.epoch_present = true;

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);

    bool ok = atalaia_radio_proto_boot_epoch(&rp);
    CHECK(ok);
    CHECK(rp.epoch == 6);
    CHECK(nvs.write_epoch_calls == 1);
    CHECK(nvs.last_written_epoch == 6);
    CHECK(!rp.tx_blocked);
}

static void test_boot_epoch_first_boot(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    /* epoch_present = false: NVS read returns -1 (not found). */

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);

    bool ok = atalaia_radio_proto_boot_epoch(&rp);
    CHECK(ok);
    /* stored=0 (from not-found default) + 1 = 1. */
    CHECK(rp.epoch == 1);
    CHECK(nvs.write_epoch_calls == 1);
    CHECK(nvs.last_written_epoch == 1);
    CHECK(!rp.tx_blocked);
}

static void test_boot_epoch_nvs_write_fail(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    nvs.stored_epoch = 0;
    nvs.epoch_present = true;
    nvs.write_epoch_result = -1;

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);

    bool ok = atalaia_radio_proto_boot_epoch(&rp);
    CHECK(!ok);
    CHECK(rp.tx_blocked);
}

/* ---- Sequence-wrap tests -------------------------------------------------- */

static void test_seq_wrap_increments_epoch(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    nvs.stored_epoch = 0;
    nvs.epoch_present = true;

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* Set the epoch and sequence directly to force a wrap on next send. */
    rp.epoch = 1;
    rp.seq = 65535;

    /* Reset NVS call count after init to isolate the wrap call. */
    nvs.write_epoch_calls = 0;

    /* Call send_event. In the stub build radio_task_send returns false,
     * but advance_seq still runs and modifies the proto state. */
    atalaia_event_t ev;
    make_test_event(&ev);
    (void)atalaia_radio_proto_send_event(&rp, &ev, NULL);

    /* seq wrapped from 65535 to 0; epoch incremented from 1 to 2. */
    CHECK(rp.seq == 0);
    CHECK(rp.epoch == 2);
    CHECK(nvs.write_epoch_calls == 1);
    CHECK(nvs.last_written_epoch == 2);
    CHECK(!rp.tx_blocked);
}

static void test_seq_wrap_nvs_fail_blocks_tx(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    nvs.stored_epoch = 0;
    nvs.epoch_present = true;
    nvs.write_epoch_result = -1;

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);

    rp.epoch = 1;
    rp.seq = 65535;
    nvs.write_epoch_calls = 0;

    atalaia_event_t ev;
    make_test_event(&ev);
    bool ok = atalaia_radio_proto_send_event(&rp, &ev, NULL);

    CHECK(!ok);
    CHECK(rp.tx_blocked);
    CHECK(nvs.write_epoch_calls == 1);
}

static void test_epoch_exhaustion(void)
{
    test_nvs_state_t nvs;
    test_nvs_reset(&nvs);
    nvs.stored_epoch = 0;
    nvs.epoch_present = true;

    atalaia_radio_nvs_ops_t ops = test_nvs_ops;
    ops.ctx = &nvs;

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* Nonce space exhausted: epoch=65535, seq=65535. */
    rp.epoch = 65535;
    rp.seq = 65535;
    nvs.write_epoch_calls = 0;

    atalaia_event_t ev;
    make_test_event(&ev);
    bool ok = atalaia_radio_proto_send_event(&rp, &ev, NULL);

    CHECK(!ok);
    CHECK(rp.tx_blocked);
    /* No NVS write should have been attempted. */
    CHECK(nvs.write_epoch_calls == 0);
}

/* ---- Receiver epoch-trial tests ------------------------------------------- */

static void test_recv_epoch_trial(void)
{
    /* Node B (receiver) at game 1, node 2. */
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* B knows that source 1 (Node A) is at epoch 3. */
    atalaia_radio_proto_set_source_epoch(&rp, 1, 3);

    /* Build a packet from Node A with epoch 3. */
    uint8_t payload[] = {0x01, 0x02, 0x03, 0x04};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    size_t pkt_len =
        build_test_packet(1, 1, 0, 3, test_key, payload, sizeof(payload), pkt, sizeof(pkt));
    CHECK(pkt_len > 0);

    /* Feed the packet to B's on_recv. */
    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, pkt_len);
    rx.len = pkt_len;
    rx.rssi = -50;
    rx.timestamp_ms = 1000;

    atalaia_header_t out_hdr;
    uint8_t out_payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_payload_len = 0;
    bool ok = atalaia_radio_proto_on_recv(&rp, &rx, &out_hdr, out_payload, &out_payload_len);

    CHECK(ok);
    CHECK(out_hdr.source == 1);
    CHECK(out_payload_len == sizeof(payload));
    CHECK(memcmp(out_payload, payload, sizeof(payload)) == 0);
}

static void test_recv_epoch_trial_reboot(void)
{
    /* Node B knows source 1 at epoch 3. */
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    atalaia_radio_proto_set_source_epoch(&rp, 1, 3);

    /* Node A rebooted and is now at epoch 4. */
    uint8_t payload[] = {0xAA, 0xBB};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    size_t pkt_len =
        build_test_packet(1, 1, 0, 4, test_key, payload, sizeof(payload), pkt, sizeof(pkt));
    CHECK(pkt_len > 0);

    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, pkt_len);
    rx.len = pkt_len;
    rx.rssi = -60;
    rx.timestamp_ms = 2000;

    atalaia_header_t out_hdr;
    uint8_t out_payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_payload_len = 0;
    bool ok = atalaia_radio_proto_on_recv(&rp, &rx, &out_hdr, out_payload, &out_payload_len);

    /* B tried epoch 3 (fail), then 4 (success). Adopts 4. */
    CHECK(ok);
    CHECK(out_hdr.source == 1);

    /* Verify the source table was updated to epoch 4. */
    int found = -1;
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES; i++) {
        if (rp.source_epochs[i].valid && rp.source_epochs[i].source == 1) {
            found = i;
            break;
        }
    }
    CHECK(found >= 0);
    CHECK(rp.source_epochs[found].epoch == 4);
}

static void test_recv_reject_lower_epoch(void)
{
    /* Node B knows source 1 at epoch 3. */
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    atalaia_radio_proto_set_source_epoch(&rp, 1, 3);

    /* Node A sends with epoch 2 (lower -- replayed or corrupted). */
    uint8_t payload[] = {0xDE, 0xAD};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    size_t pkt_len =
        build_test_packet(1, 1, 0, 2, test_key, payload, sizeof(payload), pkt, sizeof(pkt));
    CHECK(pkt_len > 0);

    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, pkt_len);
    rx.len = pkt_len;
    rx.rssi = -70;
    rx.timestamp_ms = 3000;

    atalaia_header_t out_hdr;
    uint8_t out_payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_payload_len = 0;
    bool ok = atalaia_radio_proto_on_recv(&rp, &rx, &out_hdr, out_payload, &out_payload_len);

    /* B tried epoch 3 (fail), then 4 (fail). Both miss. */
    CHECK(!ok);
}

static void test_recv_unknown_source(void)
{
    /* Node B has no known sources. */
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* Node C (source=3) sends with epoch 1. */
    uint8_t payload[] = {0xCA, 0xFE};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    size_t pkt_len =
        build_test_packet(1, 3, 0, 1, test_key, payload, sizeof(payload), pkt, sizeof(pkt));
    CHECK(pkt_len > 0);

    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, pkt_len);
    rx.len = pkt_len;
    rx.rssi = -80;
    rx.timestamp_ms = 4000;

    atalaia_header_t out_hdr;
    uint8_t out_payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_payload_len = 0;
    bool ok = atalaia_radio_proto_on_recv(&rp, &rx, &out_hdr, out_payload, &out_payload_len);

    /* B tried epoch 0 (fail), then epoch 1 (success). */
    CHECK(ok);
    CHECK(out_hdr.source == 3);

    /* C should be added to the source table with epoch 1. */
    int found = -1;
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES; i++) {
        if (rp.source_epochs[i].valid && rp.source_epochs[i].source == 3) {
            found = i;
            break;
        }
    }
    CHECK(found >= 0);
    CHECK(rp.source_epochs[found].epoch == 1);
}

/* ---- Runner --------------------------------------------------------------- */

void run_radio_protocol_tests(void)
{
    test_boot_epoch();
    test_boot_epoch_first_boot();
    test_boot_epoch_nvs_write_fail();
    test_seq_wrap_increments_epoch();
    test_seq_wrap_nvs_fail_blocks_tx();
    test_epoch_exhaustion();
    test_recv_epoch_trial();
    test_recv_epoch_trial_reboot();
    test_recv_reject_lower_epoch();
    test_recv_unknown_source();
}
