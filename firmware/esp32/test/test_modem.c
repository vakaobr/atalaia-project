/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB modem logic (modem.c) with in-memory I/O: commands, TX encryption
 * and nonce guard, RX decryption with the epoch window, dedupe, and every
 * error path. Uses the test-stub crypto backend from packet.h; the real
 * AES-CCM path is covered end to end by controller/tests/test_modem_host.py
 * against the host modem (test/modem_host/).
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "modem/modem.h"

#define MAX_OUT 16

static const uint8_t KEY[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
static const uint8_t OTHER_KEY[16] = {16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1};

typedef struct {
    /* Frames the modem wrote to the serial link, decoded. */
    modem_decoder_t dec;
    int frames;
    uint8_t type[MAX_OUT];
    size_t len[MAX_OUT];
    uint8_t payload[MAX_OUT][MODEM_FRAME_PAYLOAD_MAX];
    /* Packets handed to the radio. */
    int sent;
    uint8_t pkt[MAX_OUT][RADIO_MAX_PKT_LEN];
    size_t pkt_len[MAX_OUT];
    uint32_t tag[MAX_OUT];
    bool radio_full;
    uint32_t channel;
    int channel_calls;
    uint32_t now;
} fake_io_t;

static fake_io_t io_state;

static void out_frame(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    fake_io_t *f = (fake_io_t *)ctx;
    if (f->frames >= MAX_OUT) return;
    f->type[f->frames] = type;
    f->len[f->frames] = len;
    memcpy(f->payload[f->frames], payload, len);
    f->frames++;
}

static int fake_write(void *ctx, const uint8_t *buf, size_t len)
{
    fake_io_t *f = (fake_io_t *)ctx;
    modem_decoder_feed(&f->dec, buf, len, out_frame, f);
    return 0;
}

static bool fake_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    fake_io_t *f = (fake_io_t *)ctx;
    if (f->radio_full || f->sent >= MAX_OUT) return false;
    memcpy(f->pkt[f->sent], pkt, len);
    f->pkt_len[f->sent] = len;
    f->tag[f->sent] = tag;
    f->sent++;
    return true;
}

static int fake_channel(void *ctx, uint32_t hz)
{
    fake_io_t *f = (fake_io_t *)ctx;
    f->channel = hz;
    f->channel_calls++;
    return 0;
}

static uint32_t fake_duty(void *ctx)
{
    (void)ctx;
    return 123456;
}

static uint32_t fake_now(void *ctx)
{
    return ((fake_io_t *)ctx)->now;
}

static modem_t modem;

static void setup(bool radio, uint16_t window)
{
    memset(&io_state, 0, sizeof(io_state));
    modem_decoder_init(&io_state.dec);
    io_state.now = 1000;
    modem_io_t io = {
        .serial_write = fake_write,
        .radio_send = fake_send,
        .set_channel = fake_channel,
        .duty_cycle_remaining_ms = fake_duty,
        .now_ms = fake_now,
        .ctx = &io_state,
    };
    modem_init(&modem, &io, &atalaia_crypto_test_stub, "test-1.0", radio, window);
}

static void clear_out(void)
{
    io_state.frames = 0;
    io_state.sent = 0;
}

