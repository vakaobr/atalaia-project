/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the radio protocol layer: epoch persistence per game key (boot,
 * reboot, new key, forgetting the oldest key, power cuts, migration from the
 * single epoch, wrap, exhaustion, NVS failure) and receiver-side epoch trial.
 *
 * Uses an in-process NVS stub that records calls and returns
 * configurable results, and the test-stub crypto backend from
 * packet.h (XOR + FNV-1a, NOT cryptographically secure).
 */
#include <string.h>

#include "check.h"
#include "epoch_store_fake.h"
#include "radio/radio_protocol.h"

/* ---- NVS test stub -------------------------------------------------------- */

static int test_nvs_read_key(void *ctx, uint8_t key[16])
{
    (void)ctx;
    (void)key;
    return -1;
}

static int test_nvs_write_key(void *ctx, const uint8_t key[16])
{
    (void)ctx;
    (void)key;
    return 0;
}

static int test_nvs_erase_key(void *ctx)
{
    (void)ctx;
    return 0;
}

#define TEST_OPS(f) EPOCH_FAKE_OPS(f, test_nvs_read_key, test_nvs_write_key, test_nvs_erase_key)

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

/* ---- Epoch persistence tests (per game key: RFC 0001 amendment 2026-10-22) -- */

static const uint8_t other_key[16] = {0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8,
                                      0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF, 0x00};

/* One boot of a node with key in a game: returns its epoch (0 if refused). */
static uint16_t boot_with(epoch_fake_t *f, const uint8_t key[16], bool resuming)
{
    static atalaia_radio_nvs_ops_t ops;
    ops = TEST_OPS(f);
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, key);
    if (!atalaia_radio_proto_boot_epoch(&rp, resuming)) {
        CHECK(rp.tx_blocked);
        return 0;
    }
    CHECK(!rp.tx_blocked && rp.seq == 0);
    return rp.epoch;
}

static void test_epoch_tag_vector(void)
{
    /* protocol/vectors/epoch_tag.json (RFC 0001 amendment of 2026-10-22; computed with Python's
     * hmac module, not this code). */
    static const struct {
        uint8_t key[16];
        uint8_t tag[8];
    } v[] = {
        {{0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
          0x0f},
         {0x45, 0xaa, 0xb1, 0xd2, 0x5d, 0x35, 0x15, 0xd2}},
        {{0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
          0xff},
         {0x56, 0xc4, 0xe1, 0xd0, 0x29, 0x97, 0x26, 0xc2}},
        {{0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f,
          0x3c},
         {0x13, 0x67, 0xdf, 0x1e, 0x02, 0xd5, 0x36, 0xf0}},
    };
    uint8_t tag[ATALAIA_EPOCH_TAG_SIZE];
    for (size_t i = 0; i < sizeof(v) / sizeof(v[0]); i++) {
        atalaia_radio_epoch_tag(v[i].key, tag);
        CHECK(memcmp(tag, v[i].tag, 8) == 0);
    }
    const uint8_t *k1 = v[0].key;
    atalaia_radio_epoch_tag(k1, tag);
    /* The same key always gives the same tag; another key another one. */
    uint8_t again[ATALAIA_EPOCH_TAG_SIZE], other[ATALAIA_EPOCH_TAG_SIZE];
    atalaia_radio_epoch_tag(k1, again);
    atalaia_radio_epoch_tag(other_key, other);
    CHECK(memcmp(tag, again, 8) == 0 && memcmp(tag, other, 8) != 0);
}

static void test_boot_epoch(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    /* First boot ever: epoch 1, stored (one write) before anything is sent. */
    CHECK(boot_with(&f, test_key, false) == 1);
    CHECK(f.writes == 1 && epoch_fake_of(&f, test_key) == 1);
    /* Reboots in the same game: up by one each time, never reused. */
    for (int i = 2; i <= 6; i++) CHECK(boot_with(&f, test_key, true) == i);
    CHECK(epoch_fake_of(&f, test_key) == 6 && f.writes == 6);
    /* A join of the same game again (not a resume) goes on too. */
    CHECK(boot_with(&f, test_key, false) == 7);
}

