/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box in a controller's game (main/box_game.c): the join and its
 * refusals, the game driven by CMD, events and scores going out over the
 * link, the end of the game (key erased), the rejoin after a reboot,
 * battery.low from the battery gauge (once per crossing, with hysteresis),
 * and between games (main/box_lobby.c, protocol/field-frames.md): the
 * announcements, DISCOVER, an invite into the next game in two parts, and
 * every refusal (busy, an old token, another field's key, an ended game).
 * Real modes (modes/domination/node.lua) run in the real core.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "box_game.h"
#include "builtin_presets.h"
#include "check.h"
#include "hal/stub/hal_stub.h"
#include "state_persist.h"

#ifndef MODES_DIR
#define MODES_DIR "modes"
#endif

#define NODE    12
#define GAME_ID 0x0BEE
#define PKT_CAP (ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE)

static const uint8_t JOIN_KEY[32] = {
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF,
    0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF};
static const char JOIN_KEY_HEX[] =
    "a0a1a2a3a4a5a6a7a8a9aaabacadaeafb0b1b2b3b4b5b6b7b8b9babbbcbdbebf";
static const uint8_t GAME_KEY[16] = {0x10, 0x20, 0x30, 0x40, 0x50, 0x60, 0x70, 0x80,
                                     0x90, 0xA0, 0xB0, 0xC0, 0xD0, 0xE0, 0xF0, 0x01};

/* ---- Fakes: storage, shell, radio ------------------------------------------------- */

typedef struct {
    uint8_t join[ATALAIA_JOIN_MAX];
    int join_len;
    uint8_t key[32];
    bool have_key;
    uint16_t epoch;
    bool have_epoch;
    uint8_t device_id[8];
    bool have_device_id;
    uint32_t ff_boot;
    bool have_ff_boot;
    bool ff_boot_fails;
    bool ff_boot_read_fails;
} flash_t;

static int st_load_join(void *ctx, uint8_t *buf, size_t cap)
{
    flash_t *f = (flash_t *)ctx;
    if (f->join_len <= 0 || (size_t)f->join_len > cap) return 0;
    memcpy(buf, f->join, (size_t)f->join_len);
    return f->join_len;
}
static int st_save_join(void *ctx, const uint8_t *buf, size_t len)
{
    flash_t *f = (flash_t *)ctx;
    memcpy(f->join, buf, len);
    f->join_len = (int)len;
    return 0;
}
static int st_erase_join(void *ctx)
{
    ((flash_t *)ctx)->join_len = 0;
    return 0;
}
static int st_load_key(void *ctx, uint8_t key[32])
{
    flash_t *f = (flash_t *)ctx;
    if (!f->have_key) return -1;
    memcpy(key, f->key, 32);
    return 0;
}
static int st_save_key(void *ctx, const uint8_t key[32])
{
    flash_t *f = (flash_t *)ctx;
    memcpy(f->key, key, 32);
    f->have_key = true;
    return 0;
}
static int st_load_device(void *ctx, uint8_t id[8])
{
    flash_t *f = (flash_t *)ctx;
    if (!f->have_device_id) return -1;
    memcpy(id, f->device_id, 8);
    return 0;
}
static int st_save_device(void *ctx, const uint8_t id[8])
{
    flash_t *f = (flash_t *)ctx;
    memcpy(f->device_id, id, 8);
    f->have_device_id = true;
    return 0;
}
static int st_load_ff_boot(void *ctx, uint32_t *boot)
{
    flash_t *f = (flash_t *)ctx;
    if (f->ff_boot_read_fails) return -2; /* an NVS error, not "none stored" */
    if (!f->have_ff_boot) return -1;
    *boot = f->ff_boot;
    return 0;
}
static int st_save_ff_boot(void *ctx, uint32_t boot)
{
    flash_t *f = (flash_t *)ctx;
    if (f->ff_boot_fails) return -1;
    f->ff_boot = boot;
    f->have_ff_boot = true;
    return 0;
}
static int nv_read_epoch(void *ctx, uint16_t *e)
{
    flash_t *f = (flash_t *)ctx;
    if (!f->have_epoch) return -1;
    *e = f->epoch;
    return 0;
}
static int nv_write_epoch(void *ctx, uint16_t e)
{
    flash_t *f = (flash_t *)ctx;
    f->epoch = e;
    f->have_epoch = true;
    return 0;
}
static int nv_read_key(void *ctx, uint8_t k[16])
{
    (void)ctx;
    (void)k;
    return -1;
}
static int nv_write_key(void *ctx, const uint8_t k[16])
{
    (void)ctx;
    (void)k;
    return 0;
}
static int nv_erase_key(void *ctx)
{
    (void)ctx;
    return 0;
}

typedef struct {
    uint8_t pkt[256][PKT_CAP];
    size_t len[256];
    int count;
    char screen[32];
    char screen_data[256];
    uint32_t channel;
} shell_t;

static bool sh_send(void *user, const uint8_t *p, size_t n)
{
    shell_t *s = (shell_t *)user;
    if (s->count < 256) {
        memcpy(s->pkt[s->count], p, n);
        s->len[s->count] = n;
        s->count++;
    }
    return true;
}
static void sh_screen(void *user, const char *t, const char *d)
{
    shell_t *s = (shell_t *)user;
    snprintf(s->screen, sizeof(s->screen), "%s", t);
    snprintf(s->screen_data, sizeof(s->screen_data), "%s", d);
}
static bool sh_channel(void *user, uint32_t hz)
{
    ((shell_t *)user)->channel = hz;
    return true;
}

/* ---- Fixture ------------------------------------------------------------------------- */

static hal_t hal;
static node_runner_t runner;
static preset_t preset;
static box_game_t game;
static shell_t shell;
static flash_t flash;
static atalaia_radio_nvs_ops_t nvs_ops;
static char base[96];

/* keep_flash: the same NVS and LittleFS as before (a reboot). */
static void fixture(bool keep_flash)
{
    static int id;
    if (!keep_flash) snprintf(base, sizeof(base), "/tmp/atalaia_box_%d_%d", (int)getpid(), id++);
    mkdir(base, 0755);
    preset_store_init(base);
    char st[160];
    snprintf(st, sizeof(st), "%s/state", base);
    mkdir(st, 0755);
    state_persist_init(st);

    static char dom[PRESET_SOURCE_MAX];
    static char kc[PRESET_SOURCE_MAX];
    FILE *f = fopen(MODES_DIR "/domination/node.lua", "rb");
    CHECK(f != NULL);
    size_t dom_len = f ? fread(dom, 1, sizeof(dom) - 1, f) : 0;
    if (f) fclose(f);
    f = fopen(MODES_DIR "/kill_confirmed/node.lua", "rb");
    CHECK(f != NULL);
    size_t kc_len = f ? fread(kc, 1, sizeof(kc) - 1, f) : 0;
    if (f) fclose(f);
    static char medic[PRESET_SOURCE_MAX];
    f = fopen(MODES_DIR "/medic/node.lua", "rb");
    CHECK(f != NULL);
    size_t medic_len = f ? fread(medic, 1, sizeof(medic) - 1, f) : 0;
    if (f) fclose(f);
    const builtin_source_t sources[] = {{"org.atalaia.domination", dom, dom_len},
                                        {"org.atalaia.kill_confirmed", kc, kc_len},
                                        {"org.atalaia.medic", medic, medic_len}};
    int seeded = builtin_presets_seed(sources, 3);
    CHECK(keep_flash ? seeded == 0 : seeded >= 1);

    hal_stub_init(&hal);
    node_runner_init(&runner, &hal, 0);
    memset(&shell, 0, sizeof(shell));
    if (!keep_flash) memset(&flash, 0, sizeof(flash));
    nvs_ops = (atalaia_radio_nvs_ops_t){nv_read_epoch, nv_write_epoch, nv_read_key,
                                        nv_write_key,  nv_erase_key,   &flash};
    box_store_ops_t store = {.load_join = st_load_join,
                             .save_join = st_save_join,
                             .erase_join = st_erase_join,
                             .load_join_key = st_load_key,
                             .save_join_key = st_save_key,
                             .load_device_id = st_load_device,
                             .save_device_id = st_save_device,
                             .load_ff_boot = st_load_ff_boot,
                             .save_ff_boot = st_save_ff_boot,
                             .ctx = &flash};
    box_shell_ops_t sh = {.screen = sh_screen,
                          .log = NULL,
                          .reboot = NULL,
                          .set_channel = sh_channel,
                          .battery_pct = NULL,
                          .radio_send = sh_send,
                          .user = &shell};
    atalaia_hello_t hello;
    memset(&hello, 0, sizeof(hello));
    snprintf(hello.node_name, sizeof(hello.node_name), "box");
    snprintf(hello.fw_version, sizeof(hello.fw_version), "t");
    snprintf(hello.core_version, sizeof(hello.core_version), "0.2.0");
    hello.battery_pct = 0xFF;
    box_game_init(&game, &runner, &preset, &store, &sh, &atalaia_crypto_test_stub, &nvs_ops, NULL,
                  &hello);
    box_game_load_join_key(&game);
}

static void make_join(atalaia_join_t *j)
{
    memset(j, 0, sizeof(*j));
    j->game_id = GAME_ID;
    memcpy(j->game_key, GAME_KEY, 16);
    j->node_id = NODE;
    j->controller_id = 0;
    j->channel_hz = 869475000u;
    j->max_hops = 2;
    snprintf(j->teams[0], sizeof(j->teams[0]), "red");
    snprintf(j->teams[1], sizeof(j->teams[1]), "blue");
    j->team_count = 2;
    snprintf(j->mode_id, sizeof(j->mode_id), "org.atalaia.domination");
    snprintf(j->role, sizeof(j->role), "zone");
    j->game_seed = 7;
    snprintf(j->params_json, sizeof(j->params_json),
             "{\"capture_hold_ms\":1000,\"tick_s\":1,\"points_per_tick\":5}");
    j->kind = ATALAIA_JOIN_KIND_NODE;
}

static size_t encode(const atalaia_join_t *j, const uint8_t *key, uint8_t *buf)
{
    size_t n = atalaia_join_encode(j, key, buf, ATALAIA_JOIN_MAX);
    CHECK(n > 0);
    return n;
}

/* A packet from the controller (node 0, epoch 1) to the box. */
static void from_controller(uint8_t type, const uint8_t *pl, size_t n)
{
    static atalaia_radio_proto_t ctl;
    static uint16_t seq;
    static uint8_t out[PKT_CAP];
    static size_t out_len;
    atalaia_radio_proto_init(&ctl, GAME_ID, 0, &atalaia_crypto_test_stub, NULL);
    atalaia_radio_proto_set_key(&ctl, GAME_KEY);
    atalaia_radio_proto_set_epoch(&ctl, 1);
    ctl.seq = seq++;
    atalaia_header_t h = {ATALAIA_VF_MAKE(1, 2, 0, 1), GAME_ID, 0, ctl.seq, 2, type};
    out_len =
        atalaia_packet_encrypt(&h, 1, GAME_KEY, pl, n, out, sizeof(out), &atalaia_crypto_test_stub);
    CHECK(out_len > 0);
    box_game_on_packet(&game, out, out_len, -55);
}

static void cmd(uint8_t opcode)
{
    atalaia_cmd_msg_t m;
    memset(&m, 0, sizeof(m));
    m.cmd = opcode;
    m.dest = 0xFFFF;
    uint8_t buf[64];
    size_t n = atalaia_cmd_encode(&m, buf, sizeof(buf));
    from_controller(ATALAIA_MSG_CMD, buf, n);
}

static void ack_all(void)
{
    atalaia_ack_msg_t a;
    memset(&a, 0, sizeof(a));
    a.ack_node = NODE;
    a.ack_seq = (uint16_t)(game.link.proto.seq - 1);
    uint8_t buf[32];
    size_t n = atalaia_ack_msg_encode(&a, buf, sizeof(buf));
    from_controller(ATALAIA_MSG_ACK, buf, n);
}

/* Finds the last packet of a type the box sent; decodes into pl. */
static bool last_of(uint8_t type, atalaia_header_t *h, uint8_t *pl, size_t *n)
{
    for (int i = shell.count - 1; i >= 0; i--) {
        if (atalaia_packet_decrypt(shell.pkt[i], shell.len[i], game.link.proto.epoch, GAME_KEY, h,
                                   pl, n, &atalaia_crypto_test_stub) &&
            h->type == type) {
            return true;
        }
    }
    return false;
}

static int events_named(const char *type)
{
    int c = 0;
    for (int i = 0; i < shell.count; i++) {
        atalaia_header_t h;
        uint8_t pl[PKT_CAP];
        size_t n;
        if (!atalaia_packet_decrypt(shell.pkt[i], shell.len[i], game.link.proto.epoch, GAME_KEY, &h,
                                    pl, &n, &atalaia_crypto_test_stub) ||
            h.type != ATALAIA_MSG_EVENT) {
            continue;
        }
        atalaia_event_t ev;
        char data[128];
        if (atalaia_event_decode(pl, n, &ev, data, sizeof(data), NULL) &&
            strcmp(ev.type, type) == 0) {
            CHECK(ev.node == NODE);
            c++;
        }
    }
    return c;
}

/* The battery gauge's reading for the shell (-1: no gauge). */
static int fake_battery = -1;

static int sh_battery(void *user)
{
    (void)user;
    return fake_battery;
}

/* The percent of the last battery.low the box sent, or -1. */
static int last_battery_low(void)
{
    int pct = -1;
    for (int i = 0; i < shell.count; i++) {
        atalaia_header_t h;
        uint8_t pl[PKT_CAP];
        size_t n;
        atalaia_event_t ev;
        char data[128];
        if (atalaia_packet_decrypt(shell.pkt[i], shell.len[i], game.link.proto.epoch, GAME_KEY, &h,
                                   pl, &n, &atalaia_crypto_test_stub) &&
            h.type == ATALAIA_MSG_EVENT &&
            atalaia_event_decode(pl, n, &ev, data, sizeof(data), NULL) &&
            strcmp(ev.type, "battery.low") == 0) {
            CHECK(ev.prio == ATALAIA_PRIO_TELEMETRY && !ATALAIA_VF_ACK(h.version_flags));
            CHECK(sscanf(data, "{\"percent\":%d}", &pct) == 1);
        }
    }
    return pct;
}

static void run_ms(uint32_t *now, uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 10) {
        *now += 10;
        box_game_tick(&game, 10, *now);
    }
}

