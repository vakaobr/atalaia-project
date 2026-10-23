/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pairing a box by its code (box_pair.h, protocol/adoption.md section 7).
 */
#include "box_pair.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "atalaia/duty_cycle.h"
#include "atalaia/join.h"
#include "box_text.h"
#include "cpace.h"
#include "radio/radio_region.h"

static void say(box_pair_t *p, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(box_pair_t *p, const char *fmt, ...)
{
    if (p->ops.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    p->ops.log(p->ops.user, line);
}

static void wipe(void *buf, size_t len)
{
    volatile uint8_t *b = (volatile uint8_t *)buf;
    while (len--) *b++ = 0;
}

static uint32_t rand_u32(box_pair_t *p)
{
    uint8_t b[4] = {0};
    if (p->ops.random) p->ops.random(p->ops.user, b, sizeof(b));
    return ((uint32_t)b[0] << 24) | ((uint32_t)b[1] << 16) | ((uint32_t)b[2] << 8) | b[3];
}

static uint32_t rand_between(box_pair_t *p, uint32_t lo, uint32_t hi)
{
    return hi <= lo ? lo : lo + rand_u32(p) % (hi - lo + 1u);
}

/* A uniform 6-digit code (rejection sampling: 4294 x 10^6 fits in 32 bits). */
static void new_code(box_pair_t *p)
{
    uint32_t v;
    do {
        v = rand_u32(p);
    } while (v >= 4294000000u);
    snprintf(p->code, sizeof(p->code), "%06lu", (unsigned long)(v % 1000000u));
}

/* The pairing screen: the code, and the pair id's first two bytes, which the console shows next
 * to the box's offer so the GM types the code into this box's entry (decision AD-26). */
static void show_code(box_pair_t *p, const char *title)
{
    char data[160];
    snprintf(data, sizeof(data),
             "{\"title\":\"%s\",\"code\":\"%.3s %.3s\",\"id\":\"%02x%02x\",\"field\":\"%s\"}",
             title, p->code, p->code + 3, p->pair_id[0], p->pair_id[1], box_text(TX_FIELD_NONE));
    if (p->ops.screen) p->ops.screen(p->ops.user, "status", data);
}

/* Pair paused or locked, said on the screen instead of the code (decision AD-25). */
static void show_notice(box_pair_t *p, const char *title, const char *what)
{
    char data[128];
    snprintf(data, sizeof(data), "{\"title\":\"%s\",\"pairing\":\"%s\"}", title, what);
    if (p->ops.screen) p->ops.screen(p->ops.user, "status", data);
}

static void end_run(box_pair_t *p)
{
    p->in_run = false;
    wipe(&p->keys, sizeof(p->keys));
    wipe(p->reply_frame, sizeof(p->reply_frame));
    p->reply_len = 0;
    p->replies = 0;
}

void box_pair_init(box_pair_t *p, const box_pair_ops_t *ops, adoption_t *adopt,
                   const atalaia_crypto_ops_t *crypto, const char *name, uint8_t tier,
                   uint32_t channel_hz)
{
    memset(p, 0, sizeof(*p));
    if (ops) p->ops = *ops;
    p->adopt = adopt;
    p->crypto = crypto;
    snprintf(p->name, sizeof(p->name), "%s", name && name[0] ? name : "box");
    if (!atalaia_join_text_ok(p->name, ATALAIA_PF_NAME_MAX))
        snprintf(p->name, sizeof(p->name), "box");
    p->tier = tier <= 2 ? tier : 0;
    p->channel_hz = channel_hz ? channel_hz : radio_region_default_channel_hz(RADIO_REGION);
}

bool box_pair_showing(const box_pair_t *p)
{
    return p->active || p->lock_notice;
}

/* An offer every max(15 s, time on air / (5 % x the sub-band's duty cycle)). */
static uint32_t offer_interval(box_pair_t *p)
{
    atalaia_pf_msg_t m;
    memset(&m, 0, sizeof(m));
    m.kind = ATALAIA_PF_OFFER;
    memcpy(m.pair_id, p->pair_id, sizeof(m.pair_id));
    snprintf(m.name, sizeof(m.name), "%s", p->name);
    m.tier = p->tier;
    uint8_t frame[ATALAIA_PF_MAX];
    size_t n = atalaia_pf_encode(&m, frame, sizeof(frame));
    const atalaia_band_info_t *band = atalaia_region_band_info(
        RADIO_REGION, atalaia_region_band_of_channel(RADIO_REGION, p->channel_hz));
    uint32_t ppm = band != NULL ? band->duty_ppm : 10000u;
    uint64_t air_us = atalaia_region_airtime_us(RADIO_REGION, n ? n : 40);
    uint64_t ms = air_us * 100000u / ((uint64_t)BOX_PAIR_OFFER_SHARE_PCT * ppm);
    if (ms < BOX_PAIR_OFFER_MIN_MS) ms = BOX_PAIR_OFFER_MIN_MS;
    return ms > 0x7FFFFFFFu ? 0x7FFFFFFFu : (uint32_t)ms;
}

bool box_pair_start(box_pair_t *p, uint32_t now_ms)
{
    p->now_ms = now_ms;
    if (p->adopt != NULL && p->adopt->adopted) return false;
    if (p->locked) {
        say(p, "pairing: locked after %u failed runs; restart the box", BOX_PAIR_RUNS_MAX);
        return false;
    }
    end_run(p);
    p->done_valid = false;
    p->ops.random(p->ops.user, p->pair_id, sizeof(p->pair_id));
    new_code(p);
    p->active = true;
    p->waiting = false;
    p->failed_in_row = 0;
    p->show_until_ms = now_ms + BOX_PAIR_SHOW_MS;
    p->next_offer_ms = now_ms + rand_between(p, 1000, 3000);
    show_code(p, box_text(TX_PAIR_THIS_BOX));
    say(p,
        "pairing: code %.3s %.3s on %lu Hz, for %u minutes (the console's Adopt tab, "
        "\"Pair by code\")",
        p->code, p->code + 3, (unsigned long)p->channel_hz, BOX_PAIR_SHOW_MS / 60000u);
    return true;
}

void box_pair_stop(box_pair_t *p, const char *why)
{
    if (!p->active) return;
    end_run(p);
    p->active = false;
    p->waiting = false;
    wipe(p->code, sizeof(p->code));
    p->redraw = true;
    say(p, "pairing: stopped (%s)", why);
}

static bool send(box_pair_t *p, const atalaia_pf_msg_t *m, uint8_t *keep, size_t *keep_len)
{
    uint8_t frame[ATALAIA_PF_MAX];
    size_t n = atalaia_pf_encode(m, frame, sizeof(frame));
    if (n == 0 || p->ops.radio_send == NULL) return false;
    if (keep != NULL) {
        memcpy(keep, frame, n);
        *keep_len = n;
    }
    return p->ops.radio_send(p->ops.user, frame, n);
}

/* A run that did not end with a key: the code goes; after three in a row, a minute's wait;
 * after ten, nothing until a restart. */
static void run_failed(box_pair_t *p, const char *why)
{
    end_run(p);
    p->runs_failed++;
    p->failed_in_row++;
    p->failed_total++;
    say(p, "pairing: a run failed (%s)", why);
    if (p->failed_total >= BOX_PAIR_RUNS_MAX) {
        p->locked = true;
        box_pair_stop(p, "too many failed runs: restart the box to pair it");
        /* Said on the screen until a key, not only in the log (decision AD-25). */
        p->redraw = false;
        p->lock_notice = true;
        show_notice(p, box_text(TX_PAIR_LOCKED), box_text(TX_RESTART_THE_BOX));
        return;
    }
    new_code(p);
    if (p->failed_in_row >= BOX_PAIR_RUNS_BEFORE_WAIT) {
        p->waiting = true;
        p->wait_until_ms = p->now_ms + BOX_PAIR_WAIT_MS;
        p->failed_in_row = 0;
        show_notice(p, box_text(TX_PAIR_PAUSED), box_text(TX_FOR_ONE_MINUTE));
        say(p, "pairing: %u failed runs in a row, waiting a minute", BOX_PAIR_RUNS_BEFORE_WAIT);
    } else {
        show_code(p, box_text(TX_TRY_AGAIN));
    }
    say(p, "pairing: new code %.3s %.3s", p->code, p->code + 3);
}

static bool sid_used(const box_pair_t *p, const uint8_t sid[ATALAIA_PF_SID_SIZE])
{
    for (size_t i = 0; i < BOX_PAIR_SIDS; i++) {
        if (memcmp(p->used_sids[i], sid, ATALAIA_PF_SID_SIZE) == 0) return true;
    }
    return false;
}

static void on_start(box_pair_t *p, const atalaia_pf_msg_t *m)
{
    if (p->in_run) {
        /* The controller did not hear the REPLY: the same one again, at most twice in all. */
        if (memcmp(m->sid, p->sid, sizeof(p->sid)) == 0 && p->replies < BOX_PAIR_REPLIES_PER_RUN &&
            p->ops.radio_send != NULL) {
            p->replies++;
            p->ops.radio_send(p->ops.user, p->reply_frame, p->reply_len);
        }
        return; /* another controller's START while a run is on: ignored */
    }
    if (p->waiting || sid_used(p, m->sid)) return; /* a replay, or during the wait */
    if (p->adopt != NULL && p->adopt->ops.busy != NULL && p->adopt->ops.busy(p->adopt->ops.ctx)) {
        return;
    }
    memcpy(p->used_sids[p->used_next], m->sid, ATALAIA_PF_SID_SIZE);
    p->used_next = (uint8_t)((p->used_next + 1u) % BOX_PAIR_SIDS);
    p->runs_started++;
    memcpy(p->sid, m->sid, sizeof(p->sid));
    p->in_run = true;
    p->run_until_ms = p->now_ms + BOX_PAIR_RUN_MS;

    uint8_t ci[ATALAIA_PF_CI_SIZE], g[CPACE_POINT_SIZE], yb[32], ybp[CPACE_POINT_SIZE];
    uint8_t k[CPACE_POINT_SIZE], isk[CPACE_ISK_SIZE];
    atalaia_pf_channel_id(p->pair_id, ci);
    bool ok = cpace_generator((const uint8_t *)p->code, ATALAIA_PF_CODE_DIGITS, ci, sizeof(ci),
                              m->sid, ATALAIA_PF_SID_SIZE, g);
    p->ops.random(p->ops.user, yb, sizeof(yb));
    cpace_scalar_mult(yb, g, ybp);
    ok = ok && cpace_scalar_mult_vfy(yb, m->point, k);
    if (ok) {
        cpace_isk_ir(m->sid, ATALAIA_PF_SID_SIZE, k, m->point,
                     (const uint8_t *)ATALAIA_PF_AD_CONTROLLER,
                     sizeof(ATALAIA_PF_AD_CONTROLLER) - 1, ybp, (const uint8_t *)ATALAIA_PF_AD_BOX,
                     sizeof(ATALAIA_PF_AD_BOX) - 1, isk);
        atalaia_pf_keys(isk, m->sid, &p->keys);
    }
    wipe(yb, sizeof(yb));
    wipe(k, sizeof(k));
    wipe(isk, sizeof(isk));
    wipe(g, sizeof(g));
    if (!ok) {
        run_failed(p, "the controller's point is of low order");
        return;
    }
    atalaia_pf_msg_t r;
    memset(&r, 0, sizeof(r));
    r.kind = ATALAIA_PF_REPLY;
    memcpy(r.pair_id, p->pair_id, sizeof(r.pair_id));
    memcpy(r.sid, m->sid, sizeof(r.sid));
    memcpy(r.point, ybp, sizeof(r.point));
    atalaia_pf_tag_reply(&p->keys, r.tag);
    p->replies = 1;
    send(p, &r, p->reply_frame, &p->reply_len);
    say(p, "pairing: a controller started a run");
}

static void field_fp(const uint8_t key[ATALAIA_JOIN_KEY_SIZE], uint8_t out[ATALAIA_PF_FP_SIZE])
{
    static const char label[] = "atalaia-field-fingerprint";
    uint8_t mac[32];
    atalaia_hmac_sha256(key, ATALAIA_JOIN_KEY_SIZE, (const uint8_t *)label, sizeof(label) - 1, mac);
    memcpy(out, mac, ATALAIA_PF_FP_SIZE);
}

static void on_key(box_pair_t *p, const atalaia_pf_msg_t *m)
{
    if (!p->in_run) {
        /* Our DONE was lost: the same one again, a few times, for a short while. */
        if (p->done_valid && memcmp(m->sid, p->done_sid, sizeof(p->done_sid)) == 0 &&
            p->done_repeats < BOX_PAIR_DONE_REPEATS &&
            (int32_t)(p->now_ms - p->done_until_ms) < 0 && p->ops.radio_send != NULL) {
            p->done_repeats++;
            p->ops.radio_send(p->ops.user, p->done_frame, p->done_len);
        }
        return;
    }
    if (memcmp(m->sid, p->sid, sizeof(p->sid)) != 0) return; /* another run's */
    /* A KEY that does not authenticate ends nothing (decision AD-25): anyone on the air can send
     * one with the sid it heard, so it is counted and ignored, and the run goes on waiting for
     * the controller's own KEY until its time runs out (which burns the code anyway). */
    uint8_t want[ATALAIA_PF_TAG_SIZE];
    atalaia_pf_tag_key(&p->keys, want);
    if (!atalaia_pf_tag_equal(want, m->tag)) {
        p->bad_keys++;
        say(p, "pairing: a KEY that does not match ignored");
        return;
    }
    uint8_t key[ATALAIA_JOIN_KEY_SIZE];
    char name[ATALAIA_PF_FIELD_NAME_MAX + 1];
    if (!atalaia_pf_open_key(&p->keys, m->nonce, p->pair_id, p->sid, m->sealed, m->sealed_len, key,
                             name, p->crypto)) {
        p->bad_keys++; /* the controller's tag, someone else's sealed bytes: ignored as well */
        say(p, "pairing: a KEY whose sealed key does not open ignored");
        return;
    }
    adopt_result_t r =
        p->adopt != NULL ? adoption_offer(p->adopt, key, name, NULL) : ADOPT_STORE_FAILED;
    atalaia_pf_msg_t d;
    memset(&d, 0, sizeof(d));
    d.kind = ATALAIA_PF_DONE;
    memcpy(d.pair_id, p->pair_id, sizeof(d.pair_id));
    memcpy(d.sid, p->sid, sizeof(d.sid));
    d.result = (uint8_t)r;
    if (adopt_result_ok(r)) field_fp(key, d.fingerprint);
    atalaia_pf_tag_done(&p->keys, d.result, d.fingerprint, d.tag);
    wipe(key, sizeof(key));
    wipe(name, sizeof(name));
    send(p, &d, p->done_frame, &p->done_len);
    p->done_valid = true;
    memcpy(p->done_sid, p->sid, sizeof(p->done_sid));
    p->done_repeats = 0;
    p->done_until_ms = p->now_ms + BOX_PAIR_RUN_MS;
    if (p->adopt != NULL) adoption_report(p->adopt, "radio", r, p->now_ms);
    if (adopt_result_ok(r)) {
        end_run(p);
        p->active = false;
        wipe(p->code, sizeof(p->code));
        say(p, "pairing: done");
    } else {
        run_failed(p, adopt_result_name(r));
    }
}

bool box_pair_on_packet(box_pair_t *p, const uint8_t *pkt, size_t len, uint32_t now_ms)
{
    if (!atalaia_pf_is_frame(pkt, len)) return false;
    p->now_ms = now_ms;
    atalaia_pf_msg_t m;
    if (!atalaia_pf_decode(pkt, len, &m)) {
        p->frames_ignored++;
        return true;
    }
    /* Only frames for this box's pair id, and KEY even after it is done (its DONE again). */
    bool ours = memcmp(m.pair_id, p->pair_id, sizeof(p->pair_id)) == 0;
    if (ours && m.kind == ATALAIA_PF_KEY && !p->active) {
        on_key(p, &m);
    } else if (ours && p->active && !p->locked) {
        if (m.kind == ATALAIA_PF_START) on_start(p, &m);
        if (m.kind == ATALAIA_PF_KEY) on_key(p, &m);
    } else if (!ours || !p->active) {
        p->frames_ignored++;
    }
    wipe(&m, sizeof(m));
    return true;
}

bool box_pair_key(box_pair_t *p, char key, uint32_t now_ms)
{
    if (p->lock_notice) {
        p->lock_notice = false; /* any key: the picker again (pairing stays locked) */
        p->redraw = true;
        return true;
    }
    if (!p->active) return false;
    p->now_ms = now_ms;
    if (key == '*') {
        box_pair_stop(p, "cancelled on the keypad");
    } else if (key == '#' && !p->in_run && !p->waiting) {
        new_code(p);
        show_code(p, box_text(TX_PAIR_THIS_BOX));
        say(p, "pairing: new code %.3s %.3s", p->code, p->code + 3);
    }
    return true;
}

bool box_pair_tick(box_pair_t *p, uint32_t now_ms)
{
    p->now_ms = now_ms;
    if (p->active && p->adopt != NULL && p->adopt->adopted) {
        box_pair_stop(p, "adopted"); /* by a field card, the cable or this run */
        p->redraw = false;           /* adoption shows its own result */
    }
    if (p->active) {
        if (p->in_run && (int32_t)(now_ms - p->run_until_ms) >= 0) run_failed(p, "no key in time");
    }
    if (p->active && p->waiting && (int32_t)(now_ms - p->wait_until_ms) >= 0) {
        p->waiting = false;
        show_code(p, box_text(TX_PAIR_THIS_BOX));
    }
    if (p->active && !p->in_run && (int32_t)(now_ms - p->show_until_ms) >= 0) {
        box_pair_stop(p,
                      "no field paired it in 5 minutes; \"@pair\" or a restart shows a new code");
    }
    if (p->active && !p->waiting && !p->in_run && (int32_t)(now_ms - p->next_offer_ms) >= 0) {
        atalaia_pf_msg_t m;
        memset(&m, 0, sizeof(m));
        m.kind = ATALAIA_PF_OFFER;
        memcpy(m.pair_id, p->pair_id, sizeof(m.pair_id));
        snprintf(m.name, sizeof(m.name), "%s", p->name);
        m.tier = p->tier;
        if (send(p, &m, NULL, NULL)) p->offers_sent++;
        uint32_t interval = offer_interval(p);
        p->next_offer_ms = now_ms + interval / 10u * 9u + rand_between(p, 0, interval / 5u);
    }
    if (p->redraw) {
        p->redraw = false;
        return true;
    }
    return false;
}
