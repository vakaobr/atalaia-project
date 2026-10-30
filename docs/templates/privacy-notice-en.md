<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Privacy notice: [FIELD OR CLUB NAME] (Atalaia app, field controller and site server)

> **DRAFT. Not legal advice. Not yet reviewed by a lawyer.** This is the
> first full draft written by the Atalaia project from what the software
> does today (2026-10-28). The maintainer will have it reviewed by a lawyer
> who knows the GDPR and Portuguese Law 58/2019 **before** any field uses
> it, and before any hosted service goes live (decision P4-6). Nothing here
> is a promise by the project to anyone: it is text for the field operator
> to check, fill in and adopt as its own.
>
> **Status 2026-10-30.** The maintainer's lawyer has approved the legal
> positions this template now states: the legal bases, the card check for
> association membership, the minimum age, transfers, the joint-control terms
> for sharing, how bans end and are contested. The maintainer has decided
> the data protection officer, position data and game-history retention.
> The marks that remain are the points still open, listed in Part D. It is
> still a **template**: each field fills in its own details, checks every
> statement against what it really does, and adopts the text as its own.
> Each field also does its own impact assessment (Art. 35), for which
> `dpia-template.md` is the starting point.
>
> How to read the marks:
> - **[BRACKETS]**: something the field fills in (a name, an address).
> - **[FIELD CHOICE: ...]**: a choice that belongs to the field operator
>   (a period, a rule, whether a feature is used).
> - **[LAWYER: ...]**: a legal choice the code cannot make (a legal basis, a
>   wording, a duty). Where the draft proposes an answer it says so. Only the points still open
>   (Part D) carry this mark.
> - Remove what does not apply to the field before use, and remove every
>   mark.
>
> Pt-PT and English are kept in step: `privacy-notice-pt.md` says the same.
> When you change the notice, raise the version the server records with each
> consent (`ATALAIA_PRIVACY_NOTICE_VERSION`) and the check-in notice's
> `notice_version` on the field controller. The server publishes the notice
> the field adopted (one file per language and version, in
> `ATALAIA_PRIVACY_NOTICE_DIR`: `server/privacy-notice/README.md`) and asks
> accounts to consent again when the version changes; the text stays the
> field's.
>
> Version: [draft-2026-10-30]

This file has three parts:

- **Part A**, the full privacy notice of the field (sections 1 to 14);
- **Part B**, the short version shown in the app when someone creates an
  account (waits on decision S17-16);
- **Part C**, the short notice for a field controller's check-in poster and
  check-in page.

At the end, **Part D** lists the points the lawyer is asked to decide.

---

# Part A. The full notice

## 1. Who is responsible for your data

The data controller is **[OPERATOR'S LEGAL NAME]**, [ADDRESS], [TAX
NUMBER], which runs the games at [FIELD NAME] (the "field"). Contact for
anything about your data: [EMAIL OR POSTAL ADDRESS].

We have not appointed a data protection officer: [the field] is not a public
body, and its core activities do not consist of large-scale regular and
systematic monitoring of people or large-scale processing of special
categories of data (GDPR Art. 37(1)). [FIELD CHOICE: if the field does
appoint one, say so here instead, with their name and contact.]

Atalaia is free software made by the Atalaia project. **The project does not
receive or see the data of this field.** It runs on the field's own
equipment (or on a server the field chose). The project is not a controller
of your data here.

**Roles.** The field is the **controller** of its players' data. A hub
operator, if any, is its **processor** (below). Where several fields on one
hub switch on sharing of chronograph readings (2.4), those fields are
**joint controllers for that sharing step only** (Art. 26); the essence of
their arrangement is in 2.4.

### How the field runs Atalaia

Depending on what the field uses, your data is in one, two or three places.
The rest of this notice says which data is where.

1. **The field's game controller**, a Raspberry Pi or a phone at the field,
   which runs the game, the check-in and the chronograph. It works with
   **no internet**. Everything you give at check-in stays here.
2. **Your phone**, with the Atalaia app (storage described in section 9).
3. **A site server** (optional), where players create accounts, register
   for scheduled games and where results and chronograph records are kept
   between games. It is either:
   - run by the field itself, or
   - **[IF HOSTED:]** hosted for the field by **[HOSTING SERVICE'S LEGAL
     NAME, ADDRESS]** (the "hub operator"), which is the field's
     **processor**: it handles the data only on the field's instructions,
     under a data processing agreement (Art. 28), and does not use it for
     anything of its own. Each hosted field has its own separate database
     space. An account is per field: a player at two hosted fields has two
     accounts, which nothing links.

[FIELD CHOICE: say which of these the field uses. If the field has no site
server, delete everything marked "(site server)" and Part A section 4.]

## 2. What we keep, why, and on what basis

