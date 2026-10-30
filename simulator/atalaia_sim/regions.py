# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The radio regions a field can be in: one table, as core/src/duty_cycle.c.

RFC 0001 Amendment 12 (proposed), decisions RF-AS923-1 to RF-AS923-12 in
docs/review/decisions-to-review.md. A region gives the LoRa settings every
game packet uses (spreading factor and bandwidth: the channel's width), its
sub-bands with their power limit and airtime budget, the default channel
and the channels a GM can pick from. Everything that checks a channel (the
controller, the modem, the boxes, the join codecs, the simulator's radio)
asks the region, never an if/else on a frequency.

EU868, ERC/REC 70-03 Annex 1 (February 2025: h1.5, h1.6, h1.7, h1.9) and
ETSI EN 300 220-2 V3.2.1 Table B.1; limits in ERP; SF7 at 125 kHz:

    868.0-868.6   MHz   25 mW ERP    1% duty cycle      (this project: g)
    868.7-869.2   MHz   25 mW ERP    0.1% duty cycle    (g1)
    869.4-869.65  MHz   500 mW ERP   10% duty cycle     (g2)
    869.7-870.0   MHz   25 mW ERP    1% duty cycle      (g3)

AS923-TW, Taiwan, NCC LP0002 (edition of 2020-07-01) 5.8.1, "other IoT
devices", 920-925 MHz. A device that neither hops (at least 10 channels,
0.4 s each) nor uses a 6 dB bandwidth of 500 kHz or more falls under 5.8.2:
50 mV/m at 3 m, about -1 dBm EIRP, less than the Heltec V4's front-end
module puts out at its lowest setting. So the region uses LoRa at 500 kHz
("digital modulation", 5.8.1.5 (2): at most 8 dBm in any 3 kHz), with SF9,
which keeps SF7/125 kHz's symbol time (1.024 ms) and nearly its sensitivity.
Power: at most 0.5 W peak output outdoors (5.8.1.2 (1) (B); 1 W indoors or
in a closed site with controlled access is not used), at the antenna port,
less the antenna gain above 6 dBi. LP0002 sets no duty cycle and no
listen-before-talk for these devices; the 10% budget is this project's own
(decision RF-AS923-4). The LoRa Alliance's RP002-1.0.4 lists Taiwan under
AS923-1 (default channels 923.2 and 923.4 MHz), which the default here
avoids, with Meshtastic's TW default (923.875 MHz).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

HOUR_MS = 3_600_000

ERP, EIRP, CONDUCTED = "erp", "eirp", "conducted"


@dataclass(frozen=True)
class SubBand:
    name: str          # this project's label (RFC 0001 section 8; "tw" for 920-925 MHz)
    ref: str           # the regulation's band (ERC/REC 70-03 Annex 1, NCC LP0002)
    lo_hz: int
    hi_hz: int
    duty: float        # airtime budget as a fraction of the hour
    limit_dbm: int     # power limit, measured as limit_ref says
    limit_mw: int
    limit_ref: str = ERP       # ERP, EIRP or CONDUCTED (at the antenna port)
    free_gain_dbi: int = 0     # CONDUCTED: antenna gain allowed before it lowers the power
    full_power: bool = False   # the region's highest power: the one a scan prefers

    @property
    def duty_pct(self) -> float:
        return self.duty * 100

    @property
    def budget_ms_per_hour(self) -> float:
        return self.duty * HOUR_MS

    # The EU868 names, kept for the code and the API that used them.
    @property
    def erc(self) -> str:
        return self.ref

    @property
    def erp_dbm(self) -> int:
        return self.limit_dbm

    @property
    def erp_mw(self) -> int:
        return self.limit_mw


@dataclass(frozen=True)
class Region:
    code: str             # "eu868", "as923-tw": the config's, the API's and the console's name
    number: int           # the join payload's key 18 (0: EU868, the key left out)
    name: str
    sf: int
    bw_hz: int
    default_channel_hz: int
    sub_bands: tuple[SubBand, ...]
    candidates: tuple[int, ...]
    busy_hz: frozenset = field(default_factory=frozenset)  # channels others crowd (LoRaWAN, Meshtastic)
    max_dwell_ms: int = 0  # the longest single transmission (0: no rule)

    @property
    def lo_hz(self) -> int:
        return min(b.lo_hz for b in self.sub_bands)

    @property
    def hi_hz(self) -> int:
        return max(b.hi_hz for b in self.sub_bands)

    def band_of(self, centre_hz: int, bw_hz: Optional[int] = None) -> Optional[SubBand]:
        """The sub-band that holds the whole channel, or None (edges included)."""
        if isinstance(centre_hz, bool) or not isinstance(centre_hz, int):
            return None
        bw = self.bw_hz if bw_hz is None else bw_hz
        lo, hi = centre_hz - bw // 2, centre_hz + bw // 2
        for band in self.sub_bands:
            if band.lo_hz <= lo and hi <= band.hi_hz:
                return band
        return None

    def channel_ok(self, centre_hz: int) -> bool:
        """True if a game channel centred here fits inside one of the region's sub-bands."""
        return self.band_of(centre_hz) is not None

    def usable_for_games(self, centre_hz: int) -> bool:
        """Legal and with enough airtime for a game: not in a 0.1% sub-band (decision CH2)."""
        band = self.band_of(centre_hz)
        return band is not None and band.duty >= 0.01

    def scan_candidates(self) -> list[int]:
        """The candidates a scan measures and a random pick draws from."""
        return [hz for hz in self.candidates if self.usable_for_games(hz)]

    def overlaps_busy(self, centre_hz: int) -> bool:
        half = self.bw_hz // 2
        return any(centre_hz - half < hz < centre_hz + half or hz == centre_hz for hz in self.busy_hz)

    def describe(self, centre_hz: int) -> dict:
        """A channel and its limits, for the API and the console."""
        band = self.band_of(centre_hz)
        if band is None:
            raise ValueError(f"{centre_hz} Hz is not a legal {self.code} game channel")
        notes = []
        if centre_hz == self.default_channel_hz:
            notes.append("default")
        if self.overlaps_busy(centre_hz):
            notes.append("lorawan_default")
        if band.duty < 0.01:
            notes.append("low_airtime")
        out = {"channel_hz": centre_hz, "band": band.name, "erc_band": band.ref,
               "band_lo_hz": band.lo_hz, "band_hi_hz": band.hi_hz,
               "duty_pct": round(band.duty_pct, 3)}
        if band.limit_ref == ERP:  # the EU868 names, as before regions
            out.update(erp_mw=band.limit_mw, erp_dbm=band.limit_dbm)
        out.update(limit_mw=band.limit_mw, limit_dbm=band.limit_dbm, limit_ref=band.limit_ref,
                   full_power=band.full_power, usable=self.usable_for_games(centre_hz),
                   region=self.code, bw_khz=self.bw_hz // 1000, sf=self.sf, notes=notes)
        return out

    def airtime_ms(self, packet_bytes: int) -> float:
        """Time on air of a whole packet at the region's SF and bandwidth."""
        return airtime_ms(packet_bytes, self.sf, self.bw_hz)

    def public(self) -> dict:
        """The region for the API and the console."""
        return {"code": self.code, "name": self.name, "sf": self.sf, "bw_khz": self.bw_hz // 1000,
                "lo_hz": self.lo_hz, "hi_hz": self.hi_hz, "default_channel_hz": self.default_channel_hz,
                "max_dwell_ms": self.max_dwell_ms,
                "sub_bands": [{"name": b.name, "ref": b.ref, "lo_hz": b.lo_hz, "hi_hz": b.hi_hz,
                               "duty_pct": round(b.duty_pct, 3), "limit_mw": b.limit_mw,
                               "limit_dbm": b.limit_dbm, "limit_ref": b.limit_ref}
                              for b in self.sub_bands]}


EU868 = Region(
    code="eu868", number=0, name="EU868 (Europe, 868 MHz)", sf=7, bw_hz=125_000,
    default_channel_hz=869_525_000,
    sub_bands=(
        SubBand("g", "h1.5", 868_000_000, 868_600_000, 0.01, 14, 25),
        SubBand("g1", "h1.6", 868_700_000, 869_200_000, 0.001, 14, 25),
        SubBand("g2", "h1.7", 869_400_000, 869_650_000, 0.10, 27, 500, full_power=True),
        SubBand("g3", "h1.9", 869_700_000, 870_000_000, 0.01, 14, 25),
    ),
    # Decision CH1: non-overlapping or 100 kHz apart within each sub-band, at least 12.5 kHz
    # from the sub-band's edges.
    candidates=(
        868_100_000, 868_200_000, 868_300_000, 868_400_000, 868_500_000,   # g, 1%, 25 mW
        868_800_000, 868_950_000, 869_100_000,                             # g1, 0.1%, 25 mW
        869_475_000, 869_525_000, 869_575_000,                             # g2, 10%, 500 mW
        869_775_000, 869_850_000, 869_925_000,                             # g3, 1%, 25 mW
    ),
    # LoRaWAN's three default channels (RP002-1.0.4, Table 6): every LoRaWAN device in
    # Europe joins on them, so they are often busy.
    busy_hz=frozenset({868_100_000, 868_300_000, 868_500_000}),
)

AS923_TW = Region(
    code="as923-tw", number=1, name="AS923 Taiwan (920-925 MHz)", sf=9, bw_hz=500_000,
    default_channel_hz=921_500_000,
    sub_bands=(
        SubBand("tw", "LP0002 5.8.1", 920_000_000, 925_000_000, 0.10, 27, 500,
                limit_ref=CONDUCTED, free_gain_dbi=6, full_power=True),
    ),
    # 500 kHz apart, the whole channel inside 920-925 MHz with 250 kHz to spare at the edges
    # (decision RF-AS923-5).
    candidates=(
        920_500_000, 921_000_000, 921_500_000, 922_000_000, 922_500_000,
        923_000_000, 923_500_000, 924_000_000, 924_500_000,
    ),
    # LoRaWAN AS923-1's two default channels (RP002-1.0.4) and Meshtastic's TW default
    # (LongFast, 250 kHz).
    busy_hz=frozenset({923_200_000, 923_400_000, 923_875_000}),
)

REGIONS = (EU868, AS923_TW)
BY_CODE = {r.code: r for r in REGIONS}
BY_NUMBER = {r.number: r for r in REGIONS}
DEFAULT = EU868


def get(code: object) -> Region:
    """The region named code; raises ValueError for anything else."""
    if not isinstance(code, str) or code not in BY_CODE:
        raise ValueError(f"region: one of {', '.join(BY_CODE)}")
    return BY_CODE[code]


def tx_power_dbm(limit_dbm: int, fem_gain_db: int, antenna_gain_dbi: int, limit_ref: str = ERP,
                 free_gain_dbi: int = 0) -> int:
    """SX1262 conducted power for a limit (radio_power.h, decision C2), clamped to -9..22.

    ERP: + 2.15 dB (dipole), less the antenna and FEM gains. EIRP: less both gains.
    CONDUCTED (at the antenna port): less the FEM gain and the antenna gain above
    free_gain_dbi. Truncated toward zero, as C does. legal_tx_power_dbm says whether
    the result keeps the limit at all.
    """
    return max(-9, min(22, _conducted(limit_dbm, fem_gain_db, antenna_gain_dbi, limit_ref, free_gain_dbi)))


def legal_tx_power_dbm(band: SubBand, fem_gain_db: int, antenna_gain_dbi: int) -> Optional[int]:
    """The SX1262 power for a sub-band, or None when even its lowest setting (-9 dBm) would
    exceed the limit with these gains: such a channel may not be used (fail closed)."""
    raw = _conducted(band.limit_dbm, fem_gain_db, antenna_gain_dbi, band.limit_ref, band.free_gain_dbi)
    if raw < -9:
        return None
    return min(22, raw)


def _conducted(limit_dbm: int, fem: int, ant: int, ref: str, free: int) -> int:
    if ref == ERP:
        x100 = limit_dbm * 100 + 215 - fem * 100 - ant * 100
    elif ref == EIRP:
        x100 = limit_dbm * 100 - fem * 100 - ant * 100
    elif ref == CONDUCTED:
        x100 = limit_dbm * 100 - fem * 100 - max(0, ant - free) * 100
    else:
        raise ValueError(f"limit_ref {ref!r}")
    return x100 // 100  # round down, also below zero: the conducted power is never rounded up


def airtime_ms(packet_bytes: int, sf: int = 7, bw_hz: int = 125_000) -> float:
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
