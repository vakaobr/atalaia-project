<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the preview server

The site server, started as a **preview** (decisions PV-1 to PV-12 in [decisions-to-review.md](../review/decisions-to-review.md); [server/README.md](../../server/README.md), "Preview deployment"), at <https://tests.atalaia-project.link>: invented demo data, a banner, a feedback form. Teams and fields are invited to look at it and say what looks good, what is hard to use and what should change. It is not for real games.

Everything below runs in WSL (Ubuntu) on the maintainer's machine, from `~/atalaia-preview/src/server/preview/preview.sh` (shortened to `preview.sh`; run it as `sh ~/atalaia-preview/src/server/preview/preview.sh COMMAND`). Secrets are never printed by it.

## How it is put together

```
visitor -> Cloudflare (TLS) -> cloudflared (Windows service) -> http://localhost:8000
        -> WSL2 localhost forwarding -> 127.0.0.1:8000 (Docker) -> server container (uvicorn, port 8000)
                                                                  -> postgres container (internal network)
                                              demo-refresh container: `demo load` every hour
```

- Containers (project `atalaia-preview`): `server`, `postgres` (volume `atalaia-preview_pgdata`), `demo-refresh`. All restart unless stopped, so they come back when Docker starts. **WSL and Docker must be running for the site to answer**: if Windows restarts and nobody starts WSL, the site is down (Cloudflare shows a 502 or 1033 page).
- Only `127.0.0.1:8000` is published. Nothing listens on `0.0.0.0`; the tunnel is the only way in. The server has no way out to the internet.
- `~/atalaia-preview/` (mode 700, outside the repository): `preview.env` (the settings and secrets, mode 600), `admin-login.txt` and `reviewers/*.txt` (logins, mode 600), `backups/`, `src/` (the code the image is built from). Keep a copy of `preview.env` (above all `ATALAIA_SECRET_KEY` and `ATALAIA_BACKUP_KEY`) somewhere safe away from this machine.

## The tunnel (the maintainer's, on Windows)

The Cloudflare dashboard (Zero Trust, Networks, Tunnels, the tunnel, Public hostnames): **`tests.atalaia-project.link` -> Service type HTTP -> URL `localhost:8000`**, and nothing else. Check it:

- In PowerShell: `Get-Service cloudflared` (Status Running) or the Services app; `cloudflared.exe tunnel info TUNNEL_NAME` lists its connectors; the dashboard shows the tunnel as Healthy.
- From WSL: `sh preview.sh check` (health and the front page on `127.0.0.1:8000`, then from Windows with `/mnt/c/Windows/System32/curl.exe http://localhost:8000/api/v1/health`, then the public name).
- If the public name fails but `check` passes locally and from Windows: the Windows service or the dashboard route. If `localhost:8000` fails from Windows only: WSL's localhost forwarding (`wsl --shutdown`, then start WSL and `preview.sh up`; check `.wslconfig` for `localhostForwarding=false`).