/* ---- Tests ----------------------------------------------------------------------------- */

static void test_join_refusals(void)
{
    fixture(false);
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, JOIN_KEY, buf);

    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_NO_KEY);
    CHECK(!box_game_set_join_key_hex(&game, "a0a1"));
    CHECK(!box_game_set_join_key_hex(&game, "zz"));
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    CHECK(flash.have_key && memcmp(flash.key, JOIN_KEY, 32) == 0);

    static const uint8_t other[32] = {1};
    size_t m = encode(&j, other, buf);
    CHECK(box_game_join(&game, buf, m) == BOX_JOIN_REFUSED);
    j.kind = ATALAIA_JOIN_KIND_CONTROLLER;
    m = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, m) == BOX_JOIN_CONTROLLER);
    make_join(&j);
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.unknown");
    m = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, m) == BOX_JOIN_NO_MODE);
    CHECK(box_game_join_text(&game, "hello") == BOX_JOIN_NOT_A_JOIN);
    CHECK(flash.join_len == 0 && !box_game_active(&game) && shell.count == 0);
}

static void test_join_play_end(void)
{
    fixture(false);
    game.state_interval_ms = 1000;
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, JOIN_KEY, buf);
    char text[ATALAIA_JOIN_MAX * 2];
    CHECK(atalaia_join_to_text(buf, n, text, sizeof(text)) > 0);

    CHECK(box_game_join_text(&game, text) == BOX_JOIN_OK);
    CHECK(game.phase == BOX_JOINED && box_game_active(&game));
    CHECK(flash.join_len == (int)n && memcmp(flash.join, buf, n) == 0);
    CHECK(shell.channel == 869475000u);
    CHECK(strcmp(shell.screen, "status") == 0 && strstr(shell.screen_data, "Joined game") != NULL);
    atalaia_header_t h;
    uint8_t pl[PKT_CAP];
    size_t pn;
    CHECK(last_of(ATALAIA_MSG_HELLO, &h, pl, &pn));
    CHECK(h.source == NODE && h.game_id == GAME_ID && h.hop_limit == 2);
    /* Tapping the same card again while waiting is fine. */
    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_OK);

    uint32_t now = 100;
    run_ms(&now, 100);
    CHECK(!runner.running);
    cmd(FIELD_CMD_START);
    CHECK(game.phase == BOX_PLAYING && runner.running);
    CHECK(runner.node_id == NODE && runner.game_seed == 7);
    /* While playing, a new card is refused. */
    j.game_id = GAME_ID + 1;
    size_t n2 = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, n2) == BOX_JOIN_BUSY);

    /* Red holds the button for 1 s (capture_hold_ms from the join's params). */
    for (int ms = 250; ms <= 1000; ms += 250) {
        char json[64];
        snprintf(json, sizeof(json), "{\"team\":\"red\",\"ms\":%d}", ms);
        node_runner_input(&runner, "team_input.hold", json);
    }
    CHECK(events_named("zone.captured") == 1);
    CHECK(game.owner_team == 1);
    /* 3 s of holding the zone at 5 points a second. */
    run_ms(&now, 3000);
    const atalaia_score_t *score = atalaia_node_score(runner.node);
    CHECK(score->gained[1] >= 10);
    CHECK(last_of(ATALAIA_MSG_STATE, &h, pl, &pn));
    atalaia_state_msg_t st;
    CHECK(atalaia_state_decode(pl, pn, &st));
    CHECK(st.owner_team == 1 && st.counter_count == 2 && st.counters[0].team == 1);
    CHECK(st.counters[0].score >= 5 && st.phase == FIELD_GAME_RUNNING && (st.flags & 1));

    /* Pause: game time stands still. Resume: it moves again. */
    cmd(FIELD_CMD_PAUSE);
    CHECK(game.paused);
    uint32_t t0 = runner.game_time_ms;
    run_ms(&now, 1000);
    CHECK(runner.game_time_ms == t0);
    cmd(FIELD_CMD_RESUME);
    run_ms(&now, 500);
    CHECK(runner.game_time_ms > t0);

    /* End: the stored join goes at once; the key once everything is acknowledged. */
    cmd(FIELD_CMD_END);
    CHECK(game.phase == BOX_ENDED && flash.join_len == 0);
    run_ms(&now, 20);
    CHECK(game.phase == BOX_ENDED); /* the capture is not acknowledged yet */
    ack_all();
    run_ms(&now, 20);
    CHECK(game.phase == BOX_IDLE && !game.link.proto.has_key);
    static const uint8_t zero[16];
    CHECK(memcmp(game.link.proto.game_key, zero, 16) == 0);
}

