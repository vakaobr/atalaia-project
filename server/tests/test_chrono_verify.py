# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server's verification of synced chrono readings (``chrono_verify``, P4R15), no database.

The shared vectors (``protocol/vectors/chrono_record.json``, also checked by the
controller's Python and the app's Dart) go through it as the sync delivers them,
the record's JSON text; then tampered records and the key periods: which of a
marshal's keys was valid when the controller received the reading (P4R14).
Also run by tools/check.sh.
"""

from __future__ import annotations

import base64
import copy
import json
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import atalaia_server  # noqa: E402,F401  (puts ../controller on the path)
from atalaia_controller import chrono  # noqa: E402
from atalaia_server.chrono_verify import Key, same_record, verify_reading  # noqa: E402

VECTORS = json.loads((SERVER.parent / "protocol" / "vectors" / "chrono_record.json").read_text(encoding="utf-8"))
PUBLIC = bytes.fromhex(VECTORS["public_key"])
SEED = bytes.fromhex(VECTORS["seed"])
T = 1792333805.0  # when the controller received the readings (after the vectors' timestamps)
KEY = Key(id="k1", public_key=PUBLIC, valid_from=T - 86400)
E95 = chrono.round_half_away(chrono.energy_j(0.2, 95.0), 3)  # the first vector's BB at 95 m/s


def text(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False)


def sign(record: dict, seed: bytes = SEED) -> dict:
    """The record signed again (for tampering that keeps the format valid)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    out = {k: v for k, v in record.items() if k != "signature"}
    out["signature"] = base64.b64encode(Ed25519PrivateKey.from_private_bytes(seed).sign(chrono.canonical(out))).decode()
    return out


def keys(*ks: Key):
    return lambda marshal_id: list(ks) if marshal_id == "m-xyz789" else []


