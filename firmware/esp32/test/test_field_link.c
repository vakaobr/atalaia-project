/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's radio link (main/radio/field_link.c): HELLO, events with ACK
 * and retry, STATE, TIME and CMD handling, the time sync, relaying, and
 * the flash log after a reboot. A "controller" built from the same
 * radio_protocol code sends TIME, CMD and ACK; packets are checked by
 * decrypting them (test-stub crypto).
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "radio/field_link.h"

#define BOX      7
#define GAME     0x1234
#define SINK_MAX 96
#define PKT_CAP  (ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE)

static const uint8_t KEY[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};

/* ---- Fakes ------------------------------------------------------------------------- */

typedef struct {
    uint8_t pkt[SINK_MAX][PKT_CAP];
    size_t len[SINK_MAX];
    int count;
    bool refuse;
} sink_t;

static bool sink_tx(void *ctx, const uint8_t *p, size_t n)
{
    sink_t *s = (sink_t *)ctx;
    if (s->refuse) return false;
    if (s->count < SINK_MAX && n <= PKT_CAP) {
        memcpy(s->pkt[s->count], p, n);
        s->len[s->count] = n;
        s->count++;
    }
    return true;
}

typedef struct {
    uint16_t epoch;
    bool present;
} nvs_t;

static int nvs_read_epoch(void *ctx, uint16_t *e)
{
    nvs_t *n = (nvs_t *)ctx;
    if (!n->present) return -1;
    *e = n->epoch;
    return 0;
}
static int nvs_write_epoch(void *ctx, uint16_t e)
{
    nvs_t *n = (nvs_t *)ctx;
    n->epoch = e;
    n->present = true;
    return 0;
}
static int nvs_read_key(void *ctx, uint8_t k[16])
{
    (void)ctx;
    (void)k;
    return -1;
}
static int nvs_write_key(void *ctx, const uint8_t k[16])
{
    (void)ctx;
    (void)k;
    return 0;
}
static int nvs_erase_key(void *ctx)
{
    (void)ctx;
    return 0;
}

typedef struct {
    uint8_t cmds[32];
    char params[32][128];
    int ncmds;
    uint32_t local_ms;
    uint8_t owner;
    uint32_t counter_red;
} shell_t;

static void io_get_state(void *user, atalaia_state_msg_t *st)
{
    shell_t *sh = (shell_t *)user;
    st->owner_team = sh->owner;
    st->phase = 1;
    st->game_time_ms = sh->local_ms;
    st->counters[0].team = 1;
    st->counters[0].score = sh->counter_red;
    st->counters[1].team = 2;
    st->counters[1].score = 0;
    st->counter_count = 2;
    st->battery_pct = 90;
}

static void io_on_cmd(void *user, uint8_t cmd, const char *params)
{
    shell_t *sh = (shell_t *)user;
    if (sh->ncmds < 32) {
        snprintf(sh->params[sh->ncmds], sizeof(sh->params[0]), "%s", params);
        sh->cmds[sh->ncmds++] = cmd;
    }
}

static uint32_t io_game_time(void *user)
{
    return ((shell_t *)user)->local_ms;
}

typedef struct {
    field_link_t link;
    sink_t sink;
    nvs_t nvs;
    atalaia_radio_nvs_ops_t nvs_ops;
    shell_t shell;
    atalaia_join_t join;
    atalaia_hello_t hello;
} box_t;

static void box_join(atalaia_join_t *j)
{
    memset(j, 0, sizeof(*j));
    j->game_id = GAME;
    memcpy(j->game_key, KEY, 16);
    j->node_id = BOX;
    j->controller_id = 0;
    j->channel_hz = 869525000u;
    j->max_hops = 2;
    snprintf(j->teams[0], sizeof(j->teams[0]), "red");
    snprintf(j->teams[1], sizeof(j->teams[1]), "blue");
    j->team_count = 2;
    snprintf(j->mode_id, sizeof(j->mode_id), "org.atalaia.domination");
    snprintf(j->role, sizeof(j->role), "zone");
    j->game_seed = 99;
}

