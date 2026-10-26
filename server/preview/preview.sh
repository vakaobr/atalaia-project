#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs the preview deployment (decisions PV-*; docs/runbooks/preview-server.md). Settings, secrets and data live
# outside the repository, in ATALAIA_PREVIEW_HOME (default ~/atalaia-preview):
#
#   preview.env         the server's settings and secrets (mode 600; server/setup.sh makes it)
#   admin-login.txt     the administrator's username, password and TOTP secret (mode 600)
#   reviewers/NAME.txt  test accounts for invited reviewers (mode 600)
#   backups/            encrypted database backups
#   src/                the checked-out code the images are built from (this script is src/server/preview/)
#
#   sh preview.sh init            first time: preview.env with new secrets (nothing is started)
#   sh preview.sh up              build and start (published on 127.0.0.1:8000 only)
#   sh preview.sh down            stop everything (the data stays)
#   sh preview.sh status | logs [SERVICE] | check
#   sh preview.sh admin           make the administrator (once): login in admin-login.txt
#   sh preview.sh reviewer NAME   a test account with the GM role on the demo field: reviewers/NAME.txt
#   sh preview.sh demo            load the demo data (also done hourly by the demo-refresh service)
#   sh preview.sh reset --yes     delete the demo field and clubs and load them again (accounts, feedback stay)
#   sh preview.sh feedback [new|seen|done|all]
#   sh preview.sh backup          an encrypted backup into backups/
#   sh preview.sh update [REF | --from DIR]   new code (default: main of ATALAIA_REPO), rebuild, restart
#
# The Cloudflare Tunnel is not part of this stack: cloudflared runs on the maintainer's Windows host and forwards
# https://tests.atalaia-project.link to http://localhost:8000 (WSL2 forwards it to 127.0.0.1:8000 here).
# Secrets are never printed. Everything is bound to 127.0.0.1; the tunnel is the only way in.
set -eu

home=${ATALAIA_PREVIEW_HOME:-$HOME/atalaia-preview}
src=$home/src
server=$src/server
env_file=$home/preview.env
project=atalaia-preview
repo=${ATALAIA_REPO:-$HOME/code/atalaia-project}
domain=${ATALAIA_PREVIEW_DOMAIN:-tests.atalaia-project.link}

fail() {
    echo "preview.sh: $*" >&2
    exit 1
}

need_env() {
    [ -f "$env_file" ] || fail "$env_file is missing: run 'sh preview.sh init' first"
}

dc() {
    docker compose --env-file "$env_file" -p "$project" \
        -f "$server/docker-compose.yml" -f "$server/docker-compose.preview.yml" "$@"
}

