<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Documentation

## Design specification

The full design specification is in [`design-spec.md`](design-spec.md):
architecture, platforms, reference hardware, protocol, game runtime, apps,
security, roadmap and decision log.

## Protocol documents

| Document | What it covers |
| --- | --- |
| [`../protocol/usb-modem.md`](../protocol/usb-modem.md) | Framing between the field controller and the USB radio modem (sync byte, CRC-16, ping watchdog) |
| [`../protocol/join.md`](../protocol/join.md) | Join payload encoding: version byte, CBOR body, HMAC-SHA256 tag, NFC and QR forms |

## RFCs

Protocol changes go through the RFC process in [`rfcs/`](rfcs/).
[`rfcs/README.md`](rfcs/README.md) explains the process.

| RFC | Status | Summary |
| --- | --- | --- |
| [RFC 0001](rfcs/0001-skirmesh-rf-wire-format.md) | Accepted | Skirmesh-RF wire format, encryption, duty cycle, join, failover. Amendment 1: single shared game channel (869.525 MHz g2). Amendment 2: join payload encoding. |

## Decisions to review

Open design questions that need a maintainer decision are tracked in
[`review/decisions-to-review.md`](review/decisions-to-review.md).

## Phase folders

Each implementation phase has its own folder with `RESEARCH.md`, `ADR.md`,
`PLAN.md`, `STATUS.md`, and (once implementation begins) `IMPLEMENTATION.md`.

| Folder | Phase | Status |
| --- | --- | --- |
| [`phase-1-single-box/`](phase-1-single-box/) | 1 · Single box | Software complete; hardware gate pending |
| [`phase-2-field-network/`](phase-2-field-network/) | 2 · Field network | Software complete (A–E); mode pack in progress; hardware gate (F) pending |
| [`phase-3-android-players/`](phase-3-android-players/) | 3 · Android and players | Software of plan phases A-F done (E without the Android controller shell); field test (G) pending |
| [`phase-4-site-server/`](phase-4-site-server/) | 4 · Site server and advanced play | Planning complete; implementation pending |
| [`phase-5-community/`](phase-5-community/) | 5 · Community | Planning; ongoing after release |

## Hardware build guides

| Document | What it covers |
| --- | --- |
| [`../hardware/field-box/BUILD.md`](../hardware/field-box/BUILD.md) | Step-by-step Field Box build: parts, wiring, enclosure, first flash from Windows, troubleshooting |
| [`../hardware/field-box/README.md`](../hardware/field-box/README.md) | Bill of materials and pin table |

## Firmware guides

| Document | What it covers |
| --- | --- |
| [`../firmware/esp32/docs/BRING_UP.md`](../firmware/esp32/docs/BRING_UP.md) | Hardware bring-up runbook: first-boot smoke test through the 2-hour stability gate |
| [`../firmware/esp32/docs/WOKWI.md`](../firmware/esp32/docs/WOKWI.md) | Running the Field Box firmware in the Wokwi emulator, without hardware |