static bool box_up(box_t *b, event_log_t *log, uint32_t now)
{
    box_join(&b->join);
    b->nvs_ops = (atalaia_radio_nvs_ops_t){nvs_read_epoch, nvs_write_epoch, nvs_read_key,
                                           nvs_write_key,  nvs_erase_key,   &b->nvs};
    memset(&b->hello, 0, sizeof(b->hello));
    snprintf(b->hello.node_name, sizeof(b->hello.node_name), "box-7");
    snprintf(b->hello.fw_version, sizeof(b->hello.fw_version), "test");
    snprintf(b->hello.core_version, sizeof(b->hello.core_version), "0.2.0");
    b->hello.platform = 2;
    b->hello.transports = 1;
    b->hello.battery_pct = 0xFF;
    field_link_io_t io = {.get_state = io_get_state,
                          .on_cmd = io_on_cmd,
                          .game_time = io_game_time,
                          .log = NULL,
                          .user = &b->shell,
                          .tx = sink_tx,
                          .tx_ctx = &b->sink};
    return field_link_init(&b->link, &b->join, &atalaia_crypto_test_stub, &b->nvs_ops, log,
                           &b->hello, &io, now);
}

/* Opens a packet the box sent. */
static bool open_box(box_t *b, int i, atalaia_header_t *h, uint8_t *pl, size_t *n)
{
    return atalaia_packet_decrypt(b->sink.pkt[i], b->sink.len[i], b->link.proto.epoch, KEY, h, pl,
                                  n, &atalaia_crypto_test_stub);
}

static int count_type(box_t *b, int from, uint8_t type)
{
    int c = 0;
    for (int i = from; i < b->sink.count; i++) {
        atalaia_header_t h;
        uint8_t pl[PKT_CAP];
        size_t n;
        if (open_box(b, i, &h, pl, &n) && h.type == type) c++;
    }
    return c;
}

/* The "controller": another node of the same game, source 0 (or another id). */
typedef struct {
    atalaia_radio_proto_t proto;
    sink_t sink;
} ctl_t;

static void ctl_up(ctl_t *c, uint16_t source, uint16_t epoch)
{
    memset(&c->sink, 0, sizeof(c->sink));
    atalaia_radio_proto_init(&c->proto, GAME, source, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&c->proto, KEY);
    atalaia_radio_proto_set_epoch(&c->proto, epoch);
    c->proto.tx = sink_tx;
    c->proto.tx_ctx = &c->sink;
}

/* Sends a payload from the controller and delivers it to the box. */
static void ctl_to_box(ctl_t *c, box_t *b, uint8_t type, const uint8_t *pl, size_t n)
{
    int before = c->sink.count;
    CHECK(atalaia_radio_proto_send_payload(&c->proto, type, 2, false, pl, n, NULL));
    CHECK(c->sink.count == before + 1);
    field_link_on_packet(&b->link, c->sink.pkt[before], c->sink.len[before], -50);
}

static void send_time(ctl_t *c, box_t *b, uint8_t state, uint32_t game_ms, uint32_t term)
{
    atalaia_time_msg_t t = {game_ms, state, 0, 1700000000u, term, 0xFFFF};
    uint8_t buf[64];
    size_t n = atalaia_time_encode(&t, buf, sizeof(buf));
    CHECK(n > 0);
    ctl_to_box(c, b, ATALAIA_MSG_TIME, buf, n);
}

static void send_cmd(ctl_t *c, box_t *b, uint8_t cmd, uint16_t dest, const char *params)
{
    atalaia_cmd_msg_t m;
    memset(&m, 0, sizeof(m));
    m.cmd = cmd;
    m.dest = dest;
    snprintf(m.params_json, sizeof(m.params_json), "%s", params);
    uint8_t buf[200];
    size_t n = atalaia_cmd_encode(&m, buf, sizeof(buf));
    CHECK(n > 0);
    ctl_to_box(c, b, ATALAIA_MSG_CMD, buf, n);
}

static void send_ack(ctl_t *c, box_t *b, uint16_t ack_seq, const uint8_t *bitmap, size_t bits_len)
{
    atalaia_ack_msg_t a;
    memset(&a, 0, sizeof(a));
    a.ack_node = BOX;
    a.ack_seq = ack_seq;
    if (bits_len) memcpy(a.ack_bitmap, bitmap, bits_len);
    a.ack_bitmap_len = bits_len;
    uint8_t buf[64];
    size_t n = atalaia_ack_msg_encode(&a, buf, sizeof(buf));
    CHECK(n > 0);
    ctl_to_box(c, b, ATALAIA_MSG_ACK, buf, n);
}