/* Without any ACK the box still lets the key go: when the events give up, at most a minute. */
static void test_end_without_acks(void)
{
    fixture(false);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    uint32_t now = 10;
    cmd(FIELD_CMD_START);
    for (int ms = 250; ms <= 1000; ms += 250) {
        char json[64];
        snprintf(json, sizeof(json), "{\"team\":\"blue\",\"ms\":%d}", ms);
        node_runner_input(&runner, "team_input.hold", json);
    }
    cmd(FIELD_CMD_END);
    run_ms(&now, 20000);
    CHECK(game.phase == BOX_ENDED); /* the capture is still being retried */
    run_ms(&now, BOX_END_LINGER_MS - 20000 + 100);
    CHECK(game.phase == BOX_IDLE && !game.link.proto.has_key);
}

static void test_resume_after_reboot(void)
{
    fixture(false);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, JOIN_KEY, buf);
    /* Joined from the NFC card's memory this time. */
    uint8_t tag[ATALAIA_JOIN_MAX + 64];
    size_t tn = atalaia_join_to_ndef_tag(buf, n, tag, sizeof(tag));
    CHECK(box_game_join_tag(&game, tag, tn) == BOX_JOIN_OK);
    CHECK(game.link.proto.epoch == 1);
    uint32_t now = 10;
    cmd(FIELD_CMD_START);
    run_ms(&now, 2500); /* state saved every second */
    uint32_t played = runner.game_time_ms;
    CHECK(played >= 2000);
    node_runner_stop(&runner);

    /* Battery pulled: the same flash, a new boot. */
    fixture(true);
    CHECK(game.have_join_key);
    CHECK(box_game_resume(&game, 5));
    CHECK(game.phase == BOX_PLAYING && runner.running);
    CHECK(game.link.proto.epoch == 2 && flash.epoch == 2);
    CHECK(runner.game_time_ms >= 2000 && runner.game_time_ms <= played);
    CHECK(runner.node_id == NODE);
    CHECK(events_named("node.rebooted") == 1);
    atalaia_header_t h;
    uint8_t pl[PKT_CAP];
    size_t pn;
    CHECK(last_of(ATALAIA_MSG_HELLO, &h, pl, &pn));
    atalaia_hello_t hello;
    CHECK(atalaia_hello_decode(pl, pn, &hello) && hello.epoch == 2);
    /* A stored join from another field's key is dropped at boot. */
    fixture(true);
    flash.key[0] ^= 1;
    box_game_load_join_key(&game);
    CHECK(!box_game_resume(&game, 5));
    CHECK(flash.join_len == 0);
    state_persist_clear();
}

/* A join naming a main mode and a modifier ("main+modifier"): the box runs both
 * stored scripts in one chunk, as the controller and the simulator compose them. */