cmd=${1:-}
[ $# -gt 0 ] && shift
case "$cmd" in
    init)
        [ -d "$src" ] || fail "$src is missing: copy the code there (sh preview.sh update --from DIR)"
        umask 077
        mkdir -p "$home" "$home/backups" "$home/reviewers"
        ATALAIA_ENV_FILE=$env_file sh "$server/setup.sh" "$domain" --no-start
        add() {
            grep -q "^$1=" "$env_file" || printf '%s=%s\n' "$1" "$2" >> "$env_file"
        }
        add ATALAIA_PREVIEW on
        add ATALAIA_BIND 127.0.0.1
        add ATALAIA_PREVIEW_PORT 8000
        add ATALAIA_SERVER_IMAGE atalaia-server-preview
        add COMPOSE_PROJECT_NAME "$project"
        add ATALAIA_BACKUP_DIR "$home/backups"
        # Caddy is not part of the preview: its TLS mode is unused but the variable must be set.
        chmod 600 "$env_file"
        echo "preview.sh: $env_file ready (mode 600). Next: 'sh preview.sh up', then 'sh preview.sh admin'."
        ;;
    up)
        need_env
        dc up -d --build --wait server postgres demo-refresh
        echo "preview.sh: up on 127.0.0.1:$(sed -n 's/^ATALAIA_PREVIEW_PORT=//p' "$env_file" | tail -n 1) only;" \
            "the tunnel (Windows service) serves it at https://$domain"
        ;;
    down)
        need_env
        dc down --remove-orphans
        ;;
    status)
        need_env
        dc ps -a
        ;;
    logs)
        need_env
        dc logs --tail 200 "$@"
        ;;
    check)
        need_env
        port=$(sed -n 's/^ATALAIA_PREVIEW_PORT=//p' "$env_file" | tail -n 1)
        base=http://127.0.0.1:${port:-8000}
        curl -fsS "$base/api/v1/health" > /dev/null && echo "health: ok"
        curl -fsS "$base/" | grep -q 'preview-banner' && echo "front page with the banner: ok"
        curl -fsS "$base/f/campo-demo/" | grep -q 'campo-demo\|Campo Demo' && echo "demo field: ok"
        curl -fsS "$base/robots.txt" | grep -q 'Disallow: /' && echo "robots.txt: ok"
        win=/mnt/c/Windows/System32/curl.exe
        if [ -x "$win" ]; then
            "$win" -fsS "http://localhost:${port:-8000}/api/v1/health" > /dev/null && echo "from Windows (localhost:${port:-8000}): ok"
        fi
        if curl -fsS "https://$domain/api/v1/health" > /dev/null 2>&1; then
            echo "public ($domain): ok"
        else
            echo "public ($domain): NOT answering (is the Windows cloudflared service running? is WSL up?)"
        fi
        ;;
    admin)
        need_env
        target=$home/admin-login.txt
        [ ! -e "$target" ] || fail "$target exists: the administrator was made already"
        umask 077
        dc exec -T server rm -f /tmp/admin-login.txt
        dc exec -T server python -m atalaia_server create-admin --username admin --generate /tmp/admin-login.txt
        dc exec -T server cat /tmp/admin-login.txt > "$target"
        dc exec -T server rm -f /tmp/admin-login.txt
        chmod 600 "$target"
        echo "preview.sh: the administrator's login (username, password, TOTP secret) is in $target"
        ;;
    reviewer)
        need_env
        name=${1:-}
        [ -n "$name" ] || fail "usage: preview.sh reviewer NAME"
        target=$home/reviewers/$name.txt
        [ ! -e "$target" ] || fail "$target exists"
        umask 077
        mkdir -p "$home/reviewers"
        dc exec -T server rm -f /tmp/reviewer.txt
        dc exec -T server python -m atalaia_server demo reviewer --username "$name" --out /tmp/reviewer.txt
        dc exec -T server cat /tmp/reviewer.txt > "$target"
        dc exec -T server rm -f /tmp/reviewer.txt
        chmod 600 "$target"
        echo "preview.sh: send the reviewer the contents of $target (a password and a TOTP secret for an authenticator app)"
        ;;
    demo)
        need_env
        dc exec -T server python -m atalaia_server demo load
        ;;
    reset)
        need_env
        [ "${1:-}" = "--yes" ] || fail "this deletes the demo field and clubs and loads them again: add --yes"
        dc exec -T server python -m atalaia_server demo reset
        ;;
    feedback)
        need_env
        dc exec -T server python -m atalaia_server feedback list --status "${1:-new}"
        ;;
    backup)
        need_env
        ATALAIA_ENV_FILE=$env_file sh "$server/backup.sh"
        ;;
    update)
        mkdir -p "$home"
        new=$home/src.new
        rm -rf "$new"
        mkdir -p "$new"
        if [ "${1:-}" = "--from" ]; then
            [ -d "${2:-}" ] || fail "usage: preview.sh update --from DIR"
            (cd "$2" && tar --exclude=.git --exclude=node_modules -cf - .) | tar -xf - -C "$new"
            echo "from directory $2" > "$new/.preview-version"
        else
            ref=${1:-main}
            git -C "$repo" archive "$ref" | tar -xf - -C "$new"
            echo "$ref $(git -C "$repo" rev-parse --short "$ref")" > "$new/.preview-version"
        fi
        [ -f "$new/server/docker-compose.preview.yml" ] || fail "that code has no server/docker-compose.preview.yml"
        rm -rf "$home/src.old"
        [ ! -d "$src" ] || mv "$src" "$home/src.old"
        mv "$new" "$src"
        echo "preview.sh: code is now $(cat "$src/.preview-version")"
        if [ -f "$env_file" ]; then
            exec sh "$server/preview/preview.sh" up
        fi
        ;;
    *)
        sed -n '5,31p' "$0" | sed 's/^# \{0,1\}//'
        [ -z "$cmd" ] || exit 2
        ;;
esac
