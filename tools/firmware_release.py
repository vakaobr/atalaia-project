#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Signs Field Box firmware releases with an Ed25519 release key (protocol/firmware-update.md).

    python3 tools/firmware_release.py keygen --out ~/atalaia-keys/release-2026.pem
        a new release key: the private key (PKCS#8 PEM, encrypted with a passphrase you type,
        mode 0600), and its public halves for the firmware (hex), the controller and the site
        server (base64), and its id
    python3 tools/firmware_release.py pubkey --key ~/atalaia-keys/release-2026.pem
        the public halves of an existing key
    python3 tools/firmware_release.py sign firmware/esp32/build/atalaia_esp32.bin \\
            --key ~/atalaia-keys/release-2026.pem
        signs the image's manifest (platform, version, size, SHA-256) and writes
        atalaia_esp32.bin.release.json next to it: what the GM uploads with the image
    python3 tools/firmware_release.py verify IMAGE IMAGE.release.json --keys <base64 or hex>[,...]
        checks a release as a box would (signature, size, hash, descriptors)

The manifest is exactly the one the site server's catalogue, the field controller and
the box check: the shared ``controller/atalaia_controller/firmware_release.py``. The
image's own descriptors give its version, variant and board; the tool refuses to sign
an image whose descriptors are missing or do not match --version.

Private keys never belong in the repository: ``keygen`` and ``sign`` refuse a key path
inside it. The key ceremony is ``firmware/esp32/docs/RELEASE_SIGNING.md``. Needs the
``cryptography`` package (the dev container has it; elsewhere ``pip install cryptography``).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))

from atalaia_controller import firmware_release as fr  # noqa: E402

PASSPHRASE_ENV = "ATALAIA_RELEASE_KEY_PASSPHRASE"


def fail(message: str) -> int:
    print(f"firmware_release: {message}", file=sys.stderr)
    return 1


def outside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO)
    except ValueError:
        return True
    return False


def passphrase(confirm: bool) -> bytes:
    value = os.environ.get(PASSPHRASE_ENV)
    if value is not None:
        return value.encode("utf-8")
    first = getpass.getpass("Release key passphrase: ")
    if confirm and getpass.getpass("Again: ") != first:
        raise SystemExit(fail("the passphrases differ"))
    return first.encode("utf-8")


def public_forms(public: bytes) -> dict[str, str]:
    b64 = base64.b64encode(public).decode("ascii")
    return {"base64": b64, "hex": public.hex(), "key_id": fr.key_id(b64)}


def print_public(public: bytes) -> None:
    p = public_forms(public)
    print(f"key id:              {p['key_id']}")
    print(f"public key (base64): {p['base64']}")
    print(f"public key (hex):    {p['hex']}")
    print()
    print("Firmware (sdkconfig, or menuconfig > Firmware updates):")
    print(f'  CONFIG_ATALAIA_OTA_RELEASE_KEYS="{p["hex"]}"')
    print("Field controller (controller.toml):")
    print(f'  [firmware]\n  release_keys = ["{p["base64"]}"]')
    print("Site server (environment):")
    print(f"  ATALAIA_FIRMWARE_KEYS={p['base64']}")


def load_private(path: Path):
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    data = path.read_bytes()
    try:
        key = serialization.load_pem_private_key(data, None)
    except TypeError:  # encrypted: it needs its passphrase
        key = serialization.load_pem_private_key(data, passphrase(confirm=False))
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit(fail(f"{path} is not an Ed25519 private key"))
    return key


