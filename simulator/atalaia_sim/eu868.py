# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""EU868 game channels: the sub-bands, their limits and the candidate list.

The Python side of the table in core/src/duty_cycle.c (RFC 0001 section 8
and Amendment 3). Figures from ERC Recommendation 70-03 Annex 1 (edition
of February 2025, bands h1.5, h1.6, h1.7 and h1.9) and ETSI EN 300 220-2
V3.2.1 Table B.1:

    868.0-868.6   MHz   25 mW ERP    1% duty cycle      (this project: g)
    868.7-869.2   MHz   25 mW ERP    0.1% duty cycle    (g1)
    869.4-869.65  MHz   500 mW ERP   10% duty cycle     (g2; "g3" in the older ERC lettering)
    869.7-870.0   MHz   25 mW ERP    1% duty cycle      (g3)

A game channel is 125 kHz wide (SF7/BW125) and the whole channel must fit
in one sub-band: centre - 62.5 kHz and centre + 62.5 kHz both inside it.

Since RFC 0001 Amendment 12 the table lives in regions.py with the other
regions (AS923 as Taiwan uses it); this module keeps the EU868 names.
"""

from __future__ import annotations

from typing import Optional

from . import regions
from .regions import HOUR_MS, SubBand, airtime_ms  # noqa: F401  (re-exported)

REGION = regions.EU868
LORA_BW_HZ = REGION.bw_hz
DEFAULT_CHANNEL_HZ = REGION.default_channel_hz

SUB_BANDS = REGION.sub_bands

# LoRaWAN's three default channels (LoRa Alliance RP002-1.0.4, Table 6): every
# LoRaWAN device in Europe joins on them, so they are often busy.
LORAWAN_DEFAULTS = REGION.busy_hz

# The channels a GM can pick from (decision CH1): non-overlapping or 100 kHz
# apart within each sub-band, at least 12.5 kHz from the sub-band's edges.
CANDIDATES = REGION.candidates


def band_of(centre_hz: int, bw_hz: int = LORA_BW_HZ) -> Optional[SubBand]:
    """The sub-band that holds the whole channel, or None (edges included)."""
    return REGION.band_of(centre_hz, bw_hz)


def channel_ok(centre_hz: int) -> bool:
    """True if a 125 kHz game channel centred here fits inside one EU868 sub-band."""
    return REGION.channel_ok(centre_hz)


def usable_for_games(centre_hz: int) -> bool:
    """Legal and with enough airtime for a game: not in the 0.1% sub-band (decision CH2)."""
    return REGION.usable_for_games(centre_hz)


def scan_candidates() -> list[int]:
    """The candidates a scan measures and a random pick draws from (no 0.1% channels)."""
    return REGION.scan_candidates()


def describe(centre_hz: int) -> dict:
    """A channel and its limits, for the API and the console."""
    return REGION.describe(centre_hz)


def tx_power_dbm(erp_dbm: int, fem_gain_db: int, antenna_gain_dbi: int) -> int:
    """SX1262 conducted power for an ERP limit (radio_power.h, decision C2), clamped to -9..22."""
    return regions.tx_power_dbm(erp_dbm, fem_gain_db, antenna_gain_dbi, regions.ERP)
