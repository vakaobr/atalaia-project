/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field operations interface. The controller provides these callbacks so
 * that its node script can query and command other nodes in the field.
 * Regular (non-controller) nodes leave field_ops NULL in the config, and
 * the script API exposes only a read-only state.field{} table.
 */
#ifndef ATALAIA_FIELD_OPS_H
#define ATALAIA_FIELD_OPS_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    /* Returns a JSON array of node descriptors matching the optional role
     * filter (NULL = all nodes). The caller frees the returned string. */
    char *(*nodes)(void *user, const char *role);
    /* Returns the team name that owns the given node, or NULL. The string
     * belongs to the host and must stay valid until the next owner() call;
     * the core copies it before calling again. */
    const char *(*owner)(void *user, uint16_t node_id);
    /* Sends a command to a specific node. Returns true on success. */
    bool (*send)(void *user, uint16_t node_id, const char *cmd, const char *params_json);
} atalaia_field_ops_t;

#endif /* ATALAIA_FIELD_OPS_H */
