# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay's certificates (Phase 4 follow-up, decisions FU5-*).

Three kinds, all X.509 v3 made with ``cryptography``:

- **A field's CA** (``new_ca``): RSA 3072, SHA-256, valid ``CA_DAYS`` (3 years), ``CA:TRUE, pathlen:0``,
  key usage ``keyCertSign`` and ``cRLSign`` only. It signs that field's client certificates and nothing
  else. Its private key is stored only sealed (``CaBox``: Fernet, under a key derived from
  ATALAIA_SECRET_KEY with HKDF under its own label, with the field's id sealed in, so a sealed key copied
  to another field's row does not open there); it is never exported. Changing ATALAIA_SECRET_KEY makes
  the sealed keys unreadable: every field gets a new CA on its next certificate and its devices must
  be enrolled again (the old certificates still verify against the old CA certificate, which is kept).
- **A device's client certificate** (``issue_client``): RSA 2048 (what TAK clients take everywhere),
  SHA-256, a random 159-bit serial, ``CA:FALSE``, ``digitalSignature, keyEncipherment``, extended key
  usage ``clientAuth`` only, the device's name as the subject's common name, valid ``days`` (1-30, 7 by
  default) from a minute ago. Its private key is made here, goes into the data package once and is never
  stored.
- **The relay's own identity** (``server_identity``): what the relay's TLS listener presents and what
  every data package's trust store holds. A CA whose P-256 key is *derived* from ATALAIA_SECRET_KEY
  (HKDF, its own label), self-signed with deterministic ECDSA (RFC 6979) and fixed dates, so it is the
  same certificate, byte for byte, after every restart and in every field: nothing to store, and a
  hosted hub's fields share the hub's one identity, as they share its HTTPS name. It signs a leaf for
  the relay's names (a fresh P-256 key at each start, valid ``LEAF_DAYS``) and nothing else.

``data_package`` builds what a TAK client imports (a "data package"/mission package ZIP):
``MANIFEST/manifest.xml``, the connection preference (``certs/atalaia.pref``: one streaming connection,
``host:port:ssl``) and two PKCS#12 files: ``certs/truststore.p12`` (the relay's CA as a trusted
certificate, Java's trust-store form) and ``certs/client.p12`` (the device's key and certificate with
the field CA), both AES-256-CBC with PBKDF2-SHA256 (PKCS#12 PBES2). The client file's password is
random, shown once to the person who issued it and **not** in the package (decision FU5-5), so the ZIP
alone does not hold a usable key; the trust store's password is in the preference file (it guards
nothing secret). The file layout follows TAK's own data packages (TAK Server's configuration guide,
"Data packages"); it is checked here by reading it back, not yet with a real ATAK device (HW3).
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import secrets
import uuid
import zipfile
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3 * 365
LEAF_DAYS = 397                 # the relay's own leaf, made again at every start
DEFAULT_DAYS = 7                # a device's certificate (decision FU5-4)
MAX_DAYS = 30
BACKDATE = dt.timedelta(minutes=1)  # clocks a little behind still accept a fresh certificate
SERVER_CA_NOT_BEFORE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
SERVER_CA_NOT_AFTER = dt.datetime(2046, 1, 1, tzinfo=dt.timezone.utc)
PACKAGE_PASSWORD_BYTES = 15     # 20 characters of base64url
TRUSTSTORE_PASSWORD = "atalaia"  # guards only the relay's public CA certificate (decision FU5-5)
DEVICE_NAME = re.compile(r"[^\x00-\x1f\x7f-\x9f]{1,48}")


class PkiError(ValueError):
    """A certificate or request that is not acceptable."""


