/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box in a field controller's game (see box_game.h).
 */
#include "box_game.h"
#include "psram_attr.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "box_text.h"
#include "mode_fetch.h"
#include "mode_store.h"
#include "screen_json.h"
#include "screen_types.h"
#include "radio/radio_stats.h"
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

/* The radio report line (radio_stats.h): read-only, a stack buffer, nothing sent. */
static void radio_report(box_game_t *g, bool final)
{
    if (g->shell.radio_stats == NULL) return;
    if (g->shell.lbt_stats != NULL) {
        field_link_stats_t *w = &g->link.stats;
        g->shell.lbt_stats(g->shell.user, &w->lbt_cads, &w->lbt_deferrals, &w->lbt_gave_up);
    }
    const field_link_stats_t *s = &g->link.stats;
    radio_stats_box_t r = {.sent = s->events_sent,
                           .retries = s->retries,
                           .acked = s->acked,
                           .expired = s->expired,
                           .relayed = s->relayed,
                           .relay_skipped = s->relay_skipped,
                           .relay_cancelled = s->relay_cancelled,
                           .relay_no_slot = s->relay_no_slot,
                           .dup = s->rx_duplicates,
                           .tx_refused = s->tx_refused,
                           .rx = s->rx_ok,
                           .rx_rejected = s->rx_rejected,
                           .states = s->states_sent,
                           .hellos = s->hellos_sent,
                           .lbt_cads = s->lbt_cads,
                           .lbt_deferrals = s->lbt_deferrals,
                           .lbt_gave_up = s->lbt_gave_up,
                           .neighbours = atalaia_relay_neighbours(&g->link.relay, g->now_ms)};
    uint32_t duty = g->shell.duty_remaining_ms != NULL ? g->shell.duty_remaining_ms(g->shell.user)
                                                       : RADIO_STATS_DUTY_UNKNOWN;
    char line[RADIO_STATS_LINE_MAX];
    if (radio_stats_box_line(line, sizeof(line), g->now_ms / 1000u, g->join.game_id,
                             g->join.node_id, &r, duty, final) > 0) {
        g->shell.radio_stats(g->shell.user, line);
    }
    g->stats_last_ms = g->now_ms;
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
    case BOX_JOIN_ENDED: return "a game this box has played already";
    case BOX_JOIN_REGION: return "another radio region's game (this box is built for its own)";
    }
    return "?";
}

/* ---- Link callbacks ---------------------------------------------------------- */

