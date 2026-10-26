# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which addresses the check-in poster lists and the server certificate covers (decisions check-R8, check-R9).

The poster lists only configured *names* and addresses that are on an interface *now*. A configured
address that is on no interface (a DHCP lease that moved) is left out and warned about; a host name
cannot be checked against interfaces, so it stays. An IP literal is checked unless the controller
runs in a container (its interfaces are the container's own: the address the field reaches it at is
not on one of them, OT-10), where configured addresses are kept as given.

The rules, identical on the phone controller (app/lib/controller/field_addresses.dart) and shared as
cases in protocol/vectors/checkin.json ("poster_addresses"):

* the explicit list: the saved poster's urls (``PUT /api/v1/checkin/poster``), else ``[checkin] urls``;
  each filtered by the rule above (the saved poster is re-derived on every start, never kept as it
  was); if the saved poster keeps none, ``[checkin] urls`` is tried. If the explicit list keeps one or
  more, that is the poster (the GM's choice, never padded with others);
* otherwise the default: ``[api] tls_names`` (filtered), then the names and addresses found on this
  host now (``tls.link_names``), at most 3, each of at most 64 bytes;
* the certificate's names: the filtered ``tls_names``, the hosts of the explicit list that was kept,
  all the found names and addresses, localhost and 127.0.0.1: a superset of the poster's hosts. A
  dropped address is in neither.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import tls as tlsmod

log = logging.getLogger("atalaia.addresses")

_HOST_RE = re.compile(r"https://(\[[^\]]+\]|[^:/]+)(?::\d+)?")


def url_host(url: str) -> str:
    m = _HOST_RE.match(url)
    return m.group(1).strip("[]") if m else ""


def _ip(name: str):
    try:
        return ipaddress.ip_address(name.strip().strip("[]"))
    except ValueError:
        return None


def interface_addresses() -> list[str]:
    """The IP addresses on this host's interfaces now (Linux: SIOCGIFADDR per interface and
    /proc/net/if_inet6; elsewhere only what the host name and the route probes give)."""
    out: list[str] = []
    try:
        import fcntl  # noqa: PLC0415
        import struct  # noqa: PLC0415

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for _, name in socket.if_nameindex():
                try:
                    packed = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))
                    out.append(socket.inet_ntoa(packed[20:24]))
                except OSError:
                    continue
    except (ImportError, OSError, AttributeError):
        pass
    try:
        with open("/proc/net/if_inet6", encoding="ascii") as f:
            for line in f:
                out.append(str(ipaddress.IPv6Address(int(line.split()[0], 16))))
    except (OSError, ValueError, IndexError):
        pass
    return out


@dataclass
class Plan:
    default: list[str]            # https urls: tls_names, then what was found
    explicit: list[str]           # the GM's urls that survived (empty: none given, or none survived)
    poster: list[str]             # what the poster lists: explicit, else default
    san: list[str]                # the certificate's names (a superset of the poster's hosts)
    dropped: list[str] = field(default_factory=list)   # configured addresses left out (stale)


class FieldAddresses:
    """The addresses this host has now, and the rules above applied to them."""

    def __init__(self, *, tls_names: Iterable[str] = (), found: Iterable[str] = (),
                 interfaces: Iterable[str] = (), tls_port: int = 8443,
                 container: Optional[bool] = None) -> None:
        self.tls_names = [n.strip() for n in tls_names if n and n.strip()]
        self.found = [n for n in found if n]
        # What was found comes from the interfaces too (host name resolution, route probes).
        ips = [_ip(n) for n in list(interfaces) + self.found]
        self.interfaces = {i for i in ips if i is not None}
        self.tls_port = tls_port
        self.container = tlsmod.in_container() if container is None else container

    @classmethod
    def current(cls, tls_names: Iterable[str], tls_port: int, container: Optional[bool] = None,
                extra_interfaces: Iterable[str] = ()) -> "FieldAddresses":
        """This host now. Nothing is sent on the network. ``extra_interfaces``: addresses to count as
        on an interface (tests, whose configured addresses are not this machine's)."""
        return cls(tls_names=tls_names, found=tlsmod.local_names(()),
                   interfaces=[*interface_addresses(), *extra_interfaces], tls_port=tls_port, container=container)

    def current_host(self, host: str) -> bool:
        """A name always (it cannot be checked); an address if it is on an interface now, or if the
        controller is in a container, where that cannot be known."""
        ip = _ip(host)
        return ip is None or self.container or ip in self.interfaces

    def _url(self, name: str) -> str:
        host = f"[{name}]" if ":" in name else name
        return f"https://{host}:{self.tls_port}" if self.tls_port != 443 else f"https://{host}"

    def keep(self, urls: Iterable[str]) -> tuple[list[str], list[str]]:
        """(the urls whose host is current, at most 3; the ones left out)."""
        kept: list[str] = []
        dropped: list[str] = []
        for u in urls:
            if not isinstance(u, str):
                continue
            if self.current_host(url_host(u)):
                if u not in kept:
                    kept.append(u)
            elif u not in dropped:
                dropped.append(u)
        return kept[:3], dropped

    def plan(self, saved_urls: Iterable[str] = (), checkin_urls: Iterable[str] = ()) -> Plan:
        saved_kept, dropped = self.keep(saved_urls)
        config_kept, dropped2 = self.keep(checkin_urls)    # both, so every stale one is named
        dropped += [d for d in dropped2 if d not in dropped]
        explicit = saved_kept or config_kept
        names: list[str] = []
        for n in self.tls_names:
            if self.current_host(n):
                names.append(n)
            elif n not in dropped:
                dropped.append(n)
        default: list[str] = []
        for n in tlsmod.link_names(names, self.found, self.container):
            u = self._url(n)
            if u not in default and len(u) <= 64:
                default.append(u)
        default = default[:3]
        san: list[str] = []
        for n in names + [url_host(u) for u in explicit] + self.found + ["localhost", "127.0.0.1"]:
            n = n.strip()
            if n and n != "0.0.0.0" and n not in san:
                san.append(n)
        return Plan(default, explicit, explicit or default, san, dropped)


def warn_dropped(dropped: Iterable[str], source: str = "check-in poster") -> None:
    for d in dropped:
        log.warning("%s: %s is not an address on any interface of this host now: left out of the poster "
                    "and the server certificate (a host name would stay)", source, d)


def saved_poster_urls(store) -> list[str]:
    """The urls of the saved poster (``checkin.poster`` setting), as the GM saved them."""
    import json  # noqa: PLC0415

    try:
        urls = json.loads(store.get_setting("checkin.poster") or "{}").get("urls")
    except (ValueError, AttributeError):
        return []
    return [u for u in urls if isinstance(u, str)] if isinstance(urls, list) else []
