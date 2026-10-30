# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay on PostgreSQL 16 (Phase 4 follow-up, decisions FU5-*): enrolment, the TLS listener.

The app runs with ``atak_relay`` on (an ephemeral port), its relay in the test's event loop; the
devices are TLS clients made from the data packages the API hands out (their PKCS#12 files read back
with ``cryptography``), on real sockets to 127.0.0.1. A controller's stream is driven through the
app's ASGI interface (``test_remote_gm.Stream``). What is tried:

- who may issue (the field's admin or gm in a TOTP session), what a holder may get (positions only for
  a gm or a marshal), the data package's contents, the CA's key sealed, the audit log;
- the listener: TLS 1.2+ only, a client certificate required, a certificate of an unknown CA refused,
  another field's certificate getting nothing of this field, a revoked one closed at once and refused
  after, an expired one refused (by OpenSSL, and by the database's date), a holder without a role
  refused, positions only to a certificate allowed them, the current picture at once, TAK's ping;
- hosted mode: the certificate's field picks the tenant, and one tenant's events never reach another's
  device, and one tenant's failure does not stop the others' CAs loading;
- the review's fixes (FU5-13..20): positions need an issuer with gm or marshal, the issuer in
  ``atak_connect``, the pictures bounded, a controller's cot messages limited, handshakes capped apart
  from enrolled devices (IPv6 by /64), the periodic check running when loading CAs fails, the cot
  details' attributes, erasure scrubbing the audit details and closing connections at once, a CA's
  rotation closing connections at once, concurrent first issues sharing one CA.

The real controller through the real site server under uvicorn: ``test_atak_e2e.py``.

    python3 tools/docker_server.py test tests.test_atak
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import datetime as dt
import io
import json
import os
import ssl
import tempfile
import time
import uuid
import warnings
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Optional
from unittest import mock

from atalaia_controller import atak as cot
from atalaia_controller import sync_format
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from atalaia_server import atak_pki, atak_relay, sync, tenancy
from atalaia_server.config import Settings

from .base import METRICS_TOKEN, PASSWORD, SECRET_KEY, AppTestCase
from .test_remote_gm import CONTROLLER, Stream
from .test_tenants import DOMAIN, HubCase

HOST = "campo.test"
ROLE_IDS = {"player": 1, "marshal": 4, "gm": 5, "admin": 7}


def event(uid: str, kind: str = "b-m-p-s-m", how: str = "h-e", stale_in: float = 60.0) -> str:
    now = time.time()
    detail = cot.marker_detail("Caixa", "Atalaia: red", -1) if kind == "b-m-p-s-m" else \
        [cot._el("contact", {"callsign": uid.rsplit(".", 1)[-1]})]
    return cot.event_xml(uid=uid, cot_type=kind, how=how, lat=38.72, lon=-9.14, now=now, start=now,
                         stale=now + stale_in, detail=detail).decode("utf-8")


def box(field: str = "campo", node: int = 4) -> str:
    return event(f"atalaia.{field}.node.{node}")


def player(field: str = "campo", pid: str = "p-abcdefghijk2") -> str:
    return event(f"atalaia.{field}.player.{pid}", "a-f-G-U-C", "m-g")


class Device:
    """A TAK client made from a data package: its TLS context, and its connection when open."""

    def __init__(self, answer: dict[str, Any], host: str = HOST) -> None:
        self.answer = answer
        self.host = host
        data = base64.b64decode(answer["package"]["base64"])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.files = {n: z.read(n) for n in z.namelist()}
        client = pkcs12.load_pkcs12(self.files["certs/client.p12"], answer["password"].encode())
        trust = pkcs12.load_pkcs12(self.files["certs/truststore.p12"], atak_pki.TRUSTSTORE_PASSWORD.encode())
        assert client.cert is not None and client.key is not None
        self.cert = client.cert.certificate
        self.key = client.key
        self.relay_ca = trust.additional_certs[0].certificate
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    def context(self, *, with_cert: bool = True, max_version: Optional[ssl.TLSVersion] = None,
                cert: Optional[x509.Certificate] = None, key: Any = None) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=atak_pki.pem(self.relay_ca))
        if max_version is not None:
            with warnings.catch_warnings():  # TLS 1.0 and 1.1 are deprecated: this device asks for them anyway
                warnings.simplefilter("ignore", DeprecationWarning)
                ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
                ctx.maximum_version = max_version
        if with_cert:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "client.pem")
                with open(path, "wb") as f:
                    f.write((key or self.key).private_bytes(serialization.Encoding.PEM,
                                                            serialization.PrivateFormat.PKCS8,
                                                            serialization.NoEncryption()))
                    f.write((cert or self.cert).public_bytes(serialization.Encoding.PEM))
                ctx.load_cert_chain(path)
        return ctx

    async def open(self, port: int, ctx: Optional[ssl.SSLContext] = None) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port, ssl=ctx or self.context(), server_hostname=self.host), 5)

    async def events(self, n: int, timeout: float = 5.0) -> list[ET.Element]:
        """The next ``n`` events (each with its XML declaration, as TAK Protocol version 0 has them)."""
        assert self.reader is not None
        buf = b""
        end = time.monotonic() + timeout
        while buf.count(b"</event>") < n:
            left = end - time.monotonic()
            if left <= 0:
                raise AssertionError(f"{buf.count(b'</event>')} of {n} events in {timeout} s: {buf[:300]!r}")
            chunk = await asyncio.wait_for(self.reader.read(65536), left)
            if not chunk:
                raise AssertionError(f"closed after {buf.count(b'</event>')} of {n} events")
            buf += chunk
        out = []
        for part in buf.split(b"</event>")[:n]:
            text = (part + b"</event>").decode("utf-8")
            assert text.startswith(cot.XML_DECL), text[:80]
            out.append(ET.fromstring(text[len(cot.XML_DECL):]))
        return out

    async def nothing(self, wait: float = 0.5) -> bool:
        """True when nothing arrives (and the connection stays open) for ``wait`` seconds."""
        assert self.reader is not None
        try:
            data = await asyncio.wait_for(self.reader.read(1), wait)
        except asyncio.TimeoutError:
            return True
        raise AssertionError(f"got {data!r}" if data else "the relay closed the connection")

    async def closed(self, timeout: float = 5.0) -> bool:
        """True when the relay ends the connection (EOF or a TLS alert) within ``timeout``."""
        assert self.reader is not None
        end = time.monotonic() + timeout
        try:
            while time.monotonic() < end:
                data = await asyncio.wait_for(self.reader.read(65536), end - time.monotonic())
                if not data:
                    return True
        except asyncio.TimeoutError:  # first: on Python 3.11+ it is the builtin TimeoutError, an OSError
            return False
        except (ssl.SSLError, ConnectionError, OSError):
            return True
        return False

    async def refused(self, port: int, ctx: Optional[ssl.SSLContext] = None) -> bool:
        """True when a new connection with this context fails or is closed without a byte."""
        try:
            await self.open(port, ctx)
        except (ssl.SSLError, ConnectionError, OSError):
            return True
        try:
            return await self.closed(3.0)
        finally:
            self.close()

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None