static void test_join_with_a_modifier(void)
{
    fixture(false);
    static char codes[PRESET_SOURCE_MAX];
    FILE *f = fopen(MODES_DIR "/codes/node.lua", "rb");
    CHECK(f != NULL);
    size_t codes_len = f ? fread(codes, 1, sizeof(codes) - 1, f) : 0;
    if (f) fclose(f);
    const builtin_source_t sources[] = {{"org.atalaia.codes", codes, codes_len}};
    CHECK(builtin_presets_seed(sources, 1) == 1);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));

    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.domination+org.atalaia.nope");
    size_t n = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_NO_MODE);
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.domination+org.atalaia.codes");
    snprintf(j.params_json, sizeof(j.params_json),
             "{\"capture_hold_ms\":1000,\"tick_s\":60,\"points_per_tick\":1,"
             "\"codes\":\"4711:points:50\"}");
    n = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_OK);
    CHECK(strncmp(preset.source, "do\n", 3) == 0);
    CHECK(strstr(preset.source, "\nend\ndo\n") != NULL);
    CHECK(preset.source_len == strlen(preset.source));
    CHECK(preset.source_len > codes_len + 16 && preset.source_len < sizeof(preset.source));

    uint32_t now = 100;
    cmd(FIELD_CMD_START);
    CHECK(game.phase == BOX_PLAYING && runner.running);
    for (int ms = 250; ms <= 1000; ms += 250) {
        char json[64];
        snprintf(json, sizeof(json), "{\"team\":\"red\",\"ms\":%d}", ms);
        node_runner_input(&runner, "team_input.hold", json);
    }
    CHECK(events_named("zone.captured") == 1);
    for (const char *k = "4711#"; *k; k++) {
        char json[16];
        snprintf(json, sizeof(json), "{\"key\":\"%c\"}", *k);
        node_runner_input(&runner, "keypad.key", json);
    }
    CHECK(events_named("code.used") == 1);
    CHECK(events_named("script.error") == 0);
    run_ms(&now, 100);
    CHECK(atalaia_node_score(runner.node)->gained[1] == 50);
    cmd(FIELD_CMD_END);
    ack_all();
    run_ms(&now, 20);
    state_persist_clear();
}

/* "@tag <uid> <payload>" text for a player tag signed with key. */
static void tag_text(const char *player, uint8_t team, uint16_t game_id, const uint8_t *key,
                     char *out, size_t cap)
{
    atalaia_tag_t t;
    memset(&t, 0, sizeof(t));
    snprintf(t.player, sizeof(t.player), "%s", player);
    t.team = team;
    t.game_id = game_id;
    uint8_t buf[ATALAIA_TAG_MAX];
    size_t n = atalaia_tag_encode(&t, key, buf, sizeof(buf));
    CHECK(n > 0);
    size_t o = (size_t)snprintf(out, cap, "04a1b2c3d4e5f6 ");
    for (size_t i = 0; i < n && o + 3 < cap; i++)
        o += (size_t)snprintf(out + o, cap - o, "%02x", buf[i]);
}

/* Kill Confirmed in a joined game: player tags are checked with the join's game key. */
static void test_player_tags(void)
{
    fixture(false);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.kill_confirmed");
    snprintf(j.role, sizeof(j.role), "station");
    j.params_json[0] = '\0';
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_OK);
    char text[160];
    tag_text("b7", 2, GAME_ID, GAME_KEY, text, sizeof(text));
    CHECK(!box_game_tag_text(&game, text)); /* not started yet: nothing runs */

    uint32_t now = 100;
    cmd(FIELD_CMD_START);
    CHECK(game.phase == BOX_PLAYING && runner.running);
    CHECK(strcmp(runner.mode_id, "org.atalaia.kill_confirmed") == 0);
    node_runner_input(&runner, "team_input.press", "{\"team\":\"red\"}");
    CHECK(box_game_tag_text(&game, text));
    CHECK(events_named("kill.confirmed") == 1);
    CHECK(events_named("score.delta") == 1); /* blue's penalty */
    CHECK(atalaia_score_net(atalaia_node_score(runner.node), 1) == 1);
    CHECK(atalaia_score_net(atalaia_node_score(runner.node), 2) == -1);

    /* Signed with another key, for another game, unsigned: the node hears them, nothing counts. */
    static const uint8_t other[16] = {1};
    tag_text("b8", 2, GAME_ID, other, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    tag_text("b9", 2, GAME_ID + 1, GAME_KEY, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    CHECK(box_game_tag_text(&game, "04a1b2c3"));
    run_ms(&now, 100);
    CHECK(events_named("kill.confirmed") == 1);
    /* Malformed console text. */
    CHECK(!box_game_tag_text(&game, "zz"));
    CHECK(!box_game_tag_text(&game, "04a1 0"));
    CHECK(!box_game_tag_text(&game, "04a1 00 extra"));
    CHECK(!box_game_tag_text(&game, ""));

    /* A stand-alone game has no game key: a tag is reported but never valid. */
    fixture(false);
    preset_t *p = &preset;
    memset(p, 0, sizeof(*p));
    snprintf(p->mode_id, sizeof(p->mode_id), "org.atalaia.kill_confirmed");
    long len = preset_store_read_source(p->mode_id, p->source, sizeof(p->source));
    CHECK(len > 0);
    p->source_len = len > 0 ? (size_t)len : 0;
    snprintf(p->params_json, sizeof(p->params_json),
             "{\"confirm_points\":1,\"penalty_points\":1,\"turn_in_s\":20,\"retag_after_s\":60}");
    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, p, teams, 2));
    CHECK(runner.queues.screen_count >= 1);
    CHECK(strcmp(runner.queues.screens[0].template_name, "@mode") == 0);
    CHECK(strncmp(runner.queues.screens[0].data_json, "org.atalaia.kill_confirmed {", 28) == 0);
    node_runner_input(&runner, "team_input.press", "{\"team\":\"red\"}");
    int before = runner.event_count;
    tag_text("b7", 2, GAME_ID, GAME_KEY, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    CHECK(runner.event_count == before); /* refused: no kill.confirmed */
    node_runner_stop(&runner);
}

/* A CMD for this box with its params (compact JSON, as the controller's codec writes them). */
static void cmd_params(uint8_t opcode, const char *params_json)
{
    atalaia_cmd_msg_t m;
    memset(&m, 0, sizeof(m));
    m.cmd = opcode;
    m.dest = NODE;
    snprintf(m.params_json, sizeof(m.params_json), "%s", params_json);
    uint8_t buf[192];
    size_t n = atalaia_cmd_encode(&m, buf, sizeof(buf));
    CHECK(n > 0);
    from_controller(ATALAIA_MSG_CMD, buf, n);
}

/* The last screen the mode drew since the queue was emptied, or NULL. */
static const char *last_screen(const char **data)
{
    if (runner.queues.screen_count == 0) return NULL;
    const screen_update_t *s = &runner.queues.screens[runner.queues.screen_count - 1];
    if (data != NULL) *data = s->data_json;
    return s->template_name;
}

/* Held for ms: team_input.hold every 250 ms, then the release (as the button tracker). */
static void hold_ms(int ms)
{
    char json[64];
    for (int t = 250; t <= ms; t += 250) {
        snprintf(json, sizeof(json), "{\"team\":\"blue\",\"ms\":%d}", t);
        node_runner_input(&runner, "team_input.hold", json);
    }
    snprintf(json, sizeof(json), "{\"team\":\"blue\",\"ms\":%d}", ms);
    node_runner_input(&runner, "team_input.release", json);
}

/* The Medic Kit, a role package: the controller joins a kit with the kit's id alone, so
 * the box composes nothing; a player's tag and a held button heal; the controller's count
 * of a player's heals and the GM's refill reach the script as mode commands (opcode 8). */