static void test_boot_epoch_per_key(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    for (int i = 0; i < 30; i++) boot_with(&f, test_key, false);
    CHECK(epoch_fake_of(&f, test_key) == 30);
    /* A new game (a new key) starts at 1, whatever the box did before... */
    CHECK(boot_with(&f, other_key, false) == 1);
    CHECK(boot_with(&f, other_key, true) == 2);
    /* ...and the earlier key, back again (an old card tapped), goes on above 30. */
    CHECK(boot_with(&f, test_key, false) == 31);
    CHECK(epoch_fake_of(&f, other_key) == 2);
}

/* Review finding 2 (decision BN-19): a forgotten key coming back (an old game's card tapped after
 * eight newer games) restarted at 1 and reused its own nonces. Now the store keeps 16 keys with
 * their epochs and 48 older ones by their tag alone; an old key it still keeps goes on above, a
 * retired one is refused (its epochs are no longer known), and only a key older than 64 newer
 * ones is new to it again (the documented residual). */
static void test_boot_epoch_old_keys(void)
{
    static epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    static atalaia_radio_nvs_ops_t ops;
    ops = TEST_OPS(&f);
    uint8_t keys[70][16];
    for (int k = 0; k < 70; k++) {
        for (int i = 0; i < 16; i++) keys[k][i] = (uint8_t)(k * 31 + i);
    }
    CHECK(boot_with(&f, keys[0], false) == 1);
    for (int r = 0; r < 5; r++) boot_with(&f, keys[0], true); /* reboots: up to 6 */
    for (int k = 1; k < ATALAIA_EPOCH_KEYS; k++) CHECK(boot_with(&f, keys[k], false) == 1);
    /* Still kept: the old card goes on above its epoch 6. */
    CHECK(boot_with(&f, keys[0], false) == 7);
    /* Sixteen newer keys: keys[0] is retired, refused, and says so before any join. */
    for (int k = 1; k <= ATALAIA_EPOCH_KEYS; k++) CHECK(boot_with(&f, keys[k + 16], false) == 1);
    CHECK(f.blob[0] == ATALAIA_EPOCH_STORE_VER && f.blob[1] == ATALAIA_EPOCH_KEYS);
    CHECK(epoch_fake_of(&f, keys[0]) == -1);
    CHECK(atalaia_radio_epoch_key_retired(&ops, keys[0]));
    CHECK(!atalaia_radio_epoch_key_retired(&ops, keys[17])); /* kept */
    CHECK(!atalaia_radio_epoch_key_retired(&ops, keys[69])); /* new */
    CHECK(boot_with(&f, keys[0], false) == 0);
    CHECK(epoch_fake_of(&f, keys[0]) == -1 && atalaia_radio_epoch_key_retired(&ops, keys[0]));
    /* The blob's size: 16 records and the retired tags. */
    CHECK(f.len ==
          4 + ATALAIA_EPOCH_KEYS * ATALAIA_EPOCH_REC_SIZE + f.blob[2] * ATALAIA_EPOCH_TAG_SIZE);
    /* A version 1 blob (8 keys, no retired tags) still reads. */
    memset(&f, 0, sizeof(f));
    f.blob[0] = 1;
    f.blob[1] = 1;
    atalaia_radio_epoch_tag(keys[3], f.blob + 2);
    f.blob[2 + 9] = 9;
    f.len = 2 + ATALAIA_EPOCH_REC_SIZE;
    CHECK(boot_with(&f, keys[3], true) == 10);
    CHECK(f.blob[0] == ATALAIA_EPOCH_STORE_VER && epoch_fake_of(&f, keys[3]) == 10);
}

static void test_boot_epoch_nvs_write_fail(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    f.write_fail = true;
    CHECK(boot_with(&f, test_key, false) == 0);
    /* An unreadable store: no guess. */
    memset(&f, 0, sizeof(f));
    f.read_fails = true;
    CHECK(boot_with(&f, test_key, false) == 0);
    /* A malformed blob: no guess either. */
    memset(&f, 0, sizeof(f));
    f.blob[0] = 9;
    f.len = 2;
    CHECK(boot_with(&f, test_key, false) == 0);
    /* No key: no epoch. */
    memset(&f, 0, sizeof(f));
    static atalaia_radio_nvs_ops_t ops;
    ops = TEST_OPS(&f);
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    CHECK(!atalaia_radio_proto_boot_epoch(&rp, false) && rp.tx_blocked);
    /* The last epoch used up: refused. */
    memset(&f, 0, sizeof(f));
    boot_with(&f, test_key, false);
    f.blob[4 + 8] = 0xFF;
    f.blob[4 + 9] = 0xFF;
    CHECK(boot_with(&f, test_key, true) == 0);
    /* A blob longer than the store can be (NVS's invalid length): an error, no guess. */
    memset(&f, 0, sizeof(f));
    boot_with(&f, test_key, false);
    f.len = ATALAIA_EPOCH_STORE_MAX + 2;
    CHECK(boot_with(&f, test_key, true) == 0);
}

