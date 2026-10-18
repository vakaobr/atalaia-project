<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Decisions to review

The maintainer asked the work to go on without waiting for answers: "if anything depends on my answers, put it per your recommendation and generate a report which we can revisit later". This file lists every question that came up and the answer chosen in the meantime. Change any answer, and the affected work is adjusted.

Status: **open** means not yet reviewed by the maintainer; **confirmed** and **changed** record the review.

## How the work is run

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| R1 | What counts as "phase 2 finished" before its report goes to the phase 3 agent? | Plan phases A to E (protocol, simulator, firmware radio, controller, GM console). Phase F needs the radio boards, so it waits for the parts. | A to E can be built and tested without hardware; F is the field test itself. | open |
| R2 | When is work committed and pushed? | After each plan phase, once the main session has verified it independently from a clean copy (builds, the CI test commands, sanitizers, a Wokwi run for firmware). | The maintainer asked for a commit and push after each phase; independent checks have caught several false "done" reports. | open |
| R4 | Documentation | The README, the per-folder docs and the bilingual project page (site/i18n/pt.yaml and en.yaml, rebuilt with tools/build_site.py) are updated in every phase, as part of that phase (maintainer's instruction). | Docs kept drifting behind the work. | confirmed |
| R3 | Phases 3, 4 and 5 are being designed in parallel. When are they implemented? | Each stays design-only until the phase before it is implemented. Its design is updated with the earlier phase's report first, and committed as documentation as soon as it is reviewed. | Their plans depend on interfaces that are still being built. | open |

## Phase 2, plan phase C (firmware radio)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| C1 | How large should the OTA slots be? | 2 MB each (was 1.5 MB), plus a 4 KB nvs_keys partition; 9.9 MB of the 16 MB flash stays free. | The image was at 87% of 1.5 MB before the radio code. The agent reports that 3 MB slots broke LittleFS in Wokwi; that needs a root cause before going further. | open |
| C2 | Which antenna gain does the EU868 power cap assume? | A conservative Kconfig default for the stock antenna, to be measured at bring-up. Conducted power = the limit minus the FEM gain minus the antenna gain, never above 25 mW ERP on the g bands and 500 mW ERP on 869.4-869.65 MHz. | The first version ignored the antenna gain and could exceed the legal limit. | open |
| C3 | How is the game key protected at rest? | NVS encryption with the ESP32-S3 HMAC (eFuse) scheme in production, and a clearly marked fallback for development boards without a burned eFuse key. The eFuse burn is a one-time provisioning step, documented in BRING_UP.md. | ADR-P2-12. Burning an eFuse cannot be undone, so it must not happen by accident on a dev board. | open |
| C4 | The radio is disabled in the Wokwi build because probing it reportedly corrupted the emulated flash. Is that acceptable? | No (maintainer's answer). It must be fixed: the Wokwi build runs with the radio enabled, the probe finds no chip and carries on, and the root cause is found. A disable is only allowed with proof of an emulator defect and the maintainer's agreement. | The radio code has never run in a runtime test, and a real driver bug could look the same. | confirmed |

## Phase 3, 4 and 5 designs

The open questions from those design runs are added here as each run reports, with the recommended answer used for now.

### Phase 5, community (design: docs/phase-5-community/)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| P5-1 | Which third language comes first, after Portuguese and English? | Spanish (es). | The largest neighbouring airsoft community, and close to Portuguese for translators. | open |
| P5-2 | Is the visual mode editor a tab in the simulator or a separate page? | A separate page at `/editor/` that uses the simulator to test a mode (ADR-P5-2). | Keeps the editor and the simulator independent while reusing the simulator to run the blocks. | open |
| P5-3 | Create the separate `atalaia-modes` registry repository now, or later? | **Not yet.** The design recommends creating it now with a placeholder index, but creating a GitHub repository changes the maintainer's account, so it waits for the maintainer's go-ahead. | Outward-facing action; the rest of the registry work (schema, signing tools, tests) can proceed in this repository first. | open |
| P5-4 | Do mode packages live in the registry repository or in authors' own repositories? | Both; the registry hosts packages for authors without their own repository. | Lowers the barrier for first-time mode authors. | open |
| P5-5 | Is a partial translation acceptable? | Yes for modes and the editor, with English as the fallback; the project page must stay 100% translated (its build check enforces it). | Community translations arrive gradually. | open |
| P5-6 | Maximum size of a mode package? | 1 MB per package. | Modes are scripts and small assets; a cap limits abuse of the registry. | open |
| P5-7 | The carrier PCB: when? | Deferred until at least three perfboard prototypes work (ADR-P5-6); KiCad 8, CERN-OHL-S-2.0. | A PCB before the hand-wired boxes are proven would likely need a respin. | open |

### Phase 4, site server and advanced play (design: docs/phase-4-site-server/)

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| P4-1 | Where does the custom-scenario compiler (YAML objectives to field.lua) run? | **Changed from the design's choice.** The design puts it on the site server with a CLI fallback (ADR-P4-6). Chosen instead: a shared Python library that runs on the field controller (the GM console calls it there), and the site server reuses the same library. To be fixed in ADR-P4-6 before phase 4 is implemented. | The site server is optional and the platform is local-first (spec sections 3 and 11); a field without a site server must still build custom scenarios. | open |
| P4-2 | How are chrono records signed? | Ed25519 key per marshal (ADR-P4-5), not HMAC. | Survives password changes and lets other fields verify a record without a shared secret. | open |
| P4-3 | How are clubs isolated in hosted mode? | A PostgreSQL schema per field, with row-level security as defence in depth (ADR-P4-4). | Export and deletion are a single schema dump or drop; RLS catches query mistakes. | open |
| P4-4 | Where do geo functions (distance, inside-zone) live? | In the C core (geo.c), exposed to node and field scripts (ADR-P4-9). | Trigonometry in Lua is slow on the ESP32, and one implementation keeps every platform identical. | open |
| P4-5 | Is two-factor login mandatory? | TOTP is mandatory for admin, GM and marshal accounts, optional for players (ADR-P4-2). | These roles can change games and penalties. Field staff may find TOTP awkward on game day, so worth confirming. | open |
| P4-6 | GDPR: is a legal review needed? | Yes, before hosted mode goes live. The design ships templates and defaults (anonymise on erasure, keep chrono signatures, retention 12 and 24 months, daily purge, PT/EN notices) that a Portuguese lawyer should review. | Hosting other clubs' player data makes the project a data processor. | open |
| P4-7 | Which database for the site server? | PostgreSQL 16 in docker-compose with Caddy for TLS and daily pg_dump backups (ADR-P4-1, ADR-P4-10). | Multi-tenant hosting and JSONB event data; it runs on a mini PC or a small VPS. | open |

### Spec questions found along the way

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| S1 | The spec (section 13) says ESP32 firmware images are "signed with Ed25519", and phase 5 signs modes with Ed25519 to match. The ESP32-S3's hardware secure boot only supports RSA-3072 or ECDSA. | Keep Ed25519 for modes and for an application-level check of OTA images, and decide separately whether to also enable hardware secure boot (RSA-3072 or ECDSA) when the firmware update path is built. | Ed25519 in software is fine for modes and update packages; hardware secure boot is a separate, one-time eFuse decision. | open |