class RelayCase(AppTestCase):
    relay_on = True

    def settings(self) -> Settings:
        return Settings(database_url=self.database_url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN,
                        db_timeout_s=2.0, purge_hour=None, public_url=f"https://{HOST}", atak_relay=self.relay_on,
                        atak_relay_port=0)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo")
        self.other_id = await self.make_field("outro")
        self.devices: list[Device] = []
        self.streams: list[Stream] = []

    async def asyncTearDown(self) -> None:
        for d in self.devices:
            d.close()
        for s in self.streams:
            await s.close()
        await super().asyncTearDown()

    @property
    def relay(self) -> Any:
        return self.app.state.atak_relay

    @property
    def port(self) -> int:
        return int(self.relay.port)

    async def make_field(self, slug: str) -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id", slug.title(),
                                 slug))[0][0]

    async def person(self, *roles: str, field_id: Optional[uuid.UUID] = None,
                     server_admin: bool = False) -> tuple[dict[str, str], uuid.UUID, str]:
        user_id, name, secret = await self.make_user(with_totp=True, server_admin=server_admin)
        for role in roles:
            await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                             user_id, field_id or self.field_id, ROLE_IDS[role])
        return await self.auth(name, secret=secret), user_id, name

    async def issue(self, headers: dict[str, str], field_id: Optional[uuid.UUID] = None,
                    status: int = 201, **body: Any) -> dict[str, Any]:
        body.setdefault("device_name", "Tablet do posto")
        r = await self.client.post(f"/api/v1/fields/{field_id or self.field_id}/atak/certificates", json=body,
                                   headers=headers)
        self.assertEqual(r.status_code, status, r.text)
        return dict(r.json())

    async def device(self, headers: dict[str, str], field_id: Optional[uuid.UUID] = None, **body: Any) -> Device:
        d = await asyncio.to_thread(Device, await self.issue(headers, field_id, **body))
        self.devices.append(d)
        return d

    async def connected(self, d: Device, field_id: Optional[uuid.UUID] = None) -> None:
        """Opens the device's connection and waits until the relay lists it."""
        await d.open(self.port)
        fid = field_id or self.field_id
        for _ in range(100):
            if any(c["certificate"] == d.answer["certificate"]["id"] for c in self.relay.connected(fid)):
                return
            await asyncio.sleep(0.02)
        self.fail("the relay never listed the device")

    def publish(self, *texts: str, field_id: Optional[uuid.UUID] = None) -> None:
        self.relay.publish(field_id or self.field_id, [sync_format.cot_event(t) for t in texts])

    async def audit(self, action: str) -> list[Any]:
        return [json.loads(r["details"]) for r in await self.fetch(
            "SELECT details FROM audit_log WHERE action = $1 ORDER BY id", action)]

    async def wait_for(self, check: Any, what: str, timeout: float = 3.0) -> None:
        end = time.monotonic() + timeout
        while not check():
            if time.monotonic() > end:
                self.fail(what)
            await asyncio.sleep(0.02)