static void make_event(atalaia_event_t *ev, uint16_t seq, const char *type, uint8_t team,
                       atalaia_prio_t prio)
{
    CHECK(atalaia_event_init(ev, BOX, seq, 1000u * seq, type, team, 0, prio));
}

/* ---- Tests -------------------------------------------------------------------------- */

static void test_hello_event_retry_and_ack(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1000));
    CHECK(b.nvs.epoch == 1); /* boot epoch stored before the first packet */

    /* HELLO first, asking for an ACK, from our id, with max_hops and our epoch. */
    CHECK(b.sink.count == 1);
    atalaia_header_t h;
    uint8_t pl[PKT_CAP];
    size_t n;
    CHECK(open_box(&b, 0, &h, pl, &n));
    CHECK(h.type == ATALAIA_MSG_HELLO && h.source == BOX && h.seq == 0 && h.hop_limit == 2);
    CHECK(ATALAIA_VF_ACK(h.version_flags) == 1 && h.game_id == GAME);
    atalaia_hello_t hello;
    CHECK(atalaia_hello_decode(pl, n, &hello));
    CHECK(hello.epoch == 1 && strcmp(hello.node_name, "box-7") == 0);

    /* A capture: an EVENT with ACK requested, waiting in the outbox. */
    atalaia_event_t ev;
    make_event(&ev, 1, "zone.captured", 1, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{\"team\":\"red\"}");
    CHECK(b.sink.count == 2);
    CHECK(open_box(&b, 1, &h, pl, &n));
    CHECK(h.type == ATALAIA_MSG_EVENT && h.seq == 1 && ATALAIA_VF_ACK(h.version_flags) == 1);
    atalaia_event_t back;
    char data[128];
    CHECK(atalaia_event_decode(pl, n, &back, data, sizeof(data), NULL));
    CHECK(strcmp(back.type, "zone.captured") == 0 && back.node == BOX && back.team == 1);
    CHECK(field_link_pending(&b.link) == 1);

    /* The capture makes a STATE due at the next tick. */
    field_link_tick(&b.link, 1010);
    CHECK(count_type(&b, 2, ATALAIA_MSG_STATE) == 1);

    ctl_t c;
    ctl_up(&c, 0, 1);
    /* ACK of seq 0 (HELLO) only. */
    send_ack(&c, &b, 0, NULL, 0);
    CHECK(!b.link.hello_pending);
    CHECK(field_link_pending(&b.link) == 1);

    /* No ACK for the event in 3 s: sent again in a new packet. */
    int before = b.sink.count;
    field_link_tick(&b.link, 1000 + 3000);
    CHECK(count_type(&b, before, ATALAIA_MSG_EVENT) == 1);
    CHECK(b.link.stats.retries == 1);
    uint16_t resent_seq = b.link.outbox[1].pkt_seq;
    for (int i = 0; i < FIELD_LINK_OUTBOX; i++) {
        if (b.link.outbox[i].used && b.link.outbox[i].type == ATALAIA_MSG_EVENT) {
            resent_seq = b.link.outbox[i].pkt_seq;
        }
    }
    CHECK(resent_seq > 2);

    /* The controller missed seq 1 and 2 but has the resend: the bitmap ACKs it (D7). */
    uint8_t bits[4] = {0};
    int bit = resent_seq - 0 - 1; /* ack_seq 0: bit n is seq 1 + n */
    bits[bit / 8] |= (uint8_t)(1u << (bit % 8));
    send_ack(&c, &b, 0, bits, 4);
    CHECK(field_link_pending(&b.link) == 0);
    CHECK(b.link.stats.acked == 2);
}