static void test_medic_kit(void)
{
    fixture(false);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.medic");
    snprintf(j.role, sizeof(j.role), "medic");
    snprintf(j.params_json, sizeof(j.params_json),
             "{\"heal_hold_s\":1,\"charges\":1,\"max_heals_per_player\":1,\"cooldown_s\":0,"
             "\"lang\":\"en\"}");
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, JOIN_KEY, buf);
    CHECK(box_game_join(&game, buf, n) == BOX_JOIN_OK);
    uint32_t now = 100;
    cmd(FIELD_CMD_START);
    CHECK(game.phase == BOX_PLAYING && runner.running);
    CHECK(strcmp(runner.mode_id, "org.atalaia.medic") == 0);

    char text[160];
    tag_text("b7", 2, GAME_ID, GAME_KEY, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    hold_ms(1000);
    CHECK(events_named("medic.heal") == 1);
    CHECK(events_named("medic.empty") == 1); /* one charge: empty after one heal */

    /* The GM refills the kit; the controller says b8 had a heal at another kit. */
    cmd_params(FIELD_CMD_MODE, "{\"name\":\"refill\"}");
    cmd_params(FIELD_CMD_MODE, "{\"at\":3,\"name\":\"heals\",\"player\":\"b8\",\"used\":1}");
    runner.queues.screen_count = 0;
    tag_text("b8", 2, GAME_ID, GAME_KEY, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    const char *data = NULL;
    const char *name = last_screen(&data);
    CHECK(name != NULL && strcmp(name, "medic_refused") == 0);
    CHECK(data != NULL && strstr(data, "\"reason\":\"limit\"") != NULL);
    hold_ms(1000);
    CHECK(events_named("medic.heal") == 1);

    /* A forged tag is refused; b9 is healed with the refilled charge. */
    static const uint8_t other[16] = {1};
    runner.queues.screen_count = 0;
    tag_text("b9", 2, GAME_ID, other, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    name = last_screen(&data);
    CHECK(name != NULL && strcmp(name, "medic_refused") == 0);
    CHECK(data != NULL && strstr(data, "\"message\":\"Forged tag\"") != NULL);
    tag_text("b9", 2, GAME_ID, GAME_KEY, text, sizeof(text));
    CHECK(box_game_tag_text(&game, text));
    hold_ms(1000);
    CHECK(events_named("medic.heal") == 2);
    CHECK(events_named("medic.empty") == 2);
    CHECK(events_named("script.error") == 0);

    /* A mode command before the start of a game, or after its end, reaches no script. */
    cmd(FIELD_CMD_END);
    ack_all();
    run_ms(&now, 20);
    cmd_params(FIELD_CMD_MODE, "{\"name\":\"refill\"}");
    CHECK(!runner.running);
    state_persist_clear();
}

/* battery.low: once per crossing below the threshold, rearmed 5 points above it; never
 * without a gauge, never outside a joined game; HELLO carries the level. */
static void test_battery_low(void)
{
    fixture(false);
    game.shell.battery_pct = sh_battery;
    CHECK(game.battery_low_pct == BOX_BATTERY_LOW_PCT);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];

    /* No gauge: HELLO says unknown, and nothing is ever sent. */
    fake_battery = -1;
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    atalaia_header_t h;
    uint8_t pl[PKT_CAP];
    size_t pn;
    atalaia_hello_t hello;
    CHECK(last_of(ATALAIA_MSG_HELLO, &h, pl, &pn) && atalaia_hello_decode(pl, pn, &hello));
    CHECK(hello.battery_pct == 0xFF);
    ack_all();
    uint32_t now = 10;
    run_ms(&now, 3 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 0);

    /* A gauge at 50 %: still nothing. */
    fake_battery = 50;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 0);
    /* Below 20 %: one battery.low with the level, sent once without an ACK. */
    fake_battery = 19;
    run_ms(&now, BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 1 && last_battery_low() == 19);
    cmd(FIELD_CMD_START);
    fake_battery = 12;
    run_ms(&now, 3 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 1);
    /* Back up to 24 % (inside the hysteresis) and down again: nothing new. */
    fake_battery = 24;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    fake_battery = 18;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 1);
    /* 25 % rearms it; 17 % sends a second one. */
    fake_battery = 25;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    fake_battery = 17;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 2 && last_battery_low() == 17);
    /* A reading that is not a level (the gauge went away) changes nothing. */
    fake_battery = 101;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 2);

    /* After the game, nothing: the box is in no game. */
    cmd(FIELD_CMD_END);
    ack_all();
    run_ms(&now, 20);
    CHECK(game.phase == BOX_IDLE);
    int before = shell.count;
    fake_battery = 5;
    game.battery_low = false;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(shell.count == before);

    /* A threshold of 0 (CONFIG_ATALAIA_BATTERY_LOW_PCT=0) never sends it. */
    fixture(false);
    game.shell.battery_pct = sh_battery;
    game.battery_low_pct = 0;
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    CHECK(last_of(ATALAIA_MSG_HELLO, &h, pl, &pn) && atalaia_hello_decode(pl, pn, &hello));
    CHECK(hello.battery_pct == 5);
    now = 10;
    run_ms(&now, 2 * BOX_BATTERY_CHECK_MS);
    CHECK(events_named("battery.low") == 0);
    fake_battery = -1;
    state_persist_clear();
}

/* ---- Between games (box_lobby.c, protocol/field-frames.md) -------------------------- */

/* A deterministic "CSPRNG" for the tests (xorshift32). */
static uint32_t rng_state = 0x1234567u;

static void sh_random(void *user, uint8_t *buf, size_t len)
{
    (void)user;
    for (size_t i = 0; i < len; i++) {
        rng_state ^= rng_state << 13;
        rng_state ^= rng_state >> 17;
        rng_state ^= rng_state << 5;
        buf[i] = (uint8_t)rng_state;
    }
}

static uint8_t ff_key[ATALAIA_FF_KEY_SIZE];

/* The fixture with field frames on: a random source and the join key. */
static void lobby_fixture(void)
{
    fixture(false);
    game.shell.random = sh_random;
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    CHECK(game.lobby.ready && flash.have_device_id);
    atalaia_ff_key(JOIN_KEY, ff_key);
}

/* The field frames the box sent from packet index `from`, opened; the last one in *m. */
static int field_frames_since(int from, atalaia_ff_msg_t *m)
{
    int count = 0;
    for (int i = from; i < shell.count; i++) {
        uint8_t body[ATALAIA_FF_BODY_MAX];
        size_t n = atalaia_ff_open(ff_key, shell.pkt[i], shell.len[i], body, sizeof(body),
                                   &atalaia_crypto_test_stub);
        if (n > 0 && atalaia_ff_body_decode(body, n, m)) count++;
    }
    return count;
}

/* A controller's frame to the box (sealed under key; nonce from the counter). */
static void to_box(const uint8_t key[16], const atalaia_ff_msg_t *m, uint8_t *keep,
                   size_t *keep_len)
{
    static uint8_t counter;
    uint8_t body[ATALAIA_FF_BODY_MAX];
    size_t n = atalaia_ff_body_encode(m, body, sizeof(body));
    CHECK(n > 0);
    uint8_t nonce[ATALAIA_FF_NONCE_SIZE] = {0xC0, counter++};
    uint8_t frame[ATALAIA_FF_MAX];
    size_t len =
        atalaia_ff_seal(key, nonce, body, n, frame, sizeof(frame), &atalaia_crypto_test_stub);
    CHECK(len > 0);
    if (keep != NULL) {
        memcpy(keep, frame, len);
        *keep_len = len;
    }
    box_game_on_packet(&game, frame, len, -60);
}

/* An invite into game `gid` (node `node`) for token, in as many parts as it needs; each
 * frame is kept in rec (when given) to be played back later. */
