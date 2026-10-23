# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's radio region (RFC 0001 Amendment 12, decisions RF-AS923-1 to RF-AS923-12).

A field is in one region: EU868 (868 MHz) or AS923-TW (Taiwan, 920-925 MHz),
from the table in atalaia_sim/regions.py. ``[radio] region`` in the config is
the default until the GM picks one in the console (GET and PUT /api/v1/radio,
PUT /api/v1/radio/region); the store's ``radio.region`` keeps the choice, as
``radio.channel_hz`` keeps the channel. The region decides which channels the
GM may pick and scan, the limits shown, and join key 18, so every box learns
the field's region with its game; a box whose firmware is built for another
region refuses the join, and the USB modem (IDENT ``region``) refuses the
channels of every other region.

The region changes only with no game on this controller and no scan, like the
channel (decision CH8); changing it puts the field on the new region's default
channel, unconfirmed, and forgets the last scan (its channels were the old
region's).
"""

from __future__ import annotations

from typing import Any, Optional

from atalaia_sim import regions
from atalaia_sim.regions import Region

STORE_KEY = "radio.region"


def stored(store: Any) -> Optional[Region]:
    """The GM's choice kept in the store, or None (none made, or not a known region)."""
    code = store.get_setting(STORE_KEY)
    return regions.BY_CODE.get(code) if code else None


def field_region(store: Any, cfg: Any) -> Region:
    """The region new games use: the GM's choice, else ``[radio] region``."""
    return stored(store) or regions.get(cfg.region)


def modem_region(ident: Optional[dict[str, Any]]) -> Optional[str]:
    """The region the modem's firmware is built for: IDENT's ``region``; a modem from before
    regions (no key) is an EU868 build. None without an IDENT."""
    if ident is None:
        return None
    code = ident.get("region", regions.EU868.code)
    return code if isinstance(code, str) else None


def public(region: Region, ident: Optional[dict[str, Any]], source: str) -> dict[str, Any]:
    """The region part of GET /api/v1/radio."""
    modem = modem_region(ident)
    return {"region": region.public(), "region_source": source,
            "regions": [r.public() for r in regions.REGIONS],
            "modem_region": modem, "region_mismatch": modem is not None and modem != region.code}
