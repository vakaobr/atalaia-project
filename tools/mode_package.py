#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Packs and signs mode packages with an Ed25519 mode key (protocol/mode-packages.md).

    python3 tools/mode_package.py pack modes/domination
        the package's archive, org.atalaia.domination-0.1.0.tar: the mode folder's
        mode.yaml, node.lua, field.lua and assets/ (tests/ and other files are left out),
        in the one canonical form, so the same files always give the same SHA-256
    python3 tools/mode_package.py keygen --out ~/atalaia-keys/modes-2026.pem
        a new mode key: the private key (PKCS#8 PEM, encrypted with a passphrase you type,
        mode 0600), its public halves for the controller and the firmware, and its id
    python3 tools/mode_package.py pubkey --key ~/atalaia-keys/modes-2026.pem
    python3 tools/mode_package.py sign org.club.x-0.1.0.tar --key ~/atalaia-keys/modes-2026.pem
        signs the archive's manifest (id, version, kind, minimum tier, size, SHA-256, from its
        own mode.yaml) and writes org.club.x-0.1.0.tar.release.json next to it
    python3 tools/mode_package.py verify ARCHIVE ARCHIVE.release.json --keys <base64 or hex>[,...]
            [--revoked revoked.json]
        checks a package as the controller does before it installs one
    python3 tools/mode_package.py index index.json ARCHIVE.release.json --url URL --name NAME
            [--description TEXT] [--author TEXT] [--verified]
        adds the release to a registry index (made if missing), checked against the schema

The manifest, the archive's form and every check are the shared
``controller/atalaia_controller/mode_package.py``; signing is the firmware
releases' scheme (``tools/firmware_release.py``, decision P5R-7). Private keys
never belong in the repository: ``keygen`` and ``sign`` refuse a key path inside
it. Needs the ``cryptography`` and ``PyYAML`` packages (the dev container has both).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))

from atalaia_controller import firmware_release as fr  # noqa: E402
from atalaia_controller import mode_package as mp  # noqa: E402

PASSPHRASE_ENV = "ATALAIA_MODE_KEY_PASSPHRASE"


def fail(message: str) -> int:
    print(f"mode_package: {message}", file=sys.stderr)
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
    first = getpass.getpass("Mode key passphrase: ")
    if confirm and getpass.getpass("Again: ") != first:
        raise SystemExit(fail("the passphrases differ"))
    return first.encode("utf-8")


def raw_public(key) -> bytes:
    from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def print_public(public: bytes) -> None:
    b64 = base64.b64encode(public).decode("ascii")
    print(f"key id:              {fr.key_id(b64)}")
    print(f"public key (base64): {b64}")
    print(f"public key (hex):    {public.hex()}")
    print()
    print("Field controller (controller.toml), to install packages this key signed:")
    print(f'  [modes]\n  keys = ["{b64}"]')
    print("Field Box firmware (only through a firmware release, decision P5B-9; phase 5 plan phase 13):")
    print(f'  CONFIG_ATALAIA_MODE_KEYS="{public.hex()}"')


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


def read_folder(folder: Path) -> tuple[dict[str, str], list[str]]:
    """The files of a mode folder a package carries (the controller's), and those left out."""
    files: dict[str, str] = {}
    skipped: list[str] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file() or p.is_symlink()):
        rel = path.relative_to(folder).as_posix()
        try:
            if path.is_symlink():
                raise mp.PackageError("bad_archive", "a link")
            mp.check_file_name(rel)
            files[rel] = path.read_text(encoding="utf-8")
        except (mp.PackageError, UnicodeDecodeError):
            skipped.append(rel)
    return files, skipped


