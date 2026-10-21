# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay (Phase 4 follow-up, decisions FU5-*; ADR-P4-7's amendment, P4R12, P4R18).

A field's staff away from the field (or a TAK client in a command post) see the field's boxes and
zones on ATAK, and player positions only where P4R18 allows. Off by default
(``ATALAIA_ATAK_RELAY=on`` turns it on).

**In.** A field controller with ``[atak] remote = true`` pushes its CoT events on the sync's stream it
opened itself (``WS /api/v1/sync/stream``, ``cot`` messages, ``api/sync.py``): the site server never
connects to a controller (P4R12). Each event is checked by the shared ``sync_format.cot_event`` (a
narrow form: Atalaia's uids, spot markers and players, known detail elements, no DOCTYPE or entity)
and serialised again before it is relayed. Events are kept in memory only, per field, until they go
stale: a device that connects gets the current picture at once. Nothing is stored.

**Out.** A small asyncio TLS server in the site server's process, on ``ATALAIA_ATAK_RELAY_PORT``
(8089, TAK's streaming CoT over TLS), published by the deployment straight from the server's
container (Caddy's image has no layer-4 proxy). TLS 1.2 or 1.3 only, ECDHE with AES-GCM or
ChaCha20-Poly1305 on 1.2, no compression, no renegotiation, and a **client certificate required**:

1. OpenSSL verifies the device's certificate against the fields' CAs (``atak_pki``; every field's CA
   is in the context's trust store; a field's first CA is added when it is made, or within
   ``CA_RELOAD_S`` when the operator's command made it in another process) and its dates and
   extended key usage (``clientAuth``) during the handshake: no certificate, an expired one or one
   no field's CA signed never gets past it.
2. Then the relay finds the CA that signed it (its authority key identifier, and the signature
   checked again), which names the field and, in hosted mode, the tenant: **the certificate's field
   selects the tenant**, as a host name does for HTTP (``tenancy.py``); a suspended field is refused.
3. In that tenant, the certificate must be in ``atak_certs`` (by the SHA-256 of its DER encoding),
   of that field, not revoked, not expired, and its holder must still have a role on the field
   (``services.atak``). Anything else is refused and closed, and logged (``atak_refused``).
4. The connection is logged (``atak_connect``, with the device's address) and gets the field's
   boxes and zones; player positions only if the certificate was issued with ``positions`` and its
   holder has the field's ``gm`` or ``marshal`` role (checked again every ``REFRESH_S``).

A revoked certificate's connections are closed at once (``drop_cert``), an expiring one's at its
expiry, and every connection is checked again every ``REFRESH_S`` (revocation by the operator's
command, a role removed, a field suspended). One field per certificate: a connection only ever gets
its own field's events. What a device sends is read and thrown away (bounded), except TAK's
keep-alive ping (``t-x-c-t``), which is answered: nothing from a device reaches a controller or
another device. Connections are limited per address and in all; the handshake must finish in
``HANDSHAKE_S``. Connections still in their handshake (or not yet authorised) have their own, smaller
caps (``MAX_PENDING``, ``MAX_PENDING_PER_ADDRESS``), so addresses holding handshakes open never take
the room of enrolled devices (``MAX_CONNECTIONS`` counts authorised ones only). The per-address limits
take an IPv6 address by its /64 (one host usually has a whole /64), an IPv4 address whole (FU5-16).

The pictures are bounded (FU5-15): at most ``PICTURE_MAX`` uids per field (the oldest update goes
first), each kept at most ``KEEP_MAX_S`` whatever its stale time says, and stale ones are dropped at
every publish as well as when a device connects.

Everything lives in the server's one worker process (ADR-P4-2), as the remote GM's links do.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import ipaddress
import logging
import os
import re
import ssl
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from atalaia_controller import atak as cot
from cryptography import x509
from sqlalchemy import select

from . import atak_pki, tenancy
from .atak_models import AtakCa, AtakCert
from .audit import record
from .config import Settings
from .ratelimit import RequestLimit
from .services import atak as enrolment

log = logging.getLogger("atalaia.atak_relay")

HANDSHAKE_S = 10.0
REFRESH_S = 30.0
CA_RELOAD_S = 15.0
WRITE_TIMEOUT_S = 30.0
QUEUE_MAX = 1000          # events waiting for one device; past that it is too slow and is closed
READ_MAX = 64 * 1024      # what a device may send without an </event>
MAX_CONNECTIONS = 256    # authorised devices, in all
MAX_PER_FIELD = 64
MAX_PER_ADDRESS = 16      # open at once (an IPv6 /64 counts as one address)
MAX_PENDING = 64          # connections in their TLS handshake or not yet authorised, in all (FU5-16)
MAX_PENDING_PER_ADDRESS = 4
PICTURE_MAX = 1024        # uids kept per field's picture; past that the least recently updated goes (FU5-15)
KEEP_MAX_S = 7200.0       # an event is kept at most this long after it arrived: 2 x atak.interval_s's 3600
ATTEMPTS_PER_MINUTE = 30  # new connections per address
REFUSAL_AUDIT_S = 60.0    # one atak_refused row per certificate and reason a minute
TLS12_CIPHERS = "ECDHE+AESGCM:ECDHE+CHACHA20"
_PING = re.compile(rb'\btype\s*=\s*["\']t-x-c-t["\']')


@dataclass
class CaEntry:
    tenant: Optional[tenancy.Tenant]
    field_id: uuid.UUID
    cert: x509.Certificate


@dataclass(eq=False)
class Client:
    tenant: Optional[str]          # the tenant's schema (hosted mode), else None
    field_id: uuid.UUID
    cert_id: uuid.UUID
    device: str
    positions: bool
    not_after: dt.datetime
    address: str
    writer: asyncio.StreamWriter
    queue: "asyncio.Queue[Optional[bytes]]" = field(default_factory=lambda: asyncio.Queue(QUEUE_MAX))
    connected_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    tenant_obj: Optional[tenancy.Tenant] = None
    closed: bool = False

    @property
    def key(self) -> tuple[Optional[str], uuid.UUID]:
        return (self.tenant, self.field_id)

    def json(self) -> dict[str, Any]:
        return {"certificate": str(self.cert_id), "device_name": self.device, "positions": self.positions,
                "connected_at": self.connected_at.isoformat(), "address": self.address}


def address_group(address: str) -> str:
    """The key of the per-address limits: an IPv6 address's /64, an IPv4 address (or an IPv4-mapped one)
    as it is, anything else as given."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return address
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((ip, 64), strict=False))
    return str(ip)


class Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AtakRelay:
    """The relay: its TLS listener, the fields' current pictures and the connected devices."""

    def __init__(self, settings: Settings, sessionmaker: Any, engine: Any, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.engine = engine
        self.clock = clock
        names = ([f"*.{settings.hosted_domain}", str(settings.hosted_domain)] if settings.hosted
                 else [settings.relay_host() or "localhost"])
        self.identity = atak_pki.server_identity(settings.secret_key, names)
        self.ssl = self._context()
        self.trust: dict[str, CaEntry] = {}          # authority key identifier (hex) -> the field's CA
        self.clients: set[Client] = set()
        self.pictures: dict[tuple[Optional[str], uuid.UUID], dict[str, dict[str, Any]]] = {}
        self.attempts = RequestLimit(ATTEMPTS_PER_MINUTE, 60)
        self._open_per_address: dict[str, int] = {}
        self._pending_per_address: dict[str, int] = {}
        self._pending = 0
        self._refusals: dict[tuple[str, str], float] = {}
        self._server: Optional[asyncio.base_events.Server] = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._refresher: Optional[asyncio.Task[None]] = None
        self._loaded_at = 0.0
        self.port = 0

    # --- TLS -----------------------------------------------------------------------------------------

    def _context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers(TLS12_CIPHERS)
        ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_NO_RENEGOTIATION | ssl.OP_CIPHER_SERVER_PREFERENCE
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.verify_flags |= ssl.VERIFY_X509_STRICT
        with tempfile.TemporaryDirectory(prefix="atak-relay-") as tmp:
            chain, key = os.path.join(tmp, "chain.pem"), os.path.join(tmp, "key.pem")
            for path, data in ((chain, self.identity.chain_pem()), (key, self.identity.key_pem())):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
            ctx.load_cert_chain(chain, key)
        return ctx

    def add_ca(self, tenant: Optional[tenancy.Tenant], field_id: uuid.UUID, cert_pem: str) -> None:
        """A field's CA, trusted from the next handshake on (a field's new CA, or one loaded at start)."""
        cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
        ski = atak_pki.ski_hex(cert)
        if ski in self.trust:
            return
        self.ssl.load_verify_locations(cadata=cert_pem)
        self.trust[ski] = CaEntry(tenant, field_id, cert)

    async def load_cas(self) -> int:
        """Every field's CA (every active tenant's in hosted mode). One tenant's failure is logged and
        does not stop the others'; returns how many tenants failed."""
        self._loaded_at = time.monotonic()
        tenants: list[Optional[tenancy.Tenant]] = [None]
        if self.settings.hosted:
            tenants = list(await tenancy.active_tenants(self.engine))
        failed = 0
        for tenant in tenants:
            try:
                with tenancy.use(tenant):
                    async with self.sessionmaker() as db:
                        rows = (await db.execute(select(AtakCa.field_id, AtakCa.cert_pem))).all()
                for field_id, cert_pem in rows:
                    self.add_ca(tenant, field_id, cert_pem)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  (one field's schema: the next tenants still load)
                failed += 1
                log.exception("ATAK relay: could not load the CAs%s", f" of {tenant.slug}" if tenant else "")
        return failed

    # --- lifecycle --------------------------------------------------------------------------------------

    async def start(self, host: str = "0.0.0.0") -> None:
        try:
            await self.load_cas()
        except Exception:  # noqa: BLE001  (the database is not there yet: the refresher tries again)
            log.exception("ATAK relay: could not load the fields' CAs yet")
        self._server = await asyncio.start_server(self._accept, host, self.settings.atak_relay_port,
                                                  limit=READ_MAX)
        self.port = self._server.sockets[0].getsockname()[1]
        self._refresher = asyncio.create_task(self._refresh_loop(), name="atak-relay-refresh")
        log.info("ATAK relay listening on port %d (TLS, client certificates required)", self.port)

    async def stop(self) -> None:
        if self._refresher is not None:
            self._refresher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresher
        if self._server is not None:
            self._server.close()
        for client in list(self.clients):
            self._close(client)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 5)

    # --- events in ----------------------------------------------------------------------------------------

    def publish(self, field_id: uuid.UUID, events: list[dict[str, Any]]) -> int:
        """A controller's checked events (``sync_format.cot_event``) for the current tenant's field: kept as
        the field's picture until stale and sent to its devices (positions only to those allowed). Returns
        how many deliveries were queued."""
        key = (tenancy.current_schema(), field_id)
        now = self.clock()
        picture = self.pictures.setdefault(key, {})
        clients = [c for c in self.clients if c.key == key and not c.closed]
        sent = 0
        for ev in events:
            picture.pop(ev["uid"], None)  # an update goes to the end: the order is the least recently updated first
            if ev["stale"] >= ev["start"]:  # else a drop: it goes out, then nothing of it is kept
                picture[ev["uid"]] = {**ev, "keep_until": min(ev["stale"], now + KEEP_MAX_S)}
            data = ev["xml"].encode("utf-8")
            for client in clients:
                if ev["map"] or client.positions:
                    sent += self._queue(client, data)
        self._prune(key, now)
        return sent

    def _prune(self, key: tuple[Optional[str], uuid.UUID], now: float) -> dict[str, dict[str, Any]]:
        """The field's picture without what is stale (or kept long enough), at most ``PICTURE_MAX`` uids."""
        picture = self.pictures.get(key, {})
        for uid in [u for u, ev in picture.items() if ev["keep_until"] <= now]:
            del picture[uid]
        while len(picture) > PICTURE_MAX:
            del picture[next(iter(picture))]
        if not picture:
            self.pictures.pop(key, None)
        return picture

    def _queue(self, client: Client, data: bytes) -> int:
        try:
            client.queue.put_nowait(data)
            return 1
        except asyncio.QueueFull:
            log.warning("ATAK relay: %s is too slow; closed", client.device)
            self._close(client)
            return 0

    def _snapshot(self, client: Client) -> list[bytes]:
        picture = self._prune(client.key, self.clock())
        return [ev["xml"].encode("utf-8") for ev in picture.values() if ev["map"] or client.positions]

    # --- devices ------------------------------------------------------------------------------------------

    def connected(self, field_id: uuid.UUID) -> list[dict[str, Any]]:
        key = (tenancy.current_schema(), field_id)
        return [c.json() for c in sorted(self.clients, key=lambda c: c.connected_at) if c.key == key]

    def drop_cert(self, cert_id: uuid.UUID) -> int:
        """A certificate revoked: its connections close now (the current tenant's only)."""
        tenant = tenancy.current_schema()
        gone = [c for c in self.clients if c.cert_id == cert_id and c.tenant == tenant]
        for client in gone:
            self._close(client)
        return len(gone)

    def _close(self, client: Client) -> None:
        if client.closed:
            return
        client.closed = True
        self.clients.discard(client)
        with contextlib.suppress(asyncio.QueueFull):
            client.queue.put_nowait(None)
        client.writer.close()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        peer = writer.get_extra_info("peername")
        address = str(peer[0]) if peer else "unknown"
        group = address_group(address)
        counted = pending = False
        try:
            if (self._pending >= MAX_PENDING or self._pending_per_address.get(group, 0) >= MAX_PENDING_PER_ADDRESS
                    or len(self._tasks) > MAX_CONNECTIONS + MAX_PENDING
                    or self._open_per_address.get(group, 0) >= MAX_PER_ADDRESS or self.attempts.hit(group)):
                return
            self._open_per_address[group] = self._open_per_address.get(group, 0) + 1
            counted = True
            self._pending += 1
            self._pending_per_address[group] = self._pending_per_address.get(group, 0) + 1
            pending = True
            try:
                await writer.start_tls(self.ssl, ssl_handshake_timeout=HANDSHAKE_S)
            except (ssl.SSLError, OSError, asyncio.TimeoutError, ConnectionError) as exc:
                log.info("ATAK relay: TLS handshake from %s refused (%s)", address, type(exc).__name__)
                return
            sslobj = writer.get_extra_info("ssl_object")
            der = sslobj.getpeercert(binary_form=True) if sslobj is not None else None
            if not der:
                return  # CERT_REQUIRED makes this impossible; refuse anyway
            try:
                client = await self._authorise(der, address, writer)
            except Refused as exc:
                log.info("ATAK relay: a certificate from %s refused (%s)", address, exc.reason)
                return
            self._unpend(group)
            pending = False
            await self._serve(client, reader)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  (one device's trouble never stops the relay)
            log.exception("ATAK relay: connection from %s failed", address)
        finally:
            if pending:
                self._unpend(group)
            if counted:
                _decrement(self._open_per_address, group)
            with contextlib.suppress(Exception):
                writer.close()
            if task is not None:
                self._tasks.discard(task)

    def _unpend(self, group: str) -> None:
        self._pending -= 1
        _decrement(self._pending_per_address, group)

    def _ca_for(self, cert: x509.Certificate) -> Optional[CaEntry]:
        entry = self.trust.get(atak_pki.aki_hex(cert) or "")
        if entry is None:
            return None
        try:
            cert.verify_directly_issued_by(entry.cert)
        except Exception:  # noqa: BLE001  (InvalidSignature, or a certificate of another form)
            return None
        return entry

    async def _authorise(self, der: bytes, address: str, writer: asyncio.StreamWriter) -> Client:
        try:
            cert = x509.load_der_x509_certificate(der)
        except ValueError:
            raise Refused("not_a_certificate") from None
        entry = self._ca_for(cert)
        if entry is None:
            raise Refused("unknown_ca")
        sha = hashlib.sha256(der).hexdigest()
        with tenancy.use(entry.tenant):
            if entry.tenant is not None:
                now_tenant = await tenancy.lookup(self.engine, entry.tenant.slug)
                if now_tenant is None or now_tenant.status != "active":
                    raise Refused("field_suspended")
            async with self.sessionmaker() as db:
                row = (await db.execute(select(AtakCert).where(AtakCert.sha256 == sha))).scalar_one_or_none()
                now = dt.datetime.now(dt.timezone.utc)
                reason = enrolment.refusal(row, entry.field_id, now)
                state = await enrolment.holder_state(db, row) if reason is None and row is not None else None
                if state is not None and not state.ok:
                    reason = state.reason
                if reason is not None or row is None or state is None:
                    await self._refused(db, entry.field_id, sha, row, reason or "refused", address)
                    raise Refused(reason or "refused")
                same_field = sum(1 for c in self.clients if c.key == (tenancy.current_schema(), entry.field_id))
                if same_field >= MAX_PER_FIELD or len(self.clients) >= MAX_CONNECTIONS:
                    raise Refused("too_many_connections")
                row.last_connected_at = now
                # The holder is the row's account; who issued the certificate in their name too (FU5-14).
                record(db, "atak_connect", user_id=row.holder_id, resource="field", resource_id=entry.field_id,
                       details={"certificate": str(row.id), "device_name": row.device_name,
                                "positions": state.positions, "issued_by": _str(row.issued_by),
                                "issued_via": row.issued_via}, address=address)
                await db.commit()
                client = Client(tenant=tenancy.current_schema(), field_id=entry.field_id, cert_id=row.id,
                                device=row.device_name, positions=state.positions, not_after=row.not_after,
                                address=address, writer=writer, tenant_obj=entry.tenant)
        self.clients.add(client)
        log.info("ATAK relay: %s connected from %s (positions %s)", client.device, address,
                 "on" if client.positions else "off")
        return client

    async def _refused(self, db: Any, field_id: uuid.UUID, sha: str, row: Optional[AtakCert], reason: str,
                       address: str) -> None:
        now = time.monotonic()
        key = (sha, reason)
        if now - self._refusals.get(key, -REFUSAL_AUDIT_S) < REFUSAL_AUDIT_S:
            return
        self._refusals[key] = now
        if len(self._refusals) > 4096:
            self._refusals = {k: t for k, t in self._refusals.items() if now - t < REFUSAL_AUDIT_S}
        record(db, "atak_refused", user_id=row.holder_id if row is not None else None, resource="field",
               resource_id=field_id, details={"reason": reason, "sha256": sha,
                                              **({"certificate": str(row.id)} if row is not None else {})},
               address=address)
        await db.commit()

    async def _serve(self, client: Client, reader: asyncio.StreamReader) -> None:
        loop = asyncio.get_running_loop()
        remaining = (client.not_after - dt.datetime.now(dt.timezone.utc)).total_seconds()
        expiry = loop.call_later(max(0.0, remaining), self._close, client)
        for data in self._snapshot(client):
            self._queue(client, data)
        writer_task = asyncio.create_task(self._write(client), name="atak-relay-write")
        try:
            await self._read(client, reader)
        finally:
            expiry.cancel()
            self._close(client)
            writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await writer_task

    async def _write(self, client: Client) -> None:
        while True:
            data = await client.queue.get()
            if data is None or client.closed:
                return
            client.writer.write(data)
            try:
                await asyncio.wait_for(client.writer.drain(), WRITE_TIMEOUT_S)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                self._close(client)
                return

    async def _read(self, client: Client, reader: asyncio.StreamReader) -> None:
        """What the device sends: thrown away, except TAK's ping, answered with a pong."""
        buffer = b""
        while not client.closed:
            try:
                chunk = await reader.read(4096)
            except (ConnectionError, OSError, ssl.SSLError):
                return
            if not chunk:
                return
            buffer += chunk
            while b"</event>" in buffer:
                event, _, buffer = buffer.partition(b"</event>")
                if _PING.search(event):
                    self._queue(client, pong(self.clock()))
            if len(buffer) > READ_MAX:
                log.info("ATAK relay: %s sent too much without an event's end; closed", client.device)
                return

    # --- checking again ----------------------------------------------------------------------------------

    async def _refresh_loop(self) -> None:
        """Loads new CAs every ``CA_RELOAD_S`` and checks every connection again every ``REFRESH_S``, each in
        its own try: a failure loading CAs never holds back the check that closes revoked connections."""
        last_check = time.monotonic()
        while True:
            await asyncio.sleep(CA_RELOAD_S)
            try:
                await self.load_cas()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  (the tenants' list itself: the check below runs anyway)
                log.exception("ATAK relay: loading the fields' CAs failed")
            if time.monotonic() - last_check >= REFRESH_S:
                last_check = time.monotonic()
                try:
                    await self.recheck()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.exception("ATAK relay: checking the connections again failed")

    async def recheck(self) -> None:
        """Every connection against the database again: revoked, expired, its holder's role, the field."""
        now = dt.datetime.now(dt.timezone.utc)
        for client in list(self.clients):
            try:
                await self._recheck_one(client, now)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  (one tenant's trouble: the other connections are still checked)
                log.exception("ATAK relay: checking %s again failed", client.device)

    async def _recheck_one(self, client: Client, now: dt.datetime) -> None:
        with tenancy.use(client.tenant_obj):
            if client.tenant_obj is not None:
                current = await tenancy.lookup(self.engine, client.tenant_obj.slug)
                if current is None or current.status != "active":
                    self._close(client)
                    return
            async with self.sessionmaker() as db:
                row = await db.get(AtakCert, client.cert_id)
                reason = enrolment.refusal(row, client.field_id, now)
                state = await enrolment.holder_state(db, row) if reason is None and row is not None else None
        if reason is not None or state is None or not state.ok:
            log.info("ATAK relay: %s closed (%s)", client.device, reason or (state.reason if state else "gone"))
            self._close(client)
        else:
            client.positions = state.positions

    def status(self, field_id: uuid.UUID) -> dict[str, Any]:
        return {"enabled": True, "port": self.settings.relay_public_port(), "connected": self.connected(field_id),
                "relay_ca_sha256": atak_pki.sha256_hex(self.identity.ca)}


def _decrement(counts: dict[str, int], key: str) -> None:
    left = counts.get(key, 1) - 1
    if left > 0:
        counts[key] = left
    else:
        counts.pop(key, None)


def _str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def pong(now: float) -> bytes:
    """TAK's keep-alive answer: an event of type ``t-x-c-t-r``."""
    return cot.event_xml(uid="takPong", cot_type="t-x-c-t-r", how="h-g-i-g-o", lat=0.0, lon=0.0, now=now,
                         start=now, stale=now + 20.0)
