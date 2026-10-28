<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Deploying the site server

This is how a field runs its own site server on a small VPS or a mini PC:
Caddy for HTTPS, the site server, PostgreSQL 16, encrypted daily backups and
a tested restore (ADR-P4-10, plan phase 22 in
[docs/phase-4-site-server/PLAN.md](../../docs/phase-4-site-server/PLAN.md)).

**Status (2026-10-20):** the whole procedure below is tested in Docker on one
computer by `python3 tools/docker_server.py deploy`, with Caddy's own
certificate authority instead of a public certificate. It has **not yet run
on a real server with a real domain and a real certificate** (HW1 does that).
Please report anything that does not work as written.

## What you need

- A machine with a 64-bit Linux, reachable from the internet: 1 vCPU,
  1 GB of memory and 10 GB of disk for one field (512 MB and 5 GB on a mini
  PC at the field). See ADR-P4-10's table for hosted hubs.
- Docker Engine with the Compose plugin (`docker compose version`).
- A domain name (for example `campo.example.pt`) whose DNS `A` (and `AAAA`,
  if the machine has IPv6) record points at the machine **before** the first
  start, since Caddy asks for the certificate as it starts.
- Ports 80 (TCP) and 443 (TCP and UDP) open to the machine. Port 80 is
  needed for the certificate and redirects to HTTPS. Port 8089 (TCP) only
  if the field turns on the remote ATAK relay (below); nothing else is
  published.

Run everything as an ordinary user who may use Docker (in the `docker`
group). The scripts do not need root and do not refuse it, but know that
being in the `docker` group is as good as being root on that machine: give
it only to whoever runs the site server (decision S22-5).

## Install

```sh
git clone https://github.com/vakaobr/atalaia-project.git
cd atalaia-project
sh server/setup.sh campo.example.pt
```

`setup.sh`:

1. writes `server/.env` with mode 0600: the domain, `ATALAIA_PUBLIC_URL`
   (`https://campo.example.pt`) and four new secrets, each 32 random bytes
   from `/dev/urandom` (`POSTGRES_PASSWORD`, `ATALAIA_SECRET_KEY`,
   `ATALAIA_METRICS_TOKEN`, `ATALAIA_BACKUP_KEY`). It never prints them;
2. builds the server's image and starts Caddy, the site server and
   PostgreSQL (`docker compose up -d --build --wait`); the first build takes
   a few minutes.

It is safe to run again: values already in `.env` are kept (a new database
password would lock the server out of its own database), only missing ones
are added, the mode goes back to 0600, and it refuses a different domain
for an existing `.env`. `--no-start` writes `.env` only.

Then make the first server administrator (it shows a TOTP secret for an
authenticator app and asks for a code from it):

```sh
cd server
docker compose exec server python -m atalaia_server create-admin --username NAME
```

From the `server` folder, `docker compose ...` finds `docker-compose.yml`
and `.env` by itself. Check `https://campo.example.pt/api/v1/health`.

### Keep a copy of `.env` somewhere safe

`.env` holds what no backup can give back:

- `ATALAIA_SECRET_KEY`: the keys of the sessions and of the encrypted TOTP
  enrolments come from it. A server restored with another key logs everyone
  out and every TOTP enrolment becomes unreadable;
- `ATALAIA_BACKUP_KEY`: without it, **every backup is unreadable**.

Keep a copy of the whole file in a password manager or on paper in a safe,
away from the server and away from the backups. Never commit it, mail it or
paste it into a chat.

### Settings in `.env`