def raw_public(key) -> bytes:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def cmd_keygen(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    out = Path(args.out).expanduser()
    if not outside_repo(out):
        return fail(f"{out} is inside the repository: a private key never goes there")
    if out.exists():
        return fail(f"{out} exists; a key is never overwritten")
    key = Ed25519PrivateKey.generate()
    encryption = (serialization.NoEncryption() if args.unencrypted
                  else serialization.BestAvailableEncryption(passphrase(confirm=True)))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with open(fd, "wb") as f:
        f.write(pem)
    print(f"private key: {out} (keep it offline; back it up)")
    print_public(raw_public(key))
    return 0


def cmd_pubkey(args: argparse.Namespace) -> int:
    print_public(raw_public(load_private(Path(args.key).expanduser())))
    return 0


def describe(image: bytes) -> fr.ImageInfo:
    try:
        return fr.image_info(image[:fr.IMAGE_HEAD])
    except fr.ReleaseError as exc:
        raise SystemExit(fail(f"not an Atalaia Field Box image: {exc.detail}")) from None


def cmd_sign(args: argparse.Namespace) -> int:
    key_path = Path(args.key).expanduser()
    if not outside_repo(key_path):
        return fail(f"{key_path} is inside the repository: move the private key out of it")
    image_path = Path(args.image)
    image = image_path.read_bytes()
    info = describe(image)
    version = args.version or info.version
    if fr.version_key(version) is None:
        return fail(f"version {version!r}: MAJOR.MINOR.PATCH with an optional -pre-release")
    if info.version != version or info.project != fr.PROJECT_NAME:
        return fail(f"the image says {info.project} {info.version}, not {fr.PROJECT_NAME} {version}")
    if args.platform not in fr.PLATFORM_NAMES:
        return fail(f"platform: one of {', '.join(fr.PLATFORM_NAMES)}")
    key = load_private(key_path)
    sha = hashlib.sha256(image).hexdigest()
    signature = base64.b64encode(key.sign(fr.manifest(args.platform, version, len(image), sha))).decode("ascii")
    public = public_forms(raw_public(key))
    release = {"format": fr.MANIFEST_HEADER, "platform": args.platform, "version": version, "size": len(image),
               "sha256": sha, "signature": signature, "key_id": public["key_id"], "variant": info.variant,
               "board": info.board}
    out = Path(args.out) if args.out else image_path.with_name(image_path.name + ".release.json")
    out.write_text(json.dumps(release, indent=2) + "\n", encoding="utf-8")
    print(f"{out}: {args.platform} {version}, {len(image)} bytes, sha256 {sha[:16]}..., "
          f"variant {info.variant}, board {info.board}, key {public['key_id']}")
    if info.variant != "box":
        print(f"note: a '{info.variant}' build installs only on '{info.variant}' boards; Field Boxes take 'box' "
              "images (and the controller accepts only those)")
    return 0


def parse_keys(text: str) -> list[str]:
    keys = []
    for item in (k.strip() for k in text.split(",")):
        if not item:
            continue
        try:
            raw = bytes.fromhex(item) if len(item) == 64 else base64.b64decode(item, validate=True)
        except ValueError:
            raw = b""
        if len(raw) != 32:
            raise SystemExit(fail(f"{item!r} is not a public key (64 hex digits or 44 base64 characters)"))
        keys.append(base64.b64encode(raw).decode("ascii"))
    return keys


def cmd_verify(args: argparse.Namespace) -> int:
    image = Path(args.image).read_bytes()
    release = json.loads(Path(args.release).read_text(encoding="utf-8"))
    keys = parse_keys(args.keys)
    sha = hashlib.sha256(image).hexdigest()
    problems = []
    if release.get("size") != len(image):
        problems.append(f"size: the release says {release.get('size')}, the image has {len(image)} bytes")
    if release.get("sha256") != sha:
        problems.append("sha256: the image is not the one signed")
    signer = fr.signer(keys, release.get("platform"), release.get("version"), release.get("size"),
                       release.get("sha256"), release.get("signature"))
    if signer is None:
        problems.append("signature: no given key signed this manifest")
    info = describe(image)
    if info.version != release.get("version"):
        problems.append(f"version: the image says {info.version}, the release {release.get('version')}")
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return 1
    print(f"OK: {release['platform']} {release['version']} ({info.variant}, {info.board}), signed by key {signer}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    k = sub.add_parser("keygen", help="make a new release key")
    k.add_argument("--out", required=True, help="where the private key goes (outside the repository)")
    k.add_argument("--unencrypted", action="store_true",
                   help="no passphrase (a throw-away bench key only, never a release key)")
    p = sub.add_parser("pubkey", help="the public halves of a release key")
    p.add_argument("--key", required=True)
    s = sub.add_parser("sign", help="sign an image's release manifest")
    s.add_argument("image")
    s.add_argument("--key", required=True, help="the private key (PEM, outside the repository)")
    s.add_argument("--version", default="", help="checked against the image's own version (default: that)")
    s.add_argument("--platform", default="esp32s3")
    s.add_argument("--out", default="", help="default: IMAGE.release.json")
    v = sub.add_parser("verify", help="check a release as a box would")
    v.add_argument("image")
    v.add_argument("release")
    v.add_argument("--keys", required=True, help="trusted public keys, base64 or hex, separated by commas")
    args = parser.parse_args(argv)
    return {"keygen": cmd_keygen, "pubkey": cmd_pubkey, "sign": cmd_sign, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