async def raw_connection(port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A TCP connection that never starts its TLS handshake."""
    return await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 5)


async def ended_at_once(reader: asyncio.StreamReader, wait: float = 1.5) -> bool:
    """True when the relay closes the connection within ``wait`` (a held handshake waits HANDSHAKE_S)."""
    try:
        return await asyncio.wait_for(reader.read(1), wait) == b""
    except asyncio.TimeoutError:  # before OSError, of which it is a subclass on Python 3.11+
        return False
    except (ConnectionError, OSError):
        return True


class EnrolmentTests(RelayCase):
    async def test_a_gm_issues_a_data_package(self) -> None:
        gm, gm_id, gm_name = await self.person("gm")
        answer = await self.issue(gm, days=3)
        cert = answer["certificate"]
        self.assertEqual((cert["device_name"], cert["holder"], cert["positions"], cert["state"], cert["issued_via"]),
                         ("Tablet do posto", gm_name, False, "valid", "api"))
        self.assertEqual(answer["connect"], {"host": HOST, "port": 8089})
        d = await asyncio.to_thread(Device, answer)
        self.assertEqual(set(d.files), {"MANIFEST/manifest.xml", "certs/atalaia.pref", "certs/truststore.p12",
                                        "certs/client.p12"})
        pref = d.files["certs/atalaia.pref"].decode()
        self.assertIn(f">{HOST}:8089:ssl<", pref)
        self.assertNotIn(answer["password"], pref)  # the client certificate's password is not in the package
        for blob in d.files.values():
            self.assertNotIn(answer["password"].encode(), blob)
        manifest = ET.fromstring(d.files["MANIFEST/manifest.xml"])
        self.assertEqual(sorted(c.get("zipEntry") for c in manifest.iter("Content")),
                         ["certs/atalaia.pref", "certs/client.p12", "certs/truststore.p12"])
        # The certificate: this field's CA, the device's name, client authentication, 3 days.
        self.assertEqual(d.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value, "Tablet do posto")
        eku = d.cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        self.assertEqual(list(eku), [x509.ExtendedKeyUsageOID.CLIENT_AUTH])
        life = d.cert.not_valid_after_utc - d.cert.not_valid_before_utc
        self.assertEqual(life, dt.timedelta(days=3) + atak_pki.BACKDATE)
        ca_row = (await self.fetch("SELECT cert_pem, key_sealed FROM atak_cas WHERE field_id = $1", self.field_id))[0]
        ca = x509.load_pem_x509_certificate(ca_row["cert_pem"].encode())
        d.cert.verify_directly_issued_by(ca)
        self.assertEqual(d.relay_ca, self.relay.identity.ca)
        # The CA's key is stored sealed only: no PEM, no DER of it, and it opens only for its field.
        sealed = bytes(ca_row["key_sealed"])
        self.assertNotIn(b"PRIVATE KEY", sealed)
        box = atak_pki.CaBox(SECRET_KEY)
        key = box.open(self.field_id, sealed)
        self.assertIsNotNone(key)
        assert key is not None
        self.assertNotIn(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()), sealed)
        self.assertIsNone(box.open(self.other_id, sealed))
        self.assertIsNone(atak_pki.CaBox("x" * 43).open(self.field_id, sealed))
        # Listed, logged, and the client key is nowhere in the database.
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/atak", headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        state = r.json()
        self.assertTrue(state["enabled"])
        self.assertEqual([c["id"] for c in state["certificates"]], [cert["id"]])
        self.assertEqual(state["relay_ca_sha256"], atak_pki.sha256_hex(self.relay.identity.ca))
        issued = await self.audit("atak_cert_issued")
        self.assertEqual([(e["certificate"], e["positions"], e["ca_made"]) for e in issued],
                         [(cert["id"], False, True)])
        client_der = d.key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())
        dump = await self.fetch("SELECT string_agg(t::text, '') AS all FROM (SELECT * FROM atak_certs) t")
        self.assertNotIn(client_der.hex(), dump[0]["all"] or "")
        # A second certificate reuses the CA.
        await self.issue(gm, device_name="Telemóvel 2")
        self.assertEqual((await self.fetch("SELECT count(*) FROM atak_cas"))[0][0], 1)

    async def test_who_may_issue_and_what(self) -> None:
        admin, _, _ = await self.person("admin")
        gm, _, _ = await self.person("gm")
        marshal, marshal_id, marshal_name = await self.person("marshal")
        player, _, player_name = await self.person("player")
        other_gm, _, _ = await self.person("gm", field_id=self.other_id)
        await self.issue(admin)  # the field's admin
        for headers in (marshal, player, other_gm):  # not the field's admin or gm
            await self.issue(headers, status=403)
        # gm without the TOTP step: the role does not count.
        user_id, name, _ = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 5)", user_id,
                         self.field_id)
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertTrue(r.json().get("totp_required"))  # no access token without the second step
        # Positions: only for a holder with gm or marshal on the field (P4R18).
        self.assertTrue((await self.issue(gm, positions=True))["certificate"]["positions"])
        self.assertTrue((await self.issue(gm, holder=marshal_name, positions=True))["certificate"]["positions"])
        r = await self.issue(gm, holder=player_name, positions=True, status=409)
        self.assertEqual(r["detail"], "positions_not_allowed")
        self.assertEqual((await self.issue(gm, holder=player_name))["certificate"]["holder"], player_name)
        _, _, stranger = await self.person()
        self.assertEqual((await self.issue(gm, holder=stranger, status=409))["detail"], "holder_has_no_role")
        # SRV-4: no such account and an account with no role here are told apart by nothing.
        self.assertEqual(await self.issue(gm, holder="nobody-at-all", status=409), {"detail": "holder_has_no_role"})
        # A server administrator with no role on the field names a holder.
        root, _, _ = await self.person(server_admin=True)
        self.assertEqual((await self.issue(root, status=409))["detail"], "holder_has_no_role")
        await self.issue(root, holder=marshal_name)
        # Bad requests.
        for body in ({"device_name": ""}, {"device_name": " x"}, {"device_name": "a\nb"}, {"device_name": "x" * 49},
                     {"days": 0}, {"days": 366}, {"days": True}, {"positions": "yes"}, {"colour": "red"}):
            with self.subTest(body=body):
                self.assertEqual((await self.issue(gm, status=400, **body))["detail"], "invalid_request")
        r = await self.client.post(f"/api/v1/fields/{uuid.uuid4()}/atak/certificates", headers=gm,
                                   json={"device_name": "x"})
        self.assertEqual(r.status_code, 403)

    async def test_certificates_last_90_days_by_default_and_say_when_they_expire(self) -> None:
        """SVX-1: the default lifetime is 90 days (a setting), the state shows it, and a near expiry is flagged."""
        gm, _, _ = await self.person("gm")
        self.assertEqual(atak_pki.DEFAULT_DAYS, 90)
        self.assertEqual(self.settings().atak_cert_days, 90)
        d = await self.device(gm)  # no days: the setting's default
        life = d.cert.not_valid_after_utc - d.cert.not_valid_before_utc
        self.assertEqual(life, dt.timedelta(days=90) + atak_pki.BACKDATE)
        await self.device(gm, days=3, device_name="Short")
        await self.device(gm, days=365, device_name="Long")
        state = (await self.client.get(f"/api/v1/fields/{self.field_id}/atak", headers=gm)).json()
        self.assertEqual((state["default_days"], state["max_days"], state["warn_days"]), (90, 365, 14))
        flagged = {c["device_name"]: c["expiring"] for c in state["certificates"]}
        self.assertEqual(flagged, {"Tablet do posto": False, "Short": True, "Long": False})

    def test_the_lifetime_is_a_setting(self) -> None:
        from atalaia_server.config import ConfigError, Settings as S
        base = {"ATALAIA_DATABASE_URL": "postgresql+asyncpg://u@h/d", "ATALAIA_SECRET_KEY": SECRET_KEY}
        self.assertEqual(S.from_env(base).atak_cert_days, 90)
        self.assertEqual(S.from_env({**base, "ATALAIA_ATAK_CERT_DAYS": "30"}).atak_cert_days, 30)
        for bad in ("0", "366", "x"):
            with self.assertRaises(ConfigError):
                S.from_env({**base, "ATALAIA_ATAK_CERT_DAYS": bad})

    async def test_positions_need_an_issuer_with_gm_or_marshal(self) -> None:
        """FU5-13: the answer gives the issuer the certificate's key, so positions need the issuer's role too."""
        admin, _, _ = await self.person("admin")
        gm, _, _ = await self.person("gm")
        admin_marshal, _, _ = await self.person("admin", "marshal")
        _, _, marshal_name = await self.person("marshal")
        root, _, _ = await self.person(server_admin=True)
        for headers in (admin, root):  # the field's admin alone, a server administrator with no role on it
            with self.subTest(headers=headers):
                r = await self.issue(headers, holder=marshal_name, positions=True, status=403)
                self.assertEqual(r["detail"], "positions_need_gm_or_marshal")
                await self.issue(headers, holder=marshal_name)  # without positions: still allowed (FU5-14)
        self.assertTrue((await self.issue(gm, holder=marshal_name, positions=True))["certificate"]["positions"])
        self.assertTrue((await self.issue(admin_marshal, positions=True))["certificate"]["positions"])
        # The holder's check stays: a gm cannot give positions to a player.
        _, _, player_name = await self.person("player")
        r = await self.issue(gm, holder=player_name, positions=True, status=409)
        self.assertEqual(r["detail"], "positions_not_allowed")
        self.assertEqual([e["positions"] for e in await self.audit("atak_cert_issued")],
                         [False, False, True, True])

    async def test_concurrent_first_issues_share_one_ca(self) -> None:
        """FU5-20: two first issues for a field at once both succeed, with the one CA."""
        gm, _, _ = await self.person("gm")
        answers = await asyncio.gather(*(self.client.post(f"/api/v1/fields/{self.field_id}/atak/certificates",
                                                          json={"device_name": f"Tablet {i}"}, headers=gm)
                                         for i in range(3)))
        self.assertEqual([r.status_code for r in answers], [201, 201, 201], [r.text for r in answers])
        self.assertEqual((await self.fetch("SELECT count(*) FROM atak_cas"))[0][0], 1)
        ca = x509.load_pem_x509_certificate(
            (await self.fetch("SELECT cert_pem FROM atak_cas"))[0]["cert_pem"].encode())
        for r in answers:
            d = await asyncio.to_thread(Device, r.json())
            d.cert.verify_directly_issued_by(ca)
        self.assertEqual(sorted(e["ca_made"] for e in await self.audit("atak_cert_issued")), [False, False, True])

    async def test_revoke_and_the_log(self) -> None:
        gm, gm_id, _ = await self.person("gm")
        cert = (await self.issue(gm))["certificate"]
        path = f"/api/v1/fields/{self.field_id}/atak/certificates/{cert['id']}/revoke"
        r = await self.client.post(path, headers=gm, json={"reason": "lost"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["certificate"]["state"], r.json()["certificate"]["revoke_reason"]),
                         ("revoked", "lost"))
        self.assertEqual((await self.client.post(path, headers=gm, json={"reason": "stolen"})).status_code, 400)
        other_gm, _, _ = await self.person("gm", field_id=self.other_id)
        r = await self.client.post(f"/api/v1/fields/{self.other_id}/atak/certificates/{cert['id']}/revoke",
                                   headers=other_gm, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "certificate_not_found"))
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/atak/log", headers=gm)
        self.assertEqual([e["action"] for e in r.json()], ["atak_cert_revoked", "atak_cert_issued"])
        self.assertEqual(r.json()[0]["details"]["reason"], "lost")

    async def test_rate_limit(self) -> None:
        gm, _, _ = await self.person("gm")
        self.app.state.limits.atak_issue.limit = 2
        await self.issue(gm)
        await self.issue(gm)
        r = await self.client.post(f"/api/v1/fields/{self.field_id}/atak/certificates", headers=gm,
                                   json={"device_name": "x"})
        self.assertEqual(r.status_code, 429)


class RelayOffTests(RelayCase):
    relay_on = False

    async def test_off_by_default_nothing_listens_and_nothing_is_issued(self) -> None:
        self.assertFalse(Settings(database_url=self.database_url, secret_key=SECRET_KEY).atak_relay)
        self.assertIsNone(self.relay)
        gm, _, _ = await self.person("gm")
        self.assertEqual((await self.issue(gm, status=409))["detail"], "atak_relay_off")
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/atak", headers=gm)
        self.assertEqual((r.json()["enabled"], r.json()["connect"]), (False, None))
        # A controller asking to relay is told the relay does not take its events.
        key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(key))
        stream = Stream(self.app, key)
        self.streams.append(stream)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "hello", "sync_version": 1, "controller": CONTROLLER, "remote_gm": False,
                           "atak": True})
        self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": False, "atak_relay": False})
        await stream.send({"type": "cot", "sync_version": 1, "controller": CONTROLLER, "events": [box()]})
        await stream.send({"type": "ping"})
        self.assertEqual(await stream.receive(), {"type": "pong"})  # the cot was dropped without an answer


class ListenerTests(RelayCase):
    async def test_props_reach_a_device_and_positions_only_an_allowed_one(self) -> None:
        gm, _, _ = await self.person("gm")
        _, _, player_name = await self.person("player")
        staff = await self.device(gm, positions=True, device_name="Posto de comando")
        plain = await self.device(gm, holder=player_name, device_name="Telemóvel")
        self.publish(box(node=1))  # before anyone connects: the current picture comes at once
        await self.connected(staff)
        await self.connected(plain)
        for d in (staff, plain):
            (got,) = await d.events(1)
            self.assertEqual(got.get("uid"), "atalaia.campo.node.1")
        self.publish(box(node=2), player())
        self.assertEqual([e.get("uid") for e in await staff.events(2)],
                         ["atalaia.campo.node.2", "atalaia.campo.player.p-abcdefghijk2"])
        (only,) = await plain.events(1)
        self.assertEqual(only.get("uid"), "atalaia.campo.node.2")
        self.assertTrue(await plain.nothing())
        # A drop goes out and is forgotten: a device that connects later does not get it.
        now = time.time()
        drop = cot.drop_xml("atalaia.campo.node.1", "b-m-p-s-m", 38.72, -9.14, now).decode()
        self.publish(drop)
        (got,) = await plain.events(1)
        self.assertLess(got.get("stale"), got.get("start"))
        late = await self.device(gm, device_name="Tarde")
        await self.connected(late)
        self.assertEqual([e.get("uid") for e in await late.events(1)], ["atalaia.campo.node.2"])
        self.assertTrue(await late.nothing())
        # The connections are logged with their certificates and addresses.
        rows = await self.fetch("SELECT details, host(ip_address) AS ip FROM audit_log WHERE action = 'atak_connect' "
                                "ORDER BY id")
        self.assertEqual([(json.loads(r["details"])["positions"], r["ip"]) for r in rows],
                         [(True, "127.0.0.1"), (False, "127.0.0.1"), (False, "127.0.0.1")])
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/atak", headers=gm)
        self.assertEqual(len(r.json()["connected"]), 3)

    async def test_strict_tls_and_a_certificate_required(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        self.assertTrue(await d.refused(self.port, d.context(with_cert=False)))
        self.assertTrue(await d.refused(self.port, d.context(max_version=ssl.TLSVersion.TLSv1_1)))
        await d.open(self.port, d.context(max_version=ssl.TLSVersion.TLSv1_2))
        assert d.writer is not None
        sslobj = d.writer.get_extra_info("ssl_object")
        self.assertEqual(sslobj.version(), "TLSv1.2")
        self.assertRegex(sslobj.cipher()[0], r"^ECDHE-ECDSA-(AES\d+-GCM-SHA\d+|CHACHA20-POLY1305)$")
        d.close()
        await d.open(self.port)
        assert d.writer is not None
        self.assertEqual(d.writer.get_extra_info("ssl_object").version(), "TLSv1.3")
        self.assertTrue(await d.nothing(0.3))
        # The relay's certificate is for the site's name, from the CA in the package.
        peer = x509.load_der_x509_certificate(d.writer.get_extra_info("ssl_object").getpeercert(True))
        names = peer.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual(names.get_values_for_type(x509.DNSName), [HOST])

    async def test_unknown_ca_and_another_fields_certificate(self) -> None:
        gm, _, _ = await self.person("gm")
        other_gm, _, _ = await self.person("gm", field_id=self.other_id)
        mine = await self.device(gm)
        theirs = await self.device(other_gm, field_id=self.other_id)
        # A certificate from a CA of the same shape that no field has: refused in the handshake.
        rogue_ca, rogue_key = await asyncio.to_thread(atak_pki.new_ca, self.field_id, "Campo")
        forged = await asyncio.to_thread(atak_pki.issue_client, rogue_ca, rogue_key, "Tablet do posto", 7)
        self.assertTrue(await mine.refused(self.port, mine.context(cert=forged.cert, key=forged.key)))
        # Another field's certificate connects to its own field and gets nothing of this one.
        await self.connected(theirs, self.other_id)
        await self.connected(mine)
        self.publish(box())
        (got,) = await mine.events(1)
        self.assertEqual(got.get("uid"), "atalaia.campo.node.4")
        self.assertTrue(await theirs.nothing())
        self.publish(box("outro", 9), field_id=self.other_id)
        self.assertEqual((await theirs.events(1))[0].get("uid"), "atalaia.outro.node.9")
        self.assertTrue(await mine.nothing())
        # A row moved to another field (a database mistake) no longer lets the certificate in.
        theirs.close()
        await self.fetch("UPDATE atak_certs SET field_id = $1 WHERE id = $2", self.field_id,
                         uuid.UUID(theirs.answer["certificate"]["id"]))
        self.assertTrue(await theirs.refused(self.port))
        self.assertEqual([e["reason"] for e in await self.audit("atak_refused")], ["other_field"])

    async def test_revoked_closes_at_once_and_is_refused_after(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        await self.connected(d)
        r = await self.client.post(f"/api/v1/fields/{self.field_id}/atak/certificates/"
                                   f"{d.answer['certificate']['id']}/revoke", headers=gm, json={})
        self.assertEqual(r.json()["closed"], 1)
        self.assertTrue(await d.closed(2.0))
        d.close()
        self.assertTrue(await d.refused(self.port))
        self.assertEqual([e["reason"] for e in await self.audit("atak_refused")], ["revoked"])
        self.assertEqual(self.relay.connected(self.field_id), [])

    async def test_expired_is_refused(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm, days=1)
        # Past its date in the database (the relay's own check): refused.
        await self.fetch("UPDATE atak_certs SET issued_at = now() - interval '3 days', "
                         "not_after = now() - interval '1 second'")
        self.assertTrue(await d.refused(self.port))
        self.assertEqual([e["reason"] for e in await self.audit("atak_refused")], ["expired"])
        # Past the date in the certificate: OpenSSL refuses it in the handshake.
        sealed = (await self.fetch("SELECT key_sealed, cert_pem FROM atak_cas"))[0]
        ca = x509.load_pem_x509_certificate(sealed["cert_pem"].encode())
        key = atak_pki.CaBox(SECRET_KEY).open(self.field_id, bytes(sealed["key_sealed"]))
        assert key is not None
        old = await asyncio.to_thread(atak_pki.issue_client, ca, key, "Antigo", 1,
                                      dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2))
        await self.fetch("INSERT INTO atak_certs (field_id, serial, sha256, device_name, holder_id, issued_at, "
                         "not_after) SELECT field_id, $1, $2, 'Antigo', holder_id, $3, $4 FROM atak_certs LIMIT 1",
                         old.serial, old.sha256, old.cert.not_valid_before_utc, old.cert.not_valid_after_utc)
        self.assertTrue(await d.refused(self.port, d.context(cert=old.cert, key=old.key)))
        self.assertEqual(len(await self.audit("atak_refused")), 1)  # never past the handshake

    async def test_an_expiring_certificate_is_closed_at_its_expiry(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        await self.fetch("UPDATE atak_certs SET not_after = now() + interval '1 second'")
        await self.connected(d)
        self.assertTrue(await d.closed(4.0))

    async def test_the_holder_and_their_role_are_checked_again(self) -> None:
        gm, _, _ = await self.person("gm")
        _, marshal_id, marshal_name = await self.person("marshal")
        d = await self.device(gm, holder=marshal_name, positions=True)
        await self.connected(d)
        self.publish(player())
        self.assertEqual(len(await d.events(1)), 1)
        # The marshal becomes a player: still connected, no more positions.
        await self.fetch("UPDATE user_field_roles SET role_id = 1 WHERE user_id = $1", marshal_id)
        await self.relay.recheck()
        self.assertEqual(self.relay.connected(self.field_id)[0]["positions"], False)
        self.publish(player(pid="p-bcdefghijk23"), box())
        self.assertEqual([e.get("type") for e in await d.events(1)], ["b-m-p-s-m"])
        self.assertTrue(await d.nothing())
        # No role on the field at all: closed, and refused from then on.
        await self.fetch("DELETE FROM user_field_roles WHERE user_id = $1", marshal_id)
        await self.relay.recheck()
        self.assertTrue(await d.closed(2.0))
        d.close()
        self.assertTrue(await d.refused(self.port))
        self.assertEqual([e["reason"] for e in await self.audit("atak_refused")], ["holder_has_no_role"])

    async def test_ping_is_answered_and_nothing_a_device_sends_goes_anywhere(self) -> None:
        gm, _, _ = await self.person("gm")
        a = await self.device(gm, device_name="A")
        b = await self.device(gm, device_name="B")
        await self.connected(a)
        await self.connected(b)
        assert a.writer is not None
        now = time.time()
        ping = cot.event_xml(uid="ANDROID-x-ping", cot_type="t-x-c-t", how="h-g-i-g-o", lat=0, lon=0, now=now,
                             start=now, stale=now + 20)
        own = cot.event_xml(uid="ANDROID-x", cot_type="a-f-G-U-C", how="m-g", lat=38.7, lon=-9.1, now=now,
                            start=now, stale=now + 60)
        a.writer.write(own + ping)
        (pong,) = await a.events(1)
        self.assertEqual((pong.get("type"), pong.get("uid")), ("t-x-c-t-r", "takPong"))
        self.assertTrue(await b.nothing())  # a device's own position reaches nobody
        # Too much without an event's end: closed.
        a.writer.write(b"<event " + b"x" * (70 * 1024))
        self.assertTrue(await a.closed(3.0))


class StreamTests(RelayCase):
    async def test_a_controller_pushes_on_its_stream(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm, positions=True)
        await self.connected(d)
        key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(key))
        stream = Stream(self.app, key)
        self.streams.append(stream)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        env = {"sync_version": 1, "controller": CONTROLLER}
        await stream.send({"type": "cot", **env, "events": [box()]})
        self.assertEqual((await stream.receive())["detail"], "hello_first")
        await stream.send({"type": "hello", **env, "remote_gm": False, "atak": True})
        self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": False, "atak_relay": True})
        await stream.send({"type": "cot", **env, "events": [box(), player()]})
        self.assertEqual([e.get("uid") for e in await d.events(2)],
                         ["atalaia.campo.node.4", "atalaia.campo.player.p-abcdefghijk2"])
        # A malformed event refuses the message; nothing of it is relayed.
        bad = box().replace('type="b-m-p-s-m"', 'type="b-f-t-r"')
        await stream.send({"type": "cot", **env, "events": [box(node=5), bad]})
        got = await stream.receive()
        self.assertEqual((got["type"], got["error"], got["path"]), ("error", "bad_type", "events[1].type"))
        self.assertTrue(await d.nothing())
        # A controller that did not ask in its hello is not relayed.
        await stream.send({"type": "hello", **env, "remote_gm": True})
        self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": True, "atak_relay": False})
        await stream.send({"type": "cot", **env, "events": [box(node=6)]})
        self.assertTrue(await d.nothing())


class BoundsTests(RelayCase):
    """The review's fixes on the relay itself (decisions FU5-14..19)."""

    async def test_the_issuer_is_in_the_connection_log(self) -> None:
        gm, gm_id, _ = await self.person("gm")
        _, marshal_id, marshal_name = await self.person("marshal")
        d = await self.device(gm, holder=marshal_name, positions=True)
        await self.connected(d)
        rows = await self.fetch("SELECT user_id, details FROM audit_log WHERE action = 'atak_connect'")
        self.assertEqual(rows[0]["user_id"], marshal_id)  # the holder
        details = json.loads(rows[0]["details"])
        self.assertEqual((details["issued_by"], details["issued_via"]), (str(gm_id), "api"))

    async def test_the_pictures_are_bounded(self) -> None:
        relay = self.relay
        t = [time.time()]
        relay.clock = lambda: t[0]
        key = (None, self.field_id)
        with mock.patch.object(atak_relay, "PICTURE_MAX", 3):
            self.publish(*(box(node=n) for n in range(1, 6)))
            self.assertEqual(list(relay.pictures[key]), [f"atalaia.campo.node.{n}" for n in (3, 4, 5)])
            self.publish(box(node=3))  # updated: now the most recent, node 4 goes next
            self.publish(box(node=6))
            self.assertEqual(list(relay.pictures[key]), [f"atalaia.campo.node.{n}" for n in (5, 3, 6)])
        # A stale time years ahead keeps an event KEEP_MAX_S at most; stale ones go at the next publish.
        self.publish(event("atalaia.campo.node.9", stale_in=5 * 365 * 86400.0))
        self.assertLessEqual(relay.pictures[key]["atalaia.campo.node.9"]["keep_until"],
                             t[0] + atak_relay.KEEP_MAX_S)
        self.publish(box(node=8))
        self.assertIn("atalaia.campo.node.9", relay.pictures[key])
        # Past KEEP_MAX_S: the next publish drops it (and everything else stale), and an empty picture goes.
        t[0] += atak_relay.KEEP_MAX_S + 1
        self.publish(drop_of("atalaia.campo.node.8"))
        self.assertNotIn(key, relay.pictures)
        relay.publish(self.other_id, [])  # a field with no devices and nothing to keep: no entry
        self.assertNotIn((None, self.other_id), relay.pictures)

    async def test_a_controllers_cot_messages_are_limited(self) -> None:
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        await self.connected(d)
        self.app.state.limits.atak_cot.limit = 1
        key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(key))
        stream = Stream(self.app, key)
        self.streams.append(stream)
        await stream.open()
        env = {"sync_version": 1, "controller": CONTROLLER}
        await stream.send({"type": "hello", **env, "remote_gm": False, "atak": True})
        await stream.receive()
        await stream.send({"type": "cot", **env, "events": [box(node=1)]})
        self.assertEqual((await d.events(1))[0].get("uid"), "atalaia.campo.node.1")
        await stream.send({"type": "cot", **env, "events": [box(node=2)]})
        self.assertEqual((await stream.receive())["detail"], "too_many_requests")
        self.assertTrue(await d.nothing())

    def test_address_groups(self) -> None:
        group = atak_relay.address_group
        self.assertEqual(group("2001:db8:1:2:aaaa::1"), group("2001:db8:1:2:ffff:1:2:3"))
        self.assertEqual(group("2001:db8:1:2::1"), "2001:db8:1:2::/64")
        self.assertNotEqual(group("2001:db8:1:2::1"), group("2001:db8:1:3::1"))
        self.assertEqual((group("192.0.2.7"), group("::ffff:192.0.2.7")), ("192.0.2.7", "192.0.2.7"))
        self.assertNotEqual(group("192.0.2.7"), group("192.0.2.8"))
        self.assertEqual(group("unknown"), "unknown")

    async def test_handshakes_have_their_own_cap(self) -> None:
        """FU5-16: connections held in their handshake fill only their own room, never the enrolled devices'."""
        gm, _, _ = await self.person("gm")
        a = await self.device(gm, device_name="A")
        b = await self.device(gm, device_name="B")
        held: list[asyncio.StreamWriter] = []
        try:
            with mock.patch.multiple(atak_relay, MAX_PENDING=2, MAX_PENDING_PER_ADDRESS=2, MAX_CONNECTIONS=3):
                await self.connected(a)
                for _ in range(2):
                    _, w = await raw_connection(self.port)
                    held.append(w)
                await self.wait_for(lambda: self.relay._pending == 2, "the handshakes were never pending")
                r, w = await raw_connection(self.port)
                held.append(w)
                self.assertTrue(await ended_at_once(r))  # the third handshake: no room
                self.publish(box())
                self.assertEqual(len(await a.events(1)), 1)  # the enrolled device is not affected
                held.pop(0).close()
                await self.wait_for(lambda: self.relay._pending < 2, "a closed handshake still counted")
                await self.connected(b)  # an enrolled device still gets in beside the held handshake
                self.assertEqual(self.relay._pending, 1)
            with mock.patch.multiple(atak_relay, MAX_PENDING=10, MAX_PENDING_PER_ADDRESS=1):
                r, w = await raw_connection(self.port)  # one address: one held handshake already
                held.append(w)
                self.assertTrue(await ended_at_once(r))
        finally:
            for w in held:
                w.close()

    async def test_the_check_runs_when_loading_cas_fails(self) -> None:
        """FU5-17's companion: a failure loading CAs never holds back the check that closes revoked devices."""
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        await self.connected(d)
        relay = self.relay
        relay._refresher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay._refresher

        async def broken() -> int:
            raise RuntimeError("a tenant's schema")

        with mock.patch.multiple(atak_relay, CA_RELOAD_S=0.05, REFRESH_S=0.05), \
                mock.patch.object(relay, "load_cas", broken):
            relay._refresher = asyncio.create_task(relay._refresh_loop())
            await self.fetch("UPDATE atak_certs SET revoked_at = now(), revoke_reason = 'revoked'")
            self.assertTrue(await d.closed(3.0))

    async def test_erasure_scrubs_the_log_and_closes_at_once(self) -> None:
        """FU5-18, FU5-19: the holder's erasure closes the device's connection at once and scrubs the
        ATAK audit rows' details as the certificate's row; the issuer's erasure takes them out of it too."""
        gm_id, gm_name, gm_secret = await self.make_user(with_totp=True)
        holder_id, holder_name, holder_secret = await self.make_user(with_totp=True)
        for user_id, role in ((gm_id, "gm"), (holder_id, "marshal")):
            await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                             user_id, self.field_id, ROLE_IDS[role])
        gm = await self.auth(gm_name, secret=gm_secret)
        d = await self.device(gm, holder=holder_name, positions=True, device_name="Telemóvel da Ana")
        await self.connected(d)
        holder = await self.auth(holder_name, secret=holder_secret)
        r = await self.client.request("DELETE", "/api/v1/me", headers=holder,
                                      json={"password": PASSWORD, "code": self.code(holder_secret)})
        self.assertEqual(r.status_code, 204, r.text)
        self.assertTrue(await d.closed(1.0))  # at once, not at the next check (REFRESH_S)
        dump = (await self.fetch("SELECT string_agg(details::text, ' ') AS all FROM audit_log"))[0]["all"]
        self.assertNotIn("Ana", dump)
        self.assertNotIn(str(holder_id), dump)
        issued, = await self.audit("atak_cert_issued")
        connect, = await self.audit("atak_connect")
        self.assertEqual((issued["device_name"], issued["holder_id"]), ("erased", None))
        self.assertEqual((connect["device_name"], connect["issued_by"]), ("erased", str(gm_id)))
        # The issuer's erasure: no ATAK row's details name them any more.
        r = await self.client.request("DELETE", "/api/v1/me", headers=gm,
                                      json={"password": PASSWORD, "code": self.code(gm_secret)})
        self.assertEqual(r.status_code, 204, r.text)
        connect, = await self.audit("atak_connect")
        self.assertIsNone(connect["issued_by"])
        self.assertEqual(connect["certificate"], d.answer["certificate"]["id"])  # what happened stays

    async def test_a_ca_rotation_closes_connections_at_once(self) -> None:
        """FU5-19: a CA made again (its key no longer opens) revokes the old certificates and closes them now."""
        gm, _, _ = await self.person("gm")
        d = await self.device(gm)
        await self.connected(d)
        await self.fetch("UPDATE atak_cas SET key_sealed = $1", b"\x00" * 64)  # as if the secret key had changed
        second = await self.issue(gm, device_name="Novo")
        self.assertTrue(await d.closed(1.0))
        rows = await self.fetch("SELECT revoke_reason FROM atak_certs WHERE id = $1",
                                uuid.UUID(d.answer["certificate"]["id"]))
        self.assertEqual(rows[0]["revoke_reason"], "ca_rotated")
        self.assertEqual(second["certificate"]["state"], "valid")


