/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio region this firmware is built for (Kconfig ATALAIA_RADIO_REGION,
 * RFC 0001 Amendment 12, decision RF-AS923-2): EU868 or AS923-TW. The region's
 * table (sub-bands, limits, SF and bandwidth, default channel) is the core's
 * (atalaia_region_info() in core/src/duty_cycle.c). A Field Box, the USB modem
 * and the I/O pod use only their build's region: a join, a CONFIGURE or a
 * MEASURE on a channel of another region is refused, so a board whose antenna
 * and labelling are for one band never transmits in another.
 *
 * Host builds have no sdkconfig: EU868, and the code that tests AS923-TW sets
 * the region where it is a variable (radio_limits_set_region, modem_t.region,
 * box_game_t.region, hal_stub_radio_region).
 */
#ifndef ATALAIA_RADIO_REGION_H
#define ATALAIA_RADIO_REGION_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/duty_cycle.h"

#if defined(CONFIG_ATALAIA_RADIO_REGION_AS923_TW)
#define RADIO_REGION ATALAIA_REGION_AS923_TW
#else
#define RADIO_REGION ATALAIA_REGION_EU868
#endif

/* The region's default channel: where the radio listens at boot and an unadopted box pairs. */
static inline uint32_t radio_region_default_channel_hz(atalaia_region_t region)
{
    const atalaia_region_info_t *r = atalaia_region_info(region);
    return r != NULL ? r->default_channel_hz : 869525000u;
}

/* The region's name, for logs and IDENT ("eu868", "as923-tw"). */
static inline const char *radio_region_code(atalaia_region_t region)
{
    const atalaia_region_info_t *r = atalaia_region_info(region);
    return r != NULL ? r->code : "?";
}

#endif /* ATALAIA_RADIO_REGION_H */