static uint8_t game_state_of(const box_game_t *g)
{
    if (g->fetch_failed_link) return FIELD_GAME_WAITING; /* never in the game (P5E-8) */
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
    st->lost_count = 0;
    if (g->runner->node != NULL) {
        const atalaia_score_t *score = atalaia_node_score(g->runner->node);
        for (uint8_t t = 1; t <= g->join.team_count && st->counter_count < 16; t++) {
            /* Gains only: they never decrease, so the controller can merge by maximum. */
            st->counters[st->counter_count].team = t;
            st->counters[st->counter_count].score = score->gained[t];
            st->counter_count++;
        }
        /* Penalties (RFC 0001 Amendment 18): only the teams that lost points, so a game with no
         * penalty sends the same STATE as before; never decreasing, merged by maximum. */
        for (uint8_t t = 1; t <= g->join.team_count && st->lost_count < 16; t++) {
            if (score->lost[t] > 0) {
                st->lost[st->lost_count].team = t;
                st->lost[st->lost_count].points = score->lost[t];
                st->lost_count++;
            }
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

/* The link's timing spread (relay delays, resend gaps) comes from the shell's entropy. */
static void link_random(void *user, uint8_t *buf, size_t len)
{
    box_game_t *g = (box_game_t *)user;
    if (g->shell.random != NULL) {
        g->shell.random(g->shell.user, buf, len);
    } else {
        memset(buf, 0, len);
    }
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
    node_runner_set_mode(g->runner, g->preset->mode_id);
    if (g->join.params_json[0]) {
        snprintf(g->preset->params_json, sizeof(g->preset->params_json), "%s", g->join.params_json);
    }
    g->preset->duration_s = 0; /* the controller ends the game */
}

static void start_mode(box_game_t *g)
{
    /* The game is on, whatever the mode draws (some draw nothing until a capture): the joined
     * screen never stays up in a running game (decision BN-13). */
    char data[SCREEN_DATA_MAX];
    snprintf(data, sizeof(data), "{\"game\":%u,\"role\":\"%.24s\"}", g->join.game_id, g->join.role);
    show(g, "playing", data);
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
    if (g->stats_on) radio_report(g, true);
    g->stats_on = false;
    /* Free for the next game: announce soon, "ready for the next game" later (box_lobby.c). */
    box_lobby_game_over(g, g->now_ms);
}

void box_game_end_by_field(box_game_t *g)
{
    if (g->phase == BOX_PLAYING || g->phase == BOX_JOINED) end_game(g);
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
    if (g->fetch_failed_link) box_lobby_free_again(g); /* the fetch's failure is told */
    g->fetch_failed_link = false;
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
    case FIELD_CMD_MODE:
        /* A mode command (the GM's refill of a medic kit, a field script's count):
         * the script gets its params, name included, as on("cmd.mode", ...). */
        if (g->phase == BOX_PLAYING) node_runner_input(g->runner, "cmd.mode", params);
        break;
    case FIELD_CMD_UPDATE:
        /* A firmware update (RFC 0001 Amendment 6): never while a game is played. */
        if (g->phase == BOX_PLAYING) {
            say(g, "firmware update refused: a game is being played");
            /* The controller sends none during a game; if one came, it hears why (OT-8). */
            char id[24] = "";
            if (params == NULL || !screen_json_str(params, "id", id, sizeof(id))) id[0] = '\0';
            box_game_update_failed(g, id, "busy", g->hello.fw_version);
        } else if (g->shell.update == NULL) {
            say(g, "firmware update: not supported by this box");
        } else {
            say(g, "firmware update offered: %s", params ? params : "{}");
            g->shell.update(g->shell.user, params ? params : "{}");
        }
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
    g->region = RADIO_REGION;
    g->battery_low_pct = BOX_BATTERY_LOW_PCT;
    g->lobby.first_min_ms = BOX_ANNOUNCE_FIRST_MIN_MS;
    g->lobby.first_max_ms = BOX_ANNOUNCE_FIRST_MAX_MS;
    g->lobby.interval_min_ms = BOX_ANNOUNCE_MIN_MS;
    /* The screens' language until a game says otherwise: the last game's (BN-14). */
    char code[ATALAIA_JOIN_LANG_MAX + 1] = "";
    if (g->store.load_lang == NULL || g->store.load_lang(g->store.ctx, code, sizeof(code)) != 0) {
        code[0] = 0;
    }
    box_lang_set_code(code);
}

/* The joined game's language (join key 15) for the screens, kept for between games. */
static void take_language(box_game_t *g, const atalaia_join_t *j)
{
    if (box_lang_given() == (j->lang[0] != 0) && box_lang() == box_lang_from_code(j->lang)) {
        return;
    }
    box_lang_set_code(j->lang);
    if (g->store.save_lang != NULL && g->store.save_lang(g->store.ctx, j->lang) != 0) {
        say(g, "screen language: not stored (the last one after a reboot)");
    }
}

bool box_game_load_join_key(box_game_t *g)
{
    g->have_join_key =
        g->store.load_join_key != NULL && g->store.load_join_key(g->store.ctx, g->join_key) == 0;
    if (g->have_join_key) box_lobby_init(g);
    return g->have_join_key;
}

bool box_game_set_join_key(box_game_t *g, const uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    if (g->store.save_join_key == NULL || g->store.save_join_key(g->store.ctx, key) != 0) {
        return false;
    }
    memcpy(g->join_key, key, ATALAIA_JOIN_KEY_SIZE);
    g->have_join_key = true;
    box_lobby_init(g); /* field frames under the new key */
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
    box_lobby_init(g);
    return true;
}

/* The stored preset whose mode id is the first len bytes of id, or NULL. */
static const preset_summary_t *stored_mode(const preset_summary_t *list, int n, const char *id,
                                           size_t len)
{
    for (int i = 0; i < n; i++) {
        if (strlen(list[i].mode_id) == len && strncmp(list[i].mode_id, id, len) == 0) {
            return &list[i];
        }
    }
    return NULL;
}

/* Appends "do\n" source "\nend\n" for each stored modifier named in mods
 * ("a+b"), after the main script, which gets the same wrapper first: the
 * chunk the controller and the simulator compose (atalaia_sim.mode). */
static bool add_modifiers(box_game_t *g, const preset_summary_t *list, int n, const char *mods)
{
    preset_t *p = g->preset;
    const size_t cap = sizeof(p->source);
    size_t len = p->source_len;
    if (len + 8 >= cap) return false;
    memmove(p->source + 3, p->source, len);
    memcpy(p->source, "do\n", 3);
    memcpy(p->source + 3 + len, "\nend\n", 5);
    len += 8;
    while (*mods) {
        const char *next = strchr(mods, '+');
        size_t id_len = next != NULL ? (size_t)(next - mods) : strlen(mods);
        const preset_summary_t *mod = stored_mode(list, n, mods, id_len);
        if (mod == NULL || len + 3 + 5 + 1 >= cap) return false;
        memcpy(p->source + len, "do\n", 3);
        long part = preset_store_read_source(mod->mode_id, p->source + len + 3, cap - len - 3 - 5);
        if (part < 0) return false;
        len += 3 + (size_t)part;
        memcpy(p->source + len, "\nend\n", 5);
        len += 5;
        mods = next != NULL ? next + 1 : mods + id_len;
    }
    p->source[len] = '\0';
    p->source_len = len;
    return true;
}

/* Loads the preset of a join's mode: a main mode, or a main mode with its
 * modifiers ("org.atalaia.domination+org.atalaia.codes", modes/README.md). */
static int find_preset(box_game_t *g, const char *mode_id)
{
    /* 3.7 KB: not on the game task's stack (one box per process). */
    static preset_summary_t list[PRESET_MAX_SLOTS] ATALAIA_PSRAM_BSS;
    int n = preset_store_list(list, PRESET_MAX_SLOTS);
    const char *plus = strchr(mode_id, '+');
    size_t main_len = plus != NULL ? (size_t)(plus - mode_id) : strlen(mode_id);
    const preset_summary_t *first = stored_mode(list, n, mode_id, main_len);
    if (first == NULL || !preset_store_load(first->index, g->preset)) return -1;
    if (plus != NULL && !add_modifiers(g, list, n, plus + 1)) {
        say(g, "mode %s: a modifier is not installed, or the scripts do not fit in %u bytes",
            mode_id, (unsigned)sizeof(g->preset->source));
        return -1;
    }
    return first->index;
}

/* Joined (or invited), the game not started: its own screen, never a mode's or the
 * running game's (decision BN-12). The game id, the role and how the box joined. */
static void show_waiting(box_game_t *g)
{
    char data[SCREEN_DATA_MAX];
    snprintf(data, sizeof(data), "{\"game\":%u,\"role\":\"%.24s\",\"invited\":%s}", g->join.game_id,
             g->join.role, g->lobby.invited ? "true" : "false");
    show(g, "waiting", data);
}

static bool link_up(box_game_t *g, const atalaia_join_t *j, bool fresh);
static bool wants_fetch(const box_game_t *g, const atalaia_join_t *j);
static box_join_result_t start_fetch(box_game_t *g, const atalaia_join_t *j, const uint8_t *payload,
                                     size_t len);

/* Takes a verified join: from a card or text (fresh), or from the store (reboot). */
static box_join_result_t apply(box_game_t *g, const atalaia_join_t *j, const uint8_t *payload,
                               size_t len, bool fresh)
{
    if (j->kind != ATALAIA_JOIN_KIND_NODE) return BOX_JOIN_CONTROLLER;
    /* Join key 18: only the firmware's own region (its antenna, its limits); the decoder has
     * checked that the channel belongs to the region the join names. */
    if (j->region != (uint8_t)g->region) return BOX_JOIN_REGION;
    bool same = (g->phase == BOX_JOINED || g->phase == BOX_PLAYING) &&
                j->game_id == g->join.game_id && j->node_id == g->join.node_id &&
                memcmp(j->game_key, g->join.game_key, sizeof(j->game_key)) == 0;
    if (same) return BOX_JOIN_OK; /* the same card tapped again: nothing changes */
    if (g->phase == BOX_FETCHING && fresh) {
        /* Another game's card while fetching: the fetch stops (cancelled); a tap once the box
         * is free again joins (protocol/mode-packages.md, section 3; decision P5E-9). */
        g->fetch_cancel = true;
        return BOX_JOIN_BUSY;
    }
    if (g->phase == BOX_PLAYING || g->phase == BOX_FETCHING) return BOX_JOIN_BUSY;
    int index = find_preset(g, j->mode_id);
    if (index < 0) {
        if (fresh && wants_fetch(g, j)) return start_fetch(g, j, payload, len);
        return BOX_JOIN_NO_MODE;
    }
    if (fresh) {
        if (g->store.save_join == NULL || g->store.save_join(g->store.ctx, payload, len) != 0) {
            return BOX_JOIN_STORAGE;
        }
        /* A new game: nothing from an earlier game may be resumed or resent. */
        state_persist_clear();
        if (g->log != NULL) event_log_clear(g->log);
        mode_store_touch(j->mode_id); /* its fetched parts: the most recently used (P5B-15) */
    }
    if (!link_up(g, j, fresh)) return BOX_JOIN_RADIO;
    g->preset_index = index;
    g->phase = BOX_JOINED;
    g->paused = false;
    g->owner_team = ATALAIA_TEAM_NONE;
    say(g, "joined game %u as node %u (%s, %s), %u teams, channel %lu Hz, epoch %u", j->game_id,
        j->node_id, j->mode_id, j->role, j->team_count, (unsigned long)j->channel_hz,
        g->link.proto.epoch);
    show_waiting(g);
    return BOX_JOIN_OK;
}

/* The game's link, from a verified join: the radio's channel, HELLO, the link's keys. */
static bool link_up(box_game_t *g, const atalaia_join_t *j, bool fresh)
{
    if (j != &g->join) g->join = *j; /* after a fetch, the join is g->join itself */
    take_language(g, j);
    for (uint8_t t = 0; t < j->team_count; t++) g->teams[t] = g->join.teams[t];
    if (g->shell.set_channel != NULL && !g->shell.set_channel(g->shell.user, j->channel_hz)) {
        say(g, "radio: cannot tune to %lu Hz (no radio, or refused)", (unsigned long)j->channel_hz);
    }
    /* HELLO carries the battery level when the box has a gauge (0xFF: unknown), and the box's
     * device id, so the controller knows it in the next game (protocol/field-frames.md). */
    int battery = g->shell.battery_pct != NULL ? g->shell.battery_pct(g->shell.user) : -1;
    g->hello.battery_pct = battery >= 0 && battery <= 100 ? (uint8_t)battery : 0xFF;
    g->hello.has_device_id = g->lobby.ready;
    if (g->lobby.ready) memcpy(g->hello.device_id, g->lobby.device_id, ATALAIA_FF_DEVICE_SIZE);
    g->lobby.channel_hz = j->channel_hz; /* where it listens between games, from now on */
    box_lobby_remember_channel(g);       /* and after a reboot (RFC 0001 Amendment 19) */
    g->lobby.ready_screen_due = false;
    g->battery_low = false; /* a new game, or a reboot: battery.low may be sent again */
    g->battery_next_ms = g->now_ms;
    field_link_io_t io = {.get_state = link_get_state,
                          .on_cmd = link_on_cmd,
                          .game_time = link_game_time,
                          .log = link_log,
                          .random = g->shell.random != NULL ? link_random : NULL,
                          .user = g,
                          .tx = g->shell.radio_send != NULL ? link_tx : NULL,
                          .tx_ctx = g};
    g->now_ms = g->now_ms ? g->now_ms : 1;
    if (!field_link_init(&g->link, j, g->crypto, g->nvs, g->log, &g->hello, &io, g->now_ms,
                         !fresh)) {
        return false;
    }
    if (g->state_interval_ms != 0) g->link.state_interval_ms = g->state_interval_ms;
    return true;
}

/* ---- Fetching the mode packages a join needs (mode_fetch.h) ------------------------------- */

/* A join whose mode the box lacks makes it fetch (protocol/mode-packages.md, section 1): key 16
 * with keys 13 and 14, a shell that can (fetch_modes is set only with a mode key built in), and
 * no game being played on the box (P5B-13). Otherwise: no mode, as before. */
static bool wants_fetch(const box_game_t *g, const atalaia_join_t *j)
{
    return g->shell.fetch_modes != NULL && j->fetch_modes && j->has_ca && j->url_count > 0 &&
           (g->runner == NULL || !g->runner->running);
}

static void show_status(box_game_t *g, box_text_id_t title, const char *text)
{
    char data[SCREEN_DATA_MAX];
    snprintf(data, sizeof(data), "{\"title\":\"%s\",\"mode\":\"%.40s\"}", box_text(title), text);
    show(g, "status", data);
}

/* Takes the join as fetching: it is kept in RAM only (a reboot forgets it), the box is not on
 * the game's link yet (no HELLO), and the shell fetches what it lacks. */
static box_join_result_t start_fetch(box_game_t *g, const atalaia_join_t *j, const uint8_t *payload,
                                     size_t len)
{
    memcpy(g->fetch_payload, payload, len);
    g->fetch_len = len;
    g->join = *j;
    take_language(g, j);
    g->fetch_cancel = false;
    g->phase = BOX_FETCHING;
    g->lobby.ready_screen_due = false;
    say(g, "game %u: fetching the mode packages of %s it lacks", j->game_id, j->mode_id);
    show_status(g, TX_MODES_FETCHING, j->mode_id);
    g->shell.fetch_modes(g->shell.user, &g->join);
    return BOX_JOIN_OK;
}

/* A failed fetch the controller did not hear of over HTTPS: the box joins the game's link only to
 * say so (HELLO, then node.modes_failed), reports "waiting", and leaves once it is acknowledged
 * (decision P5E-8). Not a game played to its end: the GM may invite it again. */
static void fetch_failed_over_lora(box_game_t *g, const atalaia_join_t *j, const char *part,
                                   const char *reason)
{
    state_persist_clear();
    if (g->log != NULL) event_log_clear(g->log);
    if (!link_up(g, j, true)) {
        say(g, "the fetch's failure cannot be told over the radio either");
        memset(g->join.game_key, 0, sizeof(g->join.game_key));
        return;
    }
    g->fetch_failed_link = true;
    g->phase = BOX_ENDED;
    g->ended_ms = g->now_ms;
    field_link_send_modes_failed(&g->link, part, reason, 0);
    say(g, "mode packages: %s (%s), told the controller over the radio", reason, part);
}

void box_game_fetch_done(box_game_t *g, int result, const char *part, bool reported)
{
    if (g->phase != BOX_FETCHING) return;
    mf_result_t r = (mf_result_t)result;
    const atalaia_join_t *j = &g->join; /* apply copies it onto itself: no second copy in RAM */
    g->phase = BOX_IDLE;
    if (r == MF_INSTALLED && g->fetch_cancel) r = MF_CANCELLED;
    box_join_result_t out = BOX_JOIN_NO_MODE;
    if (r == MF_INSTALLED) {
        out = apply(g, j, g->fetch_payload, g->fetch_len, true);
        if (out == BOX_JOIN_OK) {
            say(g, "game %u: its mode packages are in", j->game_id);
        } else {
            /* Every part is in, yet the game does not start (the composed script is too big for
             * the preset buffer, storage): as a failed load. */
            say(g, "game %u: %s after the fetch", j->game_id, box_join_result_name(out));
            r = MF_LOAD;
            part = j->mode_id;
            reported = false;
        }
    }
    if (out != BOX_JOIN_OK) {
        const char *why = mf_result_name(r);
        say(g, "game %u: mode packages %s (%s)", j->game_id, why, part ? part : "");
        show_status(g, TX_MODES_FAILED, why);
        if (!reported && r != MF_CANCELLED) {
            fetch_failed_over_lora(g, j, part ? part : "", why);
        } else {
            memset(g->join.game_key, 0, sizeof(g->join.game_key));
            box_lobby_free_again(g); /* not an ended game: the GM may invite it again */
        }
    }
    memset(g->fetch_payload, 0, sizeof(g->fetch_payload));
    g->fetch_len = 0;
}

bool box_game_fetching(const box_game_t *g)
{
    return g->phase == BOX_FETCHING;
}

static box_join_result_t join_payload(box_game_t *g, const uint8_t *payload, size_t len);

box_join_result_t box_game_join(box_game_t *g, const uint8_t *payload, size_t len)
{
    bool was = g->lobby.invited;
    g->lobby.invited = false;
    box_join_result_t r = join_payload(g, payload, len);
    if (r != BOX_JOIN_OK) g->lobby.invited = was;
    return r;
}

/* True if every part of a join's mode id is installed (find_preset's test, without loading). */
static bool modes_installed(const char *mode_id)
{
    static preset_summary_t
        list[PRESET_MAX_SLOTS] ATALAIA_PSRAM_BSS; /* as find_preset: not on the stack */
    int n = preset_store_list(list, PRESET_MAX_SLOTS);
    for (const char *p = mode_id; *p;) {
        const char *next = strchr(p, '+');
        size_t len = next != NULL ? (size_t)(next - p) : strlen(p);
        if (stored_mode(list, n, p, len) == NULL) return false;
        p = next != NULL ? next + 1 : p + len;
    }
    return true;
}

box_join_result_t box_game_join_invited(box_game_t *g, const uint8_t *payload, size_t len)
{
    if (g->phase == BOX_JOINED || g->phase == BOX_PLAYING || g->phase == BOX_FETCHING) {
        return BOX_JOIN_BUSY;
    }
    if (g->phase == BOX_ENDED) {
        /* A game over whose last events are still unacknowledged: leave it only for an invite
         * the box will take, so a refused one keeps them. */
        static atalaia_join_t j; /* not on the game task's stack */
        atalaia_join_result_t r = g->have_join_key
                                      ? atalaia_join_decode(payload, len, g->join_key, &j)
                                      : ATALAIA_JOIN_ERR_MAC;
        bool ok = r == ATALAIA_JOIN_OK && j.kind == ATALAIA_JOIN_KIND_NODE &&
                  (modes_installed(j.mode_id) || wants_fetch(g, &j));
        box_join_result_t why = r != ATALAIA_JOIN_OK               ? BOX_JOIN_REFUSED
                                : j.kind != ATALAIA_JOIN_KIND_NODE ? BOX_JOIN_CONTROLLER
                                                                   : BOX_JOIN_NO_MODE;
        memset(&j, 0, sizeof(j));
        if (!ok) {
            say(g, "join refused: %s", box_join_result_name(why));
            return why;
        }
        leave_game(g);
    }
    g->lobby.invited = true;
    box_join_result_t r = join_payload(g, payload, len);
    if (r != BOX_JOIN_OK) g->lobby.invited = false;
    return r;
}

static box_join_result_t join_payload(box_game_t *g, const uint8_t *payload, size_t len)
{
    if (!g->have_join_key) return BOX_JOIN_NO_KEY;
    atalaia_join_t j;
    atalaia_join_result_t r = atalaia_join_decode(payload, len, g->join_key, &j);
    if (r != ATALAIA_JOIN_OK) {
        say(g, "join refused: %s", atalaia_join_result_name(r));
        return BOX_JOIN_REFUSED;
    }
    /* Key 17 first (protocol/mode-packages.md, section 1): the join is authentic, so the box
     * forgets every package it fetched, whatever happens to the join afterwards; never under a
     * game being played or a fetch on its way (their scripts and screens are in use). */
    if (j.forget_modes && g->phase != BOX_PLAYING && g->phase != BOX_FETCHING) {
        say(g, "forgot %d fetched mode package(s), as the join asks", mode_store_forget_all());
    }
    /* A card, a QR code or a text of a game this box has played to its end, or of an old game
     * whose key the epoch store keeps only as retired: its nonces may not be used again
     * (decision BN-19). Checked before anything of the box's state changes. */
    if (box_lobby_played_to_the_end(g, j.game_id) ||
        atalaia_radio_epoch_key_retired(g->nvs, j.game_key)) {
        memset(&j, 0, sizeof(j));
        say(g, "join refused: %s", box_join_result_name(BOX_JOIN_ENDED));
        return BOX_JOIN_ENDED;
    }
    box_join_result_t out = apply(g, &j, payload, len, true);
    memset(&j, 0, sizeof(j));
    if (out != BOX_JOIN_OK) say(g, "join refused: %s", box_join_result_name(out));
    if (out == BOX_JOIN_OK) box_lobby_joined(g); /* no invite from before works now */
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
    /* Static, not on the stack: resume runs once at boot on the main task, whose
     * stack the join (~750 B), this buffer and the saved state (~1.1 KB) overflowed
     * before the mode's restore ran (found on the bench, 2026-10-22). */
    static uint8_t buf[ATALAIA_JOIN_MAX];
    int n = g->store.load_join(g->store.ctx, buf, sizeof(buf));
    if (n <= 0) return false;
    static atalaia_join_t j;
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
    static state_persist_data_t saved; /* static: see buf above */
    if (state_persist_load(&saved)) {
        prepare_runner(g);
        if (node_runner_resume(g->runner, &saved, g->preset->source, g->preset->source_len,
                               g->preset->params_json[0] ? g->preset->params_json : NULL, g->teams,
                               g->join.team_count, false)) {
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
    if (box_lobby_on_packet(g, pkt, len)) return; /* a field frame: announcements, invites */
    if (g->phase == BOX_IDLE || g->phase == BOX_FETCHING) return; /* not on a game's link */
    field_link_on_packet(&g->link, pkt, len, rssi);
}

/* battery.low once per crossing below battery_low_pct, rearmed BOX_BATTERY_HYSTERESIS points
 * above it; only with a gauge (battery_pct() >= 0) and in a joined game (decision FU1-6). */
static void check_battery(box_game_t *g, uint32_t now_ms)
{
    if (g->battery_low_pct == 0 || g->shell.battery_pct == NULL ||
        (g->phase != BOX_JOINED && g->phase != BOX_PLAYING) ||
        (int32_t)(now_ms - g->battery_next_ms) < 0) {
        return;
    }
    g->battery_next_ms = now_ms + BOX_BATTERY_CHECK_MS;
    int pct = g->shell.battery_pct(g->shell.user);
    if (pct < 0 || pct > 100) return; /* no gauge, or no reading */
    if (!g->battery_low && pct < g->battery_low_pct) {
        g->battery_low = true;
        field_link_send_battery_low(&g->link, (uint8_t)pct, g->runner->game_time_ms);
        say(g, "battery low: %d%%", pct);
    } else if (g->battery_low && pct >= g->battery_low_pct + BOX_BATTERY_HYSTERESIS) {
        g->battery_low = false;
    }
}

/* What the link last heard of the game (a CMD or a TIME) and what the box does must agree: a
 * START or PAUSE that came while the box could not act on it (still fetching its modes) would
 * otherwise be "already known" to the link, and the TIME beacons that repeat the state would
 * never start the game (RFC 0001 Amendment 19, part 2). */
static void follow_link_state(box_game_t *g)
{
    uint8_t state = g->link.game_state;
    if (g->phase == BOX_JOINED && (state == FIELD_GAME_RUNNING || state == FIELD_GAME_PAUSED)) {
        say(g, "the game is already %s: starting",
            state == FIELD_GAME_RUNNING ? "running" : "paused");
        start_mode(g);
    }
    if (g->phase != BOX_PLAYING) return;
    if (state == FIELD_GAME_PAUSED && !g->paused) {
        node_runner_input(g->runner, "game.pause", NULL);
        g->paused = true;
        field_link_state_now(&g->link);
    } else if (state == FIELD_GAME_RUNNING && g->paused) {
        node_runner_input(g->runner, "game.resume", NULL);
        g->paused = false;
        field_link_state_now(&g->link);
    }
}

void box_game_tick(box_game_t *g, uint32_t raw_delta_ms, uint32_t now_ms)
{
    g->now_ms = now_ms;
    box_lobby_tick(g, now_ms);
    if (g->phase == BOX_IDLE || g->phase == BOX_FETCHING) return;
    follow_link_state(g);
    if (g->phase == BOX_PLAYING && !g->paused && g->runner->running) {
        node_runner_tick(g->runner, field_link_adjust_delta(&g->link, raw_delta_ms));
    }
    field_link_tick(&g->link, now_ms);
    if (g->phase != BOX_ENDED) {
        if (!g->stats_on) {
            g->stats_on = true;
            g->stats_last_ms = now_ms;
        } else if (now_ms - g->stats_last_ms >= RADIO_STATS_PERIOD_MS) {
            radio_report(g, false);
        }
    }
    check_battery(g, now_ms);
    if (g->phase == BOX_ENDED &&
        (field_link_pending(&g->link) == 0 || now_ms - g->ended_ms >= BOX_END_LINGER_MS)) {
        leave_game(g);
    }
}

bool box_game_active(const box_game_t *g)
{
    return g->phase != BOX_IDLE;
}

bool box_game_playing(const box_game_t *g)
{
    return g->phase == BOX_PLAYING;
}

bool box_game_beacon(const box_game_t *g, box_beacon_id_t *id)
{
    /* Joined or playing (paused too), never fetching, ended or idle: the beacon is for the game
     * the controller placed this box in. The join may say the GM turned it off (key 19). */
    if (g->phase != BOX_JOINED && g->phase != BOX_PLAYING) return false;
    if (!g->have_join_key || g->join.box_beacon_off) return false;
    return box_beacon_id(g->join_key, g->join.node_id, id);
}

bool box_game_update_failed(box_game_t *g, const char *release, const char *reason, const char *fw)
{
    if (g->phase == BOX_IDLE || g->phase == BOX_FETCHING) return false;
    field_link_send_update_failed(&g->link, release, reason, fw, g->runner->game_time_ms);
    say(g, "firmware update failed (%s): told the controller over the radio",
        reason ? reason : "?");
    return true;
}

/* ---- Player tags (atalaia/tag.h, protocol/nfc-tag.md) ------------------------ */

bool box_game_tag(box_game_t *g, const uint8_t *uid, size_t uid_len, const uint8_t *payload,
                  size_t len)
{
    if (g->runner == NULL || !g->runner->running) return false;
    /* Only a joined game has a game key: a stand-alone game reports "no_game". */
    bool joined = g->phase == BOX_PLAYING;
    char json[ATALAIA_TAG_JSON_MAX];
    size_t n = atalaia_tag_event_json(uid, uid_len, payload, len, joined ? g->join.game_id : 0,
                                      joined ? g->join.game_key : NULL, joined ? g->teams : NULL,
                                      joined ? g->join.team_count : 0, json, sizeof(json));
    if (n == 0) return false;
    say(g, "tag %s", json);
    return node_runner_input(g->runner, "nfc.tag", json);
}

/* Hex digits up to a space or the end; returns the byte count, or 0. */
static size_t parse_hex(const char **text, uint8_t *out, size_t cap)
{
    const char *p = *text;
    while (*p == ' ') p++;
    size_t n = 0;
    while (*p && *p != ' ') {
        int hi = hexval(p[0]);
        int lo = hi < 0 || !p[1] ? -1 : hexval(p[1]);
        if (lo < 0 || n >= cap) return 0;
        out[n++] = (uint8_t)(hi << 4 | lo);
        p += 2;
    }
    *text = p;
    return n;
}

bool box_game_tag_text(box_game_t *g, const char *text)
{
    uint8_t uid[ATALAIA_TAG_UID_MAX];
    uint8_t payload[ATALAIA_TAG_MAX];
    const char *p = text;
    size_t uid_len = parse_hex(&p, uid, sizeof(uid));
    if (uid_len == 0) return false;
    while (*p == ' ') p++;
    size_t len = 0;
    if (*p) {
        len = parse_hex(&p, payload, sizeof(payload));
        while (*p == ' ') p++;
        if (len == 0 || *p) return false;
    }
    return box_game_tag(g, uid, uid_len, len ? payload : NULL, len);
}