/* Sends a frame to the modem as the controller would (through the decoder). */
static void host_send(uint8_t type, const uint8_t *payload, size_t len)
{
    uint8_t frame[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(type, payload, len, frame, sizeof(frame));
    CHECK(n > 0);
    modem_feed_serial(&modem, frame, n);
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static void configure(uint16_t game, uint16_t node, uint16_t epoch, uint8_t hops, uint32_t hz,
                      const uint8_t key[16])
{
    uint8_t p[MODEM_CONFIGURE_LEN];
    p[0] = MODEM_CMD_CONFIGURE;
    put16(p + 1, game);
    put16(p + 3, node);
    put16(p + 5, epoch);
    p[7] = hops;
    put32(p + 8, hz);
    memcpy(p + 12, key, 16);
    host_send(MODEM_FRAME_CMD, p, sizeof(p));
}

/* The last frame of a type, or -1. */
static int last_of(uint8_t type)
{
    for (int i = io_state.frames - 1; i >= 0; i--) {
        if (io_state.type[i] == type) return i;
    }
    return -1;
}

static bool status_has(const char *needle)
{
    int i = last_of(MODEM_FRAME_STATUS);
    if (i < 0) return false;
    char json[MODEM_FRAME_PAYLOAD_MAX + 1];
    memcpy(json, io_state.payload[i], io_state.len[i]);
    json[io_state.len[i]] = '\0';
    return strstr(json, needle) != NULL;
}

/* TX frame: header + plaintext. */
static void host_tx(uint16_t game, uint16_t source, uint16_t seq, uint8_t hop, const char *text)
{
    atalaia_header_t h = {
        .version_flags = ATALAIA_VF_MAKE(1, 2, 0, 0),
        .game_id = game,
        .source = source,
        .seq = seq,
        .hop_limit = hop,
        .type = 5,
    };
    uint8_t buf[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + 8];
    atalaia_header_encode(&h, buf);
    size_t n = strlen(text);
    memcpy(buf + ATALAIA_RF_HEADER_SIZE, text, n);
    host_send(MODEM_FRAME_TX, buf, ATALAIA_RF_HEADER_SIZE + n);
}

static int tx_ack_status(uint16_t *seq)
{
    int i = last_of(MODEM_FRAME_TX_ACK);
    if (i < 0 || io_state.len[i] != 3) return -1;
    if (seq) *seq = (uint16_t)((io_state.payload[i][0] << 8) | io_state.payload[i][1]);
    return io_state.payload[i][2];
}

/* A packet as a box would send it. */
static size_t air_packet(uint16_t game, uint16_t source, uint16_t seq, uint16_t epoch,
                         const uint8_t key[16], const char *text, uint8_t *out)
{
    atalaia_header_t h = {
        .version_flags = ATALAIA_VF_MAKE(1, 1, 1, 1),
        .game_id = game,
        .source = source,
        .seq = seq,
        .hop_limit = 2,
        .type = 2,
    };
    return atalaia_packet_encrypt(&h, epoch, key, (const uint8_t *)text, strlen(text), out,
                                  RADIO_MAX_PKT_LEN, &atalaia_crypto_test_stub);
}

/* ---- Tests ---------------------------------------------------------------- */

static void test_ident_and_ping(void)
{
    setup(true, 16);
    modem_send_ident(&modem);
    CHECK(io_state.frames == 1 && io_state.type[0] == MODEM_FRAME_IDENT);
    char json[MODEM_FRAME_PAYLOAD_MAX + 1];
    memcpy(json, io_state.payload[0], io_state.len[0]);
    json[io_state.len[0]] = '\0';
    CHECK(strstr(json, "\"fw\":\"atalaia-modem\"") != NULL);
    CHECK(strstr(json, "\"fw_version\":\"test-1.0\"") != NULL);
    CHECK(strstr(json, "\"radio\":\"sx1262\"") != NULL);
    CHECK(strstr(json, "\"epoch_window\":16") != NULL);

    uint8_t ping[5] = {MODEM_CMD_PING};
    put32(ping + 1, 4242);
    host_send(MODEM_FRAME_CMD, ping, sizeof(ping));
    CHECK(status_has("\"ping\":4242"));
    CHECK(status_has("\"configured\":false"));
    CHECK(status_has("\"duty_ms\":123456"));

    uint8_t ident = MODEM_CMD_IDENT;
    clear_out();
    host_send(MODEM_FRAME_CMD, &ident, 1);
    CHECK(io_state.frames == 1 && io_state.type[0] == MODEM_FRAME_IDENT);
}

static void test_configure_validation(void)
{
    setup(true, 16);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    CHECK(status_has("\"configured\":true"));
    CHECK(status_has("\"game_id\":4660"));
    CHECK(io_state.channel == 869525000 && io_state.channel_calls == 1);

    clear_out();
    configure(0x1234, 0, 1, 4, 869525000, KEY); /* max_hops above 3 */
    int e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_BAD_PARAMS);
    CHECK(last_of(MODEM_FRAME_STATUS) < 0);

    clear_out();
    configure(0x1234, 0, 1, 2, 915000000, KEY); /* not an EU868 sub-band */
    e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_BAD_PARAMS);

    clear_out();
    uint8_t short_cfg[5] = {MODEM_CMD_CONFIGURE, 1, 2, 3, 4};
    host_send(MODEM_FRAME_CMD, short_cfg, sizeof(short_cfg));
    e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_BAD_FRAME);

    clear_out();
    uint8_t unknown = 0x7E;
    host_send(MODEM_FRAME_CMD, &unknown, 1);
    e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_UNKNOWN_CMD);

    clear_out();
    host_send(MODEM_FRAME_RX, &unknown, 1); /* modem -> host type sent by the host */
    e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_UNKNOWN_TYPE);

    clear_out();
    uint8_t ch[5] = {MODEM_CMD_SET_CHANNEL};
    put32(ch + 1, 868100000);
    host_send(MODEM_FRAME_CMD, ch, sizeof(ch));
    CHECK(status_has("\"channel_hz\":868100000"));
}