/* Power cuts at every point of a boot: the store is the old blob or the new one (one atomic
 * write), and nothing is sent before the write. Whatever happens, no (epoch, seq) is used twice
 * with one key, and a new key never inherits another key's epoch. */
static void test_boot_epoch_power_cuts(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    CHECK(boot_with(&f, test_key, false) == 1); /* epoch 1 used on the air */
    /* Cut before the write of a reboot: nothing changed, nothing sent... */
    f.write_fail = true;
    CHECK(boot_with(&f, test_key, true) == 0);
    f.write_fail = false;
    CHECK(epoch_fake_of(&f, test_key) == 1);
    /* ...and the next boot takes 2, which no packet used. */
    CHECK(boot_with(&f, test_key, true) == 2);
    /* Cut after the write, before any packet: 3 stored, never used; the next boot takes 4. */
    CHECK(boot_with(&f, test_key, true) == 3);
    CHECK(boot_with(&f, test_key, true) == 4);
    /* A new key's first boot cut before its write: the old key's record is intact, and the new
     * key still starts at 1 (no packet used it), never at the old key's epoch. */
    f.write_fail = true;
    CHECK(boot_with(&f, other_key, false) == 0);
    f.write_fail = false;
    CHECK(epoch_fake_of(&f, other_key) == -1 && epoch_fake_of(&f, test_key) == 4);
    CHECK(boot_with(&f, other_key, false) == 1);
    /* The tag and the epoch are one record in one write: one write per boot. */
    int before = f.writes;
    CHECK(boot_with(&f, test_key, true) == 5);
    CHECK(f.writes == before + 1);
}

static void test_boot_epoch_migration(void)
{
    /* The firmware before the amendment left one u16 (127, a box flashed long ago). */
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    f.legacy = 127;
    f.have_legacy = true;
    /* Resuming the stored game (its key): it goes on from the stored value. */
    CHECK(boot_with(&f, test_key, true) == 128);
    CHECK(boot_with(&f, test_key, true) == 129);
    /* The next game starts at 1; the old value is never read again. */
    CHECK(boot_with(&f, other_key, false) == 1);
    CHECK(boot_with(&f, other_key, true) == 2);

    /* A first resume whose write fails (a power cut): nothing sent, the old value still there,
     * and the next resume takes it up as if nothing had happened. */
    memset(&f, 0, sizeof(f));
    f.legacy = 127;
    f.have_legacy = true;
    f.write_fail = true;
    CHECK(boot_with(&f, test_key, true) == 0);
    f.write_fail = false;
    CHECK(boot_with(&f, test_key, true) == 128);

    /* Not resuming (the update came between games): a new game starts at 1. Left (BN-19): a card
     * of a game played before the update, tapped again after it, starts at 1 too and reuses that
     * old game's nonces; the old counter cannot say which keys it covered. */
    memset(&f, 0, sizeof(f));
    f.legacy = 127;
    f.have_legacy = true;
    CHECK(boot_with(&f, other_key, false) == 1);
    /* Once the store exists, a later resume does not pick the old value up. */
    CHECK(boot_with(&f, other_key, true) == 2);
}

/* ---- Sequence-wrap tests -------------------------------------------------- */

static void test_seq_wrap_increments_epoch(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    atalaia_radio_nvs_ops_t ops = TEST_OPS(&f);

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);
    CHECK(atalaia_radio_proto_boot_epoch(&rp, false) && rp.epoch == 1);
    /* Another key's record stays untouched by this key's wrap. */
    CHECK(boot_with(&f, other_key, false) == 1);

    /* Force a wrap on the next send. */
    rp.seq = 65535;
    f.writes = 0;

    /* In the stub build radio_task_send returns false, but advance_seq still runs. */
    atalaia_event_t ev;
    make_test_event(&ev);
    (void)atalaia_radio_proto_send_event(&rp, &ev, NULL);

    /* seq wrapped from 65535 to 0; epoch incremented from 1 to 2, stored for this key. */
    CHECK(rp.seq == 0);
    CHECK(rp.epoch == 2);
    CHECK(f.writes == 1);
    CHECK(epoch_fake_of(&f, test_key) == 2 && epoch_fake_of(&f, other_key) == 1);
    CHECK(!rp.tx_blocked);
    /* A reboot after the wrap goes on above it. */
    CHECK(boot_with(&f, test_key, true) == 3);
}

