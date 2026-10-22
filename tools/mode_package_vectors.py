#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/mode_package.json, the signed mode packages' shared vectors.

    python3 tools/mode_package_vectors.py           write the file
    python3 tools/mode_package_vectors.py --check   fail if it is stale

The Ed25519 cases ``rfc8032`` are RFC 8032 section 7.1's TEST 1 and TEST 2,
copied from the RFC (as in protocol/vectors/firmware.json); the script checks
them against the cryptography library before writing anything. The signing key
is TEST 1's, a public test key: never a mode key. The releases are this
project's manifests signed with it (Ed25519 is deterministic). The valid
archive is also read back with Python's own ``tarfile`` module, an independent
ustar reader, which must find the same files. Read by
controller/tests/test_mode_package.py (the shared Python of
controller/atalaia_controller/mode_package.py); the Field Box's C side reads the
same file in phase 5 plan phase 13. Needs the cryptography and PyYAML packages.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))

from atalaia_controller import mode_package as mp  # noqa: E402

OUT = REPO / "protocol" / "vectors" / "mode_package.json"

# RFC 8032, section 7.1, TEST 1 and TEST 2 (copied from the RFC).
RFC8032 = [
    {"name": "test_1",
     "secret_key": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "public_key": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "message": "",
     "signature": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac"
                  "c61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"},
    {"name": "test_2",
     "secret_key": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "public_key": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "message": "72",
     "signature": "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e"
                  "458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"},
]

MODE_ID = "org.example.relay"
# REUSE-IgnoreStart
FILES = {
    "mode.yaml": ("# SPDX-FileCopyrightText: 2026 Example Club\n# SPDX-License-Identifier: MIT\n"
                  f"id: {MODE_ID}\nversion: 1.2.0-rc.1\nlicense: MIT\nmin_tier: full\nkind: role\n"
                  "name: Relay\ndescription: A box that passes a message on.\n"
                  "roles:\n  relay: { requires: [team_input] }\n"),
    "node.lua": ("-- SPDX-FileCopyrightText: 2026 Example Club\n-- SPDX-License-Identifier: MIT\n"
                 "on(\"team_input.press\", function(e)\n  emit(\"x.example.relay\", { team = e.team })\nend)\n"),
    "assets/screens/relay.yaml": "template: relay\nlayout:\n  - type: label\n    text: \"Relay →\"\n",
}
# REUSE-IgnoreEnd


def private(seed_hex: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))


def check_rfc() -> None:
    for case in RFC8032:
        key = private(case["secret_key"])
        public = mp.fr.public_key_bytes(base64.b64encode(bytes.fromhex(case["public_key"])).decode())
        signature = key.sign(bytes.fromhex(case["message"]))
        if signature.hex() != case["signature"] or not mp.fr.verify_signature(
                public, bytes.fromhex(case["message"]), signature):
            raise SystemExit(f"RFC 8032 {case['name']} does not hold: the cryptography library disagrees")


def key_forms(case: dict) -> dict:
    raw = bytes.fromhex(case["public_key"])
    b64 = base64.b64encode(raw).decode()
    return {"seed": case["secret_key"], "public_key": case["public_key"], "public_key_b64": b64,
            "key_id": mp.fr.key_id(b64)}


def reheader(archive: bytes, index: int, patch, checksum: bool = True) -> bytes:
    """The archive with the header block `index` changed by patch(bytearray), its checksum redone."""
    data = bytearray(archive)
    block = bytearray(data[index * 512:(index + 1) * 512])
    patch(block)
    if checksum:
        block[148:156] = b" " * 8
        block[148:156] = format(sum(block), "o").rjust(6, "0").encode() + b"\0 "
    data[index * 512:(index + 1) * 512] = block
    return bytes(data)


def name_patch(name: bytes):
    def patch(block):
        block[0:100] = name.ljust(100, b"\0")
    return patch