static void test_tx_encrypts_and_acks(void)
{
    setup(true, 16);
    host_tx(0x1234, 0, 1, 2, "hello");
    CHECK(tx_ack_status(NULL) == MODEM_TX_NOT_CONFIGURED);
    CHECK(io_state.sent == 0);

    configure(0x1234, 0, 7, 2, 869525000, KEY);
    clear_out();
    host_tx(0x1234, 0, 1, 3, "hello"); /* hop_limit 3 above the configured 2 */
    CHECK(io_state.sent == 1);
    CHECK(io_state.tag[0] == 2); /* seq + 1 */
    CHECK(io_state.pkt_len[0] == ATALAIA_RF_HEADER_SIZE + 5 + ATALAIA_RF_MIC_SIZE);

    atalaia_header_t h;
    uint8_t plain[ATALAIA_RF_PAYLOAD_MAX];
    size_t plain_len = 0;
    CHECK(atalaia_packet_decrypt(io_state.pkt[0], io_state.pkt_len[0], 7, KEY, &h, plain,
                                 &plain_len, &atalaia_crypto_test_stub));
    CHECK(plain_len == 5 && memcmp(plain, "hello", 5) == 0);
    CHECK(ATALAIA_VF_ENC(h.version_flags) == 1);
    CHECK(ATALAIA_VF_PRIO(h.version_flags) == 2);
    CHECK(h.hop_limit == 2); /* clamped */
    /* The wrong epoch does not decrypt it: the modem used the configured one. */
    CHECK(!atalaia_packet_decrypt(io_state.pkt[0], io_state.pkt_len[0], 6, KEY, &h, plain,
                                  &plain_len, &atalaia_crypto_test_stub));

    /* No TX_ACK until the radio reports the outcome. */
    CHECK(last_of(MODEM_FRAME_TX_ACK) < 0);
    modem_on_tx_result(&modem, io_state.tag[0], MODEM_TX_OK);
    uint16_t seq = 0;
    CHECK(tx_ack_status(&seq) == MODEM_TX_OK && seq == 1);
    modem_on_tx_result(&modem, 9, MODEM_TX_DUTY_CYCLE);
    CHECK(tx_ack_status(&seq) == MODEM_TX_DUTY_CYCLE && seq == 8);
    CHECK(modem.count.tx_ok == 1 && modem.count.tx_fail == 1);
}

static void test_tx_nonce_guard(void)
{
    setup(true, 16);
    configure(0x1234, 0, 3, 2, 869525000, KEY);
    host_tx(0x1234, 0, 10, 2, "a");
    CHECK(io_state.sent == 1);
    clear_out();
    host_tx(0x1234, 0, 10, 2, "b"); /* same (epoch, seq) */
    CHECK(tx_ack_status(NULL) == MODEM_TX_NONCE_REUSE);
    host_tx(0x1234, 0, 9, 2, "c"); /* lower seq */
    CHECK(tx_ack_status(NULL) == MODEM_TX_NONCE_REUSE);
    CHECK(io_state.sent == 0);

    /* Same game, lower epoch: refused too. */
    configure(0x1234, 0, 2, 2, 869525000, KEY);
    clear_out();
    host_tx(0x1234, 0, 500, 2, "d");
    CHECK(tx_ack_status(NULL) == MODEM_TX_NONCE_REUSE);

    /* The controller restarted: new epoch, seq from 0 again. */
    configure(0x1234, 0, 4, 2, 869525000, KEY);
    clear_out();
    host_tx(0x1234, 0, 0, 2, "e");
    CHECK(io_state.sent == 1);

    /* A new game (new key) starts a fresh nonce space. */
    configure(0x5678, 0, 1, 2, 869525000, OTHER_KEY);
    clear_out();
    host_tx(0x5678, 0, 0, 2, "f");
    CHECK(io_state.sent == 1);
}