| Variable | Made by setup.sh | Meaning |
| --- | --- | --- |
| `ATALAIA_DOMAIN` | the argument | The site's name; Caddy gets its certificate |
| `ATALAIA_PUBLIC_URL` | `https://DOMAIN` | The links in the field pages and feeds (see [server/README.md](../README.md)) |
| `ATALAIA_TLS` | `acme` | `acme`: a public certificate (Let's Encrypt or ZeroSSL), renewed by Caddy. `internal`: Caddy's own certificate authority, for a trial or a field server with no public name (below) |
| `POSTGRES_PASSWORD` | random | The database's password; the database is never reachable from outside |
| `ATALAIA_SECRET_KEY` | random | See above |
| `ATALAIA_METRICS_TOKEN` | random | The bearer token for `GET /api/v1/metrics` (a monitoring system) |
| `ATALAIA_BACKUP_KEY` | random | The backups' key (below) |
| `ATALAIA_BACKUP_DAYS` | 30 | How many days backups are kept |
| `ATALAIA_FIRMWARE_KEYS` | empty | The Ed25519 release keys the firmware catalogue trusts (empty: no entries) |
| `ATALAIA_LOG_LEVEL` | `info` | `debug`, `info`, `warning` or `error` |
| `ATALAIA_HOSTED` | `on` with `--hosted` only | A hosted hub ([below](#hosted-mode)); the scripts take the hub's path. Never change it by hand |
| `COMPOSE_FILE` | with `--hosted` only | `docker-compose.yml:docker-compose.hosted.yml`: `docker compose` from `server/` uses both |
| `ATALAIA_OWNER_DB_PASSWORD`, `ATALAIA_APP_DB_PASSWORD` | random, with `--hosted` only | The passwords of the hub's owner role and of the server's role |

The server's other settings (`ATALAIA_PURGE_HOUR`,
`ATALAIA_PRIVACY_NOTICE_VERSION`, `ATALAIA_EXPORT_MIN_INTERVAL_S`, `ATALAIA_EXPORT_MAX_MB` and, for a hub,
the per-field limits `ATALAIA_QUOTA_ACCOUNTS`, `_SCHEDULED_GAMES`, `_REGISTRATIONS`, `_GAMES`, `_ATAK_CERTS`,
`_STREAMS`, `_STORED_MB` and `ATALAIA_HOSTED_WATCH_S`) can be added to `.env` too; the list, with the defaults, is in
[server/README.md](../README.md). After a change: `docker compose up -d`
(from `server/`). Not for a real deployment: `ATALAIA_TEST_ADAPTER`.
Optional, for the ports: `ATALAIA_BIND` (`0.0.0.0`), `ATALAIA_HTTP_PORT`
(80), `ATALAIA_HTTPS_PORT` (443).

## The privacy notice

The notice is the field operator's text (the project's templates in `docs/templates/` are drafts, to be filled in and
reviewed by a lawyer first). Put the adopted notice in `server/privacy-notice/` on the host, one Markdown file per
language and version: `privacy-notice-pt-<version>.md`, `privacy-notice-en-<version>.md`, `-de-` and `-zh-tw-`, where
`<version>` is `ATALAIA_PRIVACY_NOTICE_VERSION` in `.env` (`server/privacy-notice/README.md` says the same). The folder
is mounted read-only in the server's container (`ATALAIA_PRIVACY_NOTICE_DIR=/privacy-notice`); a file is read at each
request, so there is nothing to restart, and the files are not in the backups (keep them with `.env`). The server then
serves it at `https://DOMAIN/privacy` and `GET /api/v1/privacy-notice`. **To change the notice:** add the new files, set
the new `ATALAIA_PRIVACY_NOTICE_VERSION` in `.env` and run `docker compose up -d`; each account is asked to consent again
at its next sign-in. Keep the older files: they are the record of what accounts agreed to. A hub (hosted mode) has one
folder for all its fields.

## What runs, and what can be reached

| Service | Image | Networks | Reachable from outside |
| --- | --- | --- | --- |
| `caddy` | `caddy:2.11.7-alpine` (pinned by digest) | `edge`, `app` | Ports 80 and 443 only |
| `server` | built from `server/Dockerfile` | `app`, `db`, `atak` | Only port 8089, and only with `ATALAIA_ATAK_RELAY=on` (below) |
| `postgres` | `postgres:16.15-alpine` (pinned by digest) | `db` | No |

`app` and `db` are internal Docker networks: only Caddy talks to the
server, only the server to the database, and neither the server nor the
database can open a connection to the internet (the site server needs
none). The site server runs as an unprivileged user in its container. The
server is also on `atak`, which only exists so that the remote ATAK relay's
port can be published (below): Docker publishes no port from an internal
network. `atak` has its outbound NAT turned off, so on a Linux host a
packet the server sent out through it would leave with the container's
private address and get no answer (Docker Desktop routes it anyway); that is
not a firewall, and the site server's code opens no outbound connection
either way. Nothing listens on 8089 while the relay is off.

- **TLS:** Caddy gets and renews the certificate by itself and redirects
  HTTP to HTTPS. Its certificates live in the `caddy-data` volume; they are
  not backed up, since Caddy simply gets new ones.
- **Security headers:** the site server sends HSTS, `nosniff`,
  `X-Frame-Options`, its content security policy and the referrer policy;
  Caddy adds `Permissions-Policy`, `Cross-Origin-Opener-Policy` and
  `X-Permitted-Cross-Domain-Policies` and removes the `Server` and `Via`
  headers. Caddy's admin endpoint is off.
- **The controllers' WebSocket** (`WS /api/v1/sync/stream`, the remote GM):
  Caddy proxies it with nothing else to set up, and keeps open sockets for
  5 minutes if its configuration is reloaded.
- **Client addresses:** Caddy passes each client's address in
  `X-Forwarded-For` (replacing whatever the client sent) and the server
  trusts it (`--proxy-headers`, `FORWARDED_ALLOW_IPS`), so the rate limits
  and the audit log see the real address, not Caddy's (decision S22-4).
- **One worker process.** The rate limits and the remote GM's open links
  live in the memory of the server's one process (ADR-P4-2; decision
  S19-4). The image always starts one (`--workers 1`). Never run
  `docker compose up --scale server=2` or several server containers behind
  Caddy: logins would escape their limits and a GM's command would miss
  the controller's socket half of the time.
- **Logs:** `docker compose logs -f` (from `server/`); each container's log
  is rotated at 10 MB, five files kept. The database password never
  appears in them.

### A field server with no public name

A mini PC at the field, reachable only on the field's network, cannot get a
public certificate. Set `ATALAIA_TLS=internal` in `.env` (and any name the
field's DNS or the controllers' `/etc/hosts` resolve to it): Caddy then
signs with its own authority. Copy its root certificate to each controller
and point `[sync] ca_file` at it:

```sh
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./atalaia-root.crt
```

Browsers warn about such a certificate; players' phones would too.

## Login methods: passkeys, social login, no passwords