static int invite_signed(const uint8_t key[16], const uint8_t *join_key, const uint8_t token[8],
                         uint16_t gid, uint16_t node, uint16_t invite_id,
                         uint8_t rec[][ATALAIA_FF_MAX], size_t *rec_len)
{
    atalaia_join_t j;
    make_join(&j);
    j.game_id = gid;
    j.node_id = node;
    j.game_key[0] ^= (uint8_t)gid;
    /* Long enough to need two parts (the params: 200 bytes of JSON at most). */
    snprintf(j.params_json, sizeof(j.params_json),
             "{\"capture_hold_ms\":1000,\"tick_s\":1,\"points_per_tick\":5,\"note\":\"%s\"}",
             "a field-long note to make the join payload longer than one part");
    uint8_t payload[ATALAIA_JOIN_MAX];
    size_t n = encode(&j, join_key, payload);
    int parts = (int)atalaia_ff_parts_for(n);
    for (int p = 0; p < parts; p++) {
        atalaia_ff_msg_t m;
        memset(&m, 0, sizeof(m));
        m.kind = ATALAIA_FF_INVITE;
        memcpy(m.device_id, game.lobby.device_id, 8);
        memcpy(m.token, token, 8);
        m.invite_id = invite_id;
        m.parts = (uint8_t)parts;
        m.part = (uint8_t)(parts - 1 - p); /* last part first */
        size_t at = (size_t)m.part * ATALAIA_FF_CHUNK_MAX;
        m.chunk_len = (uint8_t)(n - at < ATALAIA_FF_CHUNK_MAX ? n - at : ATALAIA_FF_CHUNK_MAX);
        memcpy(m.chunk, payload + at, m.chunk_len);
        to_box(key, &m, rec ? rec[p] : NULL, rec ? &rec_len[p] : NULL);
    }
    return parts;
}

static int invite(const uint8_t key[16], const uint8_t token[8], uint16_t gid, uint16_t node,
                  uint16_t invite_id, uint8_t rec[][ATALAIA_FF_MAX], size_t *rec_len)
{
    return invite_signed(key, JOIN_KEY, token, gid, node, invite_id, rec, rec_len);
}

/* A CMD from the controller of the game the box is in now (invite() gave it its key). */
static void cmd_now(uint8_t opcode)
{
    static uint16_t seq;
    atalaia_cmd_msg_t c;
    memset(&c, 0, sizeof(c));
    c.cmd = opcode;
    c.dest = 0xFFFF;
    uint8_t pl[64];
    size_t n = atalaia_cmd_encode(&c, pl, sizeof(pl));
    atalaia_header_t h = {
        ATALAIA_VF_MAKE(1, 2, 0, 1), game.join.game_id, 0, seq++, 2, ATALAIA_MSG_CMD};
    uint8_t out[PKT_CAP];
    size_t len = atalaia_packet_encrypt(&h, 1, game.join.game_key, pl, n, out, sizeof(out),
                                        &atalaia_crypto_test_stub);
    CHECK(len > 0);
    box_game_on_packet(&game, out, len, -55);
}

/* Joins game GAME_ID by card, starts it, ends it: the box is free again. */
static void play_and_end(uint32_t *now)
{
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    CHECK(!box_lobby_available(&game));
    cmd(FIELD_CMD_START);
    run_ms(now, 100);
    cmd(FIELD_CMD_END);
    CHECK(game.phase == BOX_ENDED && box_lobby_available(&game));
}

static void test_lobby_announce_and_invite(void)
{
    lobby_fixture();
    uint32_t now = 10;
    /* At first (no game) it announces 2-20 s after starting, then about every minute or more. */
    int mark = shell.count;
    run_ms(&now, BOX_ANNOUNCE_FIRST_MAX_MS + 100);
    atalaia_ff_msg_t m;
    CHECK(field_frames_since(mark, &m) == 1);
    CHECK(m.kind == ATALAIA_FF_ANNOUNCE && memcmp(m.device_id, flash.device_id, 8) == 0);
    CHECK(strcmp(m.name, "box") == 0 && m.last_game == 0 && m.answer == 0);
    /* A field frame is not relayed, and its header is the field's, not a game's. */
    atalaia_header_t h;
    CHECK(atalaia_header_decode(shell.pkt[shell.count - 1], &h));
    CHECK(h.game_id == 0 && h.type == ATALAIA_MSG_FIELD && h.hop_limit == 0);

    play_and_end(&now);
    /* The game's last role and id go in the announcements after it. */
    mark = shell.count;
    run_ms(&now, BOX_ANNOUNCE_FIRST_MAX_MS + 100);
    CHECK(field_frames_since(mark, &m) >= 1);
    CHECK(m.last_game == GAME_ID && strcmp(m.last_role, "zone") == 0);
    uint8_t token[8];
    memcpy(token, m.token, 8);

    /* The invite for the next game, in two parts: joined, "Invited to game", an answer. */
    mark = shell.count;
    CHECK(invite(ff_key, token, 0x0C01, 31, 4242, NULL, NULL) == 2);
    CHECK(game.phase == BOX_JOINED && game.join.game_id == 0x0C01 && game.join.node_id == 31);
    CHECK(strstr(shell.screen_data, "\"Invited\",\"mode\":\"3073: zone\"") != NULL);
    CHECK(game.lobby.invites_accepted == 1 && memcmp(game.lobby.token, token, 8) != 0);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    int frames = field_frames_since(mark, &m);
    CHECK(frames == 1 && m.answer == 4242 && m.result == ATALAIA_FF_ACCEPTED);
    /* The new game's HELLO carries the device id. */
    atalaia_hello_t hello;
    uint8_t pl[PKT_CAP];
    size_t pn = 0;
    bool found = false;
    for (int i = shell.count - 1; i >= 0 && !found; i--) {
        uint8_t key2[16];
        memcpy(key2, GAME_KEY, 16);
        key2[0] ^= 0x01; /* invite(): game_key[0] ^= gid (0x0C01 -> 0x01) */
        found = atalaia_packet_decrypt(shell.pkt[i], shell.len[i], game.link.proto.epoch, key2, &h,
                                       pl, &pn, &atalaia_crypto_test_stub) &&
                h.type == ATALAIA_MSG_HELLO;
    }
    CHECK(found && atalaia_hello_decode(pl, pn, &hello));
    CHECK(hello.has_device_id && memcmp(hello.device_id, flash.device_id, 8) == 0);
    /* While in that game it does not announce. */
    mark = shell.count;
    run_ms(&now, 3 * BOX_ANNOUNCE_MIN_MS);
    CHECK(field_frames_since(mark, &m) == 0);
    state_persist_clear();
}