static void test_tx_rejects_bad_packets(void)
{
    setup(true, 16);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    clear_out();
    host_tx(0x9999, 0, 1, 2, "x"); /* another game */
    CHECK(tx_ack_status(NULL) == MODEM_TX_INVALID);
    host_tx(0x1234, 5, 2, 2, "x"); /* not the controller's source */
    CHECK(tx_ack_status(NULL) == MODEM_TX_INVALID);

    char big[ATALAIA_RF_PAYLOAD_MAX + 2];
    memset(big, 'z', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    host_tx(0x1234, 0, 3, 2, big);
    CHECK(tx_ack_status(NULL) == MODEM_TX_INVALID);

    uint8_t shorty[4] = {0x2E, 0x12, 0x34, 0};
    host_send(MODEM_FRAME_TX, shorty, sizeof(shorty));
    int e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_BAD_FRAME);
    CHECK(io_state.sent == 0);

    io_state.radio_full = true;
    host_tx(0x1234, 0, 4, 2, "x");
    CHECK(tx_ack_status(NULL) == MODEM_TX_QUEUE_FULL);

    setup(false, 16); /* no radio chip */
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    host_tx(0x1234, 0, 1, 2, "x");
    CHECK(tx_ack_status(NULL) == MODEM_TX_NO_RADIO);
    CHECK(io_state.channel_calls == 0);
}

/* Reads the RX frame i: header, plaintext, rssi, snr, epoch. */
static bool rx_frame(int i, atalaia_header_t *h, char *text, int8_t *rssi, int8_t *snr,
                     uint16_t *epoch)
{
    if (i < 0 || io_state.type[i] != MODEM_FRAME_RX) return false;
    size_t len = io_state.len[i];
    const uint8_t *p = io_state.payload[i];
    if (len < ATALAIA_RF_HEADER_SIZE + 4) return false;
    atalaia_header_decode(p, h);
    size_t text_len = len - ATALAIA_RF_HEADER_SIZE - 4;
    memcpy(text, p + ATALAIA_RF_HEADER_SIZE, text_len);
    text[text_len] = '\0';
    *rssi = (int8_t)p[len - 4];
    *snr = (int8_t)p[len - 3];
    *epoch = (uint16_t)((p[len - 2] << 8) | p[len - 1]);
    return true;
}

static void test_rx_forwards_and_dedupes(void)
{
    setup(true, 16);
    uint8_t pkt[RADIO_MAX_PKT_LEN];
    size_t n = air_packet(0x1234, 7, 3, 0, KEY, "zone", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 5);
    CHECK(io_state.frames == 0); /* not configured yet */

    configure(0x1234, 0, 1, 2, 869525000, KEY);
    clear_out();
    modem_on_air_rx(&modem, pkt, n, -60, 5);
    atalaia_header_t h;
    char text[ATALAIA_RF_PAYLOAD_MAX + 1];
    int8_t rssi = 0, snr = 0;
    uint16_t epoch = 99;
    CHECK(rx_frame(last_of(MODEM_FRAME_RX), &h, text, &rssi, &snr, &epoch));
    CHECK(h.source == 7 && h.seq == 3 && h.type == 2 && h.hop_limit == 2);
    CHECK(strcmp(text, "zone") == 0);
    CHECK(rssi == -60 && snr == 5 && epoch == 0);

    /* A relayed copy (hop_limit decremented) is a duplicate. */
    clear_out();
    pkt[7] = 1;
    modem_on_air_rx(&modem, pkt, n, -70, 1);
    CHECK(io_state.frames == 0);
    CHECK(modem.count.rx_dupes == 1);

    /* The box rebooted: epoch 1, seq 3 again. Not a duplicate. */
    n = air_packet(0x1234, 7, 3, 1, KEY, "again", pkt);
    modem_on_air_rx(&modem, pkt, n, -61, 4);
    CHECK(rx_frame(last_of(MODEM_FRAME_RX), &h, text, &rssi, &snr, &epoch));
    CHECK(strcmp(text, "again") == 0 && epoch == 1);

    /* Dedupe entries expire after 30 s. */
    clear_out();
    io_state.now += MODEM_DEDUPE_EXPIRY_MS + 1;
    modem_on_air_rx(&modem, pkt, n, -61, 4);
    CHECK(last_of(MODEM_FRAME_RX) >= 0);
}