Accounts always log in with a password, and can also log in with a **passkey** and, when you register a client with the
provider, with **Google**, **Microsoft** (personal and work or school accounts) and **Apple**
(server/README.md, "Accounts, sessions and roles"). Passkeys need nothing: the server uses the address it is served
from (`ATALAIA_PUBLIC_URL`, so set it) as the WebAuthn origin and its host name as the RP ID; that name must not
change afterwards, or the passkeys stop working. A provider is **off** until you give all of its settings in `.env`
(`docker compose up -d` afterwards); the server stores only the provider and the opaque subject it gives, never an
email or a name, so you ask the providers for nothing but sign-in.

The one address every provider needs is the **redirect URI**: `https://DOMAIN/api/v1/auth/oidc/PROVIDER/callback`, with
`DOMAIN` your site's name and `PROVIDER` `google`, `microsoft` or `apple`, typed exactly (https, no trailing slash). In
a hosted hub each field has its own name, so register `https://<slug>.<hub domain>/api/v1/auth/oidc/PROVIDER/callback`
for every field that should offer the provider (Google and Microsoft take many redirect URIs; none of the three takes
a wildcard host).

**Google** (Google Cloud console, *APIs and services*, *Credentials*): configure the OAuth consent screen (the app's
name, your address, the scope `openid` only, no sensitive or restricted scope), then *Create credentials*, *OAuth
client ID*, *Web application*, with the redirect URI above as an *Authorized redirect URI*. Put the client id and secret in
`.env`:

```
ATALAIA_OIDC_GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
ATALAIA_OIDC_GOOGLE_CLIENT_SECRET=...
```

**Microsoft** (Microsoft Entra admin center, *App registrations*, *New registration*): *Supported account types*:
"Accounts in any organizational directory and personal Microsoft accounts" (tenant `common`), the platform *Web* with the
redirect URI above; then *Certificates and secrets*, *New client secret* (it expires: note the date in your calendar and
make a new one before it does). Use the *Application (client) ID* and the secret's **value**:

```
ATALAIA_OIDC_MICROSOFT_CLIENT_ID=00000000-0000-0000-0000-000000000000
ATALAIA_OIDC_MICROSOFT_CLIENT_SECRET=...
ATALAIA_OIDC_MICROSOFT_TENANT=common
```

`ATALAIA_OIDC_MICROSOFT_TENANT` may be `organizations` (work and school only), `consumers` (personal only) or one
tenant's id (only that organisation), and must then match the registration's account types.

**Apple** (Apple Developer, *Certificates, Identifiers & Profiles*; a paid developer membership is needed): make an
*App ID* with *Sign in with Apple* on, then a *Services ID* (its identifier is the client id) with *Sign in with Apple*
configured: the domain (`DOMAIN`) and the redirect URI above as a *Return URL*. Then *Keys*, a new key with *Sign in with
Apple* on, linked to that App ID: download the `.p8` file **once** (Apple shows it only once), and note the *Key ID* and
your *Team ID* (top right of the developer page). Put the `.p8` somewhere the container can read it, outside the
repository and never in the image (for example `server/secrets/AuthKey_KEYID.p8`, mode 0600, mounted read-only by a
`docker-compose.override.yml`: `volumes: ["./secrets/AuthKey_KEYID.p8:/run/secrets/apple.p8:ro"]` on the `server` service):

```
ATALAIA_OIDC_APPLE_CLIENT_ID=pt.example.campo.web
ATALAIA_OIDC_APPLE_TEAM_ID=ABCDE12345
ATALAIA_OIDC_APPLE_KEY_ID=ABC123DEFG
ATALAIA_OIDC_APPLE_KEY_FILE=/run/secrets/apple.p8
```

The server signs Apple's short-lived client secret with that key each time, so there is nothing to renew; revoke the
key in Apple's console if the file leaks. The server asks Apple for no `name` or `email` scope, so Apple's
*private email relay* and its `form_post` answer are not involved.

