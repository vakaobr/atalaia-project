# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's own certificate authority and the controller's HTTPS certificate (ADR-P3-9, P3-8).

On first start the controller makes, in ``tls_dir``:

    ca.pem, ca.key           the field CA: ECDSA P-256, valid 10 years
    server.pem, server.key   the controller's certificate, signed by the CA, valid 1 year,
                             for its host names and addresses (subject alternative names)

The keys are written with mode 0600. The CA's fingerprint (SHA-256 of its
DER certificate) goes on the check-in poster and into join payloads (key
13); phones fetch the certificate itself from GET /api/v1/controller/ca and
pin it per field (protocol/checkin.md). The server certificate is made again
when it has less than 30 days left or when the names it must cover change;
the CA is never replaced on its own (that would break every pinned phone),
only by deleting the folder.

ADR-P3-9 sketched an Ed25519 CA. Browsers do not accept Ed25519 certificates
in TLS (the GM console runs in one), so both certificates use ECDSA P-256,
which every browser, Android and Python accept (decision PE2).
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("atalaia.tls")

CA_DAYS = 3653
SERVER_DAYS = 365
RENEW_DAYS = 30


@dataclass
class FieldTls:
    dir: Path
    ca_pem: bytes
    ca_sha256: bytes
    server_cert: Path
    server_key: Path
    names: list[str]

    @property
    def ca_der(self) -> bytes:
        from cryptography import x509  # noqa: PLC0415

        return x509.load_pem_x509_certificate(self.ca_pem).public_bytes(_der())


def _der():
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    return serialization.Encoding.DER


def local_names(extra: Iterable[str] = ()) -> list[str]:
    """The names the server certificate covers: the configured ones, localhost, this host's
    name (and name.local) and its addresses. Nothing is sent on the network to find them."""
    names: list[str] = []

    def add(n: str) -> None:
        n = n.strip()
        if n and n not in names:
            names.append(n)

    for n in extra:
        add(n)
    add("localhost")
    add("127.0.0.1")
    host = socket.gethostname()
    if host:
        add(host)
        if "." not in host:
            add(f"{host}.local")
    try:
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    # The address of the interface a packet to a private address would leave by:
    # connect() on a UDP socket picks the route and sends nothing.
    for probe in ("10.255.255.255", "192.168.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                add(s.getsockname()[0])
        except OSError:
            pass
    return [n for n in names if n != "0.0.0.0"]


def _write(path: Path, data: bytes, private: bool) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600 if private else 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    if private:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, path)


def _san(names: list[str]):
    from cryptography import x509  # noqa: PLC0415

    out = []
    for n in names:
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(n.strip("[]"))))
        except ValueError:
            out.append(x509.DNSName(n))
    return x509.SubjectAlternativeName(out)


def ensure(tls_dir: str | Path, names: list[str], field_name: str = "Atalaia",
           now: Optional[datetime.datetime] = None) -> FieldTls:
    """The field CA and a current server certificate for names, made or renewed as needed."""
    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID  # noqa: PLC0415

    d = Path(tls_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    now = now or datetime.datetime.now(datetime.timezone.utc)
    ca_key_path, ca_path = d / "ca.key", d / "ca.pem"
    key_path, cert_path = d / "server.key", d / "server.pem"
    pem = serialization.Encoding.PEM
    pkcs8 = serialization.PrivateFormat.PKCS8
    plain = serialization.NoEncryption()

    if ca_key_path.exists() and ca_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), None)
        ca_cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Atalaia field"),
                             x509.NameAttribute(NameOID.COMMON_NAME, f"{field_name[:40]} field CA")])
        ca_cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(hours=1))
                   .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                                key_encipherment=False, data_encipherment=False,
                                                key_agreement=False, key_cert_sign=True, crl_sign=True,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                                  critical=False)
                   .sign(ca_key, hashes.SHA256()))
        _write(ca_key_path, ca_key.private_bytes(pem, pkcs8, plain), private=True)
        _write(ca_path, ca_cert.public_bytes(pem), private=False)
        cert_path.unlink(missing_ok=True)
        log.warning("made the field CA in %s (fingerprint %s)", d,
                    hashlib.sha256(ca_cert.public_bytes(_der())).hexdigest())

    renew = True
    if cert_path.exists() and key_path.exists():
        try:
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            have = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            left = _not_after(cert) - now
            renew = (have != _san(names) or left < datetime.timedelta(days=RENEW_DAYS)
                     or cert.issuer != ca_cert.subject)
        except (ValueError, x509.ExtensionNotFound):
            renew = True
    if renew:
        key = ec.generate_private_key(ec.SECP256R1())
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if names else "atalaia")]))
                .issuer_name(ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(hours=1))
                .not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(_san(names), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                               critical=False)
                .sign(ca_key, hashes.SHA256()))
        _write(key_path, key.private_bytes(pem, pkcs8, plain), private=True)
        _write(cert_path, cert.public_bytes(pem) + ca_cert.public_bytes(pem), private=False)
    ca_pem = ca_cert.public_bytes(pem)
    return FieldTls(d, ca_pem, hashlib.sha256(ca_cert.public_bytes(_der())).digest(), cert_path, key_path,
                    list(names))


def _not_after(cert) -> datetime.datetime:
    value = getattr(cert, "not_valid_after_utc", None)
    if value is None:  # cryptography < 42
        value = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    return value
