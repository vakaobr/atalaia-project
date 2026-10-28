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
                                              demo-refresh container: `demo load` every hour, `demo live` every ten minutes

visitor -> Cloudflare (TLS) -> cloudflared -> http://localhost:8001 -> 127.0.0.1:8001 (Docker) -> demo-field container
          (the live demo, a second hostname: read-only proxy -> field controller + simulated boxes; see "The live demo")
```

- Containers (project `atalaia-preview`): `server`, `postgres` (volume `atalaia-preview_pgdata`), `demo-refresh`, and for the live demo `demo-field` (volume `atalaia-preview_demo-data`) and the one-shot `demo-init` (volume `atalaia-preview_demo-secrets`). All restart unless stopped, so they come back when Docker starts. **WSL and Docker must be running for the site to answer**: if Windows restarts and nobody starts WSL, the site is down (Cloudflare shows a 502 or 1033 page).
- Only `127.0.0.1:8000` (the site) and `127.0.0.1:8001` (the live demo's read-only proxy) are published. Nothing listens on `0.0.0.0`; the tunnel is the only way in. Neither the server nor the demo has a way out to the internet.
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

## The live demo

A read-only demo game, so that people get an idea of how the application works end to end (decision DEMO-1, which builds the second step PV-2 left for later). The `demo-field` container runs, with nobody there, a **field controller** (the real one: `python -m atalaia_controller`), **three simulated Field Boxes** (the Field Box firmware's own game and radio code built for Linux, as in the controller's end-to-end tests) joined through a **simulated radio** (a UDP "air" and the C host modem), and a **director** that plays games through the controller's own API: a Domination game, then another, forever. Each game: the boxes join with the controller's join cards, twelve players with made-up callsigns check in (a VIP among them, whose view the player's view shows), a marshal's signed chronograph readings come in (one replica over the limit, as happens), the game starts, teams capture the boxes for four minutes while the players walk and report their positions, the game ends, the final score stays on show for a minute, and again.

Visitors see it four ways, all read-only, from one home page ("Try the demo", `https://DEMO-HOST/`, in pt-PT, English, German and Traditional Chinese):

| What | Where |
| --- | --- |
| The GM console, read-only (boxes, plan, events, scores, log, controller) | `https://DEMO-HOST/console/#token=atalaia-demo` (the public read token; the console asks for it otherwise) |
| The scoreboard | `https://DEMO-HOST/scoreboard#token=atalaia-demo` |
| The player's view (callsign, team, check-in, chronograph, clock, score, the team's positions on the plan, the latest captures) | `https://DEMO-HOST/player/` |
| The site server's public pages of the same games | `https://tests.atalaia-project.link/f/demo-ao-vivo/` and `.../f/demo-ao-vivo/scoreboard` (the controller syncs its games to the server like a real field's) |

