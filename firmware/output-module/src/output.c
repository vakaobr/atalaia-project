/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I2C output module's portable part (output.h).
 */
#include "output.h"

#include <string.h>

/* ---- Configuration
 * -------------------------------------------------------------------------- */

static const char *const HINTS[] = {"generic", "siren", "strobe", "smoke", "light", "horn"};

/* The field [*p, end of field) as a word: true when it equals word, and *p
 * moves past it. */
static bool take_word(const char **p, const char *word)
{
    size_t n = strlen(word);
    if (strncmp(*p, word, n) != 0) return false;
    char next = (*p)[n];
    if (next != ':' && next != ',' && next != '\0') return false;
    *p += n;
    return true;
}

/* A decimal number of 1-3 digits, at most most. */
static bool take_number(const char **p, unsigned most, unsigned *out)
{
    unsigned v = 0;
    int digits = 0;
    while (**p >= '0' && **p <= '9') {
        if (++digits > 3) return false;
        v = v * 10u + (unsigned)(**p - '0');
        (*p)++;
    }
    if (digits == 0 || v > most) return false;
    *out = v;
    return true;
}

static bool take_colon(const char **p)
{
    if (**p != ':') return false;
    (*p)++;
    return true;
}

static bool fail(const char **error, const char *why)
{
    if (error != NULL) *error = why;
    return false;
}

bool output_parse_channels(const char *spec, mc_channel_t channels[OUTPUT_MAX_CHANNELS],
                           uint8_t *count, const char **error)
{
    if (spec == NULL || *spec == '\0') return fail(error, "no channel");
    const char *p = spec;
    uint8_t n = 0;
    for (;;) {
        if (n == OUTPUT_MAX_CHANNELS) return fail(error, "more than 4 channels");
        mc_channel_t c;
        memset(&c, 0, sizeof(c));
        c.kind = MC_KIND_OUTPUT;
        if (take_word(&p, "relay")) {
            c.flags = MC_CH_RELAY;
        } else if (take_word(&p, "solid")) {
            c.flags = MC_CH_SOLID_STATE;
        } else {
            return fail(error, "a channel's type is not relay or solid");
        }
        if (!take_colon(&p)) return fail(error, "a channel has no hint");
        bool hint_found = false;
        for (uint8_t h = 0; h < sizeof(HINTS) / sizeof(HINTS[0]); h++) {
            if (take_word(&p, HINTS[h])) {
                c.hint = h;
                hint_found = true;
                break;
            }
        }
        if (!hint_found)
            return fail(error, "a channel's hint is not generic, siren, strobe, "
                               "smoke, light or horn");
        unsigned max_on, min_off;
        if (!take_colon(&p) || !take_number(&p, 255u, &max_on) || max_on == 0u) {
            return fail(error, "a channel's max on is not 1-255");
        }
        if (!take_colon(&p) || !take_number(&p, 255u, &min_off)) {
            return fail(error, "a channel's min off is not 0-255");
        }
        c.max_on_s = (uint8_t)max_on;
        c.min_off_s = (uint8_t)min_off;
        if (*p == ':') {
            p++;
            if (!take_word(&p, "sense")) return fail(error, "a channel's fifth field is not sense");
            c.flags = (uint8_t)(c.flags | MC_CH_SENSES_SUPPLY);
        }
        channels[n++] = c;
        if (*p == '\0') break;
        if (*p != ',') return fail(error, "a channel does not end at a comma or the end");
        p++;
    }
    *count = n;
    return true;
}

bool output_config(mc_config_t *cfg, uint8_t jumpers, const char *spec, const uint8_t uid[4],
                   const char **error)
{
    if (jumpers > 3u) return fail(error, "the jumpers give more than 3");
    mc_channel_t channels[OUTPUT_MAX_CHANNELS];
    uint8_t count = 0;
    if (!output_parse_channels(spec, channels, &count, error)) return false;
    memset(cfg, 0, sizeof(*cfg));
    cfg->address = (uint8_t)(OUTPUT_ADDRESS + jumpers);
    cfg->model = OUTPUT_MODEL;
    cfg->hw_rev = OUTPUT_HW_REV;
    cfg->fw[0] = OUTPUT_FW_MAJOR;
    cfg->fw[1] = OUTPUT_FW_MINOR;
    cfg->fw[2] = OUTPUT_FW_PATCH;
    memcpy(cfg->uid, uid, 4);
    cfg->channel_count = count;
    memcpy(cfg->channels, channels, sizeof(channels[0]) * count);
    return true;
}

bool output_senses_supply(const mc_config_t *cfg)
{
    for (uint8_t i = 0; i < cfg->channel_count; i++) {
        if (cfg->channels[i].flags & MC_CH_SENSES_SUPPLY) return true;
    }
    return false;
}

/* ---- The I2C target
 * ------------------------------------------------------------------------- */

void output_i2c_init(output_i2c_t *t, mc_module_t *core)
{
    t->core = core;
    t->state = 0;
}

