# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the packet codec: header, nonce, AAD, payload encode/decode.

    cd simulator && python -m unittest discover -s tests

These tests do NOT require the C core library.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from atalaia_sim.protocol import PAYLOAD_FIELDS
from atalaia_sim.packet import (
    AAD_SIZE,
    HEADER_SIZE,
    KEY_SIZE,
    MIC_SIZE,
    NONCE_SIZE,
    Header,
    aad_extract,
    ack_decode,
    ack_encode,
    claim_decode,
    claim_encode,
    cmd_decode,
    cmd_encode,
    config_decode,
    config_encode,
    header_decode,
    header_encode,
    hello_decode,
    hello_encode,
    nonce_build,
    payload_problems,
    state_decode,
    state_encode,
    time_decode,
    time_encode,
    vf_ack,
    vf_enc,
    vf_make,
    vf_prio,
    vf_version,
)


class VersionFlagsTests(unittest.TestCase):
    """Test version_flags composition and extraction."""

    def test_make_and_extract(self):
        vf = vf_make(version=1, prio=2, ack=True, enc=False)
        self.assertEqual(vf_version(vf), 1)
        self.assertEqual(vf_prio(vf), 2)
        self.assertTrue(vf_ack(vf))
        self.assertFalse(vf_enc(vf))

    def test_all_flags_set(self):
        vf = vf_make(version=7, prio=3, ack=True, enc=True)
        self.assertEqual(vf_version(vf), 7)
        self.assertEqual(vf_prio(vf), 3)
        self.assertTrue(vf_ack(vf))
        self.assertTrue(vf_enc(vf))

    def test_no_flags(self):
        vf = vf_make(version=0, prio=0, ack=False, enc=False)
        self.assertEqual(vf, 0)
        self.assertEqual(vf_version(vf), 0)
        self.assertEqual(vf_prio(vf), 0)
        self.assertFalse(vf_ack(vf))
        self.assertFalse(vf_enc(vf))


class HeaderTests(unittest.TestCase):
    """Test header encode/decode round-trip."""

    def test_round_trip(self):
        hdr = Header(
            version_flags=vf_make(1, 1, False, True),
            game_id=42,
            source=7,
            seq=1234,
            hop_limit=3,
            type=2,
        )
        raw = header_encode(hdr)
        self.assertEqual(len(raw), HEADER_SIZE)
        decoded = header_decode(raw)
        self.assertEqual(decoded.version_flags, hdr.version_flags)
        self.assertEqual(decoded.game_id, hdr.game_id)
        self.assertEqual(decoded.source, hdr.source)
        self.assertEqual(decoded.seq, hdr.seq)
        self.assertEqual(decoded.hop_limit, hdr.hop_limit)
        self.assertEqual(decoded.type, hdr.type)

    def test_max_values(self):
        hdr = Header(
            version_flags=0xFF,
            game_id=0xFFFF,
            source=0xFFFF,
            seq=0xFFFF,
            hop_limit=0xFF,
            type=0xFF,
        )
        raw = header_encode(hdr)
        decoded = header_decode(raw)
        self.assertEqual(decoded.game_id, 0xFFFF)
        self.assertEqual(decoded.source, 0xFFFF)
        self.assertEqual(decoded.seq, 0xFFFF)

    def test_zero_values(self):
        hdr = Header(0, 0, 0, 0, 0, 0)
        raw = header_encode(hdr)
        self.assertEqual(raw, b"\x00" * HEADER_SIZE)
        decoded = header_decode(raw)
        self.assertEqual(decoded.game_id, 0)

    def test_decode_too_short(self):
        with self.assertRaises(ValueError):
            header_decode(b"\x00" * 4)

    def test_big_endian_byte_order(self):
        hdr = Header(0x20, 0x0102, 0x0304, 0x0506, 0x07, 0x08)
        raw = header_encode(hdr)
        self.assertEqual(raw[0], 0x20)  # version_flags
        self.assertEqual(raw[1:3], b"\x01\x02")  # game_id BE
        self.assertEqual(raw[3:5], b"\x03\x04")  # source BE
        self.assertEqual(raw[5:7], b"\x05\x06")  # seq BE
        self.assertEqual(raw[7], 0x07)  # hop_limit
        self.assertEqual(raw[8], 0x08)  # type