**What a visitor cannot do.** The proxy (`server/preview/demo/field/proxy.py`) is the only thing reachable from outside the container: GET and HEAD only (anything else is a 405 before it reaches the controller), only the console's files, the scoreboard page and a list of the controller's read endpoints (everything else, join cards, adoption, firmware, the marshal list, other people's check-in lists, is a 404), only the one public read token (the controller's GM token is made at each start, lives in the process's environment and is never accepted or forwarded), a WebSocket that is one way (what a visitor sends on it is thrown away), and a cap of 60 streams. The player's view is read with a demo player's own token, which only the proxy holds. The container runs read-only with every capability dropped, 768 MB and 1.5 CPUs at most, on a network with no way out.

**No personal data.** Everything is invented: the field (a rectangle in the open sea at latitude 0, longitude 0), the callsigns (animals, plants and weather; a test checks them), the scores. The demo does not ask for or keep anything about a visitor. The simulated players' check-ins are kept like any check-in and erased with the controller's database at the next restart.

**It restarts cleanly and loops.** A game ends and the next begins; after 24 games (about two hours) the director stops at a game boundary and the container restarts with a fresh controller database (the console lists every game a controller has, so this is how the demo forgets). Any restart (a crash, `preview.sh live restart`, Docker) starts the same way: the boxes forget what they were playing, a game left running is ended first thing, and a new one begins within about a minute. If a box, the radio, the controller or the director stops, the whole container exits and Docker restarts it. On the site server `demo-refresh` keeps the demo's field (`demo-ao-vivo`, apart from the made-up `campo-demo`), makes its API key once (written to a volume, only its hash in the database) and deletes all but the newest 12 games and controllers that stopped syncing.

### Deploying it (once)

The running preview is not touched until you do this.

1. `preview.sh update` (the new code; rebuilds the server image and builds the demo's, then starts everything including `demo-field`; the server container is recreated, a few seconds of the site being down, because it joins the demo's internal network, which waits up to 3 minutes for `demo-refresh` to make the live field's key; without it the demo still plays, only the site server's pages stay empty). New settings are optional and have defaults; to set them, edit `~/atalaia-preview/preview.env` (a new `preview.sh init` adds them to a new file): `ATALAIA_DEMO_PORT=8001`, `ATALAIA_DEMO_PUBLIC_URL=` (below), `ATALAIA_DEMO_IMAGE=atalaia-demo-preview`. The pace is `ATALAIA_DEMO_LOBBY_S` (25), `ATALAIA_DEMO_GAME_S` (240), `ATALAIA_DEMO_PAUSE_S` (60) and `ATALAIA_DEMO_RESTART_AFTER_GAMES` (24).
2. `preview.sh check` (the demo's proxy answers, refuses a POST) and `preview.sh live status`.
3. **The maintainer, in Cloudflare** (Zero Trust, Networks, Tunnels, the tunnel, Public hostnames): add **`demo.atalaia-project.link` (or any name) -> HTTP -> `localhost:8001`**. The proxy needs nothing else: no Access policy (the demo is public by design and read-only). Optional: a rate-limiting rule on that hostname.
4. Put `ATALAIA_DEMO_PUBLIC_URL=https://demo.atalaia-project.link` in `preview.env` and `preview.sh up`: the preview's landing page then has "Try the live demo" and "The live demo field's page" (and says the GM console is there, read-only).
5. Look at it: the home page, the console with the token, the scoreboard, the player's view, `https://tests.atalaia-project.link/f/demo-ao-vivo/` after the first game ends.

### Every day

| What | Command |
| --- | --- |
| State, the newest game | `preview.sh live status` |
| Log | `preview.sh live logs` |
| A clean restart | `preview.sh live restart` |
| Delete the live field's games on the site server and restart | `preview.sh live reset --yes` |
| Take the demo off the internet | delete its public hostname in the dashboard, or `docker compose -p atalaia-preview stop demo-field` |

If the demo shows no game for more than a few minutes, read `preview.sh live logs`: the director logs why a game failed and gives up (so that Docker restarts everything) after five in a row. If the console works but the site server's live field is empty, check that `demo-refresh` made the key (`docker compose -p atalaia-preview exec demo-field ls -l /secrets`) and that the controller's log says it synced; `preview.sh live reset --yes` starts both sides over.

### Check it

`python3 tools/docker_server.py preview-demo-unit` (the proxy against a stand-in controller: no write passes, the GM token is never forwarded, the stream is one way; the plan and its georeference; the callsigns) and `python3 tools/docker_server.py preview-demo` (a scratch copy of the whole stack with its own ports, subnets, images and volumes, a minute a game: a game plays itself, scores rise, positions and chrono readings exist, nothing can be changed, nothing personal is readable, the site server shows the games, a restart is clean; about ten minutes, and everything it made is removed).

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

- `python3 tools/docker_server.py preview-check` (the Compose files' promises, the live demo's included), `python3 tools/docker_server.py preview-demo-unit` and `preview-demo` (above), `python3 tools/docker_server.py test tests.test_preview`, `python3 tools/docker_server.py browser tests_browser.test_preview_browser`.
- Visitors' language: the preview opens in Portuguese whatever the browser asks for (`ATALAIA_LANG_FROM_BROWSER=off`, PV-9); the language switcher remembers the choice in a `lang` cookie. To let browsers decide, set `ATALAIA_LANG_FROM_BROWSER=on` in `preview.env` and `preview.sh up`.
- Client addresses in the logs are the visitors' (Cloudflare's `X-Forwarded-For`); an address you see as `172.29.89.1` means a request came from this machine directly.

## The project page

Nothing on the project page links to the preview (PV-11). When the maintainer wants it, add one sentence per language (pt, en, de, zh-tw) to the site's sources and run `python3 tools/build_site.py`. The "Try the demo" entry point the live demo gives the page is one link to `https://DEMO-HOST/` (the demo's own home page, which says what it is and links the four views; it follows `?lang=pt|en|de|zh-tw`); suggested texts: pt "Experimente a demonstração: um campo simulado a jogar sozinho, só de leitura"; en "Try the demo: a simulated field playing on its own, read-only"; de "Demo ausprobieren: ein simuliertes Gelände, das von allein spielt, nur lesend"; zh-tw "試用示範：自動進行遊戲的模擬場地，僅供檢視".