uint8_t output_i2c_event(output_i2c_t *t, output_i2c_event_t ev, uint8_t in, uint32_t now_ms)
{
    switch (ev) {
    case OUTPUT_I2C_RECEIVE:
        if (t->state != 1u) {
            if (t->state == 2u) mc_i2c_stop(t->core, now_ms);
            mc_i2c_start(t->core, false, now_ms);
            t->state = 1u;
        }
        mc_i2c_receive(t->core, in);
        return 0;
    case OUTPUT_I2C_REQUEST:
        if (t->state != 2u) {
            /* A start (or a repeated start after the pointer write): the write is
             * taken now. */
            mc_i2c_start(t->core, true, now_ms);
            t->state = 2u;
        }
        return mc_i2c_request(t->core);
    case OUTPUT_I2C_FINISH:
        if (t->state != 0u) mc_i2c_stop(t->core, now_ms);
        t->state = 0u;
        return 0;
    }
    return 0;
}

/* ---- The guard
 * ------------------------------------------------------------------------------
 */

static void guard_all_off(output_guard_t *g)
{
    /* Every pin the module has, fitted or not: an unused channel's pin stays low
     * too. */
    for (uint8_t i = 0; i < OUTPUT_MAX_CHANNELS; i++) g->drive(g->ctx, i, false);
    g->level = 0;
    g->timed = 0;
}

void output_guard_init(output_guard_t *g, const mc_config_t *cfg,
                       void (*drive)(void *ctx, uint8_t channel, bool on), void *ctx)
{
    memset(g, 0, sizeof(*g));
    g->ctx = ctx;
    g->drive = drive;
    g->count = cfg->channel_count > OUTPUT_MAX_CHANNELS ? (uint8_t)OUTPUT_MAX_CHANNELS
                                                        : cfg->channel_count;
    for (uint8_t i = 0; i < g->count; i++) {
        g->limit_ms[i] = (uint32_t)cfg->channels[i].max_on_s * 1000u + OUTPUT_GUARD_SLACK_MS;
    }
    guard_all_off(g);
}

void output_guard_set(output_guard_t *g, uint8_t channel, bool on)
{
    if (channel >= g->count) return;
    uint8_t bit = (uint8_t)(1u << channel);
    if (g->tripped) on = false;
    g->drive(g->ctx, channel, on);
    if (on) {
        if (!(g->level & bit)) g->timed = (uint8_t)(g->timed & ~bit); /* timed at the next check */
        g->level = (uint8_t)(g->level | bit);
    } else {
        g->level = (uint8_t)(g->level & ~bit);
        g->timed = (uint8_t)(g->timed & ~bit);
    }
}

bool output_guard_check(output_guard_t *g, uint32_t now_ms)
{
    if (g->tripped) {
        guard_all_off(g);
        return false;
    }
    for (uint8_t i = 0; i < g->count; i++) {
        uint8_t bit = (uint8_t)(1u << i);
        if (!(g->level & bit)) continue;
        if (!(g->timed & bit)) {
            g->since[i] = now_ms;
            g->timed = (uint8_t)(g->timed | bit);
        } else if ((uint32_t)(now_ms - g->since[i]) > g->limit_ms[i]) {
            g->tripped = true;
        }
    }
    if (g->tripped) {
        guard_all_off(g);
        return false;
    }
    return true;
}

uint8_t output_guard_levels(const output_guard_t *g)
{
    return g->level;
}

bool output_guard_tripped(const output_guard_t *g)
{
    return g->tripped;
}

/* ---- The watchdog's policy
 * ------------------------------------------------------------------ */

bool output_watchdog_feed(bool config_ok, const output_guard_t *g, uint32_t last_tick_ms,
                          uint32_t now_ms)
{
    if (!config_ok || g->tripped) return false;
    return (uint32_t)(now_ms - last_tick_ms) <= OUTPUT_TICK_LATE_MS;
}

/* ---- The supply sense
 * ----------------------------------------------------------------------- */

void output_supply_init(output_supply_t *s)
{
    memset(s, 0, sizeof(*s));
}

uint32_t output_supply_mv(uint16_t raw)
{
    uint64_t at_pin = (uint64_t)(raw & 0x0FFFu) * OUTPUT_ADC_FULL_MV; /* x 4095 */
    uint64_t mv = at_pin * (OUTPUT_SENSE_TOP_OHM + OUTPUT_SENSE_BOTTOM_OHM) /
                  ((uint64_t)OUTPUT_SENSE_BOTTOM_OHM * 4095u);
    return (uint32_t)mv;
}

bool output_supply_update(output_supply_t *s, uint16_t raw)
{
    uint32_t mv = output_supply_mv(raw);
    if (!s->primed) {
        s->filtered_mv = mv;
        s->primed = true;
    } else {
        /* An eighth of the new reading: a relay's switching spike does not flip it.
         */
        s->filtered_mv = (s->filtered_mv * 7u + mv) / 8u;
    }
    if (s->ok) {
        if (s->filtered_mv < OUTPUT_SUPPLY_OFF_MV) s->ok = false;
    } else if (s->filtered_mv >= OUTPUT_SUPPLY_ON_MV) {
        s->ok = true;
    }
    return s->ok;
}

/* ---- The status LED
 * ------------------------------------------------------------------------- */

bool output_led(bool fault, bool locating, uint32_t now_ms)
{
    if (fault) return (now_ms / OUTPUT_FAULT_MS) % 2u == 0u;
    if (locating) return (now_ms / OUTPUT_LOCATE_MS) % 2u == 0u;
    return false;
}
