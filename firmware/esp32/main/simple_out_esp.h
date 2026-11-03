/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The simple outputs of an ESP32 build (CONFIG_ATALAIA_SIMPLE_OUT, _OUT2; simple_out.h): their
 * RMT bursts, and their settings in the box's NVS (config_store). A build without them has
 * none: simple_out_esp_init adds nothing.
 */
#ifndef ATALAIA_SIMPLE_OUT_ESP_H
#define ATALAIA_SIMPLE_OUT_ESP_H

#include <stdbool.h>

#include "outputs.h"

/* Adds the build's simple outputs to o, each with its RMT channel and its stored settings, and
 * returns how many it added (0 without CONFIG_ATALAIA_SIMPLE_OUT, or when a pin is refused). */
int simple_out_esp_init(outputs_t *o);

/* outputs_ops_t's save: a channel's settings into NVS (keys out<n>_en, out<n>_fn, out<n>_max). */
bool simple_out_esp_save(void *ctx, int index, const out_settings_t *s);

#endif /* ATALAIA_SIMPLE_OUT_ESP_H */