A server that has a typo in these settings, or some of a provider's settings and not all, does not start: its log says
which one. A first login with an unknown provider account makes a **new** account (the consent box beside the
buttons); the server never links a provider to an existing account by email, which it does not know. An existing
account (your administrator's, say) links a provider while logged in, with `POST /api/v1/auth/oidc/PROVIDER/start`
(`{"purpose": "link", "password": "..."}`, Bearer) and registers a passkey with `POST /api/v1/me/passkeys/options` and
`POST /api/v1/me/passkeys` (server/README.md has the list); the staff page `/staff/account` and the Atalaia app's
account screen (app/README.md) do both for people.

**The Android app** logs in with the same passkeys and providers, and for that the site must say the app is its own:
set `ATALAIA_APP_ANDROID_PACKAGE` (`org.atalaia.app` for the project's build) and `ATALAIA_APP_ANDROID_SHA256` (the
SHA-256 fingerprint of the key that signed the app, as `keytool -list -v` prints it, `AB:CD:...`; several separated by
commas, for example a debug and a release key) and the server serves `/.well-known/assetlinks.json`, which lets the
app open the site's `https://DOMAIN/app/oidc` link (where a social login returns to the app) and use its passkeys; it
also accepts a passkey made in the app (whose origin is that certificate's hash) besides the site's own. Unset, the file
is a 404 and the app logs in with the password only. The app also needs the **host** in its manifest, because Android
reads App Links from there at install: the project's build is made with `-Patalaia.appLinkHost=DOMAIN` for the
site it serves (or `*.hub.example.pt` for a hosted hub), so a club with its own site server builds the app with its own
host, or keeps the password login in the app. For an iOS app, `ATALAIA_APP_IOS_APP_IDS` (`TEAMID.bundle.id`, commas)
does the same for `/.well-known/apple-app-site-association`; the iOS app does not use it yet. Check with
`curl https://DOMAIN/.well-known/assetlinks.json`.

**Switching passwords off** (`ATALAIA_PASSWORD_LOGIN=off`): password login and password registration answer 403;
accounts then log in with a passkey or a provider. Before you switch it off, make sure **every administrator has a
passkey or a linked provider** (and TOTP or a passkey as the second factor): an account must keep at least one way to
log in, and the server refuses to remove the last, but it cannot know that an account's only remaining way is one you
cannot use. The command-line `create-admin` still makes an administrator with a password and TOTP; with passwords off
that administrator logs in with a passkey made while passwords were on, or through a provider.

## Connecting a field controller

A field's admin makes an API key on the site server
(`/api/v1/fields/{field}/sync-keys`) and the controller stores it
(`python3 -m atalaia_controller sync-key`); the controller's `[sync] url`
is `https://campo.example.pt`. The controller always opens the connection
itself, so it needs no open port, even behind a 4G router. See
[protocol/sync.md](../../protocol/sync.md).

## Remote ATAK (port 8089)

Off by default (Phase 4 follow-up, decisions FU5-*; server/README.md, "Remote
ATAK"). With it, a field's staff ATAK devices away from the field, or a TAK
client in a command post, see the field's boxes and zones (and, for a gm's or
a marshal's certificate issued with that option, player positions), relayed by
the site server from the field controller's own stream.

1. On the site server, add `ATALAIA_ATAK_RELAY=on` to `server/.env` and run
   `docker compose up -d` from `server/`. Devices connect to the site's name
   (`ATALAIA_PUBLIC_URL`'s host; `ATALAIA_ATAK_RELAY_HOST` for another one)
   on port 8089 (`ATALAIA_ATAK_PORT` to publish another; the data packages
   follow it). Open TCP 8089 in the machine's firewall. In hosted mode each
   field's devices connect to `<slug>.DOMAIN:8089`; the hub's wildcard DNS
   record already points there.
2. Caddy does not carry this port: TAK clients speak TLS with client
   certificates, which needs a layer-4 proxy that Caddy's pinned image does
   not have. The server publishes 8089 straight from its container and
   terminates the TLS itself (TLS 1.2 or 1.3, a client certificate signed by
   the field's CA required, every certificate checked against the server's
   list at each connection). Its own certificate is not Caddy's or a public
   one: it comes from a CA derived from `ATALAIA_SECRET_KEY`, which every
   data package's trust store holds. Changing `ATALAIA_SECRET_KEY` therefore
   means making every device's package again (and every field's CA is
   made again on its next certificate).
3. On the field controller: `[atak] enabled = true`, `remote = true` (and
   `remote_players = true` only if positions should go to the gm's and
   marshals' certificates), with the sync on. The controller opens the
   connection, as for the sync.
4. The field's admin or gm, logged in with TOTP, issues a certificate per
   device at `https://campo.example.pt/staff/fields/<field>/atak`: a device
   name, whose account it is (positions only for a gm or a marshal), how many
   days (90 by default, set with `ATALAIA_ATAK_CERT_DAYS`; 365 at most). The page
   shows each certificate's expiry and warns when one expires within 14 days:
   issue a new package for the device and revoke the old one. The page gives the TAK data package (a
   ZIP: the connection, the relay's CA, the device's certificate) and the
   certificate's password, **once**: the server keeps neither. Import the
   package in ATAK and type the password when it asks. Revoke a lost device's
   certificate on the same page; its connection closes at once. The operator
   can do the same from the server's container:

   ```sh
   docker compose exec server python -m atalaia_server atak issue --field campo --device "Posto 1" --out /tmp/posto1.zip
   docker compose cp server:/tmp/posto1.zip . && docker compose exec server rm /tmp/posto1.zip
   docker compose exec server python -m atalaia_server atak list --field campo
   docker compose exec server python -m atalaia_server atak revoke --field campo CERTIFICATE_ID
   ```

   (in hosted mode `--field` is the field's slug on the hub). Such a package
   has no holder and never gets positions; a running server takes a CA the
   command made within 15 s and closes a revoked certificate's connections
   within 30 s.

The relay sees each device's own address, which the audit log keeps with
each connection (`atak_connect`, `atak_refused`). The CAs and certificates
are in the database, so a restore brings them back and the same packages
keep working with the same `ATALAIA_SECRET_KEY`. **Tested in Docker only**
(`python3 tools/docker_server.py deploy` and `deploy-hosted` issue a package,
reach the published port and push a box through the stack to a TLS client);
not yet with a real ATAK device (HW3) or on a real server.

## Backups

```sh
sh server/backup.sh
```

makes `server/backups/atalaia-YYYYMMDDTHHMMSSZ.backup` (or under
`ATALAIA_BACKUP_DIR`), then deletes backups older than
`ATALAIA_BACKUP_DAYS` (30) days, never the new one. Everything the site
server keeps is in the database (accounts, fields, games, events, the chrono
registry, images), so one file is the whole site.

How a backup is protected (decision S22-3):

- `pg_dump -Fc` runs in the database's container and its output goes
  straight through the `backup-crypt` tool (the server's image, with no
  network at all), so **the dump is never on disk unencrypted**;
- it is encrypted with AES-256-GCM under `ATALAIA_BACKUP_KEY`, in 64 KiB
  chunks that each carry their position and whether they are the last, so
  a backup that was changed, cut short or put together from two backups
  does not open
  ([atalaia_server/backup_crypt.py](../atalaia_server/backup_crypt.py));
- the new backup is opened in full once before it gets its name: a backup
  that cannot be opened is reported as a failure, not kept;
- files are mode 0600 in a folder of mode 0700.

The backups hold personal data (accounts, emails, registrations). Anyone
with a backup **and** the key can read them; a backup without the key is
useless to them, and to you. Copy the backups away from the machine
(another server, object storage, a disk at home): the files are safe to
copy as they are. Keep the key with your copy of `.env`, not with the
backups.

Run it every day from the crontab of the user that runs the site server
(`crontab -e`); cron mails anything printed if mail is set up, and the
exit code is 0 only for a complete backup:

```cron
30 2 * * * cd /home/atalaia/atalaia-project && sh server/backup.sh > /dev/null
```

(02:30 so that it does not run with the retention purge, 03:00 UTC.)
Two backups never run at once (a lock in the backup folder); a lock left
by a backup that was killed is taken over.

## Restore

```sh
sh server/restore.sh server/backups/atalaia-20261020T023000Z.backup --yes
```

`restore.sh`:

1. opens the whole backup once; a damaged backup or the wrong
   `ATALAIA_BACKUP_KEY` stops here and **nothing is changed**;
2. stops the site server, deletes the database and creates it again, empty;
3. pipes the backup through `backup-crypt open` into `pg_restore`, in one
   transaction that stops at the first error (an error leaves an empty
   database and the server stopped, and says so);
4. starts the server, which runs the migrations (a backup from an older
   version is brought up to date), and waits until it is healthy.

It deletes the current database, hence `--yes`. If that database holds
anything you need, run `backup.sh` first.

**On a new machine:** install Docker, clone the repository, put back your
copy of `.env` as `server/.env` (mode 0600), run `sh server/setup.sh
campo.example.pt` (it keeps your values and starts the stack), then
`restore.sh` as above. Point the DNS at the new machine.

**Erasures after the backup:** a restore brings back the database as it was
when the backup was made, so an account erased after that comes back. After
a restore, repeat the erasures made since the backup's date: the audit log
lists them as `gdpr_erasure` (an account) and `chrono_player_erasure` (a
field's chrono data of a player) with their dates; read it before you
restore (decision S22-7).

**Test your restores.** `python3 tools/docker_server.py deploy` tests the
scripts on any computer with Docker. A restore of your own backups is
proven only by doing one: now and then, restore the latest backup on a
spare machine or VPS with your `.env`, log in, and look at a recent game.

## Updates

```sh
sh server/backup.sh
git pull
cd server && docker compose up -d --build --wait
```

The server runs the migrations as it starts. Caddy and PostgreSQL change
only when `docker-compose.yml` pins a new image; PostgreSQL stays on major
version 16 (a new major version needs a dump and restore, which these
scripts do).

## Hosted mode

A hub that hosts many fields on one server (ADR-P4-4 as built, plan phase 21,
decisions S21-1 to S21-13; its deployment is a Phase 4 follow-up, decisions
FU4-1 to FU4-10; the design is in [../README.md](../README.md#hosted-mode)).
**It does not go live before a lawyer has reviewed the privacy notice and the
data processing agreement (decision P4-6).**

**Status (2026-10-21):** the procedure below is tested in Docker on one
computer by `python3 tools/docker_server.py deploy-hosted`, with Caddy's own
certificate authority issuing on demand instead of a public one, and names
that only the test's containers resolve. It has **not yet run on a real
hosted server with a real domain, a real wildcard DNS record and public
certificates.**

### What is different from a field's own server

- **Every field at its own name**, `https://<slug>.hub.example.pt`. The DNS
  needs a wildcard record, `*.hub.example.pt`, pointing at the machine (`A`,
  and `AAAA` with IPv6). The hub's own name, `hub.example.pt`, serves nothing.
- **Certificates on demand.** Caddy gets each field's own certificate the
  first time a client asks for that name (the first request takes a few
  seconds longer), renews it by itself, and keeps it in the `caddy-data`
  volume. Before it asks a certificate authority it asks the hub's `ask`
  endpoint (the `tls-ask` container), which says yes only for an **active**
  field's name: an unknown or suspended field, the hub's own name or any
  other name gets no certificate, so nobody can make the hub spend its
  certificate authority's limits on names of their choosing. The endpoint
  answers at most 5 checks a second (bursts of 20); past that it says no
  without touching the database. It is on the internal networks only: Caddy
  reaches it, nobody else does.
- **Two database roles.** The schemas, their tables and the hub's own tables
  belong to `atalaia_owner`, which runs the migrations and the operator's
  commands. The server, and the `ask` endpoint, connect as `atalaia_app`: no
  superuser, no `BYPASSRLS`, owner of nothing, member of no role, only the
  grants each field's tables need (the server refuses to start otherwise).
  PostgreSQL's own superuser (`atalaia`, `POSTGRES_PASSWORD`) is used only by
  the scripts, inside the database's container.
- **The migrations** run in the `hub` container (`hosted migrate`, as the
  owner) every time the stack starts, before the server; the server's own
  command does not migrate. `hosted migrate` also applies every field's
  grants and row-level security again, and writes one `tenant_migrate` entry
  per field to the hub's audit log.

| Service | Image | Networks | Reachable from outside |
| --- | --- | --- | --- |
| `caddy` | `caddy:2.11.7-alpine` (pinned by digest), [`Caddyfile.hosted`](../Caddyfile.hosted) | `edge`, `app` | Ports 80 and 443 only |
| `server` | built from `server/Dockerfile`, hosted mode, as `atalaia_app` | `app`, `db` | No |
| `tls-ask` | the server's image, [`atalaia_server/tls_ask.py`](../atalaia_server/tls_ask.py), as `atalaia_app` | `app`, `db` | No |
| `hub` | the server's image, `python -m atalaia_server`, as `atalaia_owner`; runs and exits | `db` | No |
| `postgres` | `postgres:16.15-alpine` (pinned by digest) | `db` | No |

### Install a hub

What the hub needs is what a field's server needs (above), plus the wildcard
DNS record and more of everything: see ADR-P4-10's table for hosted hubs.

```sh
git clone https://github.com/vakaobr/atalaia-project.git
cd atalaia-project
sh server/setup.sh hub.example.pt --hosted
```

`setup.sh --hosted`:

1. writes `server/.env` (mode 0600) with the hub's domain, `ATALAIA_HOSTED=on`,
   `COMPOSE_FILE=docker-compose.yml:docker-compose.hosted.yml` (so that
   `docker compose` from `server/` uses both files), no `ATALAIA_PUBLIC_URL`
   (each field has its own address) and six secrets of 32 random bytes:
   the four above plus `ATALAIA_OWNER_DB_PASSWORD` and
   `ATALAIA_APP_DB_PASSWORD`. It never prints them;
2. builds the server's image, starts PostgreSQL and makes the two roles with
   those passwords ([`hosted-roles.sh`](../hosted-roles.sh): through `psql`'s
   standard input, never a command line, with statement logging off; run
   again, it sets the passwords from `.env` again);
3. makes the hub's registry and audit log (`hosted init`, as the owner);
4. starts everything: `hub` migrates, then the server, `tls-ask` and Caddy.

Run again, it keeps every value and does it all again (`hosted init` is
safe to repeat and writes a `hub_init` entry each time). It refuses a
single-field server's `.env`, and `setup.sh` without `--hosted` refuses a
hub's: one deployment is one mode.

### The operator's commands

From the `server` folder (`.env`'s `COMPOSE_FILE` picks both Compose files;
from elsewhere, give `--env-file` and both `-f` files), every `hosted`
command runs as the owner role in the `hub` container, and each is written to
the hub's audit log with `--actor` (by default the container's user, so name
yourself) and, where asked, `--reason`:

```sh
cd server
docker compose run --rm hub hosted create campo-tejo --name "Campo Tejo" --actor ana
docker compose run --rm hub hosted list
docker compose exec server python -m atalaia_server create-admin --field campo-tejo --username NAME
```

`create-admin` runs in the server's container, as the server's role, and
makes that field's first administrator (it shows a TOTP secret and asks for
a code). The field is then at `https://campo-tejo.hub.example.pt`; its
controllers use that address and a key made there.

At the field's request (it is the data controller; the hub is its processor
under the DPA):

- `hosted export campo-tejo --out /tmp/campo-tejo.zip --reason "..."`: the
  field's whole dataset, personal data and credential hashes included (mode
  0600). The `hub` container's file system is gone when it exits: mount a
  folder for it, `docker compose run --rm -v "$PWD/exports:/exports" hub
  hosted export campo-tejo --out /exports/campo-tejo.zip --reason "..."`
  (the folder must be writable by the container's user, uid 10001; this
  recipe is not covered by the deployment test), and hand the file over
  encrypted. On the field's own server, at the same release,
  with an empty migrated database: `python -m atalaia_server import-field
  campo-tejo.zip`; everyone logs in and enrols TOTP again.
- **A field's own export, without the operator.** The field's administrator can download the field's own data from `GET /api/v1/fields/<field id>/export` (their TOTP session's bearer token; a ZIP of JSON Lines files, documented in its `README.txt` and `manifest.json`): everything except credentials, e-mail and IP addresses. The staff page `/staff/fields/<field id>/data` ("Dados e limites") does the download in the browser (and shows its SHA-256, which the audit log holds too). It is audit-logged in the field, limited to one every 5 minutes (`ATALAIA_EXPORT_MIN_INTERVAL_S`) and 512 MB (`ATALAIA_EXPORT_MAX_MB`). It is not the data return the DPA asks for on the controller's instruction: that is `hosted export` above, which holds every credential hash. For a field too big for the limit, use `hosted export`.
- **Per-field limits (decisions PKC-5).** The hub's limits are `ATALAIA_QUOTA_*` (accounts, scheduled games,
  registrations, synced games, live ATAK certificates, controller streams and, new, `STORED_MB`: what the field's
  schema takes in the database, 2048 MiB by default, read from the catalogue at most every 30 s, so a burst can pass it
  a little; checked on the controllers' sync, an image, a scenario and a registration import). One field may have its
  own: `hosted quota campo-tejo games 40000 --reason "bigger plan"` (a number of 1 or more, `off` for none, `default`
  to give the hub's back); it is read from the registry on every request, so it applies at once, and is audit-logged
  (`tenant_quota`). `hosted usage [campo-tejo]` prints what each field uses against its effective limits (open
  streams are the running server's: shown as `-`). The field's administrator sees the same numbers, read-only, on
  `/staff/fields/<field id>/data` (`GET /api/v1/fields/<field id>/quotas`).
- **Being told when a field hits a limit.** When the server refuses a field for a quota it leaves a note in
  `public.atalaia_quota_hits` (the server's role may only add to it, never read or change it; at most one note per
  field and quota every 10 minutes). `hosted list` and `hosted check` say how many notes wait; `hosted quota-hits`
  moves them into the hub's audit log (`quota_hit`: field, quota, limit, how many notes, first and last time) and prints
  them. There is no e-mail: run it from a cron job or look at `hosted list`, and raise the limit with `hosted quota`.
- **A custom host name per field** (decisions PKC-6): see [Custom domains](#custom-domains-per-field).
- `hosted suspend campo-tejo --reason "..."` and `hosted resume ...`: every
  request refused, data kept. A suspended field gets no **new** certificate;
  one it already has stays in Caddy's store until it expires.
- `hosted delete campo-tejo --confirm campo-tejo --reason "..."`: the schema and
  every row in it, at once. The hub's audit log (`public.atalaia_hub_audit`)
  keeps who, when, why and the row counts. The backups still hold the field
  until they expire (`ATALAIA_BACKUP_DAYS`, 30): say so when confirming the
  deletion in writing, as the DPA asks.
  Controllers connected to the field are disconnected within `ATALAIA_HOSTED_WATCH_S` seconds (2 by default): the server closes their stream, and the remote GM's link and ATAK connections, as soon as it sees the field gone or suspended in the registry (close codes 4404 and 4403); they do not wait for their next message.
- `hosted check`: reads what keeps the fields apart (every schema and table
  owned by the owner role, row-level security enabled and forced and exactly
  one policy, `atalaia_tenant`, on every table, the server role's exact
  grants, every schema registered; and, since the hub-level chrono sharing
  (SVX-2), the three `public.atalaia_share_*` tables with row-level security
  enabled and not forced and their one policy, the server role's exact
  privileges on them, and the two `SECURITY DEFINER` functions the sharing
  uses, owned by the owner role, with a fixed search path, runnable by the
  server's role only) and exits 1 on any problem. Run it after anything you
  did to the database by hand.
- Chrono sharing across fields (SVX-2): nothing to turn on at the hub. `hosted init` and `hosted migrate` make the
  sharing's tables and functions in `public` (idempotent); each field's admin switches sharing on in the field's
  settings as before, and each player consents per field and links their accounts at the hub's fields with a code
  (`POST /api/v1/me/hub-share/code` at one field, `.../link` at the other). A hub made by an older release needs
  `hosted migrate` before the new server starts (`hub` does it); `hosted check` says so otherwise. `hosted delete`
  removes the field's published records with it, and a restore of a hub brings the tables back with the rest (the
  check runs after it).

### Updates

```sh
sh server/backup.sh
git pull
cd server && docker compose up -d --build --wait caddy server tls-ask
```

`hub` runs `hosted migrate` before the new server starts; if a migration
fails, the server does not start (`docker compose logs hub`). `hosted migrate` also brings the registry up to
date (the per-field limits, the custom host names and the quota-note table of PKC-5 and PKC-6 are added to a hub made
by an older release, idempotently), and a server that finds the older registry refuses to start and says so: run
`docker compose run --rm hub hosted migrate`. `Caddyfile.hosted` changed in the same release (a second site block for
custom host names): `docker compose up -d --build` picks it up.

### Backups and restore of a hub

`backup.sh` and `restore.sh` see `ATALAIA_HOSTED=on` in `.env` and take the
hub's path by themselves; the commands, the schedule and the encryption are
those above.

- **The backup** is one `pg_dump` of the whole database by PostgreSQL's
  superuser, which reads past the row-level security: every field's schema,
  the registry and the hub's audit log, with their owners, grants,
  row-level security and policies. The roles are not in a database dump;
  their passwords are in `.env`, which you keep anyway.
- **The restore** reads the backup's table of contents first and refuses a
  single-field server's backup on a hub (and a hub's on a single-field
  server) with nothing changed. Then it makes both roles again from `.env`
  (on a new machine too), stops the server and `tls-ask`, creates the
  database owned by `atalaia_owner` and restores **with** the owners and the
  grants (no `--no-owner`), in one transaction. `hosted check` must then pass
  (everything owned by the owner again, row-level security forced on every
  table, the server role's grants exactly as they were), or the server stays
  stopped; `hub` migrates (a backup from an older release is brought up to
  date, grants and policies applied again), the server starts, and
  `hosted check` runs once more.

**On a new machine:** install Docker, clone the repository, put back your
copy of `.env` as `server/.env` (mode 0600), run `sh server/setup.sh
hub.example.pt --hosted` (it keeps your values and starts an empty hub),
then `sh server/restore.sh FILE --yes`, and point the wildcard record at the
new machine. Caddy gets every field's certificate again as clients come.

Restoring one field alone from a hub's backup is not scripted: restore the
whole backup on a spare machine and `hosted export` that field from there.
The erasures made after the backup must be repeated, as on a field's own
server, in each field's audit log.

### One wildcard certificate instead (a DNS challenge)

On-demand certificates are one per field, each from an HTTP-01 or TLS-ALPN-01
challenge. A hub with very many fields can reach its certificate authority's
limits (Let's Encrypt's limit on new certificates per registered domain was
50 a week when this was written), and some operators prefer one certificate for `*.hub.example.pt`.
That needs the ACME DNS-01 challenge, which needs Caddy built with the DNS
provider's plugin and an API token for the DNS zone. The repository does not
ship one: no single provider fits every hub, and a plugin build is not an
image pinned and tested here. To do it:

1. build Caddy with your provider's module (for example
   `caddy-dns/cloudflare`) with `xcaddy` on the same Caddy release (2.11.7)
   in a Dockerfile of your own, pin the module's version, and set
   `services.caddy.image` (or `build`) to it in a Compose override of yours;
2. replace the site block's `tls` in a copy of `Caddyfile.hosted` with
   `tls { dns <provider> {env.DNS_API_TOKEN} }` and remove `on_demand` and
   the `on_demand_tls` option (a wildcard certificate covers every field,
   so `tls-ask` is then not needed for certificates);
3. give the token only the right to edit that zone's TXT records, put it in
   `.env` (mode 0600) and pass it to the Caddy container only.

This is not tested here (decision FU4-2). A wildcard certificate covers the hub's own sub-domains only: a field's
custom host name (next) still needs its own certificate on demand, so keep the `ask` endpoint and the second site
block of `Caddyfile.hosted` for those.

### Custom domains per field

A field may have **one custom host name** besides `<slug>.hub.example.pt`, such as `jogos.clube.example.pt`
(decisions PKC-6; S21-12 had left it for later). It is kept in the hub's registry, set by the operator, routed by the
host name (the same way as the field's own name, so the field's data never depend on which name reached it), and its
certificate is issued by Caddy through the same `ask` endpoint, **only** for a name the registry holds as a registered,
active field's whose control the field proved. There are no wildcard custom names and no second name per field.

1. The field decides the name and gives it to the operator. The operator records it:
   `docker compose run --rm hub hosted domain set campo-tejo jogos.clube.example.pt --reason "club's request" --actor ana`.
   It refuses a name that is not a plain DNS name of two labels or more (no scheme, port, wildcard or IP address), the
   hub's own domain or a name under it, and a name another field has. The command prints the TXT record to publish
   (the hub's `ATALAIA_HOSTED_DOMAIN` is read from `.env` for the check):
   `_atalaia-challenge.jogos.clube.example.pt  TXT  "atalaia-verify=<32 hex digits>"`. The name is *pending*: it routes
   nowhere and gets no certificate, and the same command for another name replaces it (and starts again).
2. The field publishes that TXT record at its DNS provider **and** points the name at the hub: an `A`/`AAAA` record
   to the hub's address, or a `CNAME` to `<slug>.hub.example.pt` (Caddy's validation of the name needs it).
3. The operator runs `hosted domain verify campo-tejo`. It asks the machine's own resolver (`/etc/resolv.conf`; the
   `hub` container has none of its own to configure: it uses Docker's) for the TXT record and turns the name on only if
   the record holds the field's token (audit-logged: `tenant_domain_set`, `tenant_domain_verify`). A DNS change can take
   minutes to hours: run it again later. It does not check the `A`/`CNAME` record.
4. From then on `https://jogos.clube.example.pt` serves the field. Caddy gets the certificate at the first request
   (`https://` catch-all block of `Caddyfile.hosted`, `on_demand_tls` `ask`): the `ask` endpoint says yes to the name
   while the field is active and the name is on, and to nothing else (a pending name, another name, a suspended field).
   The ask endpoint now looks a name that is not `<slug>.hub.example.pt` up in the registry, still at most 5 checks a
   second.
5. `hosted domain remove campo-tejo --reason "..."` takes it away: it stops routing at once (404 `unknown_field`) and
   gets no new certificate; the one Caddy has stays in its store until it expires. `hosted list` shows each field's name
   and whether it is pending.

What changes on the custom name: the page addresses the field makes (the public pages' links and feeds, the game
pages' addresses) and a passkey's origin follow the name the request came by, so **passkeys are per name** (an account's
passkeys made at `<slug>.hub.example.pt` do not work at the custom name, and the other way round; passwords and TOTP do).
The remote ATAK relay's devices and the controllers keep using `<slug>.hub.example.pt` (its certificate covers the hub's
sub-domains only). **Social login** (Google, Microsoft, Apple) uses a redirect address that each provider registers one
by one: the custom name needs its address registered at the provider, as every field's own address does today; the
hub-level callback relay that will remove that work is a design only (docs/phase-4-site-server/ADR.md, ADR-P4-13). Like
the rest of hosted mode, this has not run on a real hub with real DNS; the tests cover the registry, the routing, the
`ask` endpoint and the challenge with a fake resolver and a resolver of their own on localhost.

## Monitoring

- `GET /api/v1/health` (no authentication; not rate limited): `status`,
  `database`, `version`, `uptime_s`; 503 when the database is down. Any
  uptime monitor can watch it.
- `GET /api/v1/metrics` with `Authorization: Bearer <ATALAIA_METRICS_TOKEN>`
  (or a server administrator's session).
- `docker compose ps` shows each container's health.

## Removing it

`docker compose down` (from `server/`) stops everything and keeps the data;
`docker compose down --volumes` **deletes the database** and Caddy's
certificates. Backups and `.env` are left where they are.