def entry(name: str, text: bytes) -> bytes:
    """One raw ustar member, as pack makes them, for archives pack refuses to make."""
    head = mp._header(name.encode("ascii"), len(text))
    return head + text + b"\0" * (-len(text) % 512)


def invalid_archives(valid: bytes) -> list[dict]:
    end = b"\0" * 1024
    cases = [
        ("traversal", reheader(valid, 0, name_patch(f"{MODE_ID}/../evil.lua".encode())), "bad_archive",
         "a name that leaves the root folder"),
        ("absolute", reheader(valid, 0, name_patch(b"/etc/passwd")), "bad_archive", "an absolute name"),
        ("symlink", reheader(valid, 0, lambda b: b.__setitem__(slice(156, 157), b"2")), "bad_archive",
         "a symbolic link"),
        ("hard_link", reheader(valid, 0, lambda b: b.__setitem__(slice(156, 157), b"1")), "bad_archive",
         "a hard link"),
        ("directory", reheader(entry(f"{MODE_ID}/assets", b"") + end, 0, lambda b: b.__setitem__(slice(156, 157), b"5")),
         "bad_archive", "a folder entry"),
        ("gnu_long_name", reheader(valid, 0, lambda b: b.__setitem__(slice(156, 157), b"L")), "bad_archive",
         "a GNU long-name entry"),
        ("pax_header", reheader(valid, 0, lambda b: b.__setitem__(slice(156, 157), b"x")), "bad_archive",
         "a pax extended header"),
        ("prefix", reheader(valid, 0, lambda b: b.__setitem__(slice(345, 352), b"outside")), "bad_archive",
         "a name continued in the prefix field"),
        ("bad_checksum", reheader(valid, 0, lambda b: b.__setitem__(slice(148, 154), b"000001"), checksum=False),
         "bad_archive", "a header whose checksum is wrong"),
        ("not_ustar", reheader(valid, 0, lambda b: b.__setitem__(slice(257, 265), b"ustar  \0")), "bad_archive",
         "an old GNU tar header"),
        ("mtime", reheader(valid, 0, lambda b: b.__setitem__(slice(136, 148), b"14540000000\0")), "bad_archive",
         "a modification time: not the canonical form"),
        ("mode_755", reheader(valid, 0, lambda b: b.__setitem__(slice(100, 108), b"0000755\0")), "bad_archive",
         "an executable file: not the canonical form"),
        ("owner", reheader(valid, 0, lambda b: b.__setitem__(slice(265, 269), b"root")), "bad_archive",
         "a user name: not the canonical form"),
        ("unsorted", entry(f"{MODE_ID}/node.lua", FILES["node.lua"].encode())
         + entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode()) + end, "bad_archive",
         "files out of order: not the canonical form"),
        ("duplicate", entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode())
         + entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode()) + end, "bad_archive", "a file twice"),
        ("two_roots", entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode())
         + entry("org.example.other/node.lua", FILES["node.lua"].encode()) + end, "bad_archive",
         "files under two root folders"),
        ("file_at_root", entry("mode.yaml", FILES["mode.yaml"].encode()) + end, "bad_archive",
         "a file outside any root folder"),
        ("not_a_mode_id", entry("Relay/mode.yaml", FILES["mode.yaml"].encode()) + end, "bad_archive",
         "a root folder that is not a mode id"),
        ("tests_folder", entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode())
         + entry(f"{MODE_ID}/tests/basic.yaml", b"name: x\n") + end, "bad_archive",
         "a file the controller does not take"),
        ("dot_file", entry(f"{MODE_ID}/assets/.hidden", b"x") + entry(f"{MODE_ID}/mode.yaml", FILES["mode.yaml"].encode())
         + end, "bad_archive", "a dot segment in a name"),
        ("not_utf8", entry(f"{MODE_ID}/mode.yaml", b"\xff\xfe") + end, "bad_archive", "a file that is not UTF-8"),
        ("nul_in_text", entry(f"{MODE_ID}/mode.yaml", b"id: x\0\n") + end, "bad_archive", "a NUL in a text file"),
        ("trailing_block", valid + b"\0" * 512, "bad_archive", "a third zero block after the end"),
        ("trailing_garbage", valid[:-512] + b"x" * 512, "bad_archive", "data after the first zero block"),
        ("no_end", valid[:-1024], "bad_archive", "no end of archive"),
        ("truncated", valid[:1536], "bad_archive", "a file running past the end"),
        ("not_blocks", valid + b"\0", "bad_archive", "not a whole number of blocks"),
        ("empty", end, "bad_archive", "no files"),
    ]
    return [{"name": n, "hex": data.hex(), "code": code, "why": why} for n, data, code, why in cases]