static void test_seq_wrap_nvs_fail_blocks_tx(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    atalaia_radio_nvs_ops_t ops = TEST_OPS(&f);

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);
    CHECK(atalaia_radio_proto_boot_epoch(&rp, false));

    rp.seq = 65535;
    f.write_fail = true;
    f.writes = 0;

    atalaia_event_t ev;
    make_test_event(&ev);
    bool ok = atalaia_radio_proto_send_event(&rp, &ev, NULL);

    CHECK(!ok);
    CHECK(rp.tx_blocked);
    CHECK(f.writes == 1);
}

static void test_epoch_exhaustion(void)
{
    epoch_fake_t f;
    memset(&f, 0, sizeof(f));
    atalaia_radio_nvs_ops_t ops = TEST_OPS(&f);

    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 1, &atalaia_crypto_test_stub, &ops);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* Nonce space exhausted: epoch=65535, seq=65535. */
    rp.epoch = 65535;
    rp.seq = 65535;

    atalaia_event_t ev;
    make_test_event(&ev);
    bool ok = atalaia_radio_proto_send_event(&rp, &ev, NULL);

    CHECK(!ok);
    CHECK(rp.tx_blocked);
    /* No NVS write should have been attempted. */
    CHECK(f.writes == 0);
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

/* ---- Epoch window (used by the USB modem) -------------------------------- */

static bool recv_window(atalaia_radio_proto_t *rp, uint16_t source, uint16_t epoch, uint16_t window,
                        uint16_t *got_epoch)
{
    uint8_t payload[] = {0x10, 0x20};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    size_t pkt_len = build_test_packet(1, source, 5, epoch, test_key, payload, sizeof(payload), pkt,
                                       sizeof(pkt));
    radio_rx_msg_t rx;
    memcpy(rx.data, pkt, pkt_len);
    rx.len = pkt_len;
    rx.rssi = -50;
    rx.timestamp_ms = 0;
    atalaia_header_t out_hdr;
    uint8_t out_payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_len = 0;
    return atalaia_radio_proto_on_recv_window(rp, &rx, window, &out_hdr, out_payload, &out_len,
                                              got_epoch);
}

static void test_recv_window(void)
{
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);

    /* Unknown source at epoch 6: one-epoch trial misses it, a window of 8 finds it. */
    uint16_t got = 0;
    CHECK(!recv_window(&rp, 4, 6, 1, &got));
    CHECK(recv_window(&rp, 4, 6, 8, &got));
    CHECK(got == 6);

    /* Now known at 6: a jump of 3 (two reboots out of range) is found... */
    CHECK(recv_window(&rp, 4, 9, 8, &got));
    CHECK(got == 9);
    /* ...a lower epoch never is, whatever the window... */
    CHECK(!recv_window(&rp, 4, 8, 64, &got));
    /* ...and a jump past the window is not. */
    CHECK(!recv_window(&rp, 4, 9 + 9, 8, &got));
    CHECK(recv_window(&rp, 4, 9 + 8, 8, &got));
    CHECK(got == 17);

    /* The window stops at the top of the epoch range. */
    atalaia_radio_proto_set_source_epoch(&rp, 5, 65530);
    CHECK(recv_window(&rp, 5, 65535, 64, &got));
    CHECK(got == 65535);
}

/* A box in a crash loop (35 reboots in one game, decision BN-8): its HELLO (and a controller's
 * TIME) is searched ATALAIA_RESTART_EPOCH_WINDOW above, so it is heard again; other packets keep
 * the receiver's window; lower epochs are never accepted. */
static uint32_t clock_ms = 1000;
static uint16_t typed_seq = 7; /* each packet its own counter: a repeat would be a replay */

