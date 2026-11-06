<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Site server administration manual

For a field's administrators and GMs on the optional **site server**: staff accounts and logins, the field's settings, schedules and registrations, connecting the field controllers, remote GM, chrono sharing and hosted mode. In Portuguese: [Manual da administração do site](../pt/site-admin.md). Running a game on the field is in the [Game master manual](game-master.md).

> **Not field-ready yet.** The site server is built and tested in software. It has not run as a real deployment yet. Installing it is in the [site server guide](../../../server/README.md). Games never wait for it: a controller plays without it and sends what it has when it can.

## Contents

1. [Accounts, roles and logging in](#accounts-roles-and-logging-in)
2. [Your account page](#your-account-page)
3. [The field's settings](#the-fields-settings)
4. [Schedules and registration](#schedules-and-registration)
5. [Registrations and the game-day roster](#registrations-and-the-game-day-roster)
6. [Connect the field controllers](#connect-the-field-controllers)
7. [Remote GM](#remote-gm)
8. [The staff pages](#the-staff-pages)
9. [Chrono sharing, repeat offenders and bans](#chrono-sharing-repeat-offenders-and-bans)
10. [Several fields on one server](#several-fields-on-one-server)
11. [Hosted mode](#hosted-mode)
12. [Data and privacy](#data-and-privacy)

## Accounts, roles and logging in

Roles are per field: `player`, `squad_leader`, `vip`, `marshal`, `gm`, `spectator` and `admin`. The `admin`, `gm` and `marshal` roles need a **second factor**: a **TOTP code** from an authenticator app, or a **passkey** (a passkey counts as both factors at once).

The first administrator is made on the server's command line:

```
docker compose exec server python -m atalaia_server create-admin --username NAME
```

**Log in** at `/staff/login`:

- with your password, then the TOTP code;
- with a **passkey** (*Log in with a passkey*, no username needed);
- with **Google**, **Microsoft** or **Apple**, when the server's operator turned them on. A first login with one of them makes an account if you tick, next to the buttons, that you have read the privacy notice and that you are 16 or older. Only an identifier from the provider is kept, never your email.

A login with Google, Microsoft or Apple alone is not a second factor: every page then shows **Confirm the second factor** (TOTP or a passkey), and your staff roles count from then on. If the server has password login switched off, only the passkey and provider buttons show.

When the field's privacy notice has changed since you last saw it, a **Privacy notice** panel at the top asks you to read it and confirm. It is information, not consent; nothing is blocked meanwhile.

## Your account page

**Account** (top right of every page) holds your own login methods. Each change first asks you to confirm it is you: your current password, or, without one, the TOTP code, a passkey or the provider (valid for ten minutes).

- **Passkeys**: *Add a passkey*, name it, confirm on the browser, phone or security key. Rename or remove one.
- **Google, Microsoft, Apple**: *Link Google* (and so on) or unlink.
- **Password**: set, change or remove it.
- **TOTP code**: turn it on (add the secret to your authenticator app and type the code) or off.
- **Username**: rename the account. An account made by a first provider login starts with **Choose your username** (*Use my Google name* asks the provider only when you press it; *Skip for now* leaves it for later).

The page says in words why it refuses something, for example that it is your last way to log in, or that a staff role needs a second factor. **Make a passkey before you give up TOTP.**

If you link a login that already belongs to another account of yours, the page offers **Merge the other account into this one**: its logins, passkeys and roles move here, its password does not, and it is closed. Accounts with a staff role cannot be merged this way.

## The field's settings

The field's `admin` opens **Settings** at `/staff/fields/<field>/settings` (the **Settings** link in the field's sections, or on `/staff/`). Each section is saved on its own, and a refused value is explained and nothing of it kept.

- **Public page**: the public page and feeds on or off, description, address, federation label.
- **Check-in rules**: the limit template and the most replicas per person.
- **APD / association membership**: the accepted list (or any), whether a registration needs it, whether it is checked at check-in, the expiry, and the field's own entries.
- **Chrono sharing**: see [below](#chrono-sharing-repeat-offenders-and-bans).
- **Country**: `PT` says **APD** and offers Portugal's APDs; another country (or none) says **Association membership** and offers the ones the project knows for it.
- **Data retention**: **Chrono records** and **Game data**, in days, 30 to 3653 (365 and 90 by default). See [Data and privacy](#data-and-privacy).

On the site, the `admin` also sets the field's **branding** (name, accent, logo, wallpaper) and **saved teams**.

A controller started with `[sync] branding = "site"` takes all of this from the site, a standby controller too. Changes reach connected controllers at once; others take them at their next sync. On such a controller the console cannot change the branding, the country or the retention, and a change to its check-in settings lasts only until the next pull.

## Schedules and registration

**Make a scheduled game**

1. On the staff pages, open **Schedule**. It lists the field's games (**Upcoming**, **Past** or **All**), in the field's time zone.
2. Fill in the form at the bottom: title, start and end, teams, places, the registration window, and whether a federation number is asked for.
3. Tap **Create draft**. A draft shows only on the staff pages.
4. The `admin` taps **Publish** to put it on the public page and in the feeds. **Cancel game** (with a reason) cancels a published one.

A `gm` can create, edit and delete drafts and edit a published game, but not publish or cancel. A game with no registration opening or closing time takes no online registration.

**How players register.** A published game has a public page at `/f/` *the field* with a **Register** button, in Portuguese, English, German and Traditional Chinese. Players register with an account:

- in the app: **Player › Online registration**;
- in a browser, with no app: **Register**, then **Register here** (`/f/<field>/games/<game>/register/web`). They log in with Google, Microsoft or Apple, a passkey, or a password if the server takes them. A first provider login makes the account after the player opened the privacy notice and ticked that they read it and are 16 or older.

Both use the same rules (the window, the places, the federation number, the field's APD rule, the replica classes). The player gets a **check-in ticket**, shown once as a QR code and as text to print or save. At the field the desk scans it as a printed ticket ([Game master manual](game-master.md#the-check-in-desk)). New accounts on the web page need the server's social login (`ATALAIA_OIDC_*`) and a published privacy notice. An account makes at most 20 registrations and new tickets an hour. Not yet tested on a real deployment or an iPhone.

On the controller, **Check-in › From the schedule** turns a scheduled game into a live one; its registered players show as **expected**.

## Registrations and the game-day roster

A published game's **Registrations** button lists who registered: display name, team asked for, federation number (if asked), replicas, whether there is a ticket, and the status. Only the field's `admin` and `gm` see it: it is personal data.

**Until the game starts**, the `admin` and the `gm` can:

- **Edit** a display name, team, federation number or replicas (**Add a replica**, **Remove**);
- **Move to another game** of the field that has not started. The person, the replicas and the ticket move; the team and the number are fitted to the new game, and the page says what was dropped;
- **Withdraw** a registration, or **Restore** a withdrawn one while there is a place. A restored registration has no ticket: the player taps *New ticket* in the app, or the desk ticks the name on arrival;
- **Mark paid** and **Mark unpaid**: only a note of who marked it and when. The server takes no payment.

**After the game**, **No-show** marks a player who did not come. The controller's check-in always wins over your mark.

**Game-day roster** shows the list the controller pulls (the active registrations, in the order made). **Print** gives a paper copy with a box to tick per person: print only what the day needs and destroy it afterwards. The page also says whether the controller has made a game from it, how many walk-ins it reported, and when a controller last pulled the list, with its key's name. Arrivals are marked on the controller, not here.

**Export and import.** **Export CSV** saves the list (each export is logged without names). **Import a list** reads a CSV or JSON file of registrations the field received another way: give a source name, tap **Check the file** (nothing is saved), tick that the field has its own basis for the list, and tap **Import**. Imported registrations have no account and no ticket.

**APD membership.** Players declare their APD, membership number and expiry when they register. The registrations page and the roster show them with the verdict (valid, expired, not accepted, missing), and staff can correct them. The public page says what the field asks. The field's admin sets the rule in **Settings**, or through the API: `PATCH /api/v1/fields/{field}` with `{"apd": {"accepted": [...] or null, "register": true, "checkin": true, "expiry": true, "custom": [...]}}` (the field's own APDs in `custom`, ids starting `x-`).

## Connect the field controllers

1. Get an API key for the field from the site server ([site server guide](../../../server/README.md)). Give **each controller its own labelled key** (a field can have two live), so the roster page can tell which one pulled the list.
2. On a Pi, under `[sync]` in `controller.toml`: `enabled = true`, the server's `url` and the key. On a phone controller: **Site server, failover and ATAK** in the app's settings.
3. Optionally:
   - `branding = "site"`: take the field's settings, branding and saved teams from the site;
   - `push_walkins = true` (on a phone, **Send walk-ins to the site server as guests**): after a game made from the schedule, the walk-ins go to its **Registrations** as guests (display name, checked in, chrono results; no account, ticket or number). Off by default: the site then only gets a count;
   - `remote_gm = true`: see [Remote GM](#remote-gm).
4. Restart the controller.

The controller opens every connection, and a game never waits for the network.

## Remote GM

With `remote_gm = true` in the controller's `[sync]` settings, a GM on the site's **Remote GM** page:

- sees the live game, and the **positions of the players who share them** (player, team, role, where, how old; the site passes them on and keeps none);
- can **Start**, **Pause**, **Resume**, **End**, **Send message**, **Send mode command** and **All outputs off**. From afar an output is never turned on.

**Start** runs the same check as the console: with a role missing it asks **No box (or linked phone) has joined for: …. Start anyway?**. Every command is logged on both sides.

## The staff pages

Pages: **Fields**, **History**, **Schedule**, **Scenarios**, **Presets**, **Devices**, **Remote GM**, **ATAK**, and for the admin **Data and limits**.

- **History**: each game with its summary, score timeline (in game time; pauses do not count) and event log. A game's page opens only under its own field.
- **Devices**: each box's health in words: **battery low**, **offline**, **silent**, **tampered**, **firmware outdated**.
- **Data and limits** (the field's admin): **Prepare the export** downloads everything the server holds of the field as a ZIP (personal data: keep it safe; credentials, e-mails and network addresses are not in it; each export is logged with its SHA-256). On a hosted server, a table of what the field uses of each limit.
- **A club's public page** lists the fields with a public page where it plays. Its settings (the field's admin) have a **Public scoreboard**, a **Delay for everyone but the staff** and **Keep the history for**.

## Chrono sharing, repeat offenders and bans

- **Sharing between fields.** Under **Chrono sharing** in the field's **Settings**, turning sharing on needs the field's `admin` to accept the sharing terms. The field stays responsible for its players' data; the fields that share are joint controllers for that step only. When the terms change, sharing waits until the `admin` accepts again.
- **Repeat offenders.** The field's **Chrono** page (`/staff/fields/<field>/chrono`) marks a repeat offender as advice only; a plain warning never counts.
- **Bans** recorded there end by themselves after the field's ban period (12 months by default, never longer than the chrono retention).
- A player contests a record through the field's contact, as the privacy notice says.

## Several fields on one server

On a server that hosts several fields:

- **Chrono sharing between fields** (`/staff/account/hub-share`, linked from **Account**) links your own accounts at the hub's fields. It shows the state and the linked fields, the **consent** sharing needs at this field (**Give consent**; **Withdraw consent** takes this field's records out of the others' view at once), **Make a code** (shown once, 15 minutes, used once), **Enter another field's code** and **Unlink this account**. A code made at a field does not work at that same field; at most 10 codes or links an hour. Nothing is shared unless the field's own switch is on and its terms accepted.
- **Games across fields** (`/staff/fields/<field>/hub-history`, for the admin, GMs and marshals) shares the field's game history with the other fields that share theirs, **off by default**. The admin ticks *Share this field's game history ...* and **Save**. Only game-level results cross: the mode, the times, each team's final score, the winner and the field's name; never who played, the events, the squads or the names typed for the game or teams. Turning it off withdraws every game shared, at once. The operator lists what is shared with `python -m atalaia_server hosted shared-history`.

A server with a single field shows neither.

## Hosted mode

The community hub plans servers run for clubs without IT support, one per field. It is off by default and **not offered yet**. The lawyer approved the legal positions on 30 October 2026, but conditions come first: a signed data processing agreement per field, the sharing terms, a filled-in privacy notice, every sub-processor in the EU, and a proof on a real server. See [Hosted mode](../../../server/README.md#hosted-mode) and [the privacy and data processing templates](../../README.md#templates).

## Data and privacy

- **Retention.** **Chrono records** (the registry of readings, violations, replicas and marshal keys, and the same readings on the controllers) and **Game data** (an ended game's events, scores and nodes on the controllers) are kept for the days set in **Settings › Data retention** (365 and 90 by default). A controller deletes a game only after the site server has all of it. The server's own game history keeps its own period (the **History** page).
- **Registrations**: imported registrations and walk-in guests are deleted 30 days after the game. The federation or membership number, the APD and the expiry are erased 30 days after the game, and the number as soon as the game's outcome arrives from the controller or the game ends.
- **Erasure from the field.** When a player is erased on a controller, the site server erases its copy of their chrono records and the link of their id to an account.
- **Accounts** rest on the contract, not on consent. A provider login keeps only the provider's identifier, never the email. People under 16 check in at the field without an account.
- **Exports** (CSV, ZIP, printed rosters) are personal data: keep them only as long as needed.
