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
  needed for the certificate and redirects to HTTPS; nothing else is
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

The server's other settings (`ATALAIA_PURGE_HOUR`,
`ATALAIA_PRIVACY_NOTICE_VERSION`) can be added to `.env` too; the list is in
[server/README.md](../README.md). After a change: `docker compose up -d`
(from `server/`). Not for a real deployment: `ATALAIA_TEST_ADAPTER`.
Optional, for the ports: `ATALAIA_BIND` (`0.0.0.0`), `ATALAIA_HTTP_PORT`
(80), `ATALAIA_HTTPS_PORT` (443).

## What runs, and what can be reached

| Service | Image | Networks | Reachable from outside |
| --- | --- | --- | --- |
| `caddy` | `caddy:2.11.7-alpine` (pinned by digest) | `edge`, `app` | Ports 80 and 443 only |
| `server` | built from `server/Dockerfile` | `app`, `db` | No |
| `postgres` | `postgres:16.15-alpine` (pinned by digest) | `db` | No |

`app` and `db` are internal Docker networks: only Caddy talks to the
server, only the server to the database, and neither the server nor the
database can open a connection to the internet (the site server needs
none). The site server runs as an unprivileged user in its container.

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

## Connecting a field controller

A field's admin makes an API key on the site server
(`/api/v1/fields/{field}/sync-keys`) and the controller stores it
(`python3 -m atalaia_controller sync-key`); the controller's `[sync] url`
is `https://campo.example.pt`. The controller always opens the connection
itself, so it needs no open port, even behind a 4G router. See
[protocol/sync.md](../../protocol/sync.md).

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
