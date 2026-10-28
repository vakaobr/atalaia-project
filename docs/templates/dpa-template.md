<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Data processing agreement (template): hosted Atalaia site server

> **DRAFT. Template, not legal advice. Not yet reviewed by a lawyer.** A
> draft by the Atalaia project for a hosted site server (ADR-P4-4, plan
> phase 21), where one party runs the server for fields that are not its
> own. It follows GDPR Article 28(3). It must be reviewed by a lawyer who
> knows the GDPR and Portuguese Law 58/2019 before it is signed, and before
> any hosted service goes live (decision P4-6). Text in [BRACKETS] is to be
> filled in; **[LAWYER: ...]** marks a choice for the lawyer. Updated
> 2026-10-28 to match the processing the software does today and the field's
> privacy notice (`privacy-notice-en.md`, Part A), which it must be kept in
> step with. English only for now; a Portuguese version is to be made with
> the legal review.

Between **[FIELD OPERATOR'S LEGAL NAME]**, [ADDRESS], [TAX NUMBER] (the
**controller**), and **[HOSTED SERVICE OPERATOR'S LEGAL NAME]**, [ADDRESS],
[TAX NUMBER] (the **processor**), together the parties.

## 1. Subject and duration

The processor runs an Atalaia site server for the controller's field(s)
[FIELD NAMES] under the service agreement of [DATE] (the service). This
agreement covers the personal data processed in the service and lasts as
long as the service does, plus the time needed for section 10.

## 2. Nature and purpose

Hosting, storing, backing up and serving the data the controller's site
server holds, so that the controller can run its games: accounts and login
methods, roles, sessions and the security log; [when used:] games and
results, chronograph records, registrations and scheduled games, clubs, the
scenario library, ATAK certificates, and relaying live data in memory (the
remote game master and the remote ATAK relay). The processor also performs
the operator's own commands on the controller's instruction (create,
suspend, resume, export or delete the controller's field, set quotas, a
custom host name). No other purpose: the processor does not read the data
for its own purposes, does not profile, and does not sell or share it.

The controller is the data controller of the data of each field it runs.
**Each hosted field is separate**: one database schema per field with
row-level security, and an account at one field is not linked to an account
at another.

## 3. Categories of data subjects and data

- Data subjects: players, staff (marshals, game masters, administrators)
  and people registering for the controller's games.
- Data: usernames, optional email addresses, password hashes, encrypted
  two-factor secrets, passkeys' public parts and names, linked social
  sign-ins (the provider's name and its opaque subject only; no email, no
  name), roles, sessions (refresh-token hashes, connection addresses and
  user agents), a security log, consent records; [when used:] per-field
  pseudonymous player identifiers, game events and scores, signed
  chronograph readings, violations (with a repeat-offender indicator),
  replica descriptions and registry entries, registration data (a display
  name, a team preference, an optional association membership number and
  its expiry, a hash of a ticket, whether the person came or paid), clubs
  and their members, ATAK certificates (device names, the issuer, the
  addresses of connections), the remote game master's command log (account
  and command), images the controller uploads.
- **Positions** are not stored by the site server. They pass **through its
  memory only** for the remote game master and the remote ATAK relay, when
  the controller has switched them on, and are neither stored nor logged
  (decision PKD-5). The processor must not store, log or copy them, and its
  logging must be set so that they do not appear in any log or trace.
- Not processed: check-in names, the game key, tokens (a controller's
  GM and read tokens never reach the site server), and special categories
  of data (GDPR Art. 9). [LAWYER: confirm that none of the above is a
  special category; in particular association membership.]

## 4. Instructions

The processor processes the data only on the controller's documented
instructions, this agreement and the controller's settings in the service
being such instructions, including for transfers outside the EU/EEA, unless
EU or Portuguese law requires otherwise (in which case it tells the
controller first, unless that law forbids it). It tells the controller at
once if it thinks an instruction infringes data protection law.

## 5. Confidentiality

Everyone who can access the data for the processor is bound to
confidentiality.

## 6. Security (GDPR Art. 32)

At least: encryption in transit (TLS) and at rest [DESCRIBE: disk
encryption, encrypted backups]; each field's data in its own database schema
with row-level security (ADR-P4-4); the server's database role owning
nothing and without superuser or row-security bypass; administrator access
with two-factor login only; passwords stored as Argon2id hashes, refresh
tokens and tickets as SHA-256 hashes, two-factor secrets and the field CA's
key encrypted with the server's secret key, which the processor keeps
outside the database and the backups; security updates applied [WITHIN N
DAYS]; daily backups kept [30] days and a tested restore; the retention
periods of the controller's privacy notice applied by the daily purge (03:00
UTC, once per field); the operator's access to a field's data limited to
what an instruction needs, and each operator command written to the hub's
audit log with its reason. [ANNEX: the full list of measures.]

## 7. Sub-processors

The controller authorises these sub-processors: [HOSTING PROVIDER, ITS
ADDRESS, THE DATA CENTRE'S COUNTRY]; [BACKUP STORAGE PROVIDER]; [ANY
TUNNEL, CDN OR DNS SERVICE IN FRONT OF THE SERVER, which sees the traffic
(addresses, and the content unless TLS ends at the processor)]; [EMAIL
SERVICE, if the server sends email]. The sign-in providers (Google,
Microsoft, Apple) are **not** sub-processors: they act for themselves at the
person's own choice. The
processor tells the controller of any intended change [N DAYS] in advance,
and the controller may object. Each sub-processor is bound by the same
obligations as this agreement, and the processor remains liable for it.

## 8. Helping the controller

The processor helps the controller, as far as it can, to answer data
subjects' requests (the service's access, export, rectification and
erasure functions, and the field's own data export, do most of this), and
with security, breach notification, data protection impact assessments and
prior consultation (GDPR Art. 32-36). A person's erasure, as the service
applies it (anonymises the account, deletes roles, sessions, social logins,
passkeys and links to player identifiers, keeps signed chronograph
readings and game results without the link) is the controller's chosen
way; copies in backups are covered by section 10. [LAWYER: confirm.]

## 9. Personal data breaches

The processor tells the controller of a personal data breach without undue
delay and **within 48 hours** of becoming aware of it, with what it knows
(nature, categories and approximate numbers of people and records, likely
consequences, measures taken), so that the controller can notify the CNPD
within 72 hours (GDPR Art. 33) and, where needed, the people affected.

## 10. End of the service

At the end of the service the processor, at the controller's choice,
returns all the data (the operator's `export` of the field's schema: one ZIP
with a manifest, a README and each table as CSV, with the SHA-256 of each
file; or the field's own data export) and/or deletes it (the operator's
`delete` command for the field), including copies and backups within [30]
days, unless EU or Portuguese law requires it to keep them; it confirms the
deletion in writing.

## 11. Audits

The processor makes available all information needed to show that it
meets this agreement and allows for and contributes to audits, including
inspections, by the controller or an auditor it appoints, [WITH N DAYS'
NOTICE, AT MOST ONCE A YEAR UNLESS THERE WAS A BREACH].

## 12. Law and courts

Portuguese law; the courts of [CITY].

Signed: [PLACE, DATE, NAMES, SIGNATURES]