class NonceTests(unittest.TestCase):
    """Test nonce construction."""

    def test_nonce_length(self):
        hdr = Header(0, 1, 2, 3, 0, 0)
        nonce = nonce_build(hdr, epoch=0)
        self.assertEqual(len(nonce), NONCE_SIZE)

    def test_nonce_components(self):
        hdr = Header(0, game_id=0x0001, source=0x0002, seq=0x0003, hop_limit=0, type=0)
        nonce = nonce_build(hdr, epoch=1)
        # game_id: 00 01
        self.assertEqual(nonce[0:2], b"\x00\x01")
        # source: 00 02
        self.assertEqual(nonce[2:4], b"\x00\x02")
        # (epoch << 16) | seq = (1 << 16) | 3 = 0x00010003
        self.assertEqual(nonce[4:8], b"\x00\x01\x00\x03")
        # 5 zero bytes
        self.assertEqual(nonce[8:13], b"\x00" * 5)

    def test_nonce_epoch_overflow(self):
        hdr = Header(0, game_id=1, source=1, seq=0xFFFF, hop_limit=0, type=0)
        nonce = nonce_build(hdr, epoch=0xFFFF)
        # (0xFFFF << 16) | 0xFFFF = 0xFFFFFFFF
        self.assertEqual(nonce[4:8], b"\xFF\xFF\xFF\xFF")


class AADTests(unittest.TestCase):
    """Test AAD extraction from header bytes."""

    def test_aad_length(self):
        raw = header_encode(Header(0x20, 1, 2, 3, 4, 5))
        aad = aad_extract(raw)
        self.assertEqual(len(aad), AAD_SIZE)

    def test_aad_skips_hop_limit(self):
        hdr = Header(0x20, 0x0001, 0x0002, 0x0003, 0xFF, 0x04)
        raw = header_encode(hdr)
        aad = aad_extract(raw)
        # AAD = bytes[0:7] + bytes[8:9], i.e. skip byte 7 (hop_limit=0xFF)
        expected = raw[0:7] + raw[8:9]
        self.assertEqual(aad, expected)
        # Verify hop_limit byte is NOT in AAD
        self.assertNotIn(bytes([0xFF]), aad[7:])

    def test_aad_too_short(self):
        with self.assertRaises(ValueError):
            aad_extract(b"\x00" * 5)


class PayloadCodecTests(unittest.TestCase):
    """Test all message payload codecs: round-trip string-keyed dicts."""

    def test_hello_round_trip(self):
        msg = {"node_name": "box-1", "platform": 1, "fw_version": "1.0.0",
               "core_version": "0.1.0", "tier": 0}
        self.assertEqual(hello_decode(hello_encode(msg)), msg)

    def test_hello_empty(self):
        self.assertEqual(hello_decode(hello_encode({})), {})

    def test_ack_round_trip(self):
        msg = {"ack_node": 7, "ack_seq": 42}
        decoded = ack_decode(ack_encode(msg))
        self.assertEqual(decoded["ack_node"], 7)
        self.assertEqual(decoded["ack_seq"], 42)

    def test_state_round_trip(self):
        msg = {"owner_team": 2, "phase": 1, "game_time_ms": 120000,
               "counters": [{"team": 1, "score": 500}]}
        decoded = state_decode(state_encode(msg))
        self.assertEqual(decoded["owner_team"], 2)
        self.assertEqual(decoded["phase"], 1)
        self.assertEqual(decoded["game_time_ms"], 120000)

    def test_cmd_round_trip(self):
        msg = {"cmd": 1, "params": '{"zone":"alpha"}', "dest": 5}
        self.assertEqual(cmd_decode(cmd_encode(msg)), msg)

    def test_time_round_trip(self):
        msg = {"game_time_ms": 120000, "game_state": 1, "duration_ms": 600000,
               "term": 1, "wall_s": 1700000000}
        self.assertEqual(time_decode(time_encode(msg)), msg)

    def test_config_round_trip(self):
        msg = {"mode_id": "domination", "role": "zone_node",
               "params": '{"cap_time":30}', "teams": ["Red", "Blue"],
               "game_seed": 42}
        self.assertEqual(config_decode(config_encode(msg)), msg)

    def test_claim_round_trip(self):
        msg = {"term": 2, "priority": 100, "node_id": 5}
        self.assertEqual(claim_decode(claim_encode(msg)), msg)


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")


