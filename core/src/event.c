/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "atalaia/event.h"

#include <string.h>

bool atalaia_event_init(atalaia_event_t *ev, uint16_t node, uint16_t seq,
                        uint32_t t_ms, const char *type, uint8_t team,
                        uint8_t squad, atalaia_prio_t prio)
{
    if (ev == NULL) {
        return false;
    }
    memset(ev, 0, sizeof(*ev));

    if (type == NULL || team > ATALAIA_TEAM_MAX) {
        return false;
    }
    size_t len = strlen(type);
    if (len == 0 || len >= ATALAIA_EVENT_TYPE_MAX) {
        return false;
    }

    ev->node = node;
    ev->seq = seq;
    ev->t_ms = t_ms;
    ev->team = team;
    ev->squad = squad;
    ev->prio = prio;
    memcpy(ev->type, type, len + 1);
    return true;
}

bool atalaia_event_same_id(const atalaia_event_t *a, const atalaia_event_t *b)
{
    return a->node == b->node && a->seq == b->seq;
}

int atalaia_event_compare(const atalaia_event_t *a, const atalaia_event_t *b)
{
    if (a->t_ms != b->t_ms) {
        return a->t_ms < b->t_ms ? -1 : 1;
    }
    if (a->node != b->node) {
        return a->node < b->node ? -1 : 1;
    }
    if (a->seq != b->seq) {
        return a->seq < b->seq ? -1 : 1;
    }
    return 0;
}

const char *atalaia_prio_name(atalaia_prio_t prio)
{
    switch (prio) {
    case ATALAIA_PRIO_TELEMETRY:
        return "telemetry";
    case ATALAIA_PRIO_NORMAL:
        return "normal";
    case ATALAIA_PRIO_CRITICAL:
        return "critical";
    }
    return "unknown";
}
