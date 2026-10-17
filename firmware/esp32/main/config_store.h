/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Configuration store: NVS-backed key-value storage for node settings.
 * On Linux tests this uses a simple in-memory store.
 */
#ifndef ATALAIA_CONFIG_STORE_H
#define ATALAIA_CONFIG_STORE_H

#include <stdbool.h>
#include <stdint.h>

/* Initialise the config store. Returns 0 on success. */
int config_store_init(void);

/* Check if initial setup has been completed. */
bool config_store_is_configured(void);

/* Mark setup as completed. */
void config_store_set_configured(bool configured);

/* String config getters/setters. Returns false if key not found. */
bool config_store_get_str(const char *key, char *out, int out_sz);
void config_store_set_str(const char *key, const char *value);

/* Integer config getters/setters. Returns default_val if key not found. */
uint32_t config_store_get_u32(const char *key, uint32_t default_val);
void config_store_set_u32(const char *key, uint32_t value);

/* Reset all configuration to defaults. */
void config_store_reset(void);

#endif /* ATALAIA_CONFIG_STORE_H */