The legal basis is one of those in Art. 6(1) of the GDPR: (a) your consent,
(b) a contract with you, (c) a legal obligation, (f) our legitimate
interests. The tables below say which basis applies to each purpose. Where
the software records a consent (chronograph sharing, sharing your position,
using your provider's name), that is stated.

**An account is on contract (Art. 6(1)(b)):** it is the service you ask for
(registering for games, seeing your history). Creating one does not ask for
consent. The software records which version of this notice was shown to you
at sign-up. Consent (Art. 6(1)(a)) stays for the optional things above,
each separate, granular and withdrawable.

### 2.1 Account and login (site server)

| Data | Why | Basis |
| --- | --- | --- |
| Username, optional email, when the account was made and last used | To give you an account | (b) contract: the service you ask for. The software records the **notice version shown** at sign-up |
| **Password**: only an Argon2id hash, never the password itself. The password is optional | To log in with a password | (b) contract |
| **Authenticator app (TOTP)**: whether it is on, and its secret, stored encrypted. Compulsory for marshals, game masters and administrators | A second step at login; protects staff accounts | (f) security (and Art. 32); (b) contract |
| **Passkeys** (WebAuthn): a name (yours, or one the server gives), the host name, the dates. The server keeps only the public part; **never** the private key or the passkey's identifier shown to you | To log in without a password | (b) contract |
| **Google, Microsoft or Apple sign-in**: **only the provider's name and the opaque identifier ("subject") the provider gives for you, and when you linked it**. The server asks for no email, no photo, nothing else when you sign in. **One exception, only when you press "Use my Google name" or "Use my Microsoft name" on your account page**: the provider then also tells the server your name, once, so that a username can be suggested to you. **That name is read only because you asked, is turned into a suggestion you can edit and is not kept**: only the username you confirm is saved. The provider is told which site you are signing in to, as in any social login | To log in without a password | (b) contract for the sign-in. **Reading your name to suggest a username: (a) your consent**, given by pressing the button |
| Your **roles** at the field (player, squad leader, VIP, marshal, game master, spectator, administrator) | To let you do what your role allows | (b) contract; for staff roles also (f) |
| Login sessions: a hash of the refresh token, the address and the browser or app of each login, the times | To keep you logged in and your account safe | (f) security of the service |
| **Security log**: logins, failed logins, lockouts, changes to the account, roles granted, with the address. Never a password or a code | Security and accountability | (f) |
| **Consent records**: what you agreed to, which notice version, when | To show your consent (Art. 7(1)) and which notice was shown (Art. 5(2)) | (c) legal obligation (accountability) |

### 2.2 Registration for a game and check-in

| Data | Why | Basis |
| --- | --- | --- |
| **Registration (site server)**: your player identifier at the field, a display name for the game (your username by default), your team preference, your **association membership number** if the game asks for it, the replicas you declare, whether you came or not, whether you paid (the field notes it; no payment is processed) | To organise the game | (b) contract: the game you register for |
| A **registration ticket**: a random secret shown once; only a hash is kept | To match your arrival to your registration | (b) contract |
| **Check-in at the field (field controller)**: the name or callsign you type, your team preference, the replicas you declare, **the result of the association-card check** if the field asks for it (2.3; **nothing verifies the number with anyone**), the time. Your phone makes an identifier for this field; the controller keeps it and a hash of the secret that goes with it. **No email, phone number, date of birth, identity document or photo is asked for** | To run the game and to know who is on the field | (b) contract: the game you join; (f) the field's interest in safe games |
| **Association membership**: see 2.3 | | |
| A marshal or the GM may confirm or check in a player by hand even if the membership check fails. This is logged with the player's identifier and the verdict, never the number | Staff decision | (f) |

### 2.3 Association membership (APD): the card check

Some fields ask for a membership of an airsoft association (in Portugal, an
"APD"; elsewhere a club, a federation or an insurance body). **At check-in,
staff check your membership card.** The software takes the association, the
number and the expiry date, and tells staff "valid", "expired", "not
accepted" or "missing". It never checks the number with the association or
anyone else.

**The number is erased as soon as the check-in is confirmed.** What the field
keeps, with the check-in, is a **snapshot of the verdict**: the association,
the expiry date, the result and who checked it, as evidence that the check
was made (for an inspection or an insurer). The number is not shown to other
players, to the read-only scoreboard or in any event, log or MQTT message;
staff (the game master, marshals) see it only until the check-in is
confirmed. A registration's number on the site server goes the same way, and
in any case 30 days after the game at the latest.

**Basis.** Membership of a sports association is not a special category of
data (Art. 9). In Portugal the field checks membership because the rules on
practising airsoft (Law 5/2006 and its regulations) make a recognised APD
membership a condition of play, so the basis is **Art. 6(1)(c), a legal
obligation**. Where there is no such duty (outside Portugal, or another kind
of membership), the basis is Art. 6(1)(f) (the field's insurance and rules),
or (b) where it is a condition of the game you register for.
[FIELD CHOICE: whether the field asks for it at all, which of these bases
applies to it, and whether it is needed to play or only to register.]

### 2.4 Chronograph readings, replicas, violations and bans

| Data | Why | Basis |
| --- | --- | --- |
| The **replicas** you declare or the field registers for you: type, class, make and model, an identifier on an **NFC sticker or a QR label** (`ATL-` and eight characters: nothing personal in the label itself, but the field's registry links it to you) | Safety: replica power limits | (f) safety of players |
| **Chronograph readings** (the energy of a shot, the time, the check-in or spot check, the result pass, warn or fail), **signed by the marshal**; the marshal's public key | Safety | (f) legitimate interests: the safety of everyone on the field |
| **Violations**: a spot check that failed or warned, how far over the limit, and whether you are marked a **repeat offender**. Staff record an outcome: `warning`, `pulled` (replica not allowed) or `ban` | Safety; to let staff see the history before deciding | (f) legitimate interests (see below). **Not** data on criminal offences (Art. 10): a violation is a breach of the field's own rules |

**Violations, bans and the "repeat offender" mark.**

- **Nothing is automatic.** The software enforces none of these outcomes: a
  "ban" is a note for staff, and a person decides and is logged for every
  outcome. No decision is made solely by automated means (Art. 22).
- **"Repeat offender" is advisory.** It is shown to staff, labelled as
  advisory, as an indicator and never as a decision. It counts only earlier
  violations whose outcome was more than a plain `warning`: plain warnings do
  not count.
- **A ban ends.** A ban has an **end date**: 12 months by default, **never
  longer than the field keeps chronograph readings** (section 7). The field
  tells you the outcome and its end date. [FIELD CHOICE: a shorter default.]
- **You can contest an outcome** through the field's contact (section 14).
  You also have the right to object to this processing (Art. 21).
- **The legitimate interest** (Art. 6(1)(f)) is the physical safety of
  everyone on the field, enforcing the field's own safety rules, and showing,
  if an injury happens, that replicas were checked. It needs a signed record
  of who brought which replica at what power; that is the least data that lets
  staff act on repeated breaches (the per-field identifier and the replica,
  not a name). Data stays at the field, or goes only to fields you consented
  for; it is kept as in section 7; it is visible only to staff and to you;
  there is no profiling beyond the one indicator and no automated
  consequence. Players expect chronograph checks and sanctions for
  over-powered replicas. The field has weighed this in writing (the
  legitimate interest assessment in `dpia-template.md`).

| Data | Why | Basis |
| --- | --- | --- |
| **Sharing with other fields** (optional): if two fields both switch it on **and you consent for each of the two**, the other field's staff can see your readings, each with the marshal's public key. Per-field identifiers are never matched with each other: only an account that holds both links them. On a **hosted hub**, where each field has its own accounts, you link your accounts yourself with a one-time code; the hub operator then keeps, for each field you consented for, a copy of that field's signed readings of you in the hub's sharing tables, and only fields you consented for can read it. Withdrawing your consent, unlinking or erasing your account removes that copy | So another field can see a replica's history | (a) your separate consent, per field, which you can withdraw in your account |

**Sharing between fields: who is responsible (Art. 26).** The field you are
at is the controller of everything before the sharing step (its own readings)
and after it (what its staff do with what they read). **For the sharing step
only, the fields that switch sharing on are joint controllers.** They pursue
one purpose, the safety of replicas across fields, through one system whose
means they accept together by switching sharing on. The hub operator handles
the shared tables as the processor of those fields jointly. The essence of
their arrangement (the "sharing terms", which each field accepts in the
software; the acceptance, its version and date are recorded):

- **Scope:** only the signed chronograph readings of people who consented for
  both fields. Violations, outcomes and names never cross.
- **Purpose:** replica safety. Never marketing, scoring people, or refusing
  you entry on another field's readings alone: staff measure the replica
  themselves before deciding anything.
- **Your rights:** you can go to **any** participating field; it handles your
  request or forwards it within 7 days. Withdrawing consent and erasure work
  in the software at once.
- **Breaches:** the field that finds one tells the others and the hub
  operator within 48 hours; each notifies the authority for its own data.
- **Leaving:** a field that switches sharing off stops reading, and the
  copies it published are deleted.

### 2.5 Your position (GPS, Bluetooth beacons)

This is the part to read most carefully.

- **You choose, at check-in.** Sharing your position is a **separate opt-in
  at check-in, never ticked for you**, game by game. Nothing is shared by
  default. **If you decline, you can still check in and play** (Art. 7(4)):
  declining blocks nothing.
- **You can stop at any time**, with a switch in the app. Stopping does not
  affect what was done before.
- **What is shared.** While you share and a game runs, your phone sends its
  latest GPS fix (or, indoors, **which of the field's Bluetooth beacons it
  hears strongest**: a room, not a metre-level place) to the field
  controller. The controller keeps **only the latest position per player,
  for that game, and deletes it when the game ends**. It keeps no track of
  where you went.
- **Bluetooth beacons.** The app listens only for the field's own beacons
  (registered by the field) and sends only which one is strongest. Android
  asks you for the Bluetooth and location permissions for it. Without them,
  GPS alone is used.
- **Who may see it, on the controller:** you; **your squad or team, as the
  game mode allows**; **marshals and the game master, everyone**; the
  read-only scoreboard token, nobody. A game mode may let a team see another
  for a while (for example after an objective). On the map, a position is
  tied to the pseudonymous player identifier; staff's own screens may show
  the display name next to it.
- **Staff ATAK devices on the field.** If the field uses ATAK, staff devices
  the field's controller lists may see every player's position on the
  field's local network. Positions are never broadcast to other devices.
  [FIELD CHOICE: whether ATAK is used.]
- **Remote game master, and remote ATAK (off by default).** **A game master
  away from the field sees positions only when the field turns the *remote
  game master* (`remote_gm`) on**, and then only of players who share them,
  **in memory only: the site server does not store or log them, and nor does
  the controller**. If the field also switches on remote ATAK for players
  (`remote_players`), the site server relays them to ATAK devices of the
  field's game masters and marshals whose certificate was issued with that
  right, again without storing them. The app tells you this before you
  share. [FIELD CHOICE: whether these are switched on.]
- **Never:** positions never go over the field's radio (LoRa), over MQTT, to
  other fields, to the scoreboard, in an event or a log, or into the site
  server's database.
- **Basis:** (a) your consent, the separate opt-in at check-in. Letting staff
  see positions serves the purpose you consent to, safety and running the
  game. The field's impact assessment covers this monitoring
  (`dpia-template.md`).

### 2.6 NFC player tags

Some game modes use an NFC tag (a sticker, card, key fob or wristband) you
carry. The tag holds your **player identifier at the field**, your team and
the game number, and a signature made with that game's key. **No name.** A
box or phone that reads it checks the signature; the tag's chip number is
reported but never trusted. A new key is made for each game, so a tag from
an earlier game stops working. The tag is written by the field's controller
for the game, by the game master or a marshal. Basis: (f) running the game
[LAWYER: or (b)].

### 2.7 Game history

While a game runs, the field controller logs the game's events (a box
captured, a score, a tag read, a heal), naming players **only by their
pseudonymous player identifier**, never by name. The scoreboard shows team
scores. If the field uses the site server, the controller sends the events,
the scores and the games' totals, and you can see in your account the games
your player identifiers appear in. Other roles at the field see a live game
a short time behind (60 seconds unless the field changes it) and without
staff-only data and identifiers; staff see everything. **[FIELD CHOICE:]**
whether the public scoreboard is on (it is off by default and shows scores,
not people).

Game events, scores and nodes that carry your player id are kept **90 days**
after the game ended, on the controller and on the site server. Team and
squad results without player ids (no member lists; a squad under 3 players
is folded into its team) are kept **365 days** (section 7).

Basis: (f) running the games and keeping their history
[LAWYER: confirm].

### 2.8 Remote game master and staff tools (site server)

If you are staff: the site server records, for each remote command a game
master sent to a controller (start, pause, resume, end, a message to boxes),
the account that sent it, on the controller, for 365 days. For ATAK
certificates it records the name of the device, who issued it, and the
address of each connection, kept in the security log.

### 2.9 Clubs (site server)

If the site server has clubs: the clubs you belong to and your role there,
the invitations you received, and reports of public club pages you made
while logged in (never your address). Images you upload (club logos, crests)
should be ones you have the right to use and that show no one's face
[FIELD CHOICE]. Basis: [LAWYER: (a) or (b)]; for reports, (f) moderation.

### 2.10 What does not happen

We do not sell your data, use it for advertising or profiling, or make
decisions about you by automated means. The project's own servers do not
receive your data.

## 3. Who sees your data (recipients)

- **The field's staff**: administrators, game masters and marshals, as the
  role allows (section 2).
- **Other players**: your position as in 2.5 only, and what the field's
  game rules make visible (for example your team and callsign in a game).
- **The hub operator**, only if the site server is hosted: it stores and
  backs up the data as the field's processor, under the agreement. Its own
  sub-processors: [LIST IN THE DPA'S ANNEX: HOSTING PROVIDER, BACKUP
  STORAGE].
- **Other fields of the same hosted hub that you chose to share with**
  (optional): only the fields you linked your accounts at **and consented
  for**, and only while both fields have sharing switched on: they see the
  chronograph readings in section 2.4 (signed by the marshal, with the
  marshal's public key), through a shared view that the hub operator
  maintains. They see nothing else of your account.
- **Sign-in providers** (Google, Microsoft, Apple), if you use them: see 6.
- **Map providers**, when the game master loads a field map: see 6.
- **jogarairsoft.pt or any other federation or insurance service**:
  **[PLACEHOLDER. Nothing is sent to jogarairsoft.pt or any association
  today. If the field makes an agreement to check membership numbers or
  send registrations, this notice must be changed first, before any data is
  sent: say what is sent, on what basis, under what agreement, and for how
  long the partner keeps it.]**
- **Authorities**, if the law requires it.

We do not give your data to anyone else.

## 4. How the data moves

### 4.1 With no internet

The field controller needs no internet. Check-in, the game, the chronograph
and your position work on the field's own Wi-Fi. Your name, your team preference and your declared replicas (and, until the
check-in is confirmed, your membership number) **stay on the controller and
are never sent to the site server or anywhere else**
(check-in names and numbers are never sent, even when the controller syncs).

### 4.2 With the site server (optional)

When the controller has internet and the field uses the site server, the
controller connects out to it (the site server never connects in) and
sends: the games and their events and scores, the chronograph readings (each
as signed), the replicas, the outcome of each registration (came or did not
come), the number of walk-ins as a count, and the marshals' public keys. It
receives the schedule, the roster of registrations for the next game, the
field's settings and branding, scenarios, and, for players who consented,
other fields' chronograph records. The data travels over HTTPS.

### 4.3 Your phone to the controller

Your phone talks to the field controller over the field's Wi-Fi, over HTTPS
with the field's own certificate authority, which the check-in poster's QR
code gives your phone.

## 5. Transfers outside the EU/EEA

The field controller does not send your data outside the field. Players'
phones and the controller contact none of the recipients below.

| Recipient | What it gets | Initiated by | Location | Position |
| --- | --- | --- | --- | --- |
| **Hosting provider** of a site server | Everything on the server | The field or hub operator | **EU data centres only** | A sub-processor named in the data processing agreement; no transfer, because it is in the EU |
| A **CDN, tunnel or DNS proxy** in front of the server, if used (for example Cloudflare) | Traffic metadata (IP addresses); content unless encryption ends at the server | The operator | Often a US company | A sub-processor; the EU-US Data Privacy Framework (Decision 2023/1795) if certified, otherwise standard contractual clauses; or none is used |
| **Google, Microsoft, Apple sign-in** (optional) | Your browser signs in at the provider; the server gets an opaque identifier | **You**, by choosing it | US companies (with EU establishments) | Separate controllers. The field's server does not export your data to them: you interact with them directly. Not choosing them costs nothing |
| **OpenStreetMap** tiles and search; **Overpass** map data (overpass-api.de, overpass.private.coffee); the DGT's orthophoto | The **game master's** IP address and the map area, only on the page "Load the field from a map" | Staff, while setting up a field | OpenStreetMap Foundation: UK (adequacy decision). overpass-api.de: Germany. overpass.private.coffee: run by Private.coffee, an association under Austrian law; **the server's location is not published and is unconfirmed**. DGT: Portugal | Staff data only, no player data. The field can **turn map fetching off** in its settings, and then nothing is fetched |

If the field uses a hosting provider outside the EU, the field must say so
here and the data processing agreement must name the transfer tool (an
adequacy decision or standard contractual clauses).
[FIELD CHOICE: the data centre's country and provider; whether a CDN is
used; whether map fetching is on.]

## 6. Third parties you meet

- **Sign-in providers: Google, Microsoft, Apple (only if you choose them).**
  Your browser or phone goes to the provider, which has its own privacy
  policy and is a separate controller of what it holds about you. They send
  the site server one opaque identifier for you (and your name, only if
  you press the button that suggests a username from it; it is not kept). **Atalaia's field
  controller, boxes and modem never contact them**; only your browser and
  the site server do. Not choosing them costs you nothing: a password or a
  passkey is enough. The field does not send your data to them (section 5).
- **Maps.** Only the game master's *browser*, only on the page "Load the
  field from a map" while setting up the game, fetches map tiles and search
  from **OpenStreetMap**, map data from an **Overpass** server, and, where
  the country has one, an open orthophoto service (in mainland Portugal the
  DGT's). Those services see the game master's address and the area looked
  at (section 5 lists them and where they are). The field can turn map
  fetching off. **Players' phones and the field
  controller fetch no map tiles.** If the game master does not use that
  page, nothing is fetched.
- **Passkeys** use your device or browser's own passkey store (for
  example Google Password Manager or iCloud Keychain, if you use one);
  Atalaia never sees the private key.
- **jogarairsoft.pt**: **[PLACEHOLDER: see 3.]**
- **ATAK**, if used, is a separate app by others on staff devices; it keeps
  what it displays under its own settings. [FIELD CHOICE: the field's
  rule for staff ATAK devices.]

## 7. How long we keep it

These are the periods the software applies today. A period in **[FIELD
CHOICE]** is one the field can change; the others are fixed in the code.

| Data | Where | Kept for |
| --- | --- | --- |
| Account (username, email, login methods, roles, consents) | site server | Until you erase your account |
| Login sessions | site server | 30 days after they end or expire; a login that was never finished: 10 minutes |
| Security log | site server | 36 months. Erasing your account removes the addresses from it |
| What is left of an erased account (an empty row under a random `deleted-...` name: no name, email, password or roles) | site server | Until the last security log entry that names it is deleted, at most 36 months after you used the account; then the row itself is deleted |
| Registration data of people without an account (imported guests) | site server | 30 days after the game |
| A registration's membership number | site server | Erased when the check-in is confirmed; at the latest 30 days after the game |
| Claims of a phone's player identifier | site server | 30 days after they were made |
| Scheduled games and their registrations | site server | 24 months after the game ended |
| Games, their events, scores and nodes (your game history) | site server | **Game history with your player id: 90 days** after the game ended |
| Team and squad results without player ids (no member lists; a squad under 3 players is folded into its team) | site server | **365 days** after the game ended |
| Chronograph readings, violations, replicas, marshal keys | site server | **[FIELD CHOICE:]** 365 days by default, per field (30 to 3653 days, set by the field's administrator) |
| A ban's outcome | site server | Until its **end date**: 12 months by default, never longer than the chronograph readings above |
| The verdict snapshot of an association-card check (association, expiry, result, who checked) | field controller and site server | Like the check-in's other data (30 days after the game by default) |
| Club memberships | site server | Until you leave the club or erase your account |
| Club invitations not accepted | site server | 30 days |
| Reports of club pages | site server | 12 months after they are decided |
| ATAK certificates | site server | A certificate expires in 7 days by default (30 at most); the record goes 30 days after it expired |
| Branding images nothing uses | site server | A day after upload |
| Remote game master log (which account sent a command) | field controller | 365 days |
| **Check-in: name or callsign, team preference** | field controller | **[FIELD CHOICE:]** 30 days after the game by default (`retention_days`), or at once when you leave the game in the app |
| **Check-in: membership number** | field controller | Erased as soon as the check-in is confirmed (the verdict snapshot above stays) |
| Declared replicas of a check-in | field controller | The same 30 days |
| The field identifier your phone made | field controller | Deleted after **a year** without a check-in |
| Chronograph readings, other fields' readings pulled for the roster, marshal's earlier keys | field controller | **[FIELD CHOICE:]** 365 days by default (30 to 3653): the same per-field setting as on the site server, which a controller takes over from it when the field uses it for its settings |
| Your position | field controller | Until the game ends, then deleted. Only the latest, never a track |
| Game events, scores, nodes and the list of a game's devices | field controller | **Game history with your player id: 90 days** after the game ended, then deleted whole; they name only pseudonymous player identifiers. With a site server set up, a controller never deletes a game before the site server has all of it, so a game it cannot send stays (and its erasure of a person reaches the site server by itself) |
| Position, in memory (remote GM, remote ATAK) | site server | Not stored. Gone when the connection ends |

The site server deletes what is past these periods every day (03:00 UTC); a
controller checks about every ten minutes. Backups of a hosted
server: **[HUB OPERATOR: BACKUP PERIOD, e.g. 30 days]**; after an erasure,
data may remain in a backup until it expires.

## 8. Your rights

You can, from your account (site server) or at the controller:

- **See** everything held about you (access, Art. 15): in the app (check-in
  data) and in your account (`GET /me/data`): account, roles, sessions with
  addresses, your audit entries, consents, games, chronograph readings,
  replicas, violations, registrations, claims, clubs, history, login
  methods and passkey names.
- **Download** it (portability, Art. 20): a ZIP of JSON files with a
  README in English and Portuguese.
- **Correct** it (rectification, Art. 16): your username, email and
  password; at check-in your name and details.
- **Erase** it (Art. 17): from your account, with your password (and
  authenticator code, if you use one). Your account becomes an anonymous
  record: no name, no email, no password, no consent; roles, sessions, social
  logins and passkeys are **deleted**; your links to player identifiers are
  **deleted**; registrations lose your account, name, team preference,
  membership number and ticket (the registration's outcome stays as the
  field's history); club memberships and invitations are deleted; your audit
  entries stay without addresses. **Signed chronograph readings and game
  results stay, without anything that links them to you**, because the
  safety of other players and the games' integrity depend on them
  [LAWYER: confirm Art. 17(3) or the anonymisation argument]. At the
  controller, ask the game master to erase your player identifier
  (check-ins and declarations; with the readings if you ask).
  **The last administrator of a server cannot be erased.**
- **Leave a game**, in the app: your check-in becomes "left" and your name,
  membership number and team preference are erased.
- **Object, restrict, withdraw consent** (Art. 7(3), 18, 21): at the
  contact in section 1; stopping position sharing is a switch in the app.
  Withdrawing consent does not affect what was done before. Your account is
  on contract, so you may erase it at any time instead (above).
- **Contest** a violation outcome or a ban (2.4): through the same contact.
- **Not be subject to automated decisions** (Art. 22): none are made.

The field answers within [FIELD CHOICE: one month, the GDPR's limit]. The
field's administrator can also export the field's whole dataset (for
example to hand it to a new operator or to respond to an authority).

## 9. On your phone

The Atalaia app keeps its data in the app's own private folder, which no
other app can read. **Backups are off**: the app's data is not copied to
Google's cloud. What it keeps: your display name last used; whether you
share your position (the last answer); which version of each field's notice
you read; the field identifier and a secret the field uses to know your
phone; your replicas; your registration tickets; and, if you use a site
account, the refresh token. **On Android the secrets** (the field's join
key, the marshal's private key, the read code, your secret at each field
and the site refresh token) **are sealed with a key in the Android
Keystore** and never stored in a readable file. **On an iPhone the same
secrets are kept in the app's private folder, protected by the system's
app sandbox; they are not in the Keychain today** [MAINTAINER:
confirm the wording]. Uninstalling the app deletes all of it. The app has
no analytics, advertising or crash-reporting library.

## 10. Security

HTTPS between all parts; passwords as Argon2id hashes; TOTP secrets
encrypted; refresh tokens stored as hashes; field data separated by field
with row-level security; staff roles count only in a session that passed
two-factor login; lockouts after repeated failures; a log of security
events. The field's controller makes its own certificate authority.

If there is a personal data breach that puts you at risk, we tell the
CNPD within 72 hours and you without undue delay where the risk is high
(Art. 33 and 34). [HOSTED: the hub operator tells the field within 48 hours
(DPA, section 9).]

## 11. Children

You must be **at least 16** to create an account, and you confirm that with a
tick box when you create it (an account is a contract, and a younger person's
capacity to contract is limited: Civil Code, arts. 123 ff. and 127). A
younger player plays through the field's check-in without an account, with
whatever parental agreement the field's own rules ask for. [FIELD CHOICE: the
field's own rule for players under 16 or 18.] The software checks no age
beyond the tick box.

## 12. Complaints

You have the right to lodge a complaint with the Portuguese supervisory
authority, the **Comissão Nacional de Proteção de Dados (CNPD)**, Av. D.
Carlos I, 134, 1.º, 1200-651 Lisboa, www.cnpd.pt [check the address before
use], or with the authority of the EU country where you live or work.

## 13. Changes

If this notice changes, we tell you [FIELD CHOICE: HOW: by email, on the
field's page, in the app] before the change applies. The server records
which version of the notice each consent was given under; a changed notice
that needs a new consent asks for it: with the new version (and the new
notice's files in the `ATALAIA_PRIVACY_NOTICE_DIR` folder), each account is
invited to read the notice and consent again at its next sign-in, and the app
can do the same (`GET /api/v1/me` says whether the consent is for the current
version).

## 14. Contact

[EMAIL OR POSTAL ADDRESS OF THE FIELD'S PRIVACY CONTACT]

---

# Part B. In-app notice for creating an account

Short text for the app's *create account* screen (decision S17-16). It must be shown **before** the account is made, link to the full
notice (Part A), and the person must choose to continue. Version it like
Part A. Keep it to about this length. Pt-PT in `privacy-notice-pt.md`.

> **Your account at [FIELD NAME]**
>
> **[OPERATOR'S LEGAL NAME]** runs the games at [FIELD NAME] and is
> responsible for your data. Contact: [EMAIL].
>
> **What we keep:** a username, an email if you give one, a login method
> (a password, a passkey, or a Google, Microsoft or Apple sign-in, where we
> only keep that provider's identifier for you, never your email or name;
> the provider's name is read only if you ask for it, to suggest a
> username, and is not kept),
> your roles at the field, your registrations (a display name, team, and a
> membership number if the game asks) and your game history.
>
> **What we do not keep:** your GPS position (it stays on the field's
> controller during a game and is deleted when it ends), a password in
> readable form, or anything for advertising.
>
> **Why:** to give you an account, register you for games and keep your
> game and safety records (chronograph readings).
> **Basis:** the account is a contract you ask for (Art. 6(1)(b)). Sharing
> your position and sharing with other fields are separate choices you make
> later; they need your consent.
>
> **How long:** until you erase the account, with shorter periods for some
> things. Details in the full notice.
>
> **Your rights:** see, download, correct and erase your data in the app
> ("Account"). You can complain to the CNPD (www.cnpd.pt).
>
> [ Read the full notice ]
>
> By continuing you confirm you have read the notice.
>
> [ ] I am at least 16 years old.
>
> [ Create the account ]  [ Cancel ]

The software records that the notice was shown, with its version
(`ATALAIA_PRIVACY_NOTICE_VERSION`), as a **notice-shown record**: the account
is on contract, not on consent. The tick box for age 16 must be ticked
before "Create the account" works.

---

# Part C. Short notice for the poster and check-in page

For the field controller's printed check-in poster, or the page the app shows
when it opens a poster's QR code. The controller's default text
(`controller/templates/checkin-notice-en.md`, filled with the operator's
name and the retention days) can be replaced by this once reviewed. At most
a screen of text.

> **Checking in at [FIELD NAME]: your data**
>
> **Who:** [OPERATOR'S LEGAL NAME] ([EMAIL]) runs the game and is
> responsible for your data.
>
> **What we keep when you check in:** the name or callsign you type, your
> team preference, the replicas you declare, and the time. If the field
> checks your association card, staff look at it and we keep only the
> result (association, expiry, valid or not, who checked): **the number is
> erased once your check-in is confirmed** (nothing checks it with anyone). Your phone makes an identifier for this field, and we keep that and a
> hash of its secret. We do not ask for an email, phone number, date of
> birth, ID or photo.
>
> **Your position:** only if you choose to share it: a separate box at
> check-in, never ticked for you. If you say no, you check in and play all
> the same, and you can stop sharing at any time. It stays on the field's
> controller, only the latest, and is deleted when the game ends. Marshals
> and the game master can see everyone; your squad or team sees it as the
> game's rules allow. [FIELD CHOICE, if on: "If the field has a remote game
> master, they see it too, live. Nothing is stored."]
>
> **What for:** running the game and the safety of players (the
> chronograph). The game's events and the scoreboard carry only your
> identifier, never your name.
>
> **Who sees it:** the field's staff. [If the controller syncs with a site
> server:] Your identifier, the game's events and your chronograph readings
> are sent to the field's site server; your name and membership number never
> are.
>
> **How long:** name, team preference and declared replicas are erased [30]
> days after the game, or at once if you leave the game in the app. Game
> events and scores: 90 days. Chronograph readings: [365] days. A ban ends
> after [12] months at most. Your field identifier:
> a year after your last check-in.
>
> **Your rights:** see your data in the app; leave the game and erase it;
> ask [CONTACT] to erase, correct or contest anything (including a ban).
> Complaints: CNPD, www.cnpd.pt.
>
> Full notice: [ADDRESS OR QR CODE].

---

# Part D. What is settled and what is still open

## Settled (2026-10-30)

The maintainer's lawyer approved, and the text above now states:

1. **Legal bases** (2.1 to 2.4): accounts and registration on contract
   (Art. 6(1)(b)) with a notice-shown record, security on (f), consent
   records on (c), consent kept for cross-field sharing, position sharing and
   "use my provider's name".
2. **Association membership** (2.3): not special-category data; the card is
   checked at check-in, the number erased once the check-in is confirmed,
   the verdict snapshot kept; Art. 6(1)(c) where the field has a legal duty
   to check, otherwise (f) or (b).
3. **Violations and bans** (2.4): legitimate interests, not Art. 10 data, no
   solely automated decision; bans end after 12 months by default and never
   later than chronograph retention; the field tells the person; "repeat
   offender" is advisory and plain warnings do not count; contesting goes
   through the field's contact. DPIA: `dpia-template.md`.
4. **Roles** (1, 2.4, 3): the field is the controller; the hub operator is
   its processor (`dpa-template.md`); joint controllers for the sharing step
   only, on standard sharing terms (Art. 26).
5. **Transfers** (5, 6): EU data centres only; the table of recipients; no
   transfer by the field to sign-in providers; a setting to turn map fetching
   off.
6. **Minors** (11): an account from 16, confirmed by a tick box.

Decided by the maintainer on 2026-10-30, consistent with the approved brief:

7. **Data protection officer** (1): none appointed, with the Art. 37(1)
   reasoning in section 1.
8. **Position data** (2.5): consent, asked as a separate unticked opt-in at
   check-in; declining never blocks check-in or play; who sees it is stated;
   the remote game master only when the field turns it on.
9. **Game history** (7): events, scores and nodes with a player id are kept 90 days on the
   controller and the server, and team and squad results without player ids
   (no member lists; squads under 3 folded into the team) 365 days; a controller with sync never deletes a game
   before the server has all of it; chronograph readings keep 365 days.

## Still open

1. **Erasure** (8): that signed chronograph readings and game results may
   stay without a link to the person (Art. 17(3) or the anonymisation
   argument).
2. **Other bases** not covered by the approved positions: NFC player tags
   (2.6), game history (2.7) and clubs (2.9).
3. **Smaller points**: the iPhone secrets wording (9) and the CNPD's address
   (12), both to check before use.
4. **The project's own preview server** (a feedback form that keeps an
   optional contact for 90 days and the message for 12 months, no account, no
   address) has a notice of its own, in the project's name. It is not part of
   this field notice.
