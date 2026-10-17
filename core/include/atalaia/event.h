/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Game events: the single source of truth for scores, replays and GM alerts.
 * See the "Event model" section of the design specification.
 */
#ifndef ATALAIA_EVENT_H
#define ATALAIA_EVENT_H

#include <stdbool.h>
#include <stdint.h>

/* ATALAIA_EVENT_TYPE_MAX and atalaia_prio_t come from the protocol schema. */
#include "atalaia/protocol.h"

/* Team and squad ids are one byte on the wire. 0 means "none". */
#define ATALAIA_TEAM_NONE  0u
#define ATALAIA_SQUAD_NONE 0u
#define ATALAIA_TEAM_MAX   250u

typedef struct {
    uint16_t node;     /* source node short id within the game */
    uint16_t seq;      /* per-node sequence number; (node, seq) is unique */
    uint32_t t_ms;     /* game time in milliseconds since game start */
    uint8_t team;      /* ATALAIA_TEAM_NONE if not team-specific */
    uint8_t squad;     /* ATALAIA_SQUAD_NONE if not squad-specific */
    atalaia_prio_t prio;
    char type[ATALAIA_EVENT_TYPE_MAX]; /* e.g. "zone.captured" */
} atalaia_event_t;

/*
 * Fills an event with the given header fields and type.
 * Returns false (and leaves the event zeroed) if the type is empty,
 * too long, or the team id is out of range.
 */
bool atalaia_event_init(atalaia_event_t *ev, uint16_t node, uint16_t seq,
                        uint32_t t_ms, const char *type, uint8_t team,
                        uint8_t squad, atalaia_prio_t prio);

/* True if both events have the same (node, seq) identity. */
bool atalaia_event_same_id(const atalaia_event_t *a, const atalaia_event_t *b);

/* Orders events by (t_ms, node, seq). Returns <0, 0 or >0 like strcmp. */
int atalaia_event_compare(const atalaia_event_t *a, const atalaia_event_t *b);

/* Human-readable priority name: "telemetry", "normal" or "critical". */
const char *atalaia_prio_name(atalaia_prio_t prio);

#endif /* ATALAIA_EVENT_H */