def _derive(secret: str, label: str, length: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None,
                info=f"atalaia-server {label} v1".encode()).derive(secret.encode("utf-8"))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def sha256_hex(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def ski_hex(cert: x509.Certificate) -> str:
    return cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value.digest.hex()


def aki_hex(cert: x509.Certificate) -> Optional[str]:
    try:
        ident = cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value.key_identifier
    except x509.ExtensionNotFound:
        return None
    return ident.hex() if ident else None


def pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def check_device_name(name: object) -> str:
    if not isinstance(name, str) or name != name.strip() or not DEVICE_NAME.fullmatch(name):
        raise PkiError("device_name: 1-48 characters, no control characters, no spaces at either end")
    return name


# --- a field's CA ---------------------------------------------------------------------------------


class CaBox:
    """Seals a field CA's private key for ``atak_cas.key_sealed`` (Fernet under a key derived from
    ATALAIA_SECRET_KEY), with the field's id sealed in."""

    def __init__(self, secret_key: str) -> None:
        self._fernet = Fernet(base64.urlsafe_b64encode(_derive(secret_key, "atak ca key")))

    def seal(self, field_id: uuid.UUID, key: rsa.RSAPrivateKey) -> bytes:
        der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        body = {"field": str(field_id), "key": base64.b64encode(der).decode("ascii")}
        return self._fernet.encrypt(json.dumps(body, sort_keys=True).encode("utf-8"))

    def open(self, field_id: uuid.UUID, sealed: bytes) -> Optional[rsa.RSAPrivateKey]:
        """The key, or None (sealed under another secret key, or for another field)."""
        try:
            body = json.loads(self._fernet.decrypt(bytes(sealed)).decode("utf-8"))
        except (InvalidToken, ValueError):
            return None
        if not isinstance(body, dict) or body.get("field") != str(field_id):
            return None
        key = serialization.load_der_private_key(base64.b64decode(body["key"]), password=None)
        return key if isinstance(key, rsa.RSAPrivateKey) else None


def _name(*parts: tuple[x509.ObjectIdentifier, str]) -> x509.Name:
    return x509.Name([x509.NameAttribute(oid, value) for oid, value in parts])


def new_ca(field_id: uuid.UUID, field_name: str) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    now = _now()
    subject = _name((NameOID.ORGANIZATION_NAME, "Atalaia"),
                    (NameOID.ORGANIZATIONAL_UNIT_NAME, f"field {field_id}"),
                    (NameOID.COMMON_NAME, f"ATAK CA {field_name[:40] or field_id}"))
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - BACKDATE)
            .not_valid_after(now + dt.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski), critical=False)
            .sign(key, hashes.SHA256()))
    return cert, key


@dataclass
class Issued:
    cert: x509.Certificate
    key: rsa.RSAPrivateKey

    @property
    def sha256(self) -> str:
        return sha256_hex(self.cert)

    @property
    def serial(self) -> str:
        return format(self.cert.serial_number, "x")


def issue_client(ca_cert: x509.Certificate, ca_key: rsa.RSAPrivateKey, device_name: str, days: int,
                 now: Optional[dt.datetime] = None) -> Issued:
    check_device_name(device_name)
    if not 1 <= days <= MAX_DAYS:
        raise PkiError(f"days: 1-{MAX_DAYS}")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = now or _now()
    not_after = min(now + dt.timedelta(days=days), ca_cert.not_valid_after_utc)
    if not_after <= now:
        raise PkiError("the field's CA has expired")
    cert = (x509.CertificateBuilder()
            .subject_name(_name((NameOID.ORGANIZATION_NAME, "Atalaia"), (NameOID.COMMON_NAME, device_name)))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - BACKDATE).not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return Issued(cert, key)


# --- the relay's own identity ---------------------------------------------------------------------------


@dataclass
class ServerIdentity:
    ca: x509.Certificate
    leaf: x509.Certificate
    leaf_key: ec.EllipticCurvePrivateKey

    def chain_pem(self) -> bytes:
        return (pem(self.leaf) + pem(self.ca)).encode("ascii")

    def key_pem(self) -> bytes:
        return self.leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption())


def server_ca(secret_key: str) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """The relay's CA: the same certificate after every restart (derived key, fixed dates, RFC 6979)."""
    order = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16)  # P-256's n
    scalar = int.from_bytes(_derive(secret_key, "atak relay ca", 48), "big") % (order - 1) + 1
    key = ec.derive_private_key(scalar, ec.SECP256R1())
    subject = _name((NameOID.ORGANIZATION_NAME, "Atalaia"), (NameOID.COMMON_NAME, "Atalaia ATAK relay CA"))
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    serial = int.from_bytes(ski.digest[:16], "big") >> 1 or 1
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(serial).not_valid_before(SERVER_CA_NOT_BEFORE).not_valid_after(SERVER_CA_NOT_AFTER)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(key, hashes.SHA256(), ecdsa_deterministic=True))
    return cert, key


