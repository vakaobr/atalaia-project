<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Data protection impact assessment (DPIA): [FIELD OR CLUB NAME]

> **TEMPLATE for a field operator to adopt and adapt. Not legal advice.** A
> DPIA (GDPR Art. 35) is the **controller's** duty: the Atalaia project
> cannot do it for a field. This template covers the three processing
> operations of Atalaia that call for one, written from what the software
> does today and from the positions the maintainer's lawyer approved on
> 2026-10-30. Pt-PT version: `dpia-template-pt.md`; both say the same.
>
> How to read the marks:
> - **[BRACKETS]**: something the field fills in.
> - **[FIELD CHOICE: ...]**: a choice that belongs to the field operator.
> - Check every statement against what the field really does, remove what
>   does not apply (for example sharing, if the field never switches it on),
>   remove every mark, and date and sign it (section 9).
>
> Read it with `privacy-notice-en.md` (the notice says what people are told;
> this document says why the processing is justified and how its risks are
> kept small) and `dpa-template.md` (hosted mode).
>
> Version: [draft-2026-10-30]

## 1. Why a DPIA

Against the EDPB criteria (WP248 rev.01) the three operations below meet at
least two criteria each, so a DPIA is needed (Art. 35(1)):

| Operation | Criteria met |
| --- | --- |
| Violations register and bans (3) | Evaluation of people (the repeat-offender indicator); data used to decide on access to a service (a ban); possibly vulnerable people (minors playing) |
| Sharing chronograph readings between fields (4) | Combining data from different controllers; data used to decide on access to a service; possibly minors |
| Live positions during a game (5) | Systematic monitoring of location; possibly minors |

The CNPD's list of processing that requires a DPIA (Regulation 1/2018) is
also to be checked by the field. [FIELD CHOICE: record the result of that
check here.]

## 2. The field and the system

- **Controller:** [OPERATOR'S LEGAL NAME, ADDRESS, TAX NUMBER]; contact
  [EMAIL].
- **Data protection officer:** none appointed: the field is not a public
  body and its core activities are not large-scale regular and systematic
  monitoring of people or large-scale processing of special categories of
  data (Art. 37(1)). [FIELD CHOICE: change if one is appointed.]
- **Where the data is:** the field's game controller (a Raspberry Pi or a
  phone, offline); the players' phones; optionally a site server, run by the
  field or hosted by a processor, the hub operator, **in an EU data centre**.
- **Who sees the data:** the field's staff (administrators, game masters,
  marshals) as their role allows; each person sees their own data.
- **The project** writes the software and receives none of the field's data.
- **Notice:** the field's privacy notice, version [VERSION], is shown at
  sign-up and check-in.