def release_case(name, key, archive, valid, why, **change) -> dict:
    fields = mp.manifest_fields(mp.unpack(archive)[1])
    values = {"id": fields["id"], "version": fields["version"], "kind": fields["kind"],
              "min_tier": fields["min_tier"], "size": len(archive), "sha256": mp.sha256(archive)}
    signed = dict(values)
    values.update(change)
    message = mp.manifest(signed["id"], signed["version"], signed["kind"], signed["min_tier"], signed["size"],
                          signed["sha256"])
    signature = base64.b64encode(key.sign(message)).decode()
    release = mp.Release(values["id"], values["version"], values["kind"], values["min_tier"], values["size"],
                         values["sha256"], signature)
    return {"name": name, **values, "signature": signature, "manifest": release.manifest().decode(),
            "release_text": release.text().decode(), "valid": valid, "why": why}


def signed_text(key, mode_id: str, version: str, kind: str, tier: str, size: int, digest: str) -> str:
    """A release text signed with key for exactly these fields."""
    message = mp.manifest(mode_id, version, kind, tier, size, digest)
    signature = base64.b64encode(key.sign(message)).decode()
    return mp.Release(mode_id, version, kind, tier, size, digest, signature).text().decode()


def box_checks(key, archive: bytes, tampered: bytes, releases: list[dict], invalid: list[dict]) -> list[dict]:
    """A Field Box's checks of what it fetched (phase 5 plan phase 13, protocol/mode-packages.md,
    "What a box checks"), each case's result made by mp.box_check_release then mp.box_check_archive."""
    sk = key_forms(RFC8032[0])
    ok_ = next(r for r in releases if r["name"] == "release")
    keys, other = [sk["public_key_b64"]], [key_forms(RFC8032[1])["public_key_b64"]]
    size, digest = ok_["size"], ok_["sha256"]
    text = ok_["release_text"]
    traversal = bytes.fromhex(next(a["hex"] for a in invalid if a["name"] == "traversal"))
    no_script = mp.pack(MODE_ID, {"mode.yaml": FILES["mode.yaml"]})
    cases = [
        # name, release text, wanted id, keys, tier, built-in ids, archive (or None: refused before), why
        ("ok", text, MODE_ID, keys, "full", [], "archive", "a Full box, its own mode key, the signed archive"),
        ("ok_second_key", text, MODE_ID, other + keys, "full", [], "archive", "any of its mode keys will do"),
        ("no_key", text, MODE_ID, [], "full", [], None, "no mode key is built into the box"),
        ("crlf", text.replace("\n", "\r\n"), MODE_ID, keys, "full", [], None, "exactly the manifest's lines"),
        ("other_id", text, "org.example.other", keys, "full", [], None, "not the part the box asked for"),
        ("untrusted_key", text, MODE_ID, other, "full", [], None, "none of its mode keys signed it"),
        ("changed_after_signing", next(r["release_text"] for r in releases if r["name"] == "other_version"),
         MODE_ID, keys, "full", [], None, "the version was changed after signing"),
        ("scenario", signed_text(key, MODE_ID, "1.2.0-rc.1", "scenario", "reduced", size, digest), MODE_ID, keys,
         "full", [], None, "a scenario never runs on a box"),
        ("full_on_reduced", text, MODE_ID, keys, "reduced", [], None, "min_tier=full on a Reduced box"),
        ("reduced_on_reduced", signed_text(key, MODE_ID, "1.2.0-rc.1", "role", "reduced", size, digest), MODE_ID,
         keys, "reduced", [], "archive", "min_tier=reduced on a Reduced box (the box never reads mode.yaml)"),
        ("builtin", text, MODE_ID, keys, "full", [MODE_ID, "org.atalaia.domination"], None,
         "the firmware has this id: never replaced"),
        ("too_big", signed_text(key, MODE_ID, "1.2.0-rc.1", "role", "full", mp.BOX_MAX_PACKAGE_BYTES + 512, digest),
         MODE_ID, keys, "full", [], None, "over 256 KiB, refused before the download"),
        ("signature_before_tier", text, MODE_ID, other, "reduced", [], None, "the signature is checked first"),
        ("kind_before_builtin", signed_text(key, MODE_ID, "1.2.0-rc.1", "scenario", "reduced", size, digest),
         MODE_ID, keys, "full", [MODE_ID], None, "the kind is checked before the built-in ids"),
        ("tampered", text, MODE_ID, keys, "full", [], "tampered", "one byte of the archive changed"),
        ("truncated", text, MODE_ID, keys, "full", [], "truncated", "fewer bytes than signed"),
        ("not_canonical", signed_text(key, MODE_ID, "1.2.0-rc.1", "role", "full", len(traversal),
                                      mp.sha256(traversal)), MODE_ID, keys, "full", [], traversal,
         "signed, but an archive no reader takes (a path out of its root)"),
        ("no_node_lua", signed_text(key, MODE_ID, "1.2.0-rc.1", "role", "full", len(no_script),
                                    mp.sha256(no_script)), MODE_ID, keys, "full", [], no_script,
         "signed, but nothing for a box to run"),
    ]
    named = {"archive": archive, "tampered": tampered, "truncated": archive[:-512]}
    out = []
    for name, release_text, wanted, box_keys, tier, builtin, data, why in cases:
        case: dict = {"name": name, "release_text": release_text, "wanted_id": wanted, "keys": box_keys,
                      "tier": tier, "builtin": builtin}
        try:
            release, who = mp.box_check_release(release_text.encode(), wanted, box_keys, tier, builtin)
            if data is None:
                raise SystemExit(f"box check {name}: passed its release checks but has no archive")
            raw = named[data] if isinstance(data, str) else data
            case["archive"] = data if isinstance(data, str) else None
            if not isinstance(data, str):
                case["archive_hex"] = raw.hex()
            kept = mp.box_check_archive(raw, release)
            case.update(result="ok", key_id=who, kept=sorted(kept))
        except mp.PackageError as exc:
            if "archive" not in case:
                case["archive"] = None
            case["result"] = exc.code
        case["why"] = why
        out.append(case)
    return out


