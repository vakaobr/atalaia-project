/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box in a controller's game (main/box_game.c): the join and its
 * refusals, the game driven by CMD, events and scores going out over the
 * link, the end of the game (key erased), and the rejoin after a reboot.
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
    const builtin_source_t sources[] = {{"org.atalaia.domination", dom, dom_len},
                                        {"org.atalaia.kill_confirmed", kc, kc_len}};
    int seeded = builtin_presets_seed(sources, 2);
    CHECK(keep_flash ? seeded == 0 : seeded >= 1);

    hal_stub_init(&hal);
    node_runner_init(&runner, &hal, 0);
    memset(&shell, 0, sizeof(shell));
    if (!keep_flash) memset(&flash, 0, sizeof(flash));
    nvs_ops = (atalaia_radio_nvs_ops_t){nv_read_epoch, nv_write_epoch, nv_read_key,
                                        nv_write_key,  nv_erase_key,   &flash};
    box_store_ops_t store = {st_load_join, st_save_join, st_erase_join,
                             st_load_key,  st_save_key,  &flash};
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

void run_box_game_tests(void)
{
    test_player_tags();
    test_join_refusals();
    test_join_with_a_modifier();
    test_join_play_end();
    test_end_without_acks();
    test_resume_after_reboot();
}
