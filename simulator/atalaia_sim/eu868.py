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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

LORA_BW_HZ = 125_000
DEFAULT_CHANNEL_HZ = 869_525_000
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class SubBand:
    name: str          # this project's label (RFC 0001 section 8)
    erc: str           # ERC/REC 70-03 Annex 1 band
    lo_hz: int
    hi_hz: int
    duty: float        # duty-cycle limit as a fraction of the hour
    erp_dbm: int       # ERP limit
    erp_mw: int

    @property
    def duty_pct(self) -> float:
        return self.duty * 100

    @property
    def budget_ms_per_hour(self) -> float:
        return self.duty * HOUR_MS

    @property
    def full_power(self) -> bool:
        return self.erp_mw >= 500


SUB_BANDS = (
    SubBand("g", "h1.5", 868_000_000, 868_600_000, 0.01, 14, 25),
    SubBand("g1", "h1.6", 868_700_000, 869_200_000, 0.001, 14, 25),
    SubBand("g2", "h1.7", 869_400_000, 869_650_000, 0.10, 27, 500),
    SubBand("g3", "h1.9", 869_700_000, 870_000_000, 0.01, 14, 25),
)

# LoRaWAN's three default channels (LoRa Alliance RP002-1.0.4, Table 6): every
# LoRaWAN device in Europe joins on them, so they are often busy.
LORAWAN_DEFAULTS = frozenset({868_100_000, 868_300_000, 868_500_000})

# The channels a GM can pick from (decision CH1): non-overlapping or 100 kHz
# apart within each sub-band, at least 12.5 kHz from the sub-band's edges.
CANDIDATES = (
    868_100_000, 868_200_000, 868_300_000, 868_400_000, 868_500_000,   # g, 1%, 25 mW
    868_800_000, 868_950_000, 869_100_000,                             # g1, 0.1%, 25 mW
    869_475_000, 869_525_000, 869_575_000,                             # g2, 10%, 500 mW
    869_775_000, 869_850_000, 869_925_000,                             # g3, 1%, 25 mW
)


def band_of(centre_hz: int, bw_hz: int = LORA_BW_HZ) -> Optional[SubBand]:
    """The sub-band that holds the whole channel, or None (edges included)."""
    if isinstance(centre_hz, bool) or not isinstance(centre_hz, int):
        return None
    lo, hi = centre_hz - bw_hz // 2, centre_hz + bw_hz // 2
    for band in SUB_BANDS:
        if band.lo_hz <= lo and hi <= band.hi_hz:
            return band
    return None


def channel_ok(centre_hz: int) -> bool:
    """True if a 125 kHz game channel centred here fits inside one EU868 sub-band."""
    return band_of(centre_hz) is not None


def usable_for_games(centre_hz: int) -> bool:
    """Legal and with enough airtime for a game: not in the 0.1% sub-band (decision CH2)."""
    band = band_of(centre_hz)
    return band is not None and band.duty >= 0.01


def scan_candidates() -> list[int]:
    """The candidates a scan measures and a random pick draws from (no 0.1% channels)."""
    return [hz for hz in CANDIDATES if usable_for_games(hz)]


def describe(centre_hz: int) -> dict:
    """A channel and its limits, for the API and the console."""
    band = band_of(centre_hz)
    if band is None:
        raise ValueError(f"{centre_hz} Hz is not a legal EU868 game channel")
    notes = []
    if centre_hz == DEFAULT_CHANNEL_HZ:
        notes.append("default")
    if centre_hz in LORAWAN_DEFAULTS:
        notes.append("lorawan_default")
    if band.duty < 0.01:
        notes.append("low_airtime")
    return {"channel_hz": centre_hz, "band": band.name, "erc_band": band.erc,
            "band_lo_hz": band.lo_hz, "band_hi_hz": band.hi_hz,
            "duty_pct": round(band.duty_pct, 3), "erp_mw": band.erp_mw, "erp_dbm": band.erp_dbm,
            "full_power": band.full_power, "usable": usable_for_games(centre_hz), "notes": notes}


def tx_power_dbm(erp_dbm: int, fem_gain_db: int, antenna_gain_dbi: int) -> int:
    """SX1262 conducted power for an ERP limit (radio_power.h, decision C2), clamped to -9..22."""
    conducted_x100 = erp_dbm * 100 + 215 - fem_gain_db * 100 - antenna_gain_dbi * 100
    conducted = int(conducted_x100 / 100)  # truncation toward zero, as C does
    return max(-9, min(22, conducted))


def airtime_ms(packet_bytes: int, sf: int = 7, bw_hz: int = LORA_BW_HZ) -> float:
    """LoRa time on air (explicit header, CRC on, CR 4/5, 8-symbol preamble).

    The same formula as atalaia_airtime_us() in core/src/duty_cycle.c.
    """
    t_sym_us = (1 << sf) * 1_000_000 // bw_hz
    t_preamble_us = 1225 * t_sym_us // 100
    de = 1 if sf >= 11 else 0
    num = 8 * packet_bytes - 4 * sf + 28 + 16
    den = 4 * (sf - 2 * de)
    symbols = 8 if num <= 0 else 8 + -(-num // den) * 5
    return (t_preamble_us + symbols * t_sym_us) / 1000.0
