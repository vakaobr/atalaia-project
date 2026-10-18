<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: Phase 3 events, player tags and the capability proxy

- **Author(s):** The Atalaia contributors
- **Status:** Draft (written with phase 3 plan phase A, 2026-10-18; a number is given on acceptance)
- **Discussion:** to be opened with the pull request

## Summary

Three protocol additions for phase 3 (Android and players), each already specified and implemented with shared test vectors: twelve standard events and two data fields (ADR-P3-8), the player tag (ADR-P3-9), and version 1 of the capability proxy protocol between an I/O pod and a phone (ADR-P3-2). Protocol changes go through an RFC (CONTRIBUTING.md); this one records them for review.

## Motivation

Kill Confirmed, Respawn and Lives and Player Check-in need to know which player is at a prop, and the game master needs their events in the log. Android props borrow physical buttons, LEDs, NFC and LoRa from an ESP32 I/O pod, whose link must be frozen before the pod firmware and the app are written (the research named it the highest-risk item of phase 3).

## Design

**Events** (`protocol/schema/events.yaml`; the phase 2 mode pack holds 28-32; phase 4 starts at 42):

| Id | Event | Data (besides `team` and `squad`) |
| --- | --- | --- |
| 25 | `kill.confirmed` | `player`, `owner` (the tag's team); `team` is the team credited |
| 26 | `kill.denied` | `player`, `owner`; a team recovered its own player's tag |
| 27 | `team.eliminated` | (`team`: the team out of lives) |
| 33 | `money.collected` | `player`, `amount` |
| 34 | `money.deposited` | `player`, `amount` |
| 35 | `chrono.checkin` | `replica`, `player`, `reading_mps`, `bb_g` |
| 36 | `chrono.spotcheck` | `replica`, `player`, `reading_mps`, `bb_g`, `tolerance_pct` |
| 37 | `visibility.granted` | `see_team`, `duration_s`, `text` (`team`: who sees) |
| 38 | `visibility.expired` | `see_team`, `text` |
| 39 | `node.tamper` (critical) | `reason` |
| 40 | `pod.connected` (telemetry) | `fw`, `tier` |
| 41 | `pod.disconnected` (telemetry) | `reason` |

New data fields: `see_team` (key 29, string) and `tolerance_pct` (key 30, number). ADR-P3-8 listed `[player, team]` for the kill events and `[team, text]` for visibility; `owner` and `see_team`/`duration_s` say whose tag and whose positions without overloading `team`.

**Player tags** ([protocol/nfc-tag.md](../../protocol/nfc-tag.md)): `version (1) | player (1-32) | team (1) | game_id (2) | HMAC-SHA256(game key)[:16]`, as an NDEF MIME record `application/vnd.atalaia.tag`. The node's host checks a tag and gives the mode `nfc.tag` with `valid`, `player` and `team`, or `reason`; scripts never see the key.

**Capability proxy v1** ([protocol/capability-proxy.md](../../protocol/capability-proxy.md)): the USB modem's framing (sync, type, length, payload, CRC-16) on USB-OTG and BLE; IDENT, EVT, CMD (CBOR maps with integer keys) and ACK; the modem's RX, TX, TX_ACK, CMD, STATUS and ERROR shifted by 3; GATT service `4174616c-6169-6100-0000-000000000000` with three characteristics.

## Compatibility

Older nodes pass unknown event ids through as raw CBOR (ADR-P3-8); the JSON Schema of the game log gains the new events. The tag and the proxy are new formats with version bytes or fields of their own. The capability proxy skips unknown keys 6-23, so a later pod can add optional fields.

## Alternatives

- Tags keyed with a key derived from the game key (HKDF) rather than the game key itself, which also keys AES-CCM: the HMAC and the cipher are separate primitives and no attack is known, but a derived key would keep the two uses apart. Kept as ADR-P3-9 says; open question below.
- A separate framing for the pod: rejected, the pod reuses the modem's code (ADR-P3-2).

## Open questions

1. Should tags use a key derived from the game key (decision A3 in `docs/review/decisions-to-review.md`)?
2. Should the game master be able to write tags from the console (the controller holds the game key)?