def server_identity(secret_key: str, names: list[str]) -> ServerIdentity:
    """The relay's CA and a fresh leaf for ``names`` (DNS names; ``*.domain`` in hosted mode)."""
    ca, ca_key = server_ca(secret_key)
    key = ec.generate_private_key(ec.SECP256R1())
    now = _now()
    sans: list[x509.GeneralName] = [x509.DNSName(n) for n in names]
    cert = (x509.CertificateBuilder()
            .subject_name(_name((NameOID.ORGANIZATION_NAME, "Atalaia"),
                                (NameOID.COMMON_NAME, (names[0] if names else "atalaia-relay")[:64])))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - BACKDATE).not_valid_after(now + dt.timedelta(days=LEAF_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256(), ecdsa_deterministic=True))
    return ServerIdentity(ca, cert, key)


# --- the data package -------------------------------------------------------------------------------------


def _p12_encryption(password: str) -> serialization.KeySerializationEncryption:
    return (serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(200_000)
            .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC).hmac_hash(hashes.SHA256())
            .build(password.encode("utf-8")))


def new_package_password() -> str:
    return secrets.token_urlsafe(PACKAGE_PASSWORD_BYTES)


def client_p12(issued: Issued, ca_cert: x509.Certificate, password: str) -> bytes:
    return pkcs12.serialize_key_and_certificates(b"atalaia-client", issued.key, issued.cert, [ca_cert],
                                                 _p12_encryption(password))


def truststore_p12(relay_ca: x509.Certificate) -> bytes:
    return pkcs12.serialize_java_truststore([pkcs12.PKCS12Certificate(relay_ca, b"atalaia-relay")],
                                            _p12_encryption(TRUSTSTORE_PASSWORD))


def _entry(key: str, cls: str, value: str) -> str:
    return f'    <entry key={quoteattr(key)} class={quoteattr("class java.lang." + cls)}>{escape(value)}</entry>\n'


def preference(description: str, host: str, port: int) -> str:
    """ATAK's preference file: one streaming connection over TLS, its trust store and client certificate
    (the client certificate's password is not here: decision FU5-5)."""
    return ("<?xml version='1.0' standalone='yes'?>\n<preferences>\n"
            '  <preference version="1" name="cot_streams">\n'
            + _entry("count", "Integer", "1") + _entry("description0", "String", description)
            + _entry("enabled0", "Boolean", "true") + _entry("connectString0", "String", f"{host}:{port}:ssl")
            + "  </preference>\n"
            '  <preference version="1" name="com.atakmap.app_preferences">\n'
            + _entry("displayServerConnectionWidget", "Boolean", "true")
            + _entry("caLocation", "String", "cert/truststore.p12")
            + _entry("caPassword", "String", TRUSTSTORE_PASSWORD)
            + _entry("certificateLocation", "String", "cert/client.p12")
            + "  </preference>\n</preferences>\n")


PACKAGE_FILES = ("certs/atalaia.pref", "certs/truststore.p12", "certs/client.p12")


def manifest(package_uid: str, name: str) -> str:
    contents = "".join(f'    <Content ignore="false" zipEntry={quoteattr(f)}/>\n' for f in PACKAGE_FILES)
    return ('<MissionPackageManifest version="2">\n  <Configuration>\n'
            f'    <Parameter name="uid" value={quoteattr(package_uid)}/>\n'
            f'    <Parameter name="name" value={quoteattr(name)}/>\n'
            '    <Parameter name="onReceiveDelete" value="true"/>\n'
            f'  </Configuration>\n  <Contents>\n{contents}  </Contents>\n</MissionPackageManifest>\n')


def package_name(field_slug: str, device_name: str) -> str:
    device = re.sub(r"[^A-Za-z0-9._-]+", "-", device_name).strip("-.")[:32] or "device"
    return f"atalaia-{field_slug[:40]}-{device}.zip"


def data_package(*, issued: Issued, field_ca: x509.Certificate, relay_ca: x509.Certificate, password: str,
                 host: str, port: int, description: str, name: str) -> bytes:
    """The ZIP a TAK client imports: manifest, preference, trust store, client certificate."""
    out = io.BytesIO()
    files = {"MANIFEST/manifest.xml": manifest(str(uuid.uuid4()), name).encode("utf-8"),
             "certs/atalaia.pref": preference(description, host, port).encode("utf-8"),
             "certs/truststore.p12": truststore_p12(relay_ca),
             "certs/client.p12": client_p12(issued, field_ca, password)}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return out.getvalue()
