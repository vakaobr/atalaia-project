<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Chrono records

A chrono record is one shot through the chronograph at a field's check-in or during a spot check, entered by a marshal and signed with the marshal's own Ed25519 key, so that anyone who trusts that marshal's public key (the controller, the site server, another field) can tell the record has not been changed since (ADR-P3-7 as changed by decision P3-1, ADR-P4-5). This file is the format, version 1.

Implementations: `app/lib/chrono/reading.dart` and `app/lib/chrono/record_signer.dart` (Dart: the marshal's phone signs; the canonical form is `app/lib/security/canonical_json.dart`) and `controller/atalaia_controller/chrono.py` (Python: the controller verifies, and the site server imports the same module to verify the synced records, `server/atalaia_server/chrono_verify.py`). Both check the shared vectors in [`vectors/chrono_record.json`](vectors/chrono_record.json): valid records with their exact canonical bytes and signatures, invalid ones with the reason they must fail, number and energy rounding cases, and RFC 8032's Ed25519 known answers.

## The record

A JSON object:

```json
{
  "reading_id": "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b",
  "replica_id": "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50",
  "player_id": "p-17",
  "type": "checkin",
  "velocity_mps": 102.5,
  "bb_weight_g": 0.2,
  "energy_j": 1.051,
  "chrono_id": "chrono-field-1",
  "marshal_id": "m-xyz789",
  "marshal_name": "Jose",
  "game_id": "4242",
  "field_id": "field-cqb-porto",
  "timestamp": "2026-10-18T14:30:00Z",
  "signature": "<88 characters of base64>"
}
```

| Field | Required | Value |
| --- | --- | --- |
| `reading_id` | yes | this record's id: a UUID in lowercase (`8-4-4-4-12` hex digits) |
| `replica_id` | yes | the replica's id in the field's registry, a lowercase UUID |
| `player_id` | yes | an id: 1-64 ASCII letters, digits, `.`, `_`, `:` or `-` (a player tag's id fits) |
| `type` | yes | `checkin`, `spotcheck` or `retest` |
| `velocity_mps` | yes | the measured velocity in m/s: more than 0, at most 1000, at most 2 decimals |
| `bb_weight_g` | yes | the BB (or ball) weight in grams: more than 0, at most 10, at most 3 decimals |
| `energy_j` | yes | `0.5 * (bb_weight_g / 1000) * velocity_mps * velocity_mps`, computed in that order in binary64 and rounded half away from zero to 3 decimals |
| `chrono_id` | yes | the chronograph's id |
| `marshal_id` | yes | the marshal's id |
| `marshal_name` | yes | the marshal's name as shown: 1-64 Unicode characters, no control characters (U+0000-U+001F, U+007F-U+009F), no lone surrogates; not normalised |
| `game_id` | no | the game the reading belongs to; absent before a game (a morning check-in) |
| `field_id` | yes | the field's id |
| `timestamp` | yes | when the shot was entered: `YYYY-MM-DDTHH:MM:SSZ`, UTC, whole seconds, a real date |
| `ref_reading_id` | retest: yes; spotcheck: optional; checkin: no | the reading a retest repeats (records are append-only: a retest never changes the failed record), or the check-in a spot check was compared with |
| `signature` | to verify | the marshal's Ed25519 signature: 64 bytes in standard base64 with padding (88 characters) |

Readers refuse any other field, a missing required field, and a value of the wrong JSON type (ids are strings even when they look like numbers; numbers are numbers, though a whole number may be written either `100` or `100.0`). Every shot is its own record; a check-in or spot check of three to five shots is judged by its highest `energy_j` (`app/lib/chrono/spot_check.dart`).

The ADR's list of fields is kept; `ref_reading_id` is new (ADR-P3-7 says a retest references the original reading but names no field), `game_id` became optional (ADR-P4-1's records have no game for a pre-game check-in), and the ranges, decimals and character sets are new. Decisions B3-B6 in `docs/review/decisions-to-review.md`.

## The signed bytes

The marshal signs the record's **canonical form**: the record without `signature`, written as

1. one JSON object, its members sorted by key (all keys are ASCII, so code-point and byte order agree), with no whitespace anywhere;
2. strings in UTF-8, escaping only `"` (as `\"`) and `\` (as `\\`): the characters that would need other escapes are not allowed in any field;
3. numbers as the shortest decimal that reads back as the same binary64 value, in plain notation with at least one digit after the point: `0.2`, `100.0`, `106.68`, `1.051`. Every value the ranges allow is 0 or between 0.0001 and 5000, where Python's `repr(float)` and Dart's `double.toString()` agree on this form;
4. absent optional fields are left out (never `null`).

This is exactly, in Python,

```python
json.dumps(record_without_signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

with the three numbers as `float` (the snippet in ADR-P4-5), so the site server can use it as it stands. The first vector's canonical form is

```
{"bb_weight_g":0.2,"chrono_id":"chrono-field-1","energy_j":1.051,"field_id":"field-cqb-porto","game_id":"4242","marshal_id":"m-xyz789","marshal_name":"Jose","player_id":"p-17","reading_id":"3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b","replica_id":"8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50","timestamp":"2026-10-18T14:30:00Z","type":"checkin","velocity_mps":102.5}
```

The canonical form is defined over the values, not the text a record travelled in: a verifier parses the record, checks it, and writes the canonical form again. The text may have its members in any order, spaces, `100` for `100.0` or `é` for `é`.

## The signature

```
signature = base64(Ed25519.sign(marshal_private_key, canonical_form))
```

Ed25519 is RFC 8032's pure variant: no pre-hash, no context. The private key is a 32-byte seed made and kept on the marshal's phone (`app/lib/chrono/record_signer.dart`); it never leaves it, and no copy of it exists anywhere else, encrypted or not. Only the 32-byte public key travels: to the field controller (`PUT /api/v1/checkin/me/marshal-key` or `POST /api/v1/marshals`), which keeps the marshal's current key and the earlier ones with their periods, and from there to the site server (`POST /api/v1/sync/marshals`, [`sync.md`](sync.md)), which keeps public keys only, each with the period it was the marshal's key, and links one to a marshal's account when the marshal registers it there. A lost phone means a new key; the old key keeps its period, so the records it signed still verify. *(Corrected 2026-10-20, plan phase 14: this sentence said the private key was also kept encrypted on the site server for recovery, as ADR-P4-5 first had it. It never was: decision P4R14 and ADR-P4-5's amendment keep private keys on the phones, and the code has no such copy.)* Ed25519 is deterministic, so the vectors fix the signatures too. Non-canonical signatures (S not below the group order) are refused, as RFC 8032 requires; the `signature_s_not_reduced` vector checks it.

Any change to any field, the marshal's name and the time included, breaks the signature. Nothing binds a record to one key except the verifier's choice of public key: the controller and the site server look the key up by `marshal_id` (keeping old keys after a rotation, ADR-P4-5). The site server takes the marshal's keys that were valid when the controller received the reading, by the controller's clock (decision S14-2).

## Checking a record

A reader checks, in this order: the fields (`format`), that there is a signature (`unsigned`) and that it is 64 bytes of canonical base64 (`format`), then Ed25519 with the marshal's public key (`signature`). Only then is the record valid.

## Units

Chronographs show m/s or fps. One foot is 0.3048 m exactly; a velocity entered in fps is converted, then rounded half away from zero to 2 decimals (350 fps is 106.68 m/s), and the energy computed from the rounded velocity. The `max_fps_020` figures in the limit templates are the same limit in fps with 0.20 g BBs, for display; the limit is `max_energy_j` (`app/lib/chrono/limit_template.dart`).

## Personal data

A record links a player to a measurement, so it is personal data: the field operator keeps it for its retention period (12 months by default) and deletes a player's records on request (ADR-P3-7; `app/lib/chrono/retention.dart` has the rules). A signature does not stop a record from being deleted.
