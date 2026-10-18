/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box in a field controller's game (see box_game.h).
 */
#include "box_game.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "screen_types.h"
#include "state_persist.h"

static void say(box_game_t *g, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(box_game_t *g, const char *fmt, ...)
{
    if (g->shell.log == NULL) return;
    char line[192];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    g->shell.log(g->shell.user, line);
}

static void show(box_game_t *g, const char *tmpl, const char *json)
{
    if (g->shell.screen != NULL) g->shell.screen(g->shell.user, tmpl, json);
}

const char *box_join_result_name(box_join_result_t r)
{
    switch (r) {
    case BOX_JOIN_OK: return "joined";
    case BOX_JOIN_NO_KEY: return "no field join key on this box";
    case BOX_JOIN_NOT_A_JOIN: return "not a join payload";
    case BOX_JOIN_REFUSED: return "refused";
    case BOX_JOIN_CONTROLLER: return "a standby controller's payload, not a box's";
    case BOX_JOIN_NO_MODE: return "mode not installed";
    case BOX_JOIN_BUSY: return "a game is being played";
    case BOX_JOIN_STORAGE: return "could not store the join";
    case BOX_JOIN_RADIO: return "radio halted (epoch storage failed)";
    }
    return "?";
}

/* ---- Link callbacks ---------------------------------------------------------- */

static uint8_t game_state_of(const box_game_t *g)
{
    switch (g->phase) {
    case BOX_PLAYING: return g->paused ? FIELD_GAME_PAUSED : FIELD_GAME_RUNNING;
    case BOX_ENDED: return FIELD_GAME_ENDED;
    default: return FIELD_GAME_WAITING;
    }
}

static void link_get_state(void *user, atalaia_state_msg_t *st)
{
    box_game_t *g = (box_game_t *)user;
    st->owner_team = g->owner_team;
    st->phase = game_state_of(g);
    st->game_time_ms = g->runner->game_time_ms;
    st->counter_count = 0;
    if (g->runner->node != NULL) {
        const atalaia_score_t *score = atalaia_node_score(g->runner->node);
        for (uint8_t t = 1; t <= g->join.team_count && st->counter_count < 16; t++) {
            /* Gains only: they never decrease, so the controller can merge by maximum. */
            st->counters[st->counter_count].team = t;
            st->counters[st->counter_count].score = score->gained[t];
            st->counter_count++;
        }
    }
    int battery = g->shell.battery_pct != NULL ? g->shell.battery_pct(g->shell.user) : -1;
    st->battery_pct = battery >= 0 && battery <= 100 ? (uint8_t)battery : 0xFF;
    st->flags = (uint8_t)((g->phase == BOX_PLAYING && !g->paused ? 1u : 0u) |
                          (g->phase == BOX_PLAYING && g->paused ? 2u : 0u));
}

static bool link_tx(void *ctx, const uint8_t *pkt, size_t len)
{
    box_game_t *g = (box_game_t *)ctx;
    return g->shell.radio_send(g->shell.user, pkt, len);
}

static uint32_t link_game_time(void *user)
{
    return ((box_game_t *)user)->runner->game_time_ms;
}

static void link_log(void *user, const char *line)
{
    box_game_t *g = (box_game_t *)user;
    if (g->shell.log != NULL) g->shell.log(g->shell.user, line);
}

static void on_node_event(void *ctx, const atalaia_event_t *ev, const char *data_json)
{
    box_game_t *g = (box_game_t *)ctx;
    if (g->phase == BOX_IDLE) return;
    if (strcmp(ev->type, "zone.captured") == 0) g->owner_team = ev->team;
    if (strcmp(ev->type, "zone.neutralized") == 0) g->owner_team = ATALAIA_TEAM_NONE;
    field_link_event(&g->link, ev, data_json);
}

/* ---- The game -------------------------------------------------------------------- */

static void prepare_runner(box_game_t *g)
{
    g->runner->node_id = g->join.node_id;
    g->runner->game_seed = g->join.game_seed;
    g->runner->event_hook = on_node_event;
    g->runner->event_ctx = g;
    if (g->join.params_json[0]) {
        snprintf(g->preset->params_json, sizeof(g->preset->params_json), "%s", g->join.params_json);
    }
    g->preset->duration_s = 0; /* the controller ends the game */
}

static void start_mode(box_game_t *g)
{
    prepare_runner(g);
    g->owner_team = ATALAIA_TEAM_NONE;
    if (!node_runner_start(g->runner, g->preset, g->teams, g->join.team_count)) {
        say(g, "cannot start %s: the mode failed to load", g->join.mode_id);
        return;
    }
    g->runner->preset_index = g->preset_index;
    g->phase = BOX_PLAYING;
    g->paused = false;
    field_link_reset_sync(&g->link);
    say(g, "game %u started (node %u, %s)", g->join.game_id, g->join.node_id, g->join.role);
}

static void end_game(box_game_t *g)
{
    if (g->phase == BOX_PLAYING && g->runner->node != NULL) {
        node_runner_input(g->runner, "game.end", NULL);
    }
    g->phase = BOX_ENDED;
    g->paused = false;
    g->ended_ms = g->now_ms;
    /* ADR-P2-12: the key does not survive the game. The stored join goes now, so a reboot
     * does not rejoin; the copy in RAM stays until the last events are acknowledged. */
    if (g->store.erase_join != NULL) g->store.erase_join(g->store.ctx);
    state_persist_clear();
    field_link_state_now(&g->link);
    say(g, "game %u ended", g->join.game_id);
}

static void leave_game(box_game_t *g)
{
    memset(g->link.proto.game_key, 0, sizeof(g->link.proto.game_key));
    g->link.proto.has_key = false;
    memset(g->join.game_key, 0, sizeof(g->join.game_key));
    memset(g->link.join.game_key, 0, sizeof(g->link.join.game_key));
    if (g->log != NULL) event_log_clear(g->log);
    /* The final screen stays; the mode's state does not (nothing to resume or save). */
    node_runner_stop(g->runner);
    state_persist_clear();
    g->phase = BOX_IDLE;
    say(g, "left game %u; the game key is erased", g->join.game_id);
}

static void link_on_cmd(void *user, uint8_t cmd, const char *params_json)
{
    box_game_t *g = (box_game_t *)user;
    const char *params = params_json != NULL && params_json[0] ? params_json : NULL;
    switch (cmd) {
    case FIELD_CMD_START:
        if (g->phase == BOX_JOINED) start_mode(g);
        break;
    case FIELD_CMD_PAUSE:
        if (g->phase == BOX_PLAYING && !g->paused) {
            node_runner_input(g->runner, "game.pause", params);
            g->paused = true;
            field_link_state_now(&g->link);
        }
        break;
    case FIELD_CMD_RESUME:
        if (g->phase == BOX_PLAYING && g->paused) {
            node_runner_input(g->runner, "game.resume", NULL);
            g->paused = false;
            field_link_state_now(&g->link);
        }
        break;
    case FIELD_CMD_END:
        if (g->phase == BOX_PLAYING || g->phase == BOX_JOINED) end_game(g);
        break;
    case FIELD_CMD_SET_OWNER:
        /* Modes decide what an override means: on("cmd.set_owner", ...). */
        if (g->phase == BOX_PLAYING) node_runner_input(g->runner, "cmd.set_owner", params);
        break;
    case FIELD_CMD_MESSAGE:
        snprintf(g->last_message, sizeof(g->last_message), "%s", params ? params : "");
        say(g, "message from the organisers: %s", g->last_message);
        if (g->phase == BOX_PLAYING) node_runner_input(g->runner, "gm.message", params);
        break;
    case FIELD_CMD_RESET:
        if (g->phase == BOX_PLAYING) {
            node_runner_stop(g->runner);
            g->phase = BOX_JOINED;
            start_mode(g);
        }
        break;
    case FIELD_CMD_REBOOT:
        say(g, "reboot requested by the controller");
        if (g->shell.reboot != NULL) g->shell.reboot(g->shell.user);
        break;
    default: say(g, "unknown command %u ignored", cmd); break;
    }
}

/* ---- Join ------------------------------------------------------------------------ */

void box_game_init(box_game_t *g, node_runner_t *runner, preset_t *preset_buf,
                   const box_store_ops_t *store, const box_shell_ops_t *shell,
                   const atalaia_crypto_ops_t *crypto, const atalaia_radio_nvs_ops_t *nvs,
                   event_log_t *log, const atalaia_hello_t *hello)
{
    memset(g, 0, sizeof(*g));
    g->runner = runner;
    g->preset = preset_buf;
    g->store = *store;
    g->shell = *shell;
    g->crypto = crypto;
    g->nvs = nvs;
    g->log = log;
    g->hello = *hello;
    g->preset_index = -1;
}

bool box_game_load_join_key(box_game_t *g)
{
    g->have_join_key =
        g->store.load_join_key != NULL && g->store.load_join_key(g->store.ctx, g->join_key) == 0;
    return g->have_join_key;
}

bool box_game_set_join_key(box_game_t *g, const uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    if (g->store.save_join_key == NULL || g->store.save_join_key(g->store.ctx, key) != 0) {
        return false;
    }
    memcpy(g->join_key, key, ATALAIA_JOIN_KEY_SIZE);
    g->have_join_key = true;
    return true;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool parse_key_hex(const char *hex, uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    while (*hex == ' ') hex++;
    for (size_t i = 0; i < ATALAIA_JOIN_KEY_SIZE; i++) {
        int hi = hexval(hex[2 * i]);
        int lo = hi < 0 ? -1 : hexval(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        key[i] = (uint8_t)(hi << 4 | lo);
    }
    const char *rest = hex + 2 * ATALAIA_JOIN_KEY_SIZE;
    while (*rest == ' ' || *rest == '\r' || *rest == '\n') rest++;
    return *rest == '\0';
}

bool box_game_set_join_key_hex(box_game_t *g, const char *hex)
{
    uint8_t key[ATALAIA_JOIN_KEY_SIZE];
    bool ok = parse_key_hex(hex, key) && box_game_set_join_key(g, key);
    memset(key, 0, sizeof(key));
    return ok;
}

bool box_game_use_join_key_hex(box_game_t *g, const char *hex)
{
    uint8_t key[ATALAIA_JOIN_KEY_SIZE];
    if (!parse_key_hex(hex, key)) return false;
    memcpy(g->join_key, key, ATALAIA_JOIN_KEY_SIZE);
    g->have_join_key = true;
    memset(key, 0, sizeof(key));
    return true;
}

static int find_preset(box_game_t *g, const char *mode_id)
{
    /* 3.7 KB: not on the game task's stack (one box per process). */
    static preset_summary_t list[PRESET_MAX_SLOTS];
    int n = preset_store_list(list, PRESET_MAX_SLOTS);
    for (int i = 0; i < n; i++) {
        if (strcmp(list[i].mode_id, mode_id) == 0 && preset_store_load(list[i].index, g->preset)) {
            return list[i].index;
        }
    }
    return -1;
}

static void show_waiting(box_game_t *g)
{
    char data[SCREEN_DATA_MAX];
    snprintf(data, sizeof(data), "{\"title\":\"Joined game %u\",\"mode\":\"%.24s, node %u\"}",
             g->join.game_id, g->join.role, g->join.node_id);
    show(g, "status", data);
}

/* Takes a verified join: from a card or text (fresh), or from the store (reboot). */
static box_join_result_t apply(box_game_t *g, const atalaia_join_t *j, const uint8_t *payload,
                               size_t len, bool fresh)
{
    if (j->kind != ATALAIA_JOIN_KIND_NODE) return BOX_JOIN_CONTROLLER;
    bool same = (g->phase == BOX_JOINED || g->phase == BOX_PLAYING) &&
                j->game_id == g->join.game_id && j->node_id == g->join.node_id &&
                memcmp(j->game_key, g->join.game_key, sizeof(j->game_key)) == 0;
    if (same) return BOX_JOIN_OK; /* the same card tapped again: nothing changes */
    if (g->phase == BOX_PLAYING) return BOX_JOIN_BUSY;
    int index = find_preset(g, j->mode_id);
    if (index < 0) return BOX_JOIN_NO_MODE;
    if (fresh) {
        if (g->store.save_join == NULL || g->store.save_join(g->store.ctx, payload, len) != 0) {
            return BOX_JOIN_STORAGE;
        }
        /* A new game: nothing from an earlier game may be resumed or resent. */
        state_persist_clear();
        if (g->log != NULL) event_log_clear(g->log);
    }
    g->join = *j;
    g->preset_index = index;
    for (uint8_t t = 0; t < j->team_count; t++) g->teams[t] = g->join.teams[t];
    if (g->shell.set_channel != NULL && !g->shell.set_channel(g->shell.user, j->channel_hz)) {
        say(g, "radio: cannot tune to %lu Hz (no radio, or refused)", (unsigned long)j->channel_hz);
    }
    field_link_io_t io = {.get_state = link_get_state,
                          .on_cmd = link_on_cmd,
                          .game_time = link_game_time,
                          .log = link_log,
                          .user = g,
                          .tx = g->shell.radio_send != NULL ? link_tx : NULL,
                          .tx_ctx = g};
    g->now_ms = g->now_ms ? g->now_ms : 1;
    if (!field_link_init(&g->link, j, g->crypto, g->nvs, g->log, &g->hello, &io, g->now_ms)) {
        return BOX_JOIN_RADIO;
    }
    if (g->state_interval_ms != 0) g->link.state_interval_ms = g->state_interval_ms;
    g->phase = BOX_JOINED;
    g->paused = false;
    g->owner_team = ATALAIA_TEAM_NONE;
    say(g, "joined game %u as node %u (%s, %s), %u teams, channel %lu Hz, epoch %u", j->game_id,
        j->node_id, j->mode_id, j->role, j->team_count, (unsigned long)j->channel_hz,
        g->link.proto.epoch);
    show_waiting(g);
    return BOX_JOIN_OK;
}

box_join_result_t box_game_join(box_game_t *g, const uint8_t *payload, size_t len)
{
    if (!g->have_join_key) return BOX_JOIN_NO_KEY;
    atalaia_join_t j;
    atalaia_join_result_t r = atalaia_join_decode(payload, len, g->join_key, &j);
    if (r != ATALAIA_JOIN_OK) {
        say(g, "join refused: %s", atalaia_join_result_name(r));
        return BOX_JOIN_REFUSED;
    }
    box_join_result_t out = apply(g, &j, payload, len, true);
    memset(&j, 0, sizeof(j));
    if (out != BOX_JOIN_OK) say(g, "join refused: %s", box_join_result_name(out));
    return out;
}

box_join_result_t box_game_join_text(box_game_t *g, const char *text)
{
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = atalaia_join_from_text(text, buf, sizeof(buf));
    if (n == 0) return BOX_JOIN_NOT_A_JOIN;
    return box_game_join(g, buf, n);
}

box_join_result_t box_game_join_tag(box_game_t *g, const uint8_t *mem, size_t len)
{
    const uint8_t *payload = NULL;
    size_t n = atalaia_join_from_ndef_tag(mem, len, &payload);
    if (n == 0) return BOX_JOIN_NOT_A_JOIN;
    return box_game_join(g, payload, n);
}

bool box_game_resume(box_game_t *g, uint32_t now_ms)
{
    g->now_ms = now_ms ? now_ms : 1;
    if (!g->have_join_key || g->store.load_join == NULL) return false;
    uint8_t buf[ATALAIA_JOIN_MAX];
    int n = g->store.load_join(g->store.ctx, buf, sizeof(buf));
    if (n <= 0) return false;
    atalaia_join_t j;
    if (atalaia_join_decode(buf, (size_t)n, g->join_key, &j) != ATALAIA_JOIN_OK) {
        say(g, "stored join no longer valid (another join key?): erased");
        if (g->store.erase_join != NULL) g->store.erase_join(g->store.ctx);
        return false;
    }
    box_join_result_t r = apply(g, &j, buf, (size_t)n, false);
    memset(&j, 0, sizeof(j));
    if (r != BOX_JOIN_OK) {
        say(g, "cannot rejoin the stored game: %s", box_join_result_name(r));
        return false;
    }

    /* Was the game being played? Then carry on from the saved state. */
    state_persist_data_t saved;
    if (state_persist_load(&saved)) {
        prepare_runner(g);
        if (node_runner_resume(g->runner, &saved, g->preset->source, g->preset->source_len,
                               g->preset->params_json[0] ? g->preset->params_json : NULL, g->teams,
                               g->join.team_count)) {
            g->runner->preset_index = g->preset_index;
            g->phase = BOX_PLAYING;
            g->link.game_state = FIELD_GAME_RUNNING;
            field_link_send_rebooted(&g->link, saved.game_time_ms);
            say(g, "resumed game %u at %lu ms after a reboot", g->join.game_id,
                (unsigned long)saved.game_time_ms);
        }
    }
    return true;
}

void box_game_on_packet(box_game_t *g, const uint8_t *pkt, size_t len, int8_t rssi)
{
    if (g->phase == BOX_IDLE) return;
    field_link_on_packet(&g->link, pkt, len, rssi);
}

void box_game_tick(box_game_t *g, uint32_t raw_delta_ms, uint32_t now_ms)
{
    g->now_ms = now_ms;
    if (g->phase == BOX_IDLE) return;
    if (g->phase == BOX_PLAYING && !g->paused && g->runner->running) {
        node_runner_tick(g->runner, field_link_adjust_delta(&g->link, raw_delta_ms));
    }
    field_link_tick(&g->link, now_ms);
    if (g->phase == BOX_ENDED &&
        (field_link_pending(&g->link) == 0 || now_ms - g->ended_ms >= BOX_END_LINGER_MS)) {
        leave_game(g);
    }
}

bool box_game_active(const box_game_t *g)
{
    return g->phase != BOX_IDLE;
}
