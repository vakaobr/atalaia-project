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
> How to read the marks:
> - **[BRACKETS]**: something the field fills in (a name, an address).
> - **[FIELD CHOICE: ...]**: a choice that belongs to the field operator
>   (a period, a rule, whether a feature is used).
> - **[LAWYER: ...]**: a legal choice the code cannot make (a legal basis, a
>   wording, a duty). Where the draft proposes an answer it says so.
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
> Version: [draft-2026-10-28]

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

[LAWYER: whether the field must appoint a data protection officer (GDPR
Art. 37). Usually not for a small field; say so here if so: "We have not
appointed one because ..." or "Our data protection officer is [NAME],
[CONTACT]."]

Atalaia is free software made by the Atalaia project. **The project does not
receive or see the data of this field.** It runs on the field's own
equipment (or on a server the field chose). The project is not a controller
of your data here.

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
interests. **The software cannot decide the basis**, so the table below says
what the software does and **proposes** a basis; the lawyer decides. Where
the software records a consent (the account and chronograph sharing), that
is stated.

### 2.1 Account and login (site server)

| Data | Why | Basis |
| --- | --- | --- |
| Username, optional email, when the account was made and last used | To give you an account | [LAWYER: (a) consent, which the software records when you register, or (b) contract for the service you ask for] |
| **Password**: only an Argon2id hash, never the password itself. The password is optional | To log in with a password | as above |
| **Authenticator app (TOTP)**: whether it is on, and its secret, stored encrypted. Compulsory for marshals, game masters and administrators | A second step at login; protects staff accounts | as above; for staff also (f) the security of the games |
| **Passkeys** (WebAuthn): a name (yours, or one the server gives), the host name, the dates. The server keeps only the public part; **never** the private key or the passkey's identifier shown to you | To log in without a password | as above |
| **Google, Microsoft or Apple sign-in**: **only the provider's name and the opaque identifier ("subject") the provider gives for you, and when you linked it**. The server asks for no email, no name, no photo, nothing else. The provider is told which site you are signing in to, as in any social login | To log in without a password | as above |
| Your **roles** at the field (player, squad leader, VIP, marshal, game master, spectator, administrator) | To let you do what your role allows | as above; for staff roles also (f) |
| Login sessions: a hash of the refresh token, the address and the browser or app of each login, the times | To keep you logged in and your account safe | (f) security of the service |
| **Security log**: logins, failed logins, lockouts, changes to the account, roles granted, with the address. Never a password or a code | Security and accountability | (f) |
| **Consent records**: what you agreed to, which notice version, when | To show your consent (Art. 7(1)) | (c) |

### 2.2 Registration for a game and check-in

| Data | Why | Basis |
| --- | --- | --- |
| **Registration (site server)**: your player identifier at the field, a display name for the game (your username by default), your team preference, your **association membership number** if the game asks for it, the replicas you declare, whether you came or not, whether you paid (the field notes it; no payment is processed) | To organise the game | [LAWYER: (b) contract for the game you register for, or (f)] |
| A **registration ticket**: a random secret shown once; only a hash is kept | To match your arrival to your registration | as above |
| **Check-in at the field (field controller)**: the name or callsign you type, your team preference, the replicas you declare, **your association membership number and its expiry** if the field asks for them (the check-in tells staff whether it looks valid, expired, not accepted or missing; **nothing verifies the number with anyone**), the time. Your phone makes an identifier for this field; the controller keeps it and a hash of the secret that goes with it. **No email, phone number, date of birth, identity document or photo is asked for** | To run the game and to know who is on the field | [LAWYER: (f) the field's interest in safe games, or (b)] |
| **Membership number and expiry**: see 2.3 | | |
| A marshal or the GM may confirm or check in a player by hand even if the membership check fails. This is logged with the player's identifier and the verdict, never the number | Staff decision | (f) |

### 2.3 Association membership (APD) numbers and expiry

Some fields ask for a membership of an airsoft association (in Portugal, an
"APD"; elsewhere a club, a federation or an insurance body). The software
only stores what you type: the association, the number and the expiry date,
and it tells staff "valid", "expired", "not accepted" or "missing". It
never checks the number with the association or anyone else. The membership
number is not shown to other players, to the read-only scoreboard or in any
event, log or MQTT message; staff (the game master, marshals) see it.

[FIELD CHOICE: whether the field asks for it at all, and whether it is
needed to play or only to register.]
[LAWYER: the basis. Proposed: (f), or (c) if the field's insurance or the
law requires proof of membership; say which. Membership of an airsoft
association is not a special category of data (Art. 9) on its face; confirm.]

### 2.4 Chronograph readings, replicas and repeat offenders

| Data | Why | Basis |
| --- | --- | --- |
| The **replicas** you declare or the field registers for you: type, class, make and model, an identifier on an **NFC sticker or a QR label** (`ATL-` and eight characters: nothing personal in the label itself, but the field's registry links it to you) | Safety: replica power limits | (f) safety of players |
| **Chronograph readings** (the energy of a shot, the time, the check-in or spot check, the result pass, warn or fail), **signed by the marshal**; the marshal's public key | Safety | (f) |
| **Violations**: a spot check that failed or warned, how far over the limit, and whether you are a **repeat offender** (you have an earlier violation at this field). Staff record what was done | Safety; to let staff see the history before deciding | (f) [LAWYER: confirm that showing staff a "repeat offender" mark, which is only an indicator and not a decision, is proportionate; confirm there is no "solely automated decision" under Art. 22. The software decides nothing by itself: a person confirms every consequence.] |
| **Sharing with other fields** (optional): if two fields both switch it on **and you consent for each of the two**, the other field's staff can see your readings, each with the marshal's public key. Per-field identifiers are never matched with each other: only an account that holds both links them. On a **hosted hub**, where each field has its own accounts, you link your accounts yourself with a one-time code; the hub operator then keeps, for each field you consented for, a copy of that field's signed readings of you in the hub's sharing tables, and only fields you consented for can read it. Withdrawing your consent, unlinking or erasing your account removes that copy | So another field can see a replica's history | (a) your separate consent, per field, which you can withdraw in your account |

### 2.5 Your position (GPS, Bluetooth beacons)

This is the part to read most carefully.

- **You choose, game by game.** The app asks each game whether to share
  your position. Nothing is shared by default.
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
- **Who may see it, on the controller:** you; your squad, if the game allows
  it; a squad leader, their squad; a VIP, their team; **marshals and the
  game master, everyone**; the read-only scoreboard token, nobody. A game
  mode may let a team see another for a while (for example after an
  objective). On the map, a position is tied to the pseudonymous player
  identifier; staff's own screens may show the display name next to it.
- **Staff ATAK devices on the field.** If the field uses ATAK, staff devices
  the field's controller lists may see every player's position on the
  field's local network. Positions are never broadcast to other devices.
  [FIELD CHOICE: whether ATAK is used.]
- **Remote game master, and remote ATAK (off by default).** If the field
  switches on the *remote game master* (`remote_gm`), a game master logged
  in on the site server away from the field also sees the positions of
  players who share them, **in memory only: the site server does not store
  or log them, and nor does the controller**. If the field also switches on
  remote ATAK for players (`remote_players`), the site server relays them
  to ATAK devices of the field's game masters and marshals whose
  certificate was issued with that right, again without storing them. The
  app tells you this before you share. [FIELD CHOICE: whether these are
  switched on.]
- **Never:** positions never go over the field's radio (LoRa), over MQTT, to
  other fields, to the scoreboard, in an event or a log, or into the site
  server's database.
- **Basis:** (a) your consent, given in the app each game, which you can
  withdraw by stopping sharing at any time. [LAWYER: confirm that consent is
  the right basis and that staff seeing all positions is covered by the
  purpose "safety and running the game".]

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
and your position work on the field's own Wi-Fi. Your name, your membership
number, your team preference and your declared replicas **stay on the
controller and are never sent to the site server or anywhere else**
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

The field controller does not send your data outside the field.

[IF HOSTED or if the field uses a server abroad: The site server is in
**[COUNTRY OF THE DATA CENTRE]**. [LAWYER: if outside the EU/EEA, the
transfer tool: an adequacy decision, or standard contractual clauses, per
the DPA.]]

If you sign in with Google, Microsoft or Apple, that provider (a company
with operations in the United States) learns that you are signing in to
this site; see 6.

## 6. Third parties you meet

- **Sign-in providers: Google, Microsoft, Apple (only if you choose them).**
  Your browser or phone goes to the provider, which has its own privacy
  policy and is a separate controller of what it holds about you. They send
  the site server one opaque identifier for you. **Atalaia's field
  controller, boxes and modem never contact them**; only your browser and
  the site server do. Not choosing them costs you nothing: a password or a
  passkey is enough. [LAWYER: the transfer rules for these providers.]
- **Maps.** Only the game master's *browser*, only on the page "Load the
  field from a map" while setting up the game, fetches map tiles and search
  from **OpenStreetMap** and, where the country has one, an open orthophoto
  service (in mainland Portugal the DGT's). Those services see the game
  master's address and the area looked at. **Players' phones and the field
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
| Registration data of people without an account (imported guests) | site server | 30 days after the game |
| A registration's membership number | site server | 30 days after the game |
| Claims of a phone's player identifier | site server | 30 days after they were made |
| Scheduled games and their registrations | site server | 24 months after the game ended |
| Games, their events and scores (your game history) | site server | **[FIELD CHOICE:]** 24 months after the game ended, or less if the field sets it |
| Chronograph readings, violations, replicas, marshal keys | site server | **[FIELD CHOICE:]** 365 days by default, per field (30 to 3653 days, set by the field's administrator) |
| Club memberships | site server | Until you leave the club or erase your account |
| Club invitations not accepted | site server | 30 days |
| Reports of club pages | site server | 12 months after they are decided |
| ATAK certificates | site server | A certificate expires in 7 days by default (30 at most); the record goes 30 days after it expired |
| Branding images nothing uses | site server | A day after upload |
| Remote game master log (which account sent a command) | field controller | 365 days |
| **Check-in: name or callsign, membership number and expiry, team preference** | field controller | **[FIELD CHOICE:]** 30 days after the game by default (`retention_days`), or at once when you leave the game in the app |
| Declared replicas of a check-in | field controller | The same 30 days |
| The field identifier your phone made | field controller | Deleted after **a year** without a check-in |
| Chronograph readings, other fields' readings pulled for the roster, marshal's earlier keys | field controller | **[FIELD CHOICE:]** 365 days by default (30 to 3653): the same per-field setting as on the site server, which a controller takes over from it when the field uses it for its settings |
| Your position | field controller | Until the game ends, then deleted. Only the latest, never a track |
| Game events, scores and the list of a game's devices | field controller | **[FIELD CHOICE:]** 365 days by default (30 to 3653) after the game ended, then deleted whole; they name only pseudonymous player identifiers. With a site server set up, a controller never deletes a game before the site server has all of it, so a game it cannot send stays (and its erasure of a person reaches the site server by itself) |
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
  Withdrawing consent does not affect what was done before. Withdrawing
  your consent to the account means erasing it.
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
app sandbox; they are not in the Keychain today** [LAWYER / MAINTAINER:
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

[LAWYER: minimum age. Under Portuguese law a child of 13 or more can consent
to information society services (Law 58/2019, Art. 16); below that, a
parent. Many fields also set a higher age to play. Say here what the field
requires: "You must be at least [AGE] to create an account. A parent must
register younger players."] The software does not check ages.

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

Short text for the app's *create account* screen (decision S17-16; the app
does not create accounts today, this waits on this notice and the legal
review). It must be shown **before** the account is made, link to the full
notice (Part A), and the person must choose to continue. Version it like
Part A. Keep it to about this length. Pt-PT in `privacy-notice-pt.md`.

> **Your account at [FIELD NAME]**
>
> **[OPERATOR'S LEGAL NAME]** runs the games at [FIELD NAME] and is
> responsible for your data. Contact: [EMAIL].
>
> **What we keep:** a username, an email if you give one, a login method
> (a password, a passkey, or a Google, Microsoft or Apple sign-in, where we
> only keep that provider's identifier for you, never your email or name),
> your roles at the field, your registrations (a display name, team, and a
> membership number if the game asks) and your game history.
>
> **What we do not keep:** your GPS position (it stays on the field's
> controller during a game and is deleted when it ends), a password in
> readable form, or anything for advertising.
>
> **Why:** to give you an account, register you for games and keep your
> game and safety records (chronograph readings).
> [LAWYER: the basis: consent, or contract.]
>
> **How long:** until you erase the account, with shorter periods for some
> things. Details in the full notice.
>
> **Your rights:** see, download, correct and erase your data in the app
> ("Account"). You can complain to the CNPD (www.cnpd.pt).
>
> [ Read the full notice ]
>
> [ ] I have read the notice and I agree to create the account. [LAWYER:
> keep the box if the basis is consent; with another basis, replace it with
> "By continuing you confirm you have read the notice".]
>
> [ Create the account ]  [ Cancel ]

The software records the agreement with the notice version
(`ATALAIA_PRIVACY_NOTICE_VERSION`), as a consent of purpose `account`.

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
> team preference, the replicas you declare, your membership number and its
> expiry if the field asks for them (nothing checks it with anyone), and the
> time. Your phone makes an identifier for this field, and we keep that and a
> hash of its secret. We do not ask for an email, phone number, date of
> birth, ID or photo.
>
> **Your position:** only if you choose to share it, during a game. It
> stays on the field's controller, only the latest, and is deleted when the
> game ends. Staff can see everyone; other players see only what the game's
> rules allow. [FIELD CHOICE, if on: "If the field has a remote game
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
> **How long:** name, membership number, team preference and declared
> replicas are erased [30] days after the game, or at once if you leave the
> game in the app. Chronograph readings: [365] days. Your field identifier:
> a year after your last check-in.
>
> **Your rights:** see your data in the app; leave the game and erase it;
> ask [CONTACT] to erase or correct anything. Complaints: CNPD, www.cnpd.pt.
>
> Full notice: [ADDRESS OR QR CODE].

---

# Part D. Points for the lawyer

The draft cannot settle these. Each is marked **[LAWYER]** above.

1. **Legal bases** for each purpose (2.1 to 2.9); in particular whether an
   account and registration are better based on contract (Art. 6(1)(b))
   than on consent, given that the software records a consent of purpose
   `account` today.
2. **Membership numbers** (2.3): basis, and whether any field rule or the
   field's insurance makes it a legal obligation.
3. **Position data** (2.5): consent each game, staff seeing all players, the
   remote game master and remote ATAK opt-ins; whether a data protection
   impact assessment (Art. 35) is needed.
4. **"Repeat offender"** (2.4): proportionality of showing it to staff.
5. **Erasure** (8): that signed chronograph readings and game results may
   stay without a link to the person.
6. **Controller and processor roles** (1) for a hosted server, and the DPA
   (`dpa-template.md`).
7. **Transfers** (5, 6): sign-in providers; the hosting country.
8. **Minors** (11).
9. **Data protection officer** (1).
10. **Controller's game events** (7): deleted 365 days by default after the game ended (a field setting, 30 to 3653 days): whether that default is proportionate, and whether a game the site server never received should be kept past it.
11. **The project's own preview server** (a feedback form that keeps an
    optional contact for 90 days and the message for 12 months, no account,
    no address) needs a notice of its own, in the project's name. It is not
    part of this field notice.