Cloudflare settings worth having on the zone: **Always Use HTTPS** (the server speaks HTTP to the tunnel and sends HSTS itself, but the redirect is Cloudflare's); optionally a WAF custom rule that blocks `POST /api/v1/auth/register` on this hostname (PV-6: anyone can otherwise make an account); Cloudflare Access is not used (PV-6).

To take the site off the internet at once: stop the Windows service (`Stop-Service cloudflared`) or delete the public hostname in the dashboard. `preview.sh down` stops the server too.

## First time (already done on 2026-10-26)

```sh
# the code: a copy of main (or of a working directory) in ~/atalaia-preview/src
sh /path/to/repo/server/preview/preview.sh update --from /path/to/repo      # or: update main
sh ~/atalaia-preview/src/server/preview/preview.sh init      # preview.env with new secrets; nothing starts
sh ~/atalaia-preview/src/server/preview/preview.sh up        # builds the image, starts the stack
sh ~/atalaia-preview/src/server/preview/preview.sh admin     # the administrator; login in ~/atalaia-preview/admin-login.txt
sh ~/atalaia-preview/src/server/preview/preview.sh check
```

`admin-login.txt` holds the username (`admin`), a generated password and the TOTP secret (and its `otpauth://` URI). Add the secret to an authenticator app; then log in at <https://tests.atalaia-project.link/staff/login>. Move the file somewhere safer once it is in a password manager.

## Every day

| What | Command |
| --- | --- |
| State, health | `preview.sh status`, `preview.sh check` |
| Logs | `preview.sh logs` or `preview.sh logs server` (200 lines; add `-f` after the name to follow) |
| Stop, start | `preview.sh down` (the data stays), `preview.sh up` |
| The feedback | `/staff/feedback` after logging in as `admin`, or `preview.sh feedback [new\|seen\|done\|all]` |
| Demo data again | `preview.sh demo` (idempotent; the hourly service does it too) |
| Put the demo back as it was | `preview.sh reset --yes` (deletes the demo field and clubs, loads them again; accounts, roles and feedback stay) |
| A reviewer who may see the staff pages | `preview.sh reviewer NAME`, then send them `~/atalaia-preview/reviewers/NAME.txt` (a password and a TOTP secret) over a channel you trust; they are a GM on the demo field and nothing else |
| Remove a reviewer | in the database: `docker compose -p atalaia-preview exec postgres psql -U atalaia -d atalaia -c "DELETE FROM users WHERE username = 'NAME'"` (and delete their file) |

## Update to a new commit

```sh
sh ~/atalaia-preview/src/server/preview/preview.sh update          # main of ~/code/atalaia-project (ATALAIA_REPO overrides)
sh ~/atalaia-preview/src/server/preview/preview.sh update 1a2b3c4  # any ref
sh ~/atalaia-preview/src/server/preview/preview.sh update --from DIR   # a working directory (no .git)
```

It exports the code into `src/` (the old tree stays in `src.old/`), rebuilds the image and recreates the containers; migrations run when the server starts. Take a backup first when a migration is in the release (`preview.sh backup`). A failed update: `mv src src.bad; mv src.old src; preview.sh up`, and restore a backup if a migration ran (below). The page footer does not show the version: `.preview-version` in `src/` and `docker compose ... exec server python -c "import atalaia_server; print(atalaia_server.__version__)"` do.

## Backup and restore

`preview.sh backup` writes an encrypted dump to `~/atalaia-preview/backups/` (30 days kept; the key is `ATALAIA_BACKUP_KEY`). Schedule it (a `crontab -e` line such as `17 3 * * * sh ~/atalaia-preview/src/server/preview/preview.sh backup`; cron must be running in WSL) or run it before an update. Restore with `server/restore.sh` into a fresh database ([server/docs/DEPLOY.md](../../server/docs/DEPLOY.md), "Restore"): `ATALAIA_ENV_FILE=~/atalaia-preview/preview.env sh ~/atalaia-preview/src/server/restore.sh FILE --yes`.

The feedback is the part worth keeping: before any destructive step run `preview.sh feedback all > ~/atalaia-preview/feedback-$(date +%F).txt` (mode it 600).

## Rotating secrets

- **Administrator's TOTP only (a lost authenticator, password still known):** `exec server python -m atalaia_server reset-totp --username admin --reason "..."` in the same Compose project clears the secret and signs the account out; log in with the password, enrol a new secret at `/api/v1/auth/totp/enrol`, `confirm` it with a code. `admin-login.txt` then holds a stale TOTP secret: replace or delete it.
- **Administrator's password or TOTP:** delete the account and make it again: `docker compose -p atalaia-preview --env-file ~/atalaia-preview/preview.env -f src/server/docker-compose.yml -f src/server/docker-compose.preview.yml exec postgres psql -U atalaia -d atalaia -c "DELETE FROM users WHERE username = 'admin'"`, `rm ~/atalaia-preview/admin-login.txt`, `preview.sh admin`.
- **`ATALAIA_METRICS_TOKEN`, `ATALAIA_BACKUP_KEY`:** edit `preview.env` and `preview.sh up` (an old backup needs the old key: keep it with the backup).
- **`ATALAIA_SECRET_KEY`:** edit `preview.env` and `preview.sh up`. Everybody is logged out and every TOTP secret becomes unreadable, so also delete the accounts and make the administrator and the reviewers again.
- **`POSTGRES_PASSWORD`:** change it in the database first (`ALTER ROLE atalaia PASSWORD '...'`), then in `preview.env`, then `preview.sh up`.
- **The tunnel's token** is in the Cloudflare dashboard and the Windows service, not here.

## Wiping everything

```sh
sh ~/atalaia-preview/src/server/preview/preview.sh feedback all > /dev/null   # read it first, save what you need
sh ~/atalaia-preview/src/server/preview/preview.sh down
docker volume rm atalaia-preview_pgdata
sh ~/atalaia-preview/src/server/preview/preview.sh up && sh ~/atalaia-preview/src/server/preview/preview.sh admin
```

(`admin-login.txt` must be removed first.) To remove the preview altogether: `preview.sh down`, `docker volume rm atalaia-preview_pgdata`, `docker image rm atalaia-server-preview`, `rm -r ~/atalaia-preview`, and delete the public hostname in the dashboard.

## Checks

- `python3 tools/docker_server.py preview-check` (the Compose files' promises), `python3 tools/docker_server.py test tests.test_preview`, `python3 tools/docker_server.py browser tests_browser.test_preview_browser`.
- Visitors' language: the preview opens in Portuguese whatever the browser asks for (`ATALAIA_LANG_FROM_BROWSER=off`, PV-9); the language switcher remembers the choice in a `lang` cookie. To let browsers decide, set `ATALAIA_LANG_FROM_BROWSER=on` in `preview.env` and `preview.sh up`.
- Client addresses in the logs are the visitors' (Cloudflare's `X-Forwarded-For`); an address you see as `172.29.89.1` means a request came from this machine directly.

## The project page

Nothing on the project page links to the preview (PV-11). When the maintainer wants it, add one sentence per language (pt, en, de, zh-tw) to the site's sources and run `python3 tools/build_site.py`.
