/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio settings a listen-before-talk bench run uses (docs/runbooks/lbt-bench-gate.md): the
 * build's own region, or the AS923-TW proxy: AS923-TW's modulation (SF9, 500 kHz) and CAD
 * settings (detection peak 23, the value under test) on a legal EU868 channel, 868.3 MHz inside
 * sub-band g (868.0-868.6 MHz: 1 % duty, 25 mW ERP), because a bench in Europe may not transmit
 * on 921.5 MHz. CAD depends on SF and bandwidth, not on the carrier. Plain C, host-tested.
 */
#ifndef ATALAIA_LBT_PROFILE_H
#define ATALAIA_LBT_PROFILE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/duty_cycle.h"
#include "hal/hal_radio.h"

#define LBT_PROXY_FREQ_HZ        868300000u /* centre of the 500 kHz channel 868.05-868.55 MHz */
#define LBT_PROXY_FRAMES_DEFAULT 100u
/* Conducted power by default: the boards are metres apart. The legal limit of sub-band g is
 * 0 dBm conducted with the Heltec V4's FEM (14 dB) and a 2 dBi antenna (25 mW ERP). */
#define LBT_PROXY_POWER_DEFAULT_DBM (-9)
/* The transmitter stops when this share of the budget is left (counting earlier runs). */
#define LBT_GUARD_PERCENT_LEFT 70

typedef struct {
    const char *name;     /* "build" (the image's own region) or "as923-eu868" */
    const char *mod_from; /* the region whose SF, bandwidth and CAD settings are used */
    uint8_t sf;
    uint32_t bw_hz;
    uint32_t freq_hz;
    atalaia_cad_params_t cad;
    bool proxy;
    uint8_t eu868_band;  /* the sub-band whose limits apply */
    uint32_t duty_ppm;   /* the sub-band's duty limit: 10000 = 1 % */
    int8_t limit_dbm;    /* the sub-band's limit as the regulation states it (ERP or conducted) */
    int8_t tx_power_dbm; /* proxy: conducted power asked of the radio; build: 127 (the HAL's own) */
} lbt_profile_t;

/* The build's region: its default channel, SF, bandwidth, CAD and the channel's sub-band. */
void lbt_profile_build(lbt_profile_t *p, atalaia_region_t region);

/*
 * The AS923-TW proxy. det_peak / det_min: -1 keeps the AS923-TW table's value (29 / 10), else
 * 10..40 / 1..30 (a sweep). power_dbm: INT8_MIN for LBT_PROXY_POWER_DEFAULT_DBM, else -9..22
 * (the HAL still refuses one above the sub-band's legal power). False, p untouched, when a value
 * is out of range or the channel is not legal (lbt_profile_channel_ok).
 */
bool lbt_profile_as923_eu868(lbt_profile_t *p, int det_peak, int det_min, int power_dbm);

/*
 * The proxy's safety assertion: the whole channel (centre +- bw/2) is inside the one EU868
 * sub-band the profile names and touches no AS923-TW frequency (920-925 MHz). Always true for a
 * non-proxy profile.
 */
bool lbt_profile_channel_ok(const lbt_profile_t *p);

uint32_t lbt_profile_airtime_us(const lbt_profile_t *p, size_t len);
/* The sub-band's budget per rolling hour, in ms (duty_ppm x 3600 us). */
uint32_t lbt_profile_budget_ms(const lbt_profile_t *p);
/* The transmitter's self-stop: it stops when the budget left falls under this (70 % of it). */
uint32_t lbt_profile_guard_ms(const lbt_profile_t *p);
/* The most frames a run may ask for: what the guard lets through at the longest bench frame
 * (30 % of the budget), at most LBT_TX_FRAMES_MAX. */
uint32_t lbt_profile_frames_max(const lbt_profile_t *p);
uint32_t lbt_profile_frames_default(const lbt_profile_t *p);

/* The HAL's form of a proxy profile. */
void lbt_profile_to_hal(const lbt_profile_t *p, hal_radio_profile_t *out);

#endif /* ATALAIA_LBT_PROFILE_H */