static void test_ack_seq_ffff_and_cumulative(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 5));
    atalaia_event_t ev;
    make_event(&ev, 1, "bomb.armed", 1, ATALAIA_PRIO_CRITICAL);
    field_link_event(&b.link, &ev, "{\"fuse_s\":300}");
    make_event(&ev, 2, "code.used", 2, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{\"code\":\"X\"}");
    CHECK(field_link_pending(&b.link) == 2);
    ctl_t c;
    ctl_up(&c, 0, 1);
    /* 0xFFFF: "seq 0 not received"; bit 1 = seq 1. */
    uint8_t bits[1] = {0x02};
    send_ack(&c, &b, 0xFFFF, bits, 1);
    CHECK(field_link_pending(&b.link) == 1);
    /* Cumulative: everything up to seq 2. */
    send_ack(&c, &b, 2, NULL, 0);
    CHECK(field_link_pending(&b.link) == 0);
    /* An ACK for another node changes nothing. */
    make_event(&ev, 3, "code.used", 2, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{\"code\":\"Y\"}");
    atalaia_ack_msg_t a = {9, 100, {0}, 0};
    uint8_t buf[32];
    size_t n = atalaia_ack_msg_encode(&a, buf, sizeof(buf));
    ctl_to_box(&c, &b, ATALAIA_MSG_ACK, buf, n);
    CHECK(field_link_pending(&b.link) == 1);
}

static void test_retry_limits_and_telemetry(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1));
    atalaia_event_t ev;
    make_event(&ev, 1, "zone.captured", 1, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{}");
    make_event(&ev, 2, "bomb.exploded", 1, ATALAIA_PRIO_CRITICAL);
    field_link_event(&b.link, &ev, "{}");
    /* Telemetry: sent once, no ACK asked, not kept. */
    int before = b.sink.count;
    make_event(&ev, 3, "battery.low", 0, ATALAIA_PRIO_TELEMETRY);
    field_link_event(&b.link, &ev, "{\"percent\":12}");
    CHECK(b.sink.count == before + 1);
    atalaia_header_t h;
    uint8_t pl[PKT_CAP];
    size_t n;
    CHECK(open_box(&b, before, &h, pl, &n));
    CHECK(ATALAIA_VF_ACK(h.version_flags) == 0 && ATALAIA_VF_PRIO(h.version_flags) == 0);
    CHECK(field_link_pending(&b.link) == 2);

    uint32_t now = 1;
    for (int i = 0; i < 12; i++) {
        now += 3000;
        field_link_tick(&b.link, now);
    }
    /* Normal: 1 send + 10 retries, then given up; critical: still trying. */
    CHECK(b.link.stats.expired == 1);
    CHECK(field_link_pending(&b.link) == 1);
    for (int i = 0; i < 20; i++) {
        now += 3000;
        field_link_tick(&b.link, now);
    }
    CHECK(field_link_pending(&b.link) == 1);
}

static void test_cmd_time_and_leader(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1));
    ctl_t c;
    ctl_up(&c, 0, 3);

    send_cmd(&c, &b, FIELD_CMD_START, 0xFFFF, "");
    CHECK(b.shell.ncmds == 1 && b.shell.cmds[0] == FIELD_CMD_START);
    CHECK(b.link.game_state == FIELD_GAME_RUNNING);
    /* For another node: ignored. For us: with its params. */
    send_cmd(&c, &b, FIELD_CMD_MESSAGE, 9, "{\"text\":\"no\"}");
    send_cmd(&c, &b, FIELD_CMD_MESSAGE, BOX, "{\"text\":\"Regroup\"}");
    CHECK(b.shell.ncmds == 2 && b.shell.cmds[1] == FIELD_CMD_MESSAGE);
    CHECK(strcmp(b.shell.params[1], "{\"text\":\"Regroup\"}") == 0);
    /* The same packet again (a relayed copy): handled once. */
    field_link_on_packet(&b.link, c.sink.pkt[c.sink.count - 1], c.sink.len[c.sink.count - 1], -60);
    CHECK(b.shell.ncmds == 2 && b.link.stats.rx_duplicates == 1);

    /* TIME running: nothing missed. TIME paused: the PAUSE we missed. */
    send_time(&c, &b, FIELD_GAME_RUNNING, 5000, 1);
    CHECK(b.shell.ncmds == 2 && b.link.term == 1 && b.link.leader == 0);
    send_time(&c, &b, FIELD_GAME_PAUSED, 6000, 1);
    CHECK(b.shell.ncmds == 3 && b.shell.cmds[2] == FIELD_CMD_PAUSE);

    /* A new controller (node 1) with term 2 takes over; the old one's TIME and CMD are ignored. */
    ctl_t c2;
    ctl_up(&c2, 1, 1);
    send_time(&c2, &b, FIELD_GAME_RUNNING, 7000, 2);
    CHECK(b.link.leader == 1 && b.link.term == 2);
    CHECK(b.shell.ncmds == 4 && b.shell.cmds[3] == FIELD_CMD_RESUME);
    send_time(&c, &b, FIELD_GAME_PAUSED, 7100, 1);
    CHECK(b.shell.ncmds == 4 && b.link.leader == 1);
    send_cmd(&c, &b, FIELD_CMD_END, 0xFFFF, "");
    CHECK(b.shell.ncmds == 4);
    send_cmd(&c2, &b, FIELD_CMD_END, 0xFFFF, "");
    CHECK(b.shell.ncmds == 5 && b.shell.cmds[4] == FIELD_CMD_END);
    CHECK(b.link.game_state == FIELD_GAME_ENDED);
}

