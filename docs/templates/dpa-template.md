<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Data processing agreement (template): hosted Atalaia site server

> **Template, not legal advice.** A draft by the Atalaia project for a
> hosted site server (ADR-P4-4, plan phase 21), where one party runs the
> server for fields that are not its own. It follows GDPR Article 28(3). It
> must be reviewed by a lawyer who knows the GDPR and Portuguese Law 58/2019
> before it is signed, and before any hosted service goes live (decision
> P4-6). Text in [BRACKETS] is to be filled in. English only for now; a
> Portuguese version is to be made with the legal review.

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
server holds, so that the controller can run its games: accounts, roles,
sessions and the security log; [when used:] games, results, chronograph
records, registrations and scheduled games. No other purpose.

## 3. Categories of data subjects and data

- Data subjects: players, staff (marshals, game masters, administrators)
  and people registering for the controller's games.
- Data: usernames, optional email addresses, password hashes, encrypted
  two-factor secrets, roles, connection addresses and user agents, a
  security log, consent records; [when used:] per-field pseudonymous player
  identifiers, game events and scores, signed chronograph readings and
  replica descriptions, registration data (a name, an optional federation
  number). No positions (they never reach a site server), no special
  categories of data (GDPR Art. 9).

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
with row-level security (ADR-P4-4); administrator access with two-factor
login only; passwords stored as Argon2id hashes; security updates applied
[WITHIN N DAYS]; daily backups kept 30 days and a tested restore; the
retention periods of the controller's privacy notice applied by the daily
purge. [ANNEX: the full list of measures.]

## 7. Sub-processors

The controller authorises these sub-processors: [HOSTING PROVIDER, ITS
ADDRESS, THE DATA CENTRE'S COUNTRY]; [BACKUP STORAGE PROVIDER]. The
processor tells the controller of any intended change [N DAYS] in advance,
and the controller may object. Each sub-processor is bound by the same
obligations as this agreement, and the processor remains liable for it.

## 8. Helping the controller

The processor helps the controller, as far as it can, to answer data
subjects' requests (the service's access, export, rectification and
erasure functions do most of this), and with security, breach notification,
data protection impact assessments and prior consultation (GDPR Art.
32-36).

## 9. Personal data breaches

The processor tells the controller of a personal data breach without undue
delay and **within 48 hours** of becoming aware of it, with what it knows
(nature, categories and approximate numbers of people and records, likely
consequences, measures taken), so that the controller can notify the CNPD
within 72 hours (GDPR Art. 33) and, where needed, the people affected.

## 10. End of the service

At the end of the service the processor, at the controller's choice,
returns all the data (an export of the field's schema in a documented,
machine-readable format) and/or deletes it, including copies and backups
within [30] days, unless EU or Portuguese law requires it to keep them; it
confirms the deletion in writing.

## 11. Audits

The processor makes available all information needed to show that it
meets this agreement and allows for and contributes to audits, including
inspections, by the controller or an auditor it appoints, [WITH N DAYS'
NOTICE, AT MOST ONCE A YEAR UNLESS THERE WAS A BREACH].

## 12. Law and courts

Portuguese law; the courts of [CITY].

Signed: [PLACE, DATE, NAMES, SIGNATURES]