static void test_lobby_refusals(void)
{
    lobby_fixture();
    uint32_t now = 10;
    play_and_end(&now);
    uint8_t token[8];
    memcpy(token, game.lobby.token, 8);

    /* Another field's key: not even opened. */
    uint8_t other_key[16];
    static const uint8_t other_join[32] = {9, 9, 9};
    atalaia_ff_key(other_join, other_key);
    int mark = shell.count;
    invite(other_key, token, 0x0C02, 31, 1, NULL, NULL);
    CHECK(game.phase == BOX_ENDED && game.lobby.frames_ignored == 2);
    /* An unknown token: silently refused. */
    static const uint8_t old[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    invite(ff_key, old, 0x0C02, 31, 2, NULL, NULL);
    CHECK(game.phase == BOX_ENDED && game.lobby.invites_refused == 2);
    /* Another box's device id: not for us. */
    atalaia_ff_msg_t inv = {.kind = ATALAIA_FF_INVITE, .invite_id = 3, .parts = 1, .chunk_len = 1};
    memcpy(inv.token, token, 8);
    to_box(ff_key, &inv, NULL, NULL);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    atalaia_ff_msg_t m;
    CHECK(field_frames_since(mark, &m) == 0);

    /* The game it has just played to the end, invited again: "ended". The answer carries a new
     * token (every answered invite drops both, review finding 2): the controller learns it. */
    static uint8_t rec[3][ATALAIA_FF_MAX];
    size_t rec_len[3] = {0};
    int parts = invite(ff_key, token, GAME_ID, 31, 4, rec, rec_len);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    CHECK(field_frames_since(mark, &m) == 1 && m.answer == 4 && m.result == ATALAIA_FF_ENDED);
    CHECK(game.phase != BOX_JOINED);
    CHECK(memcmp(m.token, token, 8) != 0 && memcmp(m.token, game.lobby.token, 8) == 0);
    CHECK(!game.lobby.have_prev);
    /* That refused invite played back: an old token, silence. */
    uint32_t refused = game.lobby.invites_refused;
    for (int p = 0; p < parts; p++) box_game_on_packet(&game, rec[p], rec_len[p], -60);
    CHECK(game.lobby.invites_refused == refused + (uint32_t)parts);
    memcpy(token, m.token, 8);

    /* A payload signed with another join key, under the right field key: "refused". */
    mark = shell.count;
    invite_signed(ff_key, other_join, token, 0x0C02, 31, 5, NULL, NULL);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    CHECK(field_frames_since(mark, &m) == 1 && m.answer == 5 && m.result == ATALAIA_FF_REFUSED);
    CHECK(memcmp(m.token, token, 8) != 0);
    memcpy(token, m.token, 8);

    /* A card join meanwhile drops the tokens too: the controller's last one gets no answer. */
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    CHECK(memcmp(game.lobby.token, token, 8) != 0);
    cmd(FIELD_CMD_START);
    CHECK(game.phase == BOX_PLAYING);
    mark = shell.count;
    invite(ff_key, token, 0x0C03, 31, 6, NULL, NULL);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    CHECK(field_frames_since(mark, &m) == 0);
    /* With its current token: "busy", the game goes on, and that token is gone too. */
    memcpy(token, game.lobby.token, 8);
    mark = shell.count;
    parts = invite(ff_key, token, 0x0C03, 31, 7, rec, rec_len);
    run_ms(&now, BOX_INVITE_ANSWER_MAX_MS + 20);
    CHECK(field_frames_since(mark, &m) == 1 && m.answer == 7 && m.result == ATALAIA_FF_BUSY);
    CHECK(game.phase == BOX_PLAYING && game.join.game_id == GAME_ID);
    CHECK(memcmp(game.lobby.token, token, 8) != 0);
    /* The game ends; the busy invite played back cannot pull the box into game 0x0C03. */
    cmd(FIELD_CMD_END);
    CHECK(game.phase == BOX_ENDED);
    for (int p = 0; p < parts; p++) box_game_on_packet(&game, rec[p], rec_len[p], -60);
    CHECK(game.phase == BOX_ENDED && game.join.game_id == GAME_ID);
    state_persist_clear();
}

/* Two recorded invites played back in turn get one answer each in 10 s, and at most
 * BOX_ANSWERS_PER_MIN a minute in all (review finding 3). The worst case: tokens put back. */
static void test_lobby_answers_are_limited(void)
{
    lobby_fixture();
    uint32_t now = 10;
    play_and_end(&now);
    uint8_t token[8];
    memcpy(token, game.lobby.token, 8);
    int mark = shell.count;
    for (int i = 0; i < 40; i++) {
        memcpy(game.lobby.token, token, 8); /* as if the token never moved */
        invite(ff_key, token, GAME_ID, 31, (uint16_t)(i % 2 ? 201 : 202), NULL, NULL);
        run_ms(&now, 2000);
    }
    atalaia_ff_msg_t m;
    int answers = 0;
    for (int i = mark; i < shell.count; i++) {
        uint8_t body[ATALAIA_FF_BODY_MAX];
        size_t n = atalaia_ff_open(ff_key, shell.pkt[i], shell.len[i], body, sizeof(body),
                                   &atalaia_crypto_test_stub);
        if (n > 0 && atalaia_ff_body_decode(body, n, &m) && m.answer != 0) answers++;
    }
    CHECK(answers > 0 && answers <= 2 * BOX_ANSWERS_PER_MIN);
    state_persist_clear();
}

/* A refused invite in BOX_ENDED keeps the last game's unacknowledged events (finding 7). */
static void test_lobby_refused_invite_keeps_the_ended_game(void)
{
    lobby_fixture();
    uint32_t now = 10;
    atalaia_join_t j;
    make_join(&j);
    uint8_t buf[ATALAIA_JOIN_MAX];
    CHECK(box_game_join(&game, buf, encode(&j, JOIN_KEY, buf)) == BOX_JOIN_OK);
    cmd(FIELD_CMD_START);
    for (int ms = 250; ms <= 1000; ms += 250) {
        char json[64];
        snprintf(json, sizeof(json), "{\"team\":\"red\",\"ms\":%d}", ms);
        node_runner_input(&runner, "team_input.hold", json);
    }
    cmd(FIELD_CMD_END);
    CHECK(game.phase == BOX_ENDED && field_link_pending(&game.link) > 0);
    size_t pending = field_link_pending(&game.link);
    uint8_t token[8];
    memcpy(token, game.lobby.token, 8);
    static const uint8_t other_join[32] = {7, 7, 7};
    invite_signed(ff_key, other_join, token, 0x0C20, 31, 9, NULL, NULL);
    CHECK(game.phase == BOX_ENDED && field_link_pending(&game.link) == pending);
    CHECK(game.link.proto.has_key); /* not left: the game key stays until the events are acked */
    (void)now;
    state_persist_clear();
}

/* The boot count unreadable (not "none yet"): no field frame at all (finding 6). */
static void test_lobby_unreadable_boot_count(void)
{
    lobby_fixture();
    flash.have_ff_boot = true;
    flash.ff_boot = 7;
    flash.ff_boot_read_fails = true;
    uint32_t now = 10;
    run_ms(&now, BOX_ANNOUNCE_FIRST_MAX_MS + 20);
    CHECK(shell.count == 0 && flash.ff_boot == 7);
    flash.ff_boot_read_fails = false;
    run_ms(&now, 2 * BOX_ANNOUNCE_MIN_MS);
    CHECK(shell.count > 0 && flash.ff_boot == 8); /* readable again: boot 8, not boot 1 */
}

static void test_lobby_replay_refused(void)
{
    lobby_fixture();
    uint32_t now = 10;
    play_and_end(&now);
    static uint8_t rec[3][ATALAIA_FF_MAX];
    size_t rec_len[3] = {0};
    uint8_t token[8];
    memcpy(token, game.lobby.token, 8);
    int parts = invite(ff_key, token, 0x0C10, 40, 77, rec, rec_len);
    CHECK(game.phase == BOX_JOINED && game.join.game_id == 0x0C10);
    cmd_now(FIELD_CMD_END); /* that game ends too: the box is free again */
    CHECK(game.phase == BOX_ENDED);
    /* Someone plays the recorded invite back: an old token, nothing happens. */
    uint32_t refused = game.lobby.invites_refused;
    for (int p = 0; p < parts; p++) box_game_on_packet(&game, rec[p], rec_len[p], -60);
    CHECK(game.phase == BOX_ENDED && game.lobby.invites_refused == refused + (uint32_t)parts);
    /* The token rotates every 10 minutes; the previous one still works once. */
    uint8_t before[8];
    memcpy(before, game.lobby.token, 8);
    run_ms(&now, BOX_TOKEN_ROTATE_MS + 20);
    CHECK(memcmp(before, game.lobby.token, 8) != 0 && game.lobby.have_prev);
    invite(ff_key, before, 0x0C11, 41, 78, NULL, NULL);
    CHECK(game.phase == BOX_JOINED && game.join.game_id == 0x0C11);
    state_persist_clear();
}

static void test_lobby_discover_and_ready_screen(void)
{
    lobby_fixture();
    uint32_t now = 10;
    play_and_end(&now);
    /* The final screen stays BOX_READY_MS, then "Ready" for the next game. */
    run_ms(&now, BOX_READY_MS - 200);
    CHECK(strstr(shell.screen_data, "\"Ready\",\"mode\":\"next game\"") == NULL);
    run_ms(&now, 300);
    CHECK(strcmp(shell.screen, "status") == 0 &&
          strstr(shell.screen_data, "\"Ready\",\"mode\":\"next game\"") != NULL);
    /* DISCOVER: an answer within 3 s, but not twice within a quarter of the interval (no
     * announcement for a long time, and the next periodic one far away). */
    game.lobby.announced = false;
    game.lobby.announce_ms = now + 10 * BOX_ANNOUNCE_MIN_MS;
    int mark = shell.count;
    atalaia_ff_msg_t d = {.kind = ATALAIA_FF_DISCOVER};
    to_box(ff_key, &d, NULL, NULL);
    run_ms(&now, BOX_DISCOVER_ANSWER_MAX_MS + 20);
    atalaia_ff_msg_t m;
    CHECK(field_frames_since(mark, &m) == 1 && m.kind == ATALAIA_FF_ANNOUNCE);
    mark = shell.count;
    to_box(ff_key, &d, NULL, NULL);
    run_ms(&now, BOX_DISCOVER_ANSWER_MAX_MS + 20);
    CHECK(field_frames_since(mark, &m) == 0);

    /* The shell's picker: no ready screen over it. */
    play_and_end(&now);
    box_lobby_cancel_ready_screen(&game);
    snprintf(shell.screen, sizeof(shell.screen), "preset_select");
    run_ms(&now, BOX_READY_MS + 100);
    CHECK(strcmp(shell.screen, "preset_select") == 0);

    /* The announcement interval follows the sub-band's duty cycle: about a minute on
     * 869.4-869.65 MHz (10 %), much longer at 1 %. */
    game.lobby.channel_hz = 869525000u;
    game.lobby.announce_ms = now + 1;
    mark = shell.count;
    run_ms(&now, 10 * BOX_ANNOUNCE_MIN_MS);
    int g2 = field_frames_since(mark, &m);
    CHECK(g2 >= 7 && g2 <= 10);
    game.lobby.channel_hz = 868300000u;
    run_ms(&now, 3 * BOX_ANNOUNCE_MIN_MS); /* the next one is already scheduled */
    mark = shell.count;
    run_ms(&now, 20 * BOX_ANNOUNCE_MIN_MS);
    int g = field_frames_since(mark, &m);
    CHECK(g >= 1 && g <= 3);
    state_persist_clear();
}

/* The device id is made once and kept: the same after a reboot; none without a random source. */
static void test_lobby_device_id(void)
{
    lobby_fixture();
    uint8_t id[8];
    memcpy(id, flash.device_id, 8);
    char hex[17];
    box_lobby_device_hex(&game, hex);
    CHECK(strlen(hex) == 16);
    fixture(true); /* a reboot: the same flash */
    game.shell.random = sh_random;
    CHECK(box_game_load_join_key(&game) && memcmp(game.lobby.device_id, id, 8) == 0);
    fixture(false);
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX)); /* no random source */
    CHECK(!game.lobby.ready && !box_lobby_init(&game));
    box_lobby_device_hex(&game, hex);
    CHECK(hex[0] == '\0');
    /* A field frame is still taken off the game path (not a game packet). */
    atalaia_ff_msg_t d = {.kind = ATALAIA_FF_DISCOVER};
    to_box(ff_key, &d, NULL, NULL);
    CHECK(shell.count == 0);
}