static void test_late_start_from_time(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1));
    ctl_t c;
    ctl_up(&c, 0, 1);
    /* The CMD start was lost; the TIME beacon says running. */
    send_time(&c, &b, FIELD_GAME_RUNNING, 42000, 1);
    CHECK(b.shell.ncmds == 1 && b.shell.cmds[0] == FIELD_CMD_START);
    /* Local game time is 0 and the controller's 42 s: the clock steps ahead at once. */
    CHECK(field_link_adjust_delta(&b.link, 10) == 10 + 42000 + FIELD_LINK_AIRTIME_MS);
    CHECK(field_link_adjust_delta(&b.link, 10) == 10);
}

static void test_time_sync(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1));
    ctl_t c;
    ctl_up(&c, 0, 1);
    send_cmd(&c, &b, FIELD_CMD_START, 0xFFFF, "");

    /* Local 2 s ahead of the controller: hold the game clock until it catches up. */
    b.shell.local_ms = 12000;
    send_time(&c, &b, FIELD_GAME_RUNNING, 10000 - FIELD_LINK_AIRTIME_MS, 1);
    uint32_t total = 0;
    for (int i = 0; i < 300; i++) total += field_link_adjust_delta(&b.link, 10);
    CHECK(total == 3000 - 2000);

    /* 200 ms behind: slewed at 5 %, never stepped. */
    field_link_reset_sync(&b.link);
    b.shell.local_ms = 20000;
    send_time(&c, &b, FIELD_GAME_RUNNING, 20200 - FIELD_LINK_AIRTIME_MS, 1);
    CHECK(field_link_adjust_delta(&b.link, 100) == 105);
    total = 0;
    for (int i = 0; i < 100; i++) total += field_link_adjust_delta(&b.link, 100);
    CHECK(total == 10000 + 200 - 5);
}