def cmd_pack(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not (folder / "mode.yaml").is_file():
        return fail(f"{folder} has no mode.yaml")
    files, skipped = read_folder(folder)
    try:
        own = mp.manifest_fields(files)
        archive = mp.pack(own["id"], files)
    except mp.PackageError as exc:
        return fail(str(exc))
    out = Path(args.out) if args.out else Path(f"{own['id']}-{own['version']}.tar")
    out.write_bytes(archive)
    print(f"{out}: {own['id']} {own['version']} ({own['kind']}, {own['min_tier']}, {own['license']}), "
          f"{len(files)} files, {len(archive)} bytes, sha256 {mp.sha256(archive)}")
    for name in skipped:
        print(f"  left out: {name}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    key_path = Path(args.key).expanduser()
    if not outside_repo(key_path):
        return fail(f"{key_path} is inside the repository: move the private key out of it")
    archive_path = Path(args.archive)
    archive = archive_path.read_bytes()
    try:
        _, files = mp.unpack(archive)
        own = mp.manifest_fields(files)
    except mp.PackageError as exc:
        return fail(str(exc))
    key = load_private(key_path)
    release = mp.sign_release(key, archive)
    key_id = fr.key_id(base64.b64encode(raw_public(key)).decode("ascii"))
    out = Path(args.out) if args.out else archive_path.with_name(archive_path.name + ".release.json")
    out.write_text(json.dumps(mp.release_json(release, key_id, own["license"]), indent=2) + "\n", encoding="utf-8")
    print(f"{out}: {release.id} {release.version} ({release.kind}, {release.min_tier}), {release.size} bytes, "
          f"sha256 {release.sha256[:16]}..., key {key_id}")
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
    archive = Path(args.archive).read_bytes()
    data = json.loads(Path(args.release).read_text(encoding="utf-8"))
    revoked: dict[str, str] = {}
    try:
        if args.revoked:
            revoked = mp.parse_revoked(json.loads(Path(args.revoked).read_text(encoding="utf-8")))
        release = mp.release_from(data)
        named = data.get("key_id") if isinstance(data.get("key_id"), str) else None
        package = mp.verify(archive, release, parse_keys(args.keys), revoked, named_key=named)
    except mp.PackageError as exc:
        print(f"FAIL {exc}")
        return 1
    print(f"OK: {release.id} {release.version} ({release.kind}, {release.min_tier}, {package.license}), "
          f"{len(package.files)} files, signed by key {package.key_id}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    path = Path(args.index)
    index = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "modes": []}
    data = json.loads(Path(args.release).read_text(encoding="utf-8"))
    try:
        release = mp.release_from(data)
        mp.parse_index(index)
    except mp.PackageError as exc:
        return fail(str(exc))
    entry = {"version": release.version, "kind": release.kind, "min_tier": release.min_tier, "size": release.size,
             "sha256": release.sha256, "signature": release.signature, "key_id": data.get("key_id"),
             "license": data.get("license"), "url": args.url, "verified": bool(args.verified)}
    mode = next((m for m in index["modes"] if m.get("id") == release.id), None)
    if mode is None:
        mode = {"id": release.id, "name": args.name or release.id, "versions": []}
        index["modes"].append(mode)
        index["modes"].sort(key=lambda m: m["id"])
    if args.name:
        mode["name"] = args.name
    for key in ("description", "author"):
        if getattr(args, key):
            mode[key] = getattr(args, key)
    mode["versions"] = [v for v in mode["versions"] if v.get("version") != release.version] + [entry]
    mode["versions"].sort(key=lambda v: fr.version_key(v["version"]) or ())
    try:
        mp.parse_index(index)
    except mp.PackageError as exc:
        return fail(str(exc))
    path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: {release.id} {release.version} {'(verified)' if args.verified else '(not reviewed)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pack", help="a mode folder's package archive")
    p.add_argument("folder")
    p.add_argument("--out", default="", help="default: <id>-<version>.tar here")
    k = sub.add_parser("keygen", help="make a new mode key")
    k.add_argument("--out", required=True, help="where the private key goes (outside the repository)")
    k.add_argument("--unencrypted", action="store_true", help="no passphrase (a throw-away test key only)")
    pk = sub.add_parser("pubkey", help="the public halves of a mode key")
    pk.add_argument("--key", required=True)
    s = sub.add_parser("sign", help="sign an archive's manifest")
    s.add_argument("archive")
    s.add_argument("--key", required=True, help="the private key (PEM, outside the repository)")
    s.add_argument("--out", default="", help="default: ARCHIVE.release.json")
    v = sub.add_parser("verify", help="check a package as the controller does")
    v.add_argument("archive")
    v.add_argument("release")
    v.add_argument("--keys", required=True, help="trusted public keys, base64 or hex, separated by commas")
    v.add_argument("--revoked", default="", help="a revocation list (revoked.json)")
    i = sub.add_parser("index", help="add a signed release to a registry index")
    i.add_argument("index")
    i.add_argument("release")
    i.add_argument("--url", required=True, help="where the archive is: https://... or a path relative to the index")
    i.add_argument("--name", default="")
    i.add_argument("--description", default="")
    i.add_argument("--author", default="")
    i.add_argument("--verified", action="store_true", help="the project reviewed it (the verified badge)")
    args = parser.parse_args(argv)
    return {"pack": cmd_pack, "keygen": cmd_keygen, "pubkey": cmd_pubkey, "sign": cmd_sign, "verify": cmd_verify,
            "index": cmd_index}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