def drop_of(uid: str) -> str:
    return cot.drop_xml(uid, "b-m-p-s-m", 38.72, -9.14, time.time()).decode()


class HostedRelayTests(HubCase):
    def settings(self, url: Optional[str] = None) -> Settings:
        base = super().settings(url)
        return Settings(**{**base.__dict__, "atak_relay": True, "atak_relay_port": 0})

    async def test_the_certificates_field_picks_the_tenant(self) -> None:
        relay = self.app.state.atak_relay
        gm_a = await self.staff(self.ta, self.a, "gm")
        gm_b = await self.staff(self.tb, self.b, "gm")
        devices = {}
        for slug, client, tenant, headers in (("campo-a", self.a, self.ta, gm_a), ("campo-b", self.b, self.tb, gm_b)):
            r = await client.post(f"/api/v1/fields/{tenant.field_id}/atak/certificates", headers=headers,
                                  json={"device_name": f"Tablet {slug}"})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json()["connect"]["host"], f"{slug}.{DOMAIN}")
            d = await asyncio.to_thread(Device, r.json(), f"{slug}.{DOMAIN}")
            await d.open(relay.port)
            devices[slug] = d
        try:
            for _ in range(100):
                with tenancy.use(self.ta):
                    a_in = relay.connected(self.ta.field_id)
                with tenancy.use(self.tb):
                    b_in = relay.connected(self.tb.field_id)
                if a_in and b_in:
                    break
                await asyncio.sleep(0.02)
            self.assertEqual(([c["device_name"] for c in a_in], [c["device_name"] for c in b_in]),
                             (["Tablet campo-a"], ["Tablet campo-b"]))
            # Field A's events (as its controller's stream would publish them, in its tenant) reach A only.
            with tenancy.use(self.ta):
                relay.publish(self.ta.field_id, [sync_format.cot_event(box("a"))])
            self.assertEqual((await devices["campo-a"].events(1))[0].get("uid"), "atalaia.a.node.4")
            self.assertTrue(await devices["campo-b"].nothing())
            # Even with the same field id in another tenant (they differ, but the key is the pair).
            with tenancy.use(self.tb):
                relay.publish(self.ta.field_id, [sync_format.cot_event(box("x"))])
            self.assertTrue(await devices["campo-a"].nothing())
            # Each tenant's audit log has its own device's connection only.
            rows_a = await self.sql(self.ta, "SELECT details->>'device_name' AS d FROM audit_log "
                                    "WHERE action = 'atak_connect'")
            self.assertEqual([r["d"] for r in rows_a], ["Tablet campo-a"])
            # A suspended field's devices are refused.
            devices["campo-b"].close()
            await hosted_status(self.hub.owner_url, "campo-b", "suspended")
            try:
                self.assertTrue(await devices["campo-b"].refused(relay.port))
            finally:
                await hosted_status(self.hub.owner_url, "campo-b", "active")
        finally:
            for d in devices.values():
                d.close()


    async def test_one_tenants_failure_does_not_stop_the_others_cas(self) -> None:
        relay = self.app.state.atak_relay
        for client, tenant, headers in ((self.a, self.ta, await self.staff(self.ta, self.a, "gm")),
                                        (self.b, self.tb, await self.staff(self.tb, self.b, "gm"))):
            r = await client.post(f"/api/v1/fields/{tenant.field_id}/atak/certificates", headers=headers,
                                  json={"device_name": "Tablet"})
            self.assertEqual(r.status_code, 201, r.text)
        relay.trust.clear()  # as at a start: nothing loaded yet
        broken = dataclasses.replace(self.ta, slug="gone", schema="field_gone")

        async def tenants(engine: Any) -> list[tenancy.Tenant]:
            return [broken, self.ta, self.tb]

        with mock.patch.object(atak_relay.tenancy, "active_tenants", tenants):
            self.assertEqual(await relay.load_cas(), 1)
        self.assertEqual(sorted(e.tenant.slug for e in relay.trust.values()), ["campo-a", "campo-b"])


async def hosted_status(url: str, slug: str, status: str) -> None:
    from atalaia_server import hosted  # noqa: PLC0415

    await hosted.set_status(url, slug, status, "test", "test:operator")


def test_relay_leaf_validity_within_apple_limit() -> None:
    # Apple refuses TLS server certificates valid for more than 825 days (iOS/macOS SecTrust); a longer one breaks every iPhone's check-in over HTTPS
    from atalaia_server import atak_pki  # noqa: PLC0415

    assert atak_pki.LEAF_DAYS <= 825