static void test_relay_and_filters(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 100));
    ctl_t other;
    ctl_up(&other, 9, 1);
    uint8_t pl[] = {0xA0};

    /* Another box's packet with hop_limit 2: relayed once, after the jitter, with hop 1. */
    CHECK(atalaia_radio_proto_send_payload(&other.proto, ATALAIA_MSG_STATE, 0, false, pl, 1, NULL));
    field_link_on_packet(&b.link, other.sink.pkt[0], other.sink.len[0], -70);
    int before = b.sink.count;
    field_link_tick(&b.link, 105);
    CHECK(b.sink.count == before); /* not yet: 10-50 ms jitter */
    field_link_tick(&b.link, 160);
    CHECK(b.sink.count == before + 1);
    CHECK(b.sink.len[before] == other.sink.len[0]);
    CHECK(b.sink.pkt[before][ATALAIA_RF_HOP_LIMIT_OFFSET] == 1);
    CHECK(memcmp(b.sink.pkt[before], other.sink.pkt[0], ATALAIA_RF_HOP_LIMIT_OFFSET) == 0);
    CHECK(b.link.stats.relayed == 1);
    /* The relayed copy is still authentic for the receiver (hop_limit is not in the AAD). */
    atalaia_header_t h;
    uint8_t out[PKT_CAP];
    size_t n;
    CHECK(atalaia_packet_decrypt(b.sink.pkt[before], b.sink.len[before], 1, KEY, &h, out, &n,
                                 &atalaia_crypto_test_stub));
    /* The same packet again: not relayed twice. */
    field_link_on_packet(&b.link, other.sink.pkt[0], other.sink.len[0], -70);
    field_link_tick(&b.link, 300);
    CHECK(b.link.stats.relayed == 1);

    /* hop_limit = relays left (core flood.c): 0 is not relayed, 1 is relayed once more
     * with 0, and 3 (above the clamp of 2) is relayed with 1. */
    other.proto.max_hops = 0;
    CHECK(atalaia_radio_proto_send_payload(&other.proto, ATALAIA_MSG_STATE, 0, false, pl, 1, NULL));
    field_link_on_packet(&b.link, other.sink.pkt[1], other.sink.len[1], -70);
    other.proto.max_hops = 1;
    CHECK(atalaia_radio_proto_send_payload(&other.proto, ATALAIA_MSG_STATE, 0, false, pl, 1, NULL));
    field_link_on_packet(&b.link, other.sink.pkt[2], other.sink.len[2], -70);
    other.proto.max_hops = 3;
    CHECK(atalaia_radio_proto_send_payload(&other.proto, ATALAIA_MSG_STATE, 0, false, pl, 1, NULL));
    field_link_on_packet(&b.link, other.sink.pkt[3], other.sink.len[3], -70);
    before = b.sink.count;
    field_link_tick(&b.link, 500);
    CHECK(b.sink.count == before + 2);
    int hops = 0;
    for (int i = before; i < b.sink.count; i++) {
        hops |= 1 << b.sink.pkt[i][ATALAIA_RF_HOP_LIMIT_OFFSET];
    }
    CHECK(hops == 0x3); /* one relayed with 0, one with 1 */

    /* Our own relayed packet, another game, a wrong key: ignored. */
    uint32_t ok = b.link.stats.rx_ok;
    field_link_on_packet(&b.link, b.sink.pkt[0], b.sink.len[0], -40);
    ctl_t stranger;
    ctl_up(&stranger, 9, 1);
    stranger.proto.game_id = GAME + 1;
    CHECK(atalaia_radio_proto_send_payload(&stranger.proto, ATALAIA_MSG_STATE, 0, false, pl, 1,
                                           NULL));
    field_link_on_packet(&b.link, stranger.sink.pkt[0], stranger.sink.len[0], -40);
    ctl_t forger;
    ctl_up(&forger, 9, 1);
    static const uint8_t other_key[16] = {9};
    atalaia_radio_proto_set_key(&forger.proto, other_key);
    CHECK(atalaia_radio_proto_send_payload(&forger.proto, ATALAIA_MSG_CMD, 2, false, pl, 1, NULL));
    field_link_on_packet(&b.link, forger.sink.pkt[0], forger.sink.len[0], -40);
    CHECK(b.link.stats.rx_ok == ok && b.link.stats.rx_rejected == 1);
}

static void test_state_contents_and_interval(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1000));
    b.shell.owner = 1;
    b.shell.counter_red = 40;
    b.shell.local_ms = 33000;
    int before = b.sink.count;
    field_link_tick(&b.link, 1000 + FIELD_LINK_STATE_MS - 1);
    CHECK(count_type(&b, before, ATALAIA_MSG_STATE) == 0);
    field_link_tick(&b.link, 1000 + FIELD_LINK_STATE_MS);
    CHECK(count_type(&b, before, ATALAIA_MSG_STATE) == 1);
    for (int i = before; i < b.sink.count; i++) {
        atalaia_header_t h;
        uint8_t pl[PKT_CAP];
        size_t n;
        if (!open_box(&b, i, &h, pl, &n) || h.type != ATALAIA_MSG_STATE) continue;
        atalaia_state_msg_t st;
        CHECK(atalaia_state_decode(pl, n, &st));
        CHECK(st.owner_team == 1 && st.game_time_ms == 33000 && st.epoch == 1);
        CHECK(st.counter_count == 2 && st.counters[0].team == 1 && st.counters[0].score == 40);
        CHECK(st.battery_pct == 90);
        CHECK(ATALAIA_VF_ACK(h.version_flags) == 0);
    }
}

