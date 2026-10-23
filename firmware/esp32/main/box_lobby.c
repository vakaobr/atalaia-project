/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box between games (box_game.h, protocol/field-frames.md, RFC 0001
 * Amendment 7): announcements, the controller's DISCOVER and INVITE, and
 * the "ready for the next game" screen. Platform-free, like box_game.c: the
 * shell supplies the random bytes, the store keeps the device id.
 *
 * What a box accepts: a frame that opens under the key derived from its field
 * join key (anything else is ignored silently: another field's, a stranger's),
 * an INVITE for its own device id and its current or previous token, while it
 * has no game or its game is over, whose parts make a join payload that passes
 * every check a join card passes, for a game it has not already played to its
 * end. It answers every invite it could read (accepted, busy, refused...) with
 * an ANNOUNCE carrying the invite's id and the result, and changes its token
 * when it accepts, so an old invite recorded and played again never works.
 *
 * In a game, it takes one kind: GAME_OVER for its own game id and its game key's
 * tag (decision OT-13), which a controller sends when the GM ends a game, also one
 * whose key it no longer has (a restart without persist_game_key): the box ends
 * the game as on CMD end. A GAME_OVER for another game, or for its game id under
 * another key (an old game's, played back), changes nothing.
 */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "atalaia/duty_cycle.h"
#include "box_game.h"
#include "screen_types.h"

static void say(box_game_t *g, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(box_game_t *g, const char *fmt, ...)
{
    if (g->shell.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    g->shell.log(g->shell.user, line);
}

static uint32_t rand_u32(box_game_t *g)
{
    uint8_t b[4] = {0};
    if (g->shell.random != NULL) g->shell.random(g->shell.user, b, sizeof(b));
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
}

/* A number in [lo, hi]. */
static uint32_t rand_between(box_game_t *g, uint32_t lo, uint32_t hi)
{
    return hi <= lo ? lo : lo + rand_u32(g) % (hi - lo + 1u);
}

static void new_token(box_game_t *g, bool keep_previous)
{
    box_lobby_t *l = &g->lobby;
    if (keep_previous) {
        memcpy(l->prev_token, l->token, sizeof(l->token));
        l->have_prev = true;
    } else {
        l->have_prev = false;
    }
    g->shell.random(g->shell.user, l->token, sizeof(l->token));
    l->rotate_ms = g->now_ms + BOX_TOKEN_ROTATE_MS;
}

bool box_lobby_init(box_game_t *g)
{
    box_lobby_t *l = &g->lobby;
    if (!g->have_join_key || g->shell.random == NULL) {
        l->ready = false;
        return false;
    }
    bool stored =
        g->store.load_device_id != NULL && g->store.load_device_id(g->store.ctx, l->device_id) == 0;
    if (!l->ready && !stored) {
        g->shell.random(g->shell.user, l->device_id, sizeof(l->device_id));
        if (g->store.save_device_id == NULL ||
            g->store.save_device_id(g->store.ctx, l->device_id) != 0) {
            say(g, "device id: not stored (a new one after a reboot)");
        }
    }
    atalaia_ff_key(g->join_key, l->key);
    atalaia_ff_nonce_key(g->join_key, l->nonce_key);
    l->boot_ok = false; /* a new key, or a new run: the next frame raises the boot count */
    new_token(g, false);
    atalaia_ff_reasm_reset(&l->reasm);
    if (l->channel_hz == 0) l->channel_hz = radio_region_default_channel_hz(g->region);
    l->ready = true;
    /* The first announcement, 2-20 s from the next tick (announce_ms 0: not chosen yet). */
    l->announce_due = true;
    l->announce_ms = 0;
    /* Silent: "@lobby" prints the device id (a host box prints nothing before READY). */
    return true;
}

void box_lobby_device_hex(const box_game_t *g, char out[17])
{
    out[0] = '\0';
    if (!g->lobby.ready) return;
    for (size_t i = 0; i < ATALAIA_FF_DEVICE_SIZE; i++) {
        snprintf(out + 2 * i, 3, "%02x", g->lobby.device_id[i]);
    }
}

bool box_lobby_available(const box_game_t *g)
{
    if (g->phase == BOX_JOINED || g->phase == BOX_PLAYING || g->phase == BOX_FETCHING) return false;
    /* A game picked on the box itself is being played. */
    if (g->phase == BOX_IDLE && g->runner != NULL && g->runner->running) return false;
    return true;
}

/* ---- Sending ----------------------------------------------------------------------- */

/*
 * The next nonce (decision RJ-15): the device id's pseudonym, this run's boot count, the frame
 * count. The boot count is raised and stored before its first frame, and again when the frame
 * count would wrap, so a nonce never repeats whatever the random number generator does. False
 * (and nothing is sent) when it cannot be stored.
 */
static bool next_nonce(box_game_t *g, uint8_t nonce[ATALAIA_FF_NONCE_SIZE])
{
    box_lobby_t *l = &g->lobby;
    if (!l->boot_ok || l->ctr > ATALAIA_FF_CTR_MAX) {
        uint32_t stored = 0;
        if (g->store.load_ff_boot == NULL || g->store.save_ff_boot == NULL) return false;
        int rc = g->store.load_ff_boot(g->store.ctx, &stored);
        if (rc == -1) {
            stored = 0; /* none stored yet: the box's first run */
        } else if (rc != 0) {
            /* Unreadable is not "none": starting again at 1 could repeat nonces. */
            if (!l->boot_error_logged) say(g, "field frames stopped: the boot count is unreadable");
            l->boot_error_logged = true;
            return false;
        }
        if (stored >= ATALAIA_FF_BOOT_MAX || g->store.save_ff_boot(g->store.ctx, stored + 1) != 0) {
            say(g, "field frames stopped: their boot count cannot be stored");
            l->boot_ok = false;
            return false;
        }
        l->boot = stored + 1;
        l->ctr = 0;
        l->boot_ok = true;
    }
    atalaia_ff_nonce(l->nonce_key, l->device_id, l->boot, (uint16_t)l->ctr, nonce);
    l->ctr++;
    return true;
}

static bool send_frame(box_game_t *g, const atalaia_ff_msg_t *m)
{
    uint8_t body[ATALAIA_FF_BODY_MAX];
    size_t n = atalaia_ff_body_encode(m, body, sizeof(body));
    if (n == 0) return false;
    uint8_t nonce[ATALAIA_FF_NONCE_SIZE];
    if (!next_nonce(g, nonce)) return false;
    uint8_t frame[ATALAIA_FF_MAX];
    size_t len = atalaia_ff_seal(g->lobby.key, nonce, body, n, frame, sizeof(frame), g->crypto);
    if (len == 0 || g->shell.radio_send == NULL) return false;
    return g->shell.radio_send(g->shell.user, frame, len);
}

static void announce_msg(box_game_t *g, atalaia_ff_msg_t *m)
{
    box_lobby_t *l = &g->lobby;
    memset(m, 0, sizeof(*m));
    m->kind = ATALAIA_FF_ANNOUNCE;
    memcpy(m->device_id, l->device_id, sizeof(m->device_id));
    memcpy(m->token, l->token, sizeof(m->token));
    snprintf(m->name, sizeof(m->name), "%s", g->hello.node_name[0] ? g->hello.node_name : "box");
    m->tier = g->hello.tier <= 2 ? g->hello.tier : 0;
    m->last_game = l->last_game;
    snprintf(m->last_role, sizeof(m->last_role), "%s", l->last_role);
    int battery = g->shell.battery_pct != NULL ? g->shell.battery_pct(g->shell.user) : -1;
    m->battery_pct = battery >= 0 && battery <= 100 ? (uint8_t)battery : 0xFF;
}

/* How often a free box announces itself: BOX_ANNOUNCE_SHARE_PCT of the duty-cycle budget of
 * its channel's sub-band, never more often than interval_min_ms (BOX_ANNOUNCE_MIN_MS). */
static uint32_t announce_interval(box_game_t *g)
{
    if (g->lobby.interval_fixed_ms != 0) return g->lobby.interval_fixed_ms;
    atalaia_ff_msg_t m;
    announce_msg(g, &m);
    uint8_t body[ATALAIA_FF_BODY_MAX];
    size_t n = atalaia_ff_body_encode(&m, body, sizeof(body));
    size_t frame = ATALAIA_RF_HEADER_SIZE + ATALAIA_FF_NONCE_SIZE + n + ATALAIA_RF_MIC_SIZE;
    const atalaia_band_info_t *band = atalaia_region_band_info(
        g->region, atalaia_region_band_of_channel(g->region, g->lobby.channel_hz));
    uint32_t ppm = band != NULL ? band->duty_ppm : 10000u;
    uint64_t air_us = atalaia_region_airtime_us(g->region, frame);
    /* air_ms * 1e6 / (share * ppm), with share in percent: air_us * 1e5 / (share * ppm). */
    uint64_t ms = air_us * 100000u / ((uint64_t)BOX_ANNOUNCE_SHARE_PCT * ppm);
    if (ms < g->lobby.interval_min_ms) ms = g->lobby.interval_min_ms;
    return ms > 0x7FFFFFFFu ? 0x7FFFFFFFu : (uint32_t)ms;
}

/* An announcement lo-hi ms from now; unless force, only if that is sooner than the next one. */
static void schedule_announce(box_game_t *g, uint32_t lo, uint32_t hi, bool force)
{
    box_lobby_t *l = &g->lobby;
    uint32_t at = g->now_ms + rand_between(g, lo, hi);
    if (force || !l->announce_due || l->announce_ms == 0 || (int32_t)(at - l->announce_ms) < 0) {
        l->announce_due = true;
        l->announce_ms = at ? at : 1;
    }
}

/* One answer per invite in BOX_ANSWER_REPEAT_MS (a table of the last BOX_ANSWER_IDS), and at
 * most BOX_ANSWERS_PER_MIN answers a minute in all: recorded invites played back in turn cannot
 * make the box spend its airtime. */
static void answer(box_game_t *g, uint16_t invite, atalaia_ff_result_t result)
{
    box_lobby_t *l = &g->lobby;
    size_t slot = 0;
    for (size_t i = 0; i < BOX_ANSWER_IDS; i++) {
        if (l->answered_ids[i] == invite && g->now_ms - l->answered_at[i] < BOX_ANSWER_REPEAT_MS) {
            return;
        }
        if (l->answered_ids[i] == 0 || g->now_ms - l->answered_at[i] >= BOX_ANSWER_REPEAT_MS ||
            l->answered_at[i] - l->answered_at[slot] > 0x7FFFFFFFu) {
            slot = i; /* a free or expired entry, else the oldest */
        }
    }
    uint32_t oldest = l->answer_times[l->answer_next];
    if (oldest != 0 && g->now_ms - oldest < 60000u) {
        say(g, "invite %u: no answer (more than %d a minute)", invite, BOX_ANSWERS_PER_MIN);
        return;
    }
    l->answer_times[l->answer_next] = g->now_ms ? g->now_ms : 1;
    l->answer_next = (uint8_t)((l->answer_next + 1u) % BOX_ANSWERS_PER_MIN);
    l->answered_ids[slot] = invite;
    l->answered_at[slot] = g->now_ms;
    l->answer_due = true;
    l->answer_invite = invite;
    l->answer_result = (uint8_t)result;
    l->answer_ms = g->now_ms + rand_between(g, BOX_INVITE_ANSWER_MIN_MS, BOX_INVITE_ANSWER_MAX_MS);
}

/* ---- Receiving ----------------------------------------------------------------------- */

static atalaia_ff_result_t result_of(box_join_result_t r)
{
    switch (r) {
    case BOX_JOIN_OK: return ATALAIA_FF_ACCEPTED;
    case BOX_JOIN_CONTROLLER: return ATALAIA_FF_NOT_BOX;
    case BOX_JOIN_NO_MODE: return ATALAIA_FF_NO_MODE;
    case BOX_JOIN_BUSY: return ATALAIA_FF_BUSY;
    case BOX_JOIN_STORAGE: return ATALAIA_FF_STORAGE;
    case BOX_JOIN_RADIO: return ATALAIA_FF_RADIO;
    case BOX_JOIN_ENDED: return ATALAIA_FF_ENDED;
    default: return ATALAIA_FF_REFUSED;
    }
}

static const char *result_name(atalaia_ff_result_t r)
{
    static const char *const names[] = {"accepted",  "busy",    "refused", "no mode",
                                        "not a box", "storage", "radio",   "ended"};
    return r <= ATALAIA_FF_ENDED ? names[r] : "?";
}

bool box_lobby_played_to_the_end(const box_game_t *g, uint16_t game_id)
{
    for (size_t i = 0; i < BOX_ENDED_GAMES; i++) {
        if (g->lobby.ended[i] == game_id && game_id != 0) return true;
    }
    return false;
}

static void on_invite(box_game_t *g, const atalaia_ff_msg_t *m)
{
    box_lobby_t *l = &g->lobby;
    if (memcmp(m->device_id, l->device_id, sizeof(l->device_id)) != 0) return; /* another box's */
    bool current = memcmp(m->token, l->token, sizeof(l->token)) == 0;
    bool previous = l->have_prev && memcmp(m->token, l->prev_token, sizeof(l->token)) == 0;
    if (!current && !previous) {
        /* Recorded and played back, or older than the last two tokens: silence. */
        l->invites_refused++;
        say(g, "invite %u refused: an old token", m->invite_id);
        return;
    }
    if (!box_lobby_available(g)) {
        new_token(g, false); /* answered: this invite and every older one never work again */
        answer(g, m->invite_id, ATALAIA_FF_BUSY);
        return;
    }
    /* Static, not on the game task's stack (one box per process): the card's path that
     * follows needs its own join struct there. */
    static uint8_t payload[ATALAIA_JOIN_MAX];
    static atalaia_join_t j;
    int n = atalaia_ff_reasm_add(&l->reasm, m, payload, sizeof(payload));
    if (n <= 0) return; /* parts still missing, or they make no join payload */
    /* A join for a game this box has already played to its end is stale, whoever sends it. */
    atalaia_ff_result_t result;
    if (atalaia_join_decode(payload, (size_t)n, g->join_key, &j) == ATALAIA_JOIN_OK &&
        box_lobby_played_to_the_end(g, j.game_id)) {
        result = ATALAIA_FF_ENDED;
    } else {
        result = result_of(box_game_join_invited(g, payload, (size_t)n));
    }
    memset(&j, 0, sizeof(j));
    memset(payload, 0, sizeof(payload));
    /* Whatever the result, the invite (and every older one) never works again (decision RJ-8):
     * a refusal recorded now must not join the box to that game later. */
    new_token(g, false);
    if (result == ATALAIA_FF_ACCEPTED) {
        l->invites_accepted++;
        l->ready_screen_due = false;
    } else {
        l->invites_refused++;
    }
    say(g, "invite %u: %s", m->invite_id, result_name(result));
    answer(g, m->invite_id, result);
}

/* "Game N (its key's tag T) is over" (decision OT-13): only the box's own game, named by its id
 * and its key's tag, ends. A game's end is a fact that stays true, so the frame needs no time:
 * played back later it can only end that same game again, which the box no longer joins
 * (played to its end, BN-19); a new game with the same id has another key, so another tag. */
static void on_game_over(box_game_t *g, const atalaia_ff_msg_t *m)
{
    box_lobby_t *l = &g->lobby;
    if (g->phase != BOX_JOINED && g->phase != BOX_PLAYING && g->phase != BOX_FETCHING) {
        return; /* no game, or over already */
    }
    if (m->game_id != g->join.game_id) return; /* another game's */
    uint8_t tag[ATALAIA_EPOCH_TAG_SIZE];
    atalaia_radio_epoch_tag(g->join.game_key, tag);
    bool same = memcmp(tag, m->key_tag, sizeof(tag)) == 0;
    memset(tag, 0, sizeof(tag));
    if (!same) {
        l->games_over_refused++;
        say(g, "game over for game %u refused: another game's key", m->game_id);
        return;
    }
    l->games_over_heard++;
    if (g->phase == BOX_FETCHING) {
        /* The game it was fetching for is over: the fetch stops (cancelled, P5B-13). */
        say(g, "game %u is over: the mode fetch stops", m->game_id);
        g->fetch_cancel = true;
        return;
    }
    say(g, "game %u is over (said by a field controller)", m->game_id);
    box_game_end_by_field(g);
}

bool box_lobby_on_packet(box_game_t *g, const uint8_t *pkt, size_t len)
{
    if (!atalaia_ff_is_frame(pkt, len)) return false;
    box_lobby_t *l = &g->lobby;
    if (!l->ready) return true;
    uint8_t body[ATALAIA_FF_BODY_MAX];
    size_t n = atalaia_ff_open(l->key, pkt, len, body, sizeof(body), g->crypto);
    atalaia_ff_msg_t m;
    if (n == 0 || !atalaia_ff_body_decode(body, n, &m)) {
        l->frames_ignored++; /* another field's, a stranger's, or broken */
        return true;
    }
    switch (m.kind) {
    case ATALAIA_FF_DISCOVER: {
        if (!box_lobby_available(g)) break;
        uint32_t gap = announce_interval(g) / 4;
        if (l->announced && g->now_ms - l->last_announce_ms < gap) break;
        schedule_announce(g, 0, BOX_DISCOVER_ANSWER_MAX_MS, false);
        break;
    }
    case ATALAIA_FF_INVITE: on_invite(g, &m); break;
    case ATALAIA_FF_GAME_OVER: on_game_over(g, &m); break;
    default: break; /* other boxes' announcements */
    }
    memset(&m, 0, sizeof(m));
    return true;
}

/* ---- Time --------------------------------------------------------------------------- */

void box_lobby_game_over(box_game_t *g, uint32_t now_ms)
{
    box_lobby_t *l = &g->lobby;
    l->last_game = g->join.game_id;
    snprintf(l->last_role, sizeof(l->last_role), "%s", g->join.role);
    memmove(l->ended + 1, l->ended, sizeof(l->ended) - sizeof(l->ended[0]));
    l->ended[0] = g->join.game_id;
    l->invited = false;
    l->ready_screen_due = true;
    l->ready_screen_ms = now_ms + BOX_READY_MS;
    g->now_ms = now_ms;
    if (l->ready) {
        new_token(g, false); /* free again: nothing sent before this counts */
        schedule_announce(g, l->first_min_ms, l->first_max_ms, true);
    }
}

void box_lobby_free_again(box_game_t *g)
{
    box_lobby_t *l = &g->lobby;
    l->invited = false;
    l->ready_screen_due = true;
    l->ready_screen_ms = g->now_ms + BOX_READY_MS;
    if (l->ready) {
        new_token(g, false); /* free again: nothing sent before this counts */
        schedule_announce(g, l->first_min_ms, l->first_max_ms, true);
    }
}

void box_lobby_joined(box_game_t *g)
{
    if (g->lobby.ready) new_token(g, false);
}

void box_lobby_cancel_ready_screen(box_game_t *g)
{
    g->lobby.ready_screen_due = false;
}

static void show_ready(box_game_t *g)
{
    /* "Ready / next game" in the box's language (screen_renderer.c, oled_view.c). */
    const char *data = g->has_picker ? "{\"picker\":true}" : "{}";
    if (g->shell.screen != NULL) g->shell.screen(g->shell.user, "ready", data);
}

void box_lobby_show_ready(box_game_t *g)
{
    g->lobby.ready_screen_due = false;
    show_ready(g);
}

void box_lobby_tick(box_game_t *g, uint32_t now_ms)
{
    box_lobby_t *l = &g->lobby;
    g->now_ms = now_ms;
    if (l->ready_screen_due && (int32_t)(now_ms - l->ready_screen_ms) >= 0) {
        l->ready_screen_due = false;
        if (box_lobby_available(g)) show_ready(g);
    }
    if (!l->ready) return;
    if ((int32_t)(now_ms - l->rotate_ms) >= 0) new_token(g, true);
    if (l->answer_due && (int32_t)(now_ms - l->answer_ms) >= 0) {
        l->answer_due = false;
        atalaia_ff_msg_t m;
        announce_msg(g, &m);
        m.answer = l->answer_invite;
        m.result = l->answer_result;
        send_frame(g, &m);
        l->announced = true;
        l->last_announce_ms = now_ms;
    }
    if (!box_lobby_available(g)) return;
    if (l->announce_due && l->announce_ms == 0) {
        l->announce_ms = now_ms + rand_between(g, l->first_min_ms, l->first_max_ms);
    }
    if (l->announce_due && (int32_t)(now_ms - l->announce_ms) >= 0) {
        atalaia_ff_msg_t m;
        announce_msg(g, &m);
        send_frame(g, &m);
        l->announced = true;
        l->last_announce_ms = now_ms;
        uint32_t interval = announce_interval(g);
        l->announce_ms = now_ms + interval / 10u * 9u + rand_between(g, 0, interval / 5u);
        if (l->announce_ms == 0) l->announce_ms = 1;
    }
}