def reports() -> dict:
    """A box's reports (protocol/mode-packages.md, "The report"), with their MACs under a game key."""
    game_key = bytes(range(0x2b, 0x2b + 16))
    valid = [
        (4242, 7, MODE_ID, "1.2.0-rc.1", "installed", {MODE_ID: "1.2.0-rc.1", "org.club.codes": "0.3.0"}),
        (4242, 7, "org.club.codes", None, "unreachable", {}),
        (1, 65534, "org.club.codes", "0.4.0", "bad_signature", {"org.club.codes": "0.3.0"}),
    ]
    out = []
    for game, node, mode_id, version, result, kept in valid:
        body = mp.report_body(game, node, mode_id, version, result, kept)
        out.append({"game": game, "node": node, "mode": mode_id, "version": version, "result": result,
                    "kept": kept, "body": body.decode(), "mac": mp.report_mac(game_key, body)})
    good = out[0]["body"]
    KEPT = f"kept=org.club.codes@0.3.0,{MODE_ID}@1.2.0-rc.1"
    assert KEPT in good
    invalid = [
        ("unknown_result", good.replace("result=installed", "result=great"), "a known result"),
        ("game_leading_zero", good.replace("game=4242", "game=04242"), "numbers have no leading zero"),
        ("node_zero", good.replace("node=7", "node=0"), "node 1-65534"),
        ("crlf", good.replace("\n", "\r\n"), "lines end with a line feed only"),
        ("extra_line", good + "x=1\n", "nothing after kept"),
        ("bad_mode", good.replace("mode=org.example.relay", "mode=relay"), "a reverse-domain id"),
        ("bad_version", good.replace("version=1.2.0-rc.1", "version=1.2"), "MAJOR.MINOR.PATCH or -"),
        ("kept_unsorted", good.replace(KEPT, f"kept={MODE_ID}@1.2.0-rc.1,org.club.codes@0.3.0"),
         "kept sorted by id"),
        ("kept_empty", good.replace(KEPT, "kept="), "- for none"),
        ("kept_twice", good.replace(KEPT, "kept=org.club.codes@0.3.0,org.club.codes@0.3.0"), "an id once"),
        ("kept_nine", good.replace(KEPT, "kept=" + ",".join(f"org.club.m{i}@1.0.0" for i in range(9))),
         "at most 8 kept"),
        ("empty", "", "not a report"),
    ]
    for n, b, _ in invalid:
        try:
            mp.parse_report(b.encode())
        except mp.PackageError:
            continue
        raise SystemExit(f"report {n}: parse_report takes it")
    return {"game_key": game_key.hex(), "valid": out,
            "invalid": [{"name": n, "body": b, "why": w} for n, b, w in invalid]}