static bool recv_typed(atalaia_radio_proto_t *rp, uint16_t source, uint16_t epoch, uint8_t type,
                       uint16_t window, uint16_t *got)
{
    uint8_t payload[] = {0x33};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    atalaia_header_t hdr = {ATALAIA_VF_MAKE(1, 0, 0, 1), 1, source, typed_seq++, 2, type};
    size_t n = atalaia_packet_encrypt(&hdr, epoch, test_key, payload, sizeof(payload), pkt,
                                      sizeof(pkt), &atalaia_crypto_test_stub);
    radio_rx_msg_t rx;
    memset(&rx, 0, sizeof(rx));
    memcpy(rx.data, pkt, n);
    rx.len = n;
    rx.timestamp_ms = clock_ms;
    clock_ms += ATALAIA_WIDE_GAP_MS; /* each packet a retry later: within the budget */
    atalaia_header_t out_hdr;
    uint8_t out[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_len = 0;
    return atalaia_radio_proto_on_recv_window(rp, &rx, window, &out_hdr, out, &out_len, got);
}

static void test_recv_after_a_crash_loop(void)
{
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    atalaia_radio_proto_set_source_epoch(&rp, 4, 3);
    uint16_t got = 0;
    /* 35 reboots later: an EVENT is past the window of 16... */
    CHECK(!recv_typed(&rp, 4, 38, ATALAIA_MSG_EVENT, 16, &got));
    /* ...its HELLO is not, and then the rest is heard again. */
    CHECK(recv_typed(&rp, 4, 38, ATALAIA_MSG_HELLO, 16, &got) && got == 38);
    CHECK(recv_typed(&rp, 4, 38, ATALAIA_MSG_EVENT, 16, &got) && got == 38);
    /* A controller's TIME too; and never lower. */
    CHECK(recv_typed(&rp, 4, 38 + ATALAIA_RESTART_EPOCH_WINDOW, ATALAIA_MSG_TIME, 16, &got));
    CHECK(!recv_typed(&rp, 4, 37, ATALAIA_MSG_HELLO, 16, &got));
    CHECK(!recv_typed(&rp, 4, 38 + ATALAIA_RESTART_EPOCH_WINDOW - 1, ATALAIA_MSG_TIME, 16, &got));
}

/* A box that lost its epoch store takes an epoch in [4096, 61439] (SR-27); the receivers find it by
 * the deep search of its HELLO, a slice of the range a retry (SR-110), with no controller's help.
 * Only a HELLO or a TIME is searched so far; the table only goes up; a lower epoch is never found.
 */
static void test_deep_search_finds_a_lost_store_box(void)
{
    static atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    atalaia_radio_proto_set_source_epoch(&rp, 4, 3);
    uint16_t got = 0;
    /* An EVENT is never searched far, a HELLO is, a slice at a time. */
    CHECK(!recv_typed(&rp, 4, 40000, ATALAIA_MSG_EVENT, 16, &got));
    CHECK(rp.deep_searches == 0);
    int tries = 0;
    while (!recv_typed(&rp, 4, 40000, ATALAIA_MSG_HELLO, 16, &got)) {
        tries++;
        CHECK(tries <= 65536 / ATALAIA_DEEP_SLICE + 1);
        if (tries > 65536 / ATALAIA_DEEP_SLICE + 1) return;
    }
    CHECK(got == 40000 && rp.deep_found == 1);
    /* The slice is a bounded cost: (40000 - 260) / 2048 slices before it, each at most once per
     * gap. */
    CHECK(tries >= 19 && rp.deep_searches == (uint32_t)tries + 1);
    /* Now it is the source's epoch: its other packets are heard, a lower epoch never. */
    CHECK(recv_typed(&rp, 4, 40000, ATALAIA_MSG_EVENT, 16, &got) && got == 40000);
    CHECK(!recv_typed(&rp, 4, 39999, ATALAIA_MSG_HELLO, 16, &got));
    CHECK(!recv_typed(&rp, 4, 3, ATALAIA_MSG_HELLO, 16, &got));
    /* A source never heard is searched from epoch 0 the same way. */
    tries = 0;
    while (!recv_typed(&rp, 9, 61000, ATALAIA_MSG_TIME, 16, &got) && tries < 100) tries++;
    CHECK(got == 61000 && tries < 100); /* 30 slices, 20 a minute */
    /* The cursor wraps: a source at epoch 300 (inside the first slice) is found at once. */
    CHECK(recv_typed(&rp, 12, 300, ATALAIA_MSG_HELLO, 16, &got) && got == 300);
}

/* A controller's announcement (SET_PEER_EPOCH, CMD peer) only ever moves a source's epoch up. */
static void test_set_source_epoch_never_goes_back(void)
{
    static atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    uint16_t got = 0;
    CHECK(atalaia_radio_proto_set_source_epoch(&rp, 6, 100));
    CHECK(!atalaia_radio_proto_set_source_epoch(&rp, 6, 50));  /* lower: ignored */
    CHECK(!atalaia_radio_proto_set_source_epoch(&rp, 6, 100)); /* equal: nothing moves */
    CHECK(recv_window(&rp, 6, 100, 16, &got) && got == 100);   /* still heard at 100 */
    CHECK(!recv_window(&rp, 6, 50, 16, &got));
    CHECK(atalaia_radio_proto_set_source_epoch(&rp, 6, 5000));
    CHECK(recv_window(&rp, 6, 5000, 16, &got) && got == 5000);
    CHECK(!atalaia_radio_proto_set_source_epoch(&rp, 6, 4999));
    CHECK(!recv_window(&rp, 6, 100, 16, &got));
}

/* A crypto backend that counts decryptions (the test stub underneath). */
static int decrypts;
static int counting_decrypt(void *ctx, const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                            const uint8_t *aad, size_t aad_len, const uint8_t *ct, size_t ct_len,
                            uint8_t *pt, const uint8_t *tag, size_t tag_len)
{
    decrypts++;
    return atalaia_crypto_test_stub.decrypt(ctx, key, nonce, nonce_len, aad, aad_len, ct, ct_len,
                                            pt, tag, tag_len);
}

/* Review finding 3 (decision BN-20): junk HELLOs (source and type are in the clear) made every
 * receiver try 257 epochs each. Now the normal window first, then a wide search at most once per
 * source every ATALAIA_WIDE_GAP_MS and ATALAIA_WIDE_PER_MIN a minute. */
static void test_wide_search_budget(void)
{
    atalaia_crypto_ops_t counting = atalaia_crypto_test_stub;
    counting.decrypt = counting_decrypt;
    static atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &counting, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    static const uint8_t wrong[16] = {9, 9, 9};
    uint8_t payload[] = {0x33};
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + sizeof(payload) + ATALAIA_RF_MIC_SIZE + 8];
    atalaia_header_t out_hdr;
    uint8_t out[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_len = 0;
    uint16_t got = 0;
    radio_rx_msg_t rx;
    memset(&rx, 0, sizeof(rx));
    /* 1000 junk HELLOs in 10 s from 50 made-up sources (not under the game key). */
    decrypts = 0;
    for (int i = 0; i < 1000; i++) {
        atalaia_header_t h = {
            ATALAIA_VF_MAKE(1, 0, 0, 1), 1, (uint16_t)(100 + i % 50), 1, 2, ATALAIA_MSG_HELLO};
        rx.len = atalaia_packet_encrypt(&h, 0, wrong, payload, sizeof(payload), rx.data,
                                        sizeof(rx.data), &atalaia_crypto_test_stub);
        rx.timestamp_ms = 5000u + (uint32_t)i * 10u;
        CHECK(!atalaia_radio_proto_on_recv_window(&rp, &rx, 16, &out_hdr, out, &out_len, &got));
    }
    /* Without the budget: 257 each, 257000. With it: 17 each, plus 20 wide searches of 240 and a
     * deep slice (SR-110) each. */
    CHECK(decrypts == 1000 * 17 + ATALAIA_WIDE_PER_MIN * (240 + ATALAIA_DEEP_SLICE));
    CHECK(rp.wide_searches == ATALAIA_WIDE_PER_MIN &&
          rp.wide_refused == 1000 - ATALAIA_WIDE_PER_MIN);
    /* A genuine HELLO a minute later is searched and heard; its retry inside the gap is not
     * searched again (it already authenticates in the normal window). */
    atalaia_header_t h = {ATALAIA_VF_MAKE(1, 0, 0, 1), 1, 7, 1, 2, ATALAIA_MSG_HELLO};
    size_t n = atalaia_packet_encrypt(&h, 120, test_key, payload, sizeof(payload), pkt, sizeof(pkt),
                                      &atalaia_crypto_test_stub);
    memcpy(rx.data, pkt, n);
    rx.len = n;
    rx.timestamp_ms = 80000u;
    CHECK(atalaia_radio_proto_on_recv_window(&rp, &rx, 16, &out_hdr, out, &out_len, &got));
    CHECK(got == 120);
}

/* FLD-1: the replay window sits in the per-source table, one entry per source: a field of 30
 * boxes and the controllers (RADIO_PROTO_MAX_SOURCES) each keep their own window, and a replay
 * of any of them is refused. */
static void test_replay_window_per_source(void)
{
    static atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    uint8_t payload[] = {0x33};
    static uint8_t recorded[40][ATALAIA_RF_HEADER_SIZE + 1 + ATALAIA_RF_MIC_SIZE + 8];
    size_t rec_len[40];
    for (uint16_t src = 100; src < 140; src++) {
        atalaia_header_t hdr = {ATALAIA_VF_MAKE(1, 0, 0, 1), 1, src, 5, 2, ATALAIA_MSG_EVENT};
        rec_len[src - 100] =
            atalaia_packet_encrypt(&hdr, 1, test_key, payload, sizeof(payload), recorded[src - 100],
                                   sizeof(recorded[0]), &atalaia_crypto_test_stub);
        radio_rx_msg_t rx;
        memset(&rx, 0, sizeof(rx));
        memcpy(rx.data, recorded[src - 100], rec_len[src - 100]);
        rx.len = rec_len[src - 100];
        atalaia_header_t out_hdr;
        uint8_t out[ATALAIA_RF_PAYLOAD_MAX];
        size_t out_len = 0;
        CHECK(atalaia_radio_proto_on_recv_window(&rp, &rx, 16, &out_hdr, out, &out_len, NULL));
    }
    /* Played back: every one of the 40 sources still remembers its packet. */
    for (int i = 0; i < 40; i++) {
        radio_rx_msg_t rx;
        memset(&rx, 0, sizeof(rx));
        memcpy(rx.data, recorded[i], rec_len[i]);
        rx.len = rec_len[i];
        atalaia_header_t out_hdr;
        uint8_t out[ATALAIA_RF_PAYLOAD_MAX];
        size_t out_len = 0;
        CHECK(!atalaia_radio_proto_on_recv_window(&rp, &rx, 16, &out_hdr, out, &out_len, NULL));
        CHECK(rp.last_replay == ATALAIA_REPLAY_DUPLICATE);
    }
    CHECK(rp.replay_duplicates == 40);
    /* A garbled packet is not a replay: the verdict is only for what authenticated. */
    radio_rx_msg_t bad;
    memset(&bad, 0, sizeof(bad));
    memcpy(bad.data, recorded[0], rec_len[0]);
    bad.len = rec_len[0];
    bad.data[ATALAIA_RF_HEADER_SIZE] ^= 1;
    atalaia_header_t out_hdr;
    uint8_t out[ATALAIA_RF_PAYLOAD_MAX];
    size_t out_len = 0;
    CHECK(!atalaia_radio_proto_on_recv_window(&rp, &bad, 16, &out_hdr, out, &out_len, NULL));
    CHECK(rp.last_replay == ATALAIA_REPLAY_FRESH && rp.replay_duplicates == 40);
}

/* FLD-10: a box that resumes its stored game with no epoch record for its key lost its store.
 * Starting again at epoch 1 would reuse the nonces of its earlier life under the same key (the
 * old store said epoch 7, then was erased): it takes a random epoch far above, or refuses. */
static void test_lost_epoch_store_starts_high(void)
{
    uint8_t key[16];
    memset(key, 0x5a, sizeof(key));
    for (uint32_t seed = 1; seed <= 200; seed++) {
        epoch_fake_t f;
        memset(&f, 0, sizeof(f));
        f.rnd = seed * 2654435761u;
        atalaia_radio_nvs_ops_t ops = EPOCH_FAKE_OPS(&f, NULL, NULL, NULL);
        atalaia_radio_proto_t rp;
        atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, &ops);
        atalaia_radio_proto_set_key(&rp, key);
        CHECK(atalaia_radio_proto_boot_epoch(&rp, true));
        CHECK(rp.epoch >= ATALAIA_EPOCH_LOST_MIN && rp.epoch <= ATALAIA_EPOCH_LOST_MAX);
        CHECK(epoch_fake_of(&f, key) == rp.epoch); /* stored before the first packet */
        CHECK(rp.epoch_lost);
        /* And from there it goes on as ever. */
        CHECK(atalaia_radio_proto_boot_epoch(&rp, true) && rp.epoch > ATALAIA_EPOCH_LOST_MIN);
    }
    /* A new key (a fresh join, not a resume) still starts at 1: its nonces are new. */
    epoch_fake_t g;
    memset(&g, 0, sizeof(g));
    atalaia_radio_nvs_ops_t gops = EPOCH_FAKE_OPS(&g, NULL, NULL, NULL);
    atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, &gops);
    atalaia_radio_proto_set_key(&rp, key);
    CHECK(atalaia_radio_proto_boot_epoch(&rp, false) && rp.epoch == 1 && !rp.epoch_lost);
    /* A resume with a record goes on above it, as ever. */
    CHECK(atalaia_radio_proto_boot_epoch(&rp, true) && rp.epoch == 2);
    /* No random source, or one that fails: the radio stays silent rather than guess. */
    epoch_fake_t h;
    memset(&h, 0, sizeof(h));
    h.no_random = true;
    atalaia_radio_nvs_ops_t hops = EPOCH_FAKE_OPS(&h, NULL, NULL, NULL);
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, &hops);
    atalaia_radio_proto_set_key(&rp, key);
    CHECK(!atalaia_radio_proto_boot_epoch(&rp, true) && rp.tx_blocked && h.writes == 0);
    hops.random_bytes = NULL;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, &hops);
    atalaia_radio_proto_set_key(&rp, key);
    CHECK(!atalaia_radio_proto_boot_epoch(&rp, true) && rp.tx_blocked);
}