/* The field frames' nonces never repeat (decision RJ-15): pseudonym | boot | count, the boot
 * count stored before the first frame of a run, raised again after a reboot; no frame at all
 * when it cannot be stored. */
static void test_lobby_nonces(void)
{
    lobby_fixture();
    uint32_t now = 10;
    int mark = shell.count;
    atalaia_ff_msg_t dsc = {.kind = ATALAIA_FF_DISCOVER};
    for (int i = 0; i < 3; i++) {
        game.lobby.announced = false;
        to_box(ff_key, &dsc, NULL, NULL);
        run_ms(&now, BOX_DISCOVER_ANSWER_MAX_MS + BOX_ANNOUNCE_FIRST_MAX_MS + 20);
    }
    CHECK(flash.have_ff_boot && flash.ff_boot == 1);
    uint8_t nk[32];
    atalaia_ff_nonce_key(JOIN_KEY, nk);
    static uint8_t seen[64][ATALAIA_FF_NONCE_SIZE];
    int seen_n = 0;
    for (int i = mark; i < shell.count && seen_n < 64; i++) {
        if (!atalaia_ff_is_frame(shell.pkt[i], shell.len[i])) continue;
        const uint8_t *n = shell.pkt[i] + ATALAIA_RF_HEADER_SIZE;
        uint8_t want[ATALAIA_FF_NONCE_SIZE];
        atalaia_ff_nonce(nk, game.lobby.device_id, 1, (uint16_t)seen_n, want);
        CHECK(memcmp(n, want, sizeof(want)) == 0); /* boot 1, count 0, 1, 2 ... */
        memcpy(seen[seen_n++], n, ATALAIA_FF_NONCE_SIZE);
    }
    CHECK(seen_n >= 3);
    /* A reboot (the same flash): boot 2, so the first frame's nonce is new. */
    fixture(true);
    game.shell.random = sh_random;
    CHECK(box_game_load_join_key(&game));
    mark = shell.count;
    run_ms(&now, BOX_ANNOUNCE_FIRST_MAX_MS + 20);
    CHECK(flash.ff_boot == 2);
    bool fresh = false;
    for (int i = mark; i < shell.count; i++) {
        if (!atalaia_ff_is_frame(shell.pkt[i], shell.len[i])) continue;
        uint8_t want[ATALAIA_FF_NONCE_SIZE];
        atalaia_ff_nonce(nk, game.lobby.device_id, 2, 0, want);
        fresh = memcmp(shell.pkt[i] + ATALAIA_RF_HEADER_SIZE, want, sizeof(want)) == 0;
        break;
    }
    CHECK(fresh);
    /* The count would wrap: the boot count rises first. */
    game.lobby.ctr = ATALAIA_FF_CTR_MAX + 1u;
    game.lobby.announced = false;
    to_box(ff_key, &dsc, NULL, NULL);
    run_ms(&now, BOX_DISCOVER_ANSWER_MAX_MS + 20);
    CHECK(flash.ff_boot == 3 && game.lobby.boot == 3);
    /* A boot count that cannot be stored: nothing is sent. */
    fixture(false);
    game.shell.random = sh_random;
    flash.ff_boot_fails = true;
    CHECK(box_game_set_join_key_hex(&game, JOIN_KEY_HEX));
    run_ms(&now, BOX_ANNOUNCE_FIRST_MAX_MS + 20);
    CHECK(shell.count == 0);
    flash.ff_boot_fails = false;
    state_persist_clear();
}

void run_box_game_tests(void)
{
    test_lobby_nonces();
    test_lobby_answers_are_limited();
    test_lobby_refused_invite_keeps_the_ended_game();
    test_lobby_unreadable_boot_count();
    test_lobby_announce_and_invite();
    test_lobby_refusals();
    test_lobby_replay_refused();
    test_lobby_discover_and_ready_screen();
    test_lobby_device_id();
    test_battery_low();
    test_medic_kit();
    test_player_tags();
    test_join_refusals();
    test_join_with_a_modifier();
    test_join_play_end();
    test_end_without_acks();
    test_resume_after_reboot();
}