class AESCCMTests(unittest.TestCase):
    """Test AES-CCM encryption/decryption (requires cryptography library)."""

    def _skip_if_no_crypto(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography library not available")

    def test_encrypt_decrypt_round_trip(self):
        self._skip_if_no_crypto()
        from atalaia_sim.packet import aes_ccm_decrypt, aes_ccm_encrypt

        key = b"\x01" * KEY_SIZE
        nonce = b"\x02" * NONCE_SIZE
        aad = b"\x03" * AAD_SIZE
        plaintext = b"hello world"

        ct, tag = aes_ccm_encrypt(key, nonce, aad, plaintext)
        self.assertEqual(len(tag), MIC_SIZE)
        self.assertNotEqual(ct, plaintext)

        result = aes_ccm_decrypt(key, nonce, aad, ct, tag)
        self.assertEqual(result, plaintext)

    def test_tampered_ciphertext_fails(self):
        self._skip_if_no_crypto()
        from cryptography.exceptions import InvalidTag
        from atalaia_sim.packet import aes_ccm_decrypt, aes_ccm_encrypt

        key = b"\x01" * KEY_SIZE
        nonce = b"\x02" * NONCE_SIZE
        aad = b"\x03" * AAD_SIZE

        ct, tag = aes_ccm_encrypt(key, nonce, aad, b"secret")
        tampered = bytes([ct[0] ^ 0xFF]) + ct[1:]
        with self.assertRaises(InvalidTag):
            aes_ccm_decrypt(key, nonce, aad, tampered, tag)

    def test_wrong_key_fails(self):
        self._skip_if_no_crypto()
        from cryptography.exceptions import InvalidTag
        from atalaia_sim.packet import aes_ccm_decrypt, aes_ccm_encrypt

        key1 = b"\x01" * KEY_SIZE
        key2 = b"\x02" * KEY_SIZE
        nonce = b"\x03" * NONCE_SIZE
        aad = b"\x04" * AAD_SIZE

        ct, tag = aes_ccm_encrypt(key1, nonce, aad, b"data")
        with self.assertRaises(InvalidTag):
            aes_ccm_decrypt(key2, nonce, aad, ct, tag)


class FullPacketTests(unittest.TestCase):
    """Test full packet encrypt/decrypt (requires cryptography library)."""

    def _skip_if_no_crypto(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography library not available")

    def test_packet_round_trip(self):
        self._skip_if_no_crypto()
        from atalaia_sim.packet import packet_decrypt, packet_encrypt

        key = b"\xAA" * KEY_SIZE
        hdr = Header(vf_make(1, 1, False, False), game_id=5, source=3, seq=100, hop_limit=2, type=2)
        payload = hello_encode({"node_name": "test-node", "role": "shell"})

        raw = packet_encrypt(hdr, epoch=0, key=key, payload=payload)
        self.assertTrue(len(raw) >= HEADER_SIZE + MIC_SIZE)

        dec_hdr, dec_payload = packet_decrypt(raw, epoch=0, key=key)
        self.assertEqual(dec_hdr.game_id, 5)
        self.assertEqual(dec_hdr.source, 3)
        self.assertEqual(dec_payload, payload)

    def test_packet_too_short(self):
        with self.assertRaises(ValueError):
            from atalaia_sim.packet import packet_decrypt
            packet_decrypt(b"\x00" * 10, epoch=0, key=b"\x00" * KEY_SIZE)


VECTORS_DIR = Path(__file__).resolve().parents[2] / "protocol" / "vectors"


class HeaderVectorTests(unittest.TestCase):
    """Test header encode/decode against protocol/vectors/header.json."""

    @classmethod
    def setUpClass(cls):
        with open(VECTORS_DIR / "header.json", encoding="utf-8") as f:
            cls.vectors = json.load(f)

    def test_valid_vectors(self):
        for v in self.vectors["valid"]:
            with self.subTest(v["name"]):
                raw = bytes.fromhex(v["bytes"])
                hdr = header_decode(raw)
                h = v["header"]
                vf = int(h["version_flags"], 16) if isinstance(h["version_flags"], str) else h["version_flags"]
                self.assertEqual(hdr.version_flags, vf)
                self.assertEqual(hdr.game_id, h["game_id"])
                self.assertEqual(hdr.source, h["source"])
                self.assertEqual(hdr.seq, h["seq"])
                self.assertEqual(hdr.hop_limit, h["hop_limit"])
                self.assertEqual(hdr.type, h["type"])
                # Re-encode must produce identical bytes.
                self.assertEqual(header_encode(hdr), raw)

    def test_invalid_vectors(self):
        for v in self.vectors.get("invalid", []):
            with self.subTest(v["name"]):
                raw = bytes.fromhex(v["bytes"])
                hdr = header_decode(raw)
                # Invalid headers should have version != 1 or reserved bit set.
                vf = hdr.version_flags
                version = (vf >> 5) & 0x07
                reserved = vf & 0x01
                self.assertTrue(version != 1 or reserved != 0,
                                f"expected invalid header: {v['reason']}")


class PayloadVectorTests(unittest.TestCase):
    """Test payload encode/decode against protocol/vectors/*.json."""

    def _run_payload_vectors(self, filename, encode_fn, decode_fn):
        """Every valid vector decodes to its fields and re-encodes to the same bytes;
        every invalid one is flagged by payload_problems (the C tests do the same)."""
        path = VECTORS_DIR / filename
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        msg_type = filename.split(".")[0].upper()
        self.assertTrue(data["valid"])
        for v in data["valid"]:
            with self.subTest(v["name"]):
                expected_cbor = bytes.fromhex(v["cbor"])
                decoded = decode_fn(expected_cbor)
                self.assertEqual(decoded, _vector_fields(msg_type, v["fields"]))
                self.assertEqual(payload_problems(msg_type, decoded), [])
                self.assertEqual(encode_fn(decoded), expected_cbor,
                                 f"{v['name']}: re-encoded CBOR differs from vector")
        for v in data.get("invalid", []):
            with self.subTest(v["name"]):
                try:
                    decoded = decode_fn(bytes.fromhex(v["cbor"]))
                except Exception:
                    continue  # not even CBOR: rejected
                self.assertNotEqual(payload_problems(msg_type, decoded), [], v["reason"])

    def test_hello_vectors(self):
        self._run_payload_vectors("hello.json", hello_encode, hello_decode)

    def test_ack_vectors(self):
        self._run_payload_vectors("ack.json", ack_encode, ack_decode)

    def test_state_vectors(self):
        self._run_payload_vectors("state.json", state_encode, state_decode)

    def test_cmd_vectors(self):
        self._run_payload_vectors("cmd.json", cmd_encode, cmd_decode)

    def test_time_vectors(self):
        self._run_payload_vectors("time.json", time_encode, time_decode)

    def test_config_vectors(self):
        self._run_payload_vectors("config.json", config_encode, config_decode)

    def test_claim_vectors(self):
        self._run_payload_vectors("claim.json", claim_encode, claim_decode)


def _vector_fields(msg_type, fields):
    """The JSON vector fields as the decoder returns them (bytes as hex, map keys as text)."""
    out = {}
    for name, value in fields.items():
        kind = PAYLOAD_FIELDS[msg_type][name].type
        if kind == "bytes":
            value = bytes.fromhex(value)
        elif kind in ("map_u8_u32", "map_u16_u16"):
            value = {int(k): v for k, v in value.items()}
        out[name] = value
    return out


class RFC3610Tests(unittest.TestCase):
    """Published AES-128-CCM test vector from RFC 3610, section 8.

    Source: D. Whiting, R. Housley, N. Ferguson, "Counter with CBC-MAC
    (CCM)", RFC 3610, September 2003, Packet Vector #1.
    https://www.rfc-editor.org/rfc/rfc3610#section-8

    Parameters: 13-byte nonce, 8-byte tag, 8-byte AAD, 23-byte payload.
    """

    def test_rfc3610_packet_vector_1(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM

        key = bytes.fromhex("C0C1C2C3C4C5C6C7C8C9CACBCCCDCECF")
        nonce = bytes.fromhex("00000003020100A0A1A2A3A4A5")
        aad = bytes.fromhex("0001020304050607")
        pt = bytes.fromhex("08090A0B0C0D0E0F101112131415161718191A1B1C1D1E")
        # Copied from the RFC, not computed, so a broken backend fails.
        expected_ct = bytes.fromhex("588C979A61C663D2F066D0C2C0F989806D5F6B61DAC384")
        expected_tag = bytes.fromhex("17E8D12CFDF926E0")

        cipher = AESCCM(key, tag_length=8)
        result = cipher.encrypt(nonce, pt, aad)
        ct = result[:-8]
        tag = result[-8:]
        self.assertEqual(ct, expected_ct)
        self.assertEqual(tag, expected_tag)

        decrypted = cipher.decrypt(nonce, result, aad)
        self.assertEqual(decrypted, pt)


class AESCCMVectorTests(unittest.TestCase):
    """Test AES-CCM against protocol/vectors/aes_ccm.json."""

    def _skip_if_no_crypto(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography library not available")

    def test_aes_ccm_vectors(self):
        self._skip_if_no_crypto()
        from atalaia_sim.packet import aes_ccm_encrypt, aes_ccm_decrypt

        path = VECTORS_DIR / "aes_ccm.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        for v in data["vectors"]:
            with self.subTest(v["name"]):
                key = bytes.fromhex(v["key"])
                expected_nonce = bytes.fromhex(v["nonce"])
                expected_aad = bytes.fromhex(v["aad"])
                plaintext = bytes.fromhex(v["plaintext"])
                expected_ct = bytes.fromhex(v["ciphertext"])
                expected_tag = bytes.fromhex(v["tag"])

                # Verify nonce construction
                h = v["header"]
                vf = int(h["version_flags"], 16) if isinstance(h["version_flags"], str) else h["version_flags"]
                hdr = Header(vf, h["game_id"], h["source"], h["seq"], h["hop_limit"], h["type"])
                nonce = nonce_build(hdr, v["epoch"])
                self.assertEqual(nonce, expected_nonce)

                # Verify AAD construction
                raw_hdr = header_encode(hdr)
                aad = aad_extract(raw_hdr)
                self.assertEqual(aad, expected_aad)

                # Encrypt and compare
                ct, tag = aes_ccm_encrypt(key, nonce, aad, plaintext)
                self.assertEqual(ct, expected_ct)
                self.assertEqual(tag, expected_tag)

                # Decrypt and verify
                result = aes_ccm_decrypt(key, nonce, aad, ct, tag)
                self.assertEqual(result, plaintext)


if __name__ == "__main__":
    unittest.main()