/* Review finding 4 (decision BN-21): a receiver that no longer knows a source (its slot reused)
 * took an old recorded HELLO at a low epoch, and then dropped the source's real packets more than
 * 16 above it. A first epoch is now provisional: the real packets are searched up (within the
 * budget) until one authenticates in the normal window, which confirms the source. */
static void test_provisional_source(void)
{
    static atalaia_radio_proto_t rp;
    atalaia_radio_proto_init(&rp, 1, 2, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&rp, test_key);
    uint16_t got = 0;
    /* The recording: the box's HELLO at epoch 3, played back. */
    CHECK(recv_typed(&rp, 9, 3, ATALAIA_MSG_HELLO, 16, &got) && got == 3);
    int idx = -1;
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES; i++) {
        if (rp.source_epochs[i].valid && rp.source_epochs[i].source == 9) idx = i;
    }
    CHECK(idx >= 0 && rp.source_epochs[idx].provisional);
    /* The box is really at epoch 60: its STATE is still heard... */
    CHECK(recv_typed(&rp, 9, 60, ATALAIA_MSG_STATE, 16, &got) && got == 60);
    /* ...the next one authenticates in the normal window: confirmed. */
    CHECK(recv_typed(&rp, 9, 60, ATALAIA_MSG_EVENT, 16, &got) && got == 60);
    CHECK(!rp.source_epochs[idx].provisional);
    /* Confirmed sources keep the normal window for ordinary packets. */
    CHECK(!recv_typed(&rp, 9, 90, ATALAIA_MSG_EVENT, 16, &got));
    /* A source the controller names (SET_PEER_EPOCH) is not provisional. */
    atalaia_radio_proto_set_source_epoch(&rp, 11, 5);
    CHECK(!recv_typed(&rp, 11, 40, ATALAIA_MSG_EVENT, 16, &got));
}

/* ---- Runner --------------------------------------------------------------- */

void run_radio_protocol_tests(void)
{
    test_epoch_tag_vector();
    test_boot_epoch();
    test_boot_epoch_per_key();
    test_boot_epoch_old_keys();
    test_boot_epoch_nvs_write_fail();
    test_boot_epoch_power_cuts();
    test_boot_epoch_migration();
    test_lost_epoch_store_starts_high();
    test_replay_window_per_source();
    test_seq_wrap_increments_epoch();
    test_seq_wrap_nvs_fail_blocks_tx();
    test_epoch_exhaustion();
    test_recv_epoch_trial();
    test_recv_epoch_trial_reboot();
    test_recv_reject_lower_epoch();
    test_recv_unknown_source();
    test_recv_window();
    test_recv_after_a_crash_loop();
    test_wide_search_budget();
    test_deep_search_finds_a_lost_store_box();
    test_set_source_epoch_never_goes_back();
    test_provisional_source();
}
