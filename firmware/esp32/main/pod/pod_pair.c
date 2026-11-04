/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's Bluetooth pairing, apart from the stack (see pod_pair.h).
 */
#include "pod_pair.h"

#include <stdio.h>
#include <string.h>

/* The largest multiple of a million that a 32-bit word reaches: words from it up are drawn
 * again, so that no passkey is likelier than another. */
#define PASSKEY_LIMIT 4294000000u

void pod_pair_init(pod_pair_t *p, bool require_mitm)
{
    memset(p, 0, sizeof(*p));
    p->require_mitm = require_mitm;
}

void pod_pair_set_name(pod_pair_t *p, const char *name)
{
    snprintf(p->name, sizeof(p->name), "%s", name ? name : "");
}

uint32_t pod_pair_passkey(uint32_t (*rand32)(void *ctx), void *ctx)
{
    uint32_t r;
    do {
        r = rand32(ctx);
    } while (r >= PASSKEY_LIMIT);
    return r % 1000000u;
}

static void show(pod_pair_t *p, oled_pair_t what, uint32_t now_ms)
{
    p->show = what;
    p->show_ms = now_ms;
}

void pod_pair_on_connect(pod_pair_t *p, uint32_t now_ms)
{
    p->connected = true;
    p->secure = false;
    p->dropping = false;
    p->connect_ms = now_ms;
}

void pod_pair_on_disconnect(pod_pair_t *p, uint32_t now_ms)
{
    /* The phone went while the passkey showed: it cancelled, or its pairing failed. */
    if (p->show == OLED_PAIR_PASSKEY) {
        p->count.failures++;
        show(p, OLED_PAIR_FAILED, now_ms);
    }
    p->connected = false;
    p->secure = false;
    p->dropping = false;
}

void pod_pair_on_passkey(pod_pair_t *p, uint32_t passkey, uint32_t now_ms)
{
    p->passkey = passkey % 1000000u;
    show(p, OLED_PAIR_PASSKEY, now_ms);
}

pod_pair_action_t pod_pair_on_encryption(pod_pair_t *p, pod_pair_result_t result, bool encrypted,
                                         bool authenticated, uint32_t now_ms)
{
    if (!p->connected || p->dropping) return POD_PAIR_ACT_NONE;
    bool pairing = p->show == OLED_PAIR_PASSKEY;
    if (result == POD_PAIR_RESULT_OK && encrypted) {
        if (authenticated || !p->require_mitm) {
            p->secure = true;
            if (pairing) {
                p->count.pairings++;
                show(p, OLED_PAIR_PAIRED, now_ms);
            }
            /* A phone that comes back with its bond: nothing to show. */
            return POD_PAIR_ACT_NONE;
        }
        /* Encrypted with a key a man in the middle could have made (a Just Works bond from a pod
         * firmware before PODPK): not trusted. The phone is told to pair again (PODPK-4). */
        p->count.stale_bonds++;
        p->dropping = true;
        show(p, OLED_PAIR_AGAIN, now_ms);
        return POD_PAIR_ACT_DROP_STALE;
    }
    switch (result) {
    case POD_PAIR_RESULT_NO_KEY:
        /* The phone has a bond the pod forgot (cleared, or the NVS erased). */
        p->count.stale_bonds++;
        p->dropping = true;
        show(p, OLED_PAIR_AGAIN, now_ms);
        return POD_PAIR_ACT_DROP_STALE;
    case POD_PAIR_RESULT_TIMEOUT:
        p->count.timeouts++;
        show(p, OLED_PAIR_TIMEOUT, now_ms);
        break;
    default:
        p->count.failures++;
        show(p, OLED_PAIR_FAILED, now_ms);
        break;
    }
    /* The link goes at once: the app says why (Android's bond went back to none) instead of
     * waiting for an IDENT that cannot come; linking again shows a new passkey (PODPK-5). */
    p->dropping = true;
    return POD_PAIR_ACT_DROP;
}

pod_pair_action_t pod_pair_tick(pod_pair_t *p, uint32_t now_ms, bool button)
{
    uint32_t shown = now_ms - p->show_ms;

    /* The PRG button: held long enough, every bond goes (once a press). */
    if (button && !p->button) {
        p->button = true;
        p->button_done = false;
        p->button_ms = now_ms;
    } else if (!button && p->button) {
        p->button = false;
        if (p->show == OLED_PAIR_CLEARING) p->show = OLED_PAIR_NONE;
    }
    if (p->button && !p->button_done) {
        uint32_t held = now_ms - p->button_ms;
        if (held >= POD_PAIR_CLEAR_HOLD_MS) {
            p->button_done = true;
            p->count.clears++;
            p->secure = false;
            if (p->connected) p->dropping = true;
            show(p, OLED_PAIR_CLEARED, now_ms);
            return POD_PAIR_ACT_CLEAR_BONDS;
        }
        if (held >= POD_PAIR_CLEAR_SHOW_MS && p->show != OLED_PAIR_CLEARING) {
            show(p, OLED_PAIR_CLEARING, now_ms);
        }
        shown = now_ms - p->show_ms;
    }

    /* Outcomes stay a while, then the OLED goes dark; the passkey stays until the pairing
     * ends (the stack's timeout or the phone's answer), the hold until the button is let go. */
    switch (p->show) {
    case OLED_PAIR_PAIRED:
    case OLED_PAIR_FAILED:
    case OLED_PAIR_TIMEOUT:
    case OLED_PAIR_AGAIN:
    case OLED_PAIR_CLEARED:
        if (shown >= POD_PAIR_RESULT_MS) p->show = OLED_PAIR_NONE;
        break;
    default: break;
    }

    /* A phone that holds the pod's one connection without pairing is let go. */
    if (p->connected && !p->secure && !p->dropping &&
        now_ms - p->connect_ms >= POD_PAIR_TIMEOUT_MS) {
        p->dropping = true;
        p->count.timeouts++;
        show(p, OLED_PAIR_TIMEOUT, now_ms);
        return POD_PAIR_ACT_DROP;
    }
    return POD_PAIR_ACT_NONE;
}

void pod_pair_view(const pod_pair_t *p, uint32_t now_ms, oled_pair_view_t *out)
{
    memset(out, 0, sizeof(*out));
    out->show = p->show;
    out->secs_left = -1;
    snprintf(out->name, sizeof(out->name), "%s", p->name);
    if (p->show == OLED_PAIR_PASSKEY) {
        out->passkey = p->passkey;
        uint32_t gone = now_ms - p->show_ms;
        out->secs_left =
            gone >= POD_PAIR_PASSKEY_MS ? 0 : (long)((POD_PAIR_PASSKEY_MS - gone + 999) / 1000);
    } else if (p->show == OLED_PAIR_CLEARING) {
        uint32_t held = now_ms - p->button_ms;
        out->progress = held >= POD_PAIR_CLEAR_HOLD_MS
                            ? 100
                            : (int)((uint64_t)held * 100u / POD_PAIR_CLEAR_HOLD_MS);
    }
}