static void test_log_replay_after_reboot(void)
{
    char dir[96];
    snprintf(dir, sizeof(dir), "/tmp/atalaia_fl_%d", (int)getpid());
    mkdir(dir, 0755);
    static event_log_t log;
    event_log_init(&log, dir);
    event_log_clear(&log);

    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, &log, 10));
    atalaia_event_t ev;
    make_event(&ev, 1, "zone.captured", 1, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{\"team\":\"red\"}");
    make_event(&ev, 2, "zone.captured", 2, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{\"team\":\"blue\"}");
    CHECK(log.file_size > 0);

    /* Battery pulled before any ACK. On reboot: a new epoch, and both events go out again. */
    nvs_t kept = b.nvs;
    static box_t b2;
    memset(&b2, 0, sizeof(b2));
    b2.nvs = kept;
    event_log_init(&log, dir);
    CHECK(box_up(&b2, &log, 20));
    CHECK(b2.link.proto.epoch == 2 && b2.nvs.epoch == 2);
    CHECK(field_link_pending(&b2.link) == 2);
    field_link_tick(&b2.link, 21);
    CHECK(count_type(&b2, 0, ATALAIA_MSG_EVENT) == 2);
    int teams_seen = 0;
    for (int i = 0; i < b2.sink.count; i++) {
        atalaia_header_t h;
        uint8_t pl[PKT_CAP];
        size_t n;
        if (!open_box(&b2, i, &h, pl, &n) || h.type != ATALAIA_MSG_EVENT) continue;
        atalaia_event_t back;
        char data[64];
        CHECK(atalaia_event_decode(pl, n, &back, data, sizeof(data), NULL));
        teams_seen |= 1 << back.team;
    }
    CHECK(teams_seen == 0x6);

    /* All acknowledged: the log is compacted to nothing; a third boot resends nothing. */
    ctl_t c;
    ctl_up(&c, 0, 1);
    atalaia_ack_msg_t a = {BOX, (uint16_t)(b2.link.proto.seq - 1), {0}, 0};
    uint8_t buf[32];
    size_t n = atalaia_ack_msg_encode(&a, buf, sizeof(buf));
    ctl_to_box(&c, &b2, ATALAIA_MSG_ACK, buf, n);
    CHECK(field_link_pending(&b2.link) == 0);
    CHECK(log.file_size == 0);
    static box_t b3;
    memset(&b3, 0, sizeof(b3));
    b3.nvs = b2.nvs;
    event_log_init(&log, dir);
    CHECK(box_up(&b3, &log, 30));
    CHECK(field_link_pending(&b3.link) == 0);
    event_log_clear(&log);
    rmdir(dir);
}

static void test_refused_tx_still_acknowledged(void)
{
    static box_t b;
    memset(&b, 0, sizeof(b));
    CHECK(box_up(&b, NULL, 1));
    b.sink.refuse = true; /* the radio queue is full */
    atalaia_event_t ev;
    make_event(&ev, 1, "zone.captured", 1, ATALAIA_PRIO_NORMAL);
    field_link_event(&b.link, &ev, "{}");
    CHECK(b.link.stats.tx_refused == 1);
    CHECK(field_link_pending(&b.link) == 1);
    b.sink.refuse = false;
    field_link_tick(&b.link, 3002);
    CHECK(field_link_pending(&b.link) == 1);
    ctl_t c;
    ctl_up(&c, 0, 1);
    send_ack(&c, &b, b.link.proto.seq - 1, NULL, 0);
    CHECK(field_link_pending(&b.link) == 0);
}

void run_field_link_tests(void)
{
    test_hello_event_retry_and_ack();
    test_ack_seq_ffff_and_cumulative();
    test_retry_limits_and_telemetry();
    test_cmd_time_and_leader();
    test_late_start_from_time();
    test_time_sync();
    test_relay_and_filters();
    test_state_contents_and_interval();
    test_log_replay_after_reboot();
    test_refused_tx_still_acknowledged();
}