def build() -> dict:
    check_rfc()
    signing, other = RFC8032
    key, other_key = private(signing["secret_key"]), private(other["secret_key"])
    archive = mp.pack(MODE_ID, {k: v for k, v in FILES.items()})
    # An independent reader finds the same files.
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        members = tar.getmembers()
        read = {m.name.split("/", 1)[1]: tar.extractfile(m).read().decode() for m in members}
        if read != FILES or any(not m.isreg() or m.mtime or m.uid or m.mode != 0o644 for m in members):
            raise SystemExit("tarfile reads the canonical archive differently")
    sk = key_forms(signing)
    ok = release_case("release", key, archive, True, "signed with signing_key")
    verify_cases = [
        {"name": "ok", "release": "release", "keys": [sk["public_key_b64"]], "revoked": [], "named_key": sk["key_id"],
         "result": "ok", "why": "a trusted key signed exactly this archive's manifest"},
        {"name": "ok_two_keys", "release": "release", "keys": [key_forms(other)["public_key_b64"], sk["public_key_b64"]],
         "revoked": [], "named_key": None, "result": "ok", "why": "any trusted key will do"},
        {"name": "no_key", "release": "release", "keys": [key_forms(other)["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "no_key", "why": "the key it names is not trusted here"},
        {"name": "untrusted_unnamed", "release": "release", "keys": [key_forms(other)["public_key_b64"]],
         "revoked": [], "named_key": None, "result": "bad_signature", "why": "no trusted key signed it"},
        {"name": "revoked", "release": "release", "keys": [sk["public_key_b64"]], "revoked": [sk["key_id"]],
         "named_key": sk["key_id"], "result": "revoked", "why": "the key that signed it is revoked"},
        {"name": "no_keys", "release": "release", "keys": [], "revoked": [], "named_key": None,
         "result": "bad_signature", "why": "a controller without mode keys installs nothing signed"},
        {"name": "other_version", "release": "other_version", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "bad_signature", "why": "the version was changed after signing"},
        {"name": "other_id", "release": "other_id", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "bad_signature", "why": "the id was changed after signing"},
        {"name": "other_kind", "release": "other_kind", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "bad_signature", "why": "the kind was changed after signing"},
        {"name": "other_tier", "release": "other_tier", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "bad_signature", "why": "the tier was changed after signing"},
        {"name": "tampered_archive", "release": "release", "archive": "tampered", "keys": [sk["public_key_b64"]],
         "revoked": [], "named_key": sk["key_id"], "result": "bad_hash", "why": "one byte of the archive changed"},
        {"name": "wrong_size", "release": "wrong_size", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "bad_hash", "why": "the size does not match the archive"},
        {"name": "mismatched_manifest", "release": "lies_about_version", "keys": [sk["public_key_b64"]], "revoked": [],
         "named_key": sk["key_id"], "result": "mismatch",
         "why": "a trusted key signed a manifest whose version is not the archive's mode.yaml's"},
    ]
    tampered = bytearray(archive)
    tampered[530] ^= 1
    lying = mp.Release(ok["id"], "9.9.9", ok["kind"], ok["min_tier"], ok["size"], ok["sha256"], "")
    lying_signature = base64.b64encode(key.sign(lying.manifest())).decode()
    lying = mp.Release(lying.id, lying.version, lying.kind, lying.min_tier, lying.size, lying.sha256, lying_signature)
    releases = [
        ok,
        release_case("other_version", key, archive, False, "version changed after signing", version="1.2.0"),
        release_case("other_id", key, archive, False, "id changed after signing", id="org.example.relay2"),
        release_case("other_kind", key, archive, False, "kind changed after signing", kind="mode"),
        release_case("other_tier", key, archive, False, "min_tier changed after signing", min_tier="reduced"),
        release_case("wrong_size", key, archive, False, "size changed after signing", size=len(archive) + 512),
        {"name": "lies_about_version", "id": lying.id, "version": lying.version, "kind": lying.kind,
         "min_tier": lying.min_tier, "size": lying.size, "sha256": lying.sha256, "signature": lying.signature,
         "manifest": lying.manifest().decode(), "release_text": lying.text().decode(), "valid": False,
         "why": "signed, but its version is not the archive's"},
    ]
    text = ok["release_text"]
    texts_invalid = [
        ("crlf", text.replace("\n", "\r\n"), "lines end with a line feed only"),
        ("no_signature", ok["manifest"], "the signature line is missing"),
        ("no_final_newline", text[:-1], "the last line ends with a line feed"),
        ("extra_line", text + "key_id=" + sk["key_id"] + "\n", "nothing after the signature"),
        ("lines_swapped", text.replace("kind=role\nmin_tier=full", "min_tier=full\nkind=role"), "the lines' order is fixed"),
        ("other_header", text.replace(mp.MANIFEST_HEADER, "atalaia-firmware-release-v1"), "a firmware release is not a mode package"),
        ("size_leading_zero", text.replace(f"size={ok['size']}", f"size=0{ok['size']}"), "a size has no leading zero"),
        ("upper_case_hash", text.replace(ok["sha256"], ok["sha256"].upper()), "the hash is lower-case hex"),
        ("unknown_kind", text.replace("kind=role", "kind=plugin"), "kind is mode, modifier, role or scenario"),
        ("unknown_tier", text.replace("min_tier=full", "min_tier=huge"), "min_tier is reduced or full"),
        ("short_signature", text.replace(ok["signature"], ok["signature"][:-4]), "a signature is 64 bytes in base64"),
        ("space", text.replace("version=", "version= "), "no spaces"),
    ]
    entry_ok = {"version": ok["version"], "kind": ok["kind"], "min_tier": ok["min_tier"], "size": ok["size"],
                "sha256": ok["sha256"], "signature": ok["signature"], "key_id": sk["key_id"], "license": "MIT",
                "url": f"packages/{MODE_ID}-{ok['version']}.tar", "verified": True}
    index_ok = {"schema_version": 1, "name": "Example registry",
                "modes": [{"id": MODE_ID, "name": "Relay", "description": "A box that passes a message on.",
                           "author": "Example Club", "versions": [entry_ok]}]}

    def bad_index(name, why, **change):
        e = {**entry_ok, **change}
        return {"name": name, "index": {"schema_version": 1, "modes": [{"id": MODE_ID, "name": "Relay",
                                                                         "versions": [e]}]}, "why": why}
    index_invalid = [
        {"name": "schema_version", "index": {"schema_version": 2, "modes": []}, "why": "only version 1"},
        {"name": "extra_key", "index": {"schema_version": 1, "modes": [], "mirror": "x"}, "why": "no other keys"},
        bad_index("http_url", "only https:// or a relative path", url=f"http://example.org/{MODE_ID}.tar"),
        bad_index("parent_url", "a relative path stays under the index's folder", url="../outside.tar"),
        bad_index("licence", "only the approved licences", license="WTFPL"),
        bad_index("verified_text", "verified is true or false", verified="yes"),
        bad_index("key_id", "a key id is 16 lower-case hex digits", key_id="XYZ"),
        bad_index("kind", "a known kind", kind="plugin"),
        bad_index("too_big", "at most 1000000 bytes", size=1_000_001),
        {"name": "twice", "index": {"schema_version": 1, "modes": [
            {"id": MODE_ID, "name": "Relay", "versions": [entry_ok, entry_ok]}]}, "why": "a version listed twice"},
    ]
    revoked_ok = {"schema_version": 1, "keys": [{"key_id": sk["key_id"], "reason": "test key", "date": "2026-10-22"}]}
    return {
        "description": (
            "Signed mode packages (protocol/mode-packages.md, decisions P5R-7, P5B-10, P5C-8 to P5C-13). Made by "
            "tools/mode_package_vectors.py; checked by controller/tests/test_mode_package.py (the shared Python of "
            "controller/atalaia_controller/mode_package.py) and, from phase 5 plan phase 13, by the Field Box. "
            "rfc8032: RFC 8032 section 7.1's TEST 1 and 2, copied from the RFC. signing_key is TEST 1's key and "
            "other_key TEST 2's: public test keys, never mode keys. archive: the canonical ustar archive of the "
            "files under its id (read back by Python's tarfile too). archives_invalid: archives every reader "
            "refuses, with the code. releases: manifests of that archive signed with signing_key, some changed "
            "after signing. verify: whole checks (archive, release, trusted keys, revoked ids) and their result. "
            "release_texts_invalid: texts a reader refuses. index and index_invalid: the registry index "
            "(registry/schema/index.schema.json); revoked: a revocation list. Phase 5 plan phase 13 (a box "
            "fetching the modes it lacks, protocol/mode-packages.md, decisions P5B-10 to P5B-16, P5D-*): "
            "box_limits; box_checks: a Field Box's checks in its order (release_text, the part it asked for "
            "wanted_id, its mode keys, its tier, its built-in ids), then of the archive it downloaded (archive: "
            "'archive', 'tampered', 'truncated' (the valid one less its last block) or archive_hex; null: refused "
            "before any download), with the result (ok, with the signer's key_id and the files kept, or the "
            "refusal's code); reports: a box's reports with their HMAC-SHA256 under game_key, and bodies to "
            "refuse."),
        "rfc8032": RFC8032,
        "signing_key": sk,
        "other_key": key_forms(other),
        "archive": {"mode_id": MODE_ID, "files": FILES, "hex": archive.hex(), "size": len(archive),
                    "sha256": mp.sha256(archive), "tampered_hex": bytes(tampered).hex()},
        "archives_invalid": invalid_archives(archive),
        "releases": releases,
        "verify": verify_cases,
        "release_texts_invalid": [{"name": n, "text": t, "why": w} for n, t, w in texts_invalid],
        "index": index_ok,
        "index_invalid": index_invalid,
        "revoked": revoked_ok,
        "box_limits": {"max_package_bytes": mp.BOX_MAX_PACKAGE_BYTES, "max_fetched": mp.BOX_MAX_FETCHED,
                       "max_fetched_bytes": mp.BOX_MAX_FETCHED_BYTES},
        "box_checks": box_checks(key, archive, bytes(tampered), releases, invalid_archives(archive)),
        "reports": reports(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python3 tools/mode_package_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