class VectorTests(unittest.TestCase):
    def test_every_valid_record_verifies(self) -> None:
        for vector in VECTORS["valid"]:
            with self.subTest(vector=vector["name"]):
                verdict = verify_reading(text(vector["record"]), T, keys(KEY))
                self.assertTrue(verdict.ok, verdict.detail)
                self.assertIs(verdict.key, KEY)
                self.assertEqual(verdict.fields["reading_id"], vector["record"]["reading_id"])
                self.assertEqual(json.dumps(verdict.fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                                 vector["canonical"])

    def test_every_invalid_record_is_refused_with_its_reason(self) -> None:
        for vector in VECTORS["invalid"]:
            with self.subTest(vector=vector["name"]):
                verdict = verify_reading(text(vector["record"]), T, keys(KEY))
                self.assertFalse(verdict.ok)
                self.assertEqual(verdict.reason, vector["reason"], verdict.detail)

    def test_the_text_may_differ_the_values_may_not(self) -> None:
        """Member order, spaces and 100 for 100.0 do not matter (the canonical form is over the values)."""
        record = next(v for v in VECTORS["valid"] if v["name"] == "retest_whole_number")["record"]
        shuffled = json.dumps(dict(reversed(list(record.items()))), indent=2).replace("100.0", "100")
        self.assertTrue(verify_reading(shuffled, T, keys(KEY)).ok)
        self.assertTrue(same_record(shuffled, text(record)))
        self.assertFalse(same_record(shuffled, text({**record, "chrono_id": "x"})))


class TamperedTests(unittest.TestCase):
    """Records changed after the marshal signed them, each still in the format: the signature catches it."""

    def setUp(self) -> None:
        self.record = copy.deepcopy(VECTORS["valid"][0]["record"])
        self.assertTrue(verify_reading(text(self.record), T, keys(KEY)).ok)

    def assert_refused(self, record: dict, reason: str = "signature") -> None:
        verdict = verify_reading(text(record), T, keys(KEY))
        self.assertEqual((verdict.ok, verdict.reason), (False, reason), verdict.detail)

    def test_a_lower_velocity_with_its_energy(self) -> None:
        v = 95.0
        self.assert_refused({**self.record, "velocity_mps": v,
                             "energy_j": chrono.round_half_away(chrono.energy_j(self.record["bb_weight_g"], v), 3)})

    def test_another_player_replica_marshal_name_field_or_time(self) -> None:
        for name, value in (("player_id", "p-18"), ("replica_id", "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f51"),
                            ("marshal_name", "Josefina"), ("field_id", "outro-campo"),
                            ("timestamp", "2026-10-18T14:30:01Z"), ("type", "spotcheck"), ("game_id", "4243")):
            with self.subTest(field=name):
                self.assert_refused({**self.record, name: value})

    def test_a_dropped_optional_field(self) -> None:
        self.assert_refused({k: v for k, v in self.record.items() if k != "game_id"})

    def test_another_records_signature(self) -> None:
        other = VECTORS["valid"][1]["record"]
        self.assert_refused({**self.record, "signature": other["signature"]})

    def test_signed_by_someone_else(self) -> None:
        self.assert_refused(sign({**self.record, "velocity_mps": 95.0, "energy_j": E95}, seed=bytes(32)))

    def test_re_signed_with_the_marshals_key_is_genuine(self) -> None:
        """Only the key's holder can change a record: re-signed with the marshal's own key it verifies."""
        changed = sign({**self.record, "velocity_mps": 95.0, "energy_j": E95})
        self.assertTrue(verify_reading(text(changed), T, keys(KEY)).ok)

    def test_not_json_or_not_an_object(self) -> None:
        for bad in ("{not json", "[1, 2]", '"a"', "null"):
            with self.subTest(text=bad):
                self.assertEqual(verify_reading(bad, T, keys(KEY)).reason, "format")
        self.assert_refused({k: v for k, v in self.record.items() if k != "signature"}, "unsigned")
        sig = self.record["signature"]
        self.assert_refused({**self.record, "signature": sig[:10] + "-" + sig[11:]}, "format")  # not standard base64


class KeyPeriodTests(unittest.TestCase):
    """Which key: the marshal's keys valid when the controller received the reading (P4R14)."""

    record = VECTORS["valid"][0]["record"]

    def verdict(self, *ks: Key, at: float = T):
        return verify_reading(text(self.record), at, keys(*ks))

    def test_unknown_marshal(self) -> None:
        verdict = self.verdict()
        self.assertEqual((verdict.ok, verdict.reason), (False, "marshal"))
        self.assertEqual(verdict.reading_id, self.record["reading_id"])
        self.assertEqual(verdict.text_field("player_id"), "p-17")

    def test_a_key_not_yet_registered_or_already_replaced(self) -> None:
        self.assertEqual(self.verdict(Key("k", PUBLIC, valid_from=T + 1)).reason, "marshal")
        self.assertEqual(self.verdict(Key("k", PUBLIC, valid_from=T - 100, valid_until=T - 1)).reason, "marshal")
        self.assertTrue(self.verdict(Key("k", PUBLIC, valid_from=T - 100, valid_until=T)).ok)

    def test_a_rotation_keeps_the_old_keys_records(self) -> None:
        """The marshal's phone was replaced: the old key verifies what it signed in its own period."""
        old = Key("old", PUBLIC, valid_from=T - 1000, valid_until=T + 10)
        new = Key("new", base64.b64decode("axowl0m4jLGAOVG3dvi1Ja7n+MwrAk9IC85eKprtfB4=")[::-1], valid_from=T + 10)
        verdict = self.verdict(old, new)
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.key.id, "old")
        # The same reading claimed to arrive after the rotation: only the new key counts, and it did not sign.
        self.assertEqual(self.verdict(old, new, at=T + 20).reason, "signature")

    def test_overlapping_keys_try_each(self) -> None:
        """Two controllers' clocks can overlap two keys' periods: any key valid then may have signed."""
        other = Key("other", bytes(range(32)), valid_from=T - 10)
        verdict = self.verdict(other, KEY)
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.key.id, "k1")

    def test_a_revoked_key(self) -> None:
        """Revoked as compromised: nothing received after the revocation verifies with it, earlier still does."""
        revoked = Key("k", PUBLIC, valid_from=T - 100, revoked_at=T - 1)
        self.assertEqual(self.verdict(revoked).reason, "marshal")
        self.assertTrue(self.verdict(Key("k", PUBLIC, valid_from=T - 100, revoked_at=T + 1)).ok)


if __name__ == "__main__":
    unittest.main()