- **Number of people:** about [NUMBER] players a year; [FIELD CHOICE: whether
  players under 18 take part, and the field's own rule for them].

## 3. Violations register and bans

### 3.1 Description

- A marshal measures a replica with a chronograph. **The reading is signed**
  by the marshal's key, so it cannot be altered afterwards without
  detection.
- A reading over the field's limit (or within its tolerance) creates a
  **violation**. The software marks the person a **"repeat offender"** when
  they have an earlier violation at the field whose outcome was more than a
  plain warning; **plain warnings do not count**. The mark is **advisory**
  and says so in the staff screens.
- Staff can record an **outcome**: `warning`, `pulled` (replica not
  allowed) or `ban`. **The software enforces none of these**: nothing
  blocks check-in, registration or login because of an outcome. A person
  decides and is logged for each one.
- A `ban` has an **end date**: 12 months by default, never longer than the
  field keeps chronograph readings. The field tells the person.
- Violations and outcomes **never leave the field** that recorded them.
- The person sees their own readings in their account or app. Readings are
  deleted after the field's retention period (365 days by default).
- The field's limits are its own rules; they are not checked against any
  law.

### 3.2 Legal basis

- **Art. 6(1)(f), legitimate interests**, assessed in section 6.
- **Not Art. 10 data.** A violation is a breach of a private field's rules,
  not a criminal offence; the field establishes no offence and its limits
  are its own.
- **No solely automated decision (Art. 22).** The repeat-offender mark is an
  indicator for staff; every outcome is set by a person.

### 3.3 Necessity and proportionality

- The least data: the per-field player identifier, the replica and the
  signed reading; no name, no date of birth, no photo, no identity document.
- The outcome stays at the field; only the readings may go to other fields
  (section 4), and only with consent.
- Bans end; the "repeat offender" mark ignores plain warnings; retention is
  limited and enforced by a daily purge.

## 4. Sharing chronograph readings between fields (optional)

### 4.1 Description

- Off by default. A field switches it on; a person with accounts at two
  fields links them with a one-time code and gives **consent per field**.
- The hub then keeps, in common tables, a copy of the **signed readings
  only** (not violations, not outcomes, not names) from each field the
  person consented for, and the staff of the other field can read them.
  Withdrawing consent, unlinking or erasing the account removes the copy.
- Purpose: replica safety. A field can see that a replica measured over the
  limit elsewhere before letting it on its own field. Staff measure the
  replica themselves before deciding anything.

### 4.2 Roles (Art. 26 and 28)

- Each field is the **controller** of its own players' data.
- The hub operator is a **processor** for each field (Art. 28), under the
  data processing agreement, and processes the shared tables as the
  processor of the fields jointly.
- **For the sharing step only, the participating fields are joint
  controllers** (Art. 26). The arrangement is a standard set of sharing
  terms that each field accepts in the software when it switches sharing on
  (acceptance, version and date recorded). Its essence, which each field's
  notice repeats (section 2.4): scope only the signed readings of people who
  consented for both fields; purpose replica safety, never marketing,
  scoring, or refusing entry on another field's readings alone; a person may
  go to **any** participating field, which handles the request or forwards
  it within 7 days; a field that finds a breach tells the others and the hub
  operator within 48 hours, and each notifies the authority for its own
  data; a field that switches sharing off stops reading and its published
  copies are deleted.
- **Legal basis for the person's data:** Art. 6(1)(a), their consent, per
  field, withdrawable at any time.

### 4.3 Necessity and proportionality

- Only the signed readings cross; consent per field; no effect on the
  person's access except through the staff's own measurement.
- Hosting is in the EU only; the hub's sub-processors are in the data
  processing agreement's annex.

## 5. Live positions during a game

### 5.1 Description

- A separate opt-in **at check-in, never ticked for you**, game by game.
  Declining never blocks check-in or play (Art. 7(4)); the player can stop
  at any time.
- While sharing and a game runs, the phone sends its latest GPS fix, or
  which of the field's Bluetooth beacons it hears strongest. The controller
  keeps **only the latest position per player for that game, and deletes it
  when the game ends**. No track is kept.
- Who sees it: the player; their squad or team, as the game mode allows;
  marshals and the game master; a remote game master **only when the field
  turns that on** (in memory only, nothing stored); staff ATAK devices, if
  the field uses ATAK. Never over the radio, MQTT, to other fields, the
  scoreboard, an event, a log or the server's database.

### 5.2 Legal basis

Art. 6(1)(a), consent, as above. Letting staff see positions serves the
purpose consented to: safety and running the game.

### 5.3 Necessity and proportionality

- Optional; the game is fully playable without it.
- Latest fix only, deleted at the end of the game; a room, not a metre,
  where beacons are used.
- Remote and ATAK relays are off by default and stored nowhere.

## 6. Legitimate interest assessment (violations register and bans)

| Step | Assessment |
| --- | --- |
| Interest | Physical safety of everyone on the field; enforcing the field's own safety rules; showing, if an injury happens, that replicas were checked. |
| Necessity | A signed record of who brought which replica at what power is the least data that lets staff act on repeated breaches; no name, only the per-field id and the replica. Without history, a person removed one day can return the next with the same replica. |
| Balancing | Data is limited to the field (outcomes) or to fields the person consented for (readings); kept for the retention period; visible only to staff and the person; no profiling beyond the one advisory indicator; no automated consequence; bans end; the person can see, contest and object. Reasonable expectation: players of airsoft fields expect chronograph checks and sanctions for over-powered replicas. |
| Result | The interest is not overridden, **provided** the safeguards are in place: an end date for bans, a contest route, the advisory label, plain warnings not counted, and limited retention. |

[FIELD CHOICE: add anything particular to the field, for example
players under 18.]

## 7. Risks to people and the measures

Rate each risk before and after the measures (low, medium, high).
[FIELD CHOICE: rate for the field.]

| Risk | Operation | Measures | Before | After |
| --- | --- | --- | --- | --- |
| A person is refused play on a wrong or stale record | 3, 4 | Readings are signed; staff measure the replica themselves; outcomes set by a person and logged; bans end; contest through the contact; the repeat-offender mark is advisory and ignores plain warnings | [ ] | [ ] |
| The register is kept too long or used for something else | 3 | Retention enforced by a daily purge; bans never outlive the readings; purpose limited in the notice and, for sharing, in the sharing terms | [ ] | [ ] |
| A person's readings reach a field they did not choose | 4 | Consent per field; linking by one-time code by the person; the copy is deleted on withdrawal, unlinking or erasure; only signed readings cross | [ ] | [ ] |
| A person cannot tell who to ask | 4 | The notice's section 2.4 gives the essence of the terms; any participating field handles a request or forwards it within 7 days | [ ] | [ ] |
| Location is used to follow or expose a player | 5 | Opt-in at check-in; latest fix only, deleted at game end; staff access listed; remote relays off by default and stored nowhere; never over the radio, MQTT or to the scoreboard | [ ] | [ ] |
| A player feels pushed to share position | 5 | Unticked separate opt-in; declining blocks nothing; staff briefed not to ask players to share [FIELD CHOICE] | [ ] | [ ] |
| Data leaks from a phone, the controller or the server | all | HTTPS everywhere; field data separated by row-level security; staff roles need two-factor login; secrets sealed on the device; backups of the hosted server for [PERIOD]; breach routine (section 8) | [ ] | [ ] |
| A younger player is processed without a parent's say | 3, 4, 5 | Accounts from 16, confirmed by a tick box; a younger player plays through check-in without an account, with the field's own parental rules [FIELD CHOICE] | [ ] | [ ] |
| Data goes outside the EU/EEA | hosted | EU data centres only; any CDN under the EU-US Data Privacy Framework or standard clauses; sign-in providers are chosen by the person; map fetching can be turned off | [ ] | [ ] |

## 8. Breaches

The field tells the CNPD within 72 hours when a breach puts people at risk
and the people without undue delay where the risk is high (Art. 33 and 34).
On a hosted server, the hub operator tells the field within 48 hours. For
shared readings, the field that finds a breach tells the other fields and
the hub operator within 48 hours. [FIELD CHOICE: who at the field does this.]

## 9. Consultation, decision and review

- **Views of the people concerned** (Art. 35(9)): [FIELD CHOICE: for example
  asked at a players' meeting; or why not appropriate].
- **Data protection officer:** none (section 2).
- **Prior consultation of the CNPD (Art. 36):** needed only if a risk stays
  **high** after the measures. [FIELD CHOICE: yes / no, why.]
- **Decision:** [APPROVED / APPROVED WITH CONDITIONS / NOT APPROVED], by
  [NAME, ROLE], on [DATE].
- **Review:** when the software or the field's rules change (new notice
  version, sharing switched on, remote game master or ATAK switched on, new
  retention period) and at least every [12] months. Next review: [DATE].