static void test_rx_drops_foreign_and_forged(void)
{
    setup(true, 16);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    clear_out();
    uint8_t pkt[RADIO_MAX_PKT_LEN];

    size_t n = air_packet(0x4321, 7, 1, 0, KEY, "other game", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    n = air_packet(0x1234, 0, 1, 0, KEY, "our own echo", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(modem.count.rx_dropped == 2);

    n = air_packet(0x1234, 7, 1, 0, OTHER_KEY, "wrong key", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    n = air_packet(0x1234, 8, 1, 0, KEY, "tampered", pkt);
    pkt[ATALAIA_RF_HEADER_SIZE] ^= 0x01;
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(modem.count.rx_auth_fail == 2);
    CHECK(io_state.frames == 0);

    modem_on_air_rx(&modem, pkt, 5, -60, 0); /* shorter than header + MIC */
    CHECK(modem.count.rx_dropped == 3);
}

static void test_rx_epoch_window(void)
{
    uint8_t pkt[RADIO_MAX_PKT_LEN];
    atalaia_header_t h;
    char text[ATALAIA_RF_PAYLOAD_MAX + 1];
    int8_t rssi, snr;
    uint16_t epoch = 0;

    /* ADR-P2-2's one-epoch trial misses a box that joined at epoch 5. */
    setup(true, 1);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    size_t n = air_packet(0x1234, 9, 1, 5, KEY, "late", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(modem.count.rx_auth_fail == 1);

    /* The modem's window finds it, and remembers epoch 5. */
    setup(true, 16);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    clear_out();
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(rx_frame(last_of(MODEM_FRAME_RX), &h, text, &rssi, &snr, &epoch));
    CHECK(epoch == 5);

    /* A replay from a lower epoch is never accepted. */
    clear_out();
    n = air_packet(0x1234, 9, 2, 4, KEY, "replay", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(io_state.frames == 0);

    /* Beyond the window: not found... */
    n = air_packet(0x1234, 9, 3, 5 + 17, KEY, "far", pkt);
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(io_state.frames == 0);

    /* ...until the controller tells the modem the box's epoch. */
    uint8_t peer[5] = {MODEM_CMD_SET_PEER_EPOCH};
    put16(peer + 1, 9);
    put16(peer + 3, 20);
    host_send(MODEM_FRAME_CMD, peer, sizeof(peer));
    CHECK(status_has("\"configured\":true"));
    clear_out();
    modem_on_air_rx(&modem, pkt, n, -60, 0);
    CHECK(rx_frame(last_of(MODEM_FRAME_RX), &h, text, &rssi, &snr, &epoch));
    CHECK(epoch == 22 && strcmp(text, "far") == 0);
}

static void test_clear_forgets_the_game(void)
{
    setup(true, 16);
    configure(0x1234, 0, 1, 2, 869525000, KEY);
    uint8_t clear = MODEM_CMD_CLEAR;
    host_send(MODEM_FRAME_CMD, &clear, 1);
    CHECK(status_has("\"configured\":false"));
    for (size_t i = 0; i < sizeof(modem.rx.game_key); i++) {
        CHECK(modem.rx.game_key[i] == 0);
    }
    clear_out();
    host_tx(0x1234, 0, 1, 2, "x");
    CHECK(tx_ack_status(NULL) == MODEM_TX_NOT_CONFIGURED);

    uint8_t peer[5] = {MODEM_CMD_SET_PEER_EPOCH, 0, 1, 0, 1};
    host_send(MODEM_FRAME_CMD, peer, sizeof(peer));
    int e = last_of(MODEM_FRAME_ERROR);
    CHECK(e >= 0 && io_state.payload[e][0] == MODEM_ERR_NOT_CONFIGURED);
}

void run_modem_tests(void)
{
    test_ident_and_ping();
    test_configure_validation();
    test_tx_encrypts_and_acks();
    test_tx_nonce_guard();
    test_tx_rejects_bad_packets();
    test_rx_forwards_and_dedupes();
    test_rx_drops_foreign_and_forged();
    test_rx_epoch_window();
    test_clear_forgets_the_game();
}
