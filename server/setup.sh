#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# First-time setup of a site server (ADR-P4-10, plan phase 22; server/docs/DEPLOY.md).
#   sh server/setup.sh campo.example.pt [--no-start]
# Makes server/.env (mode 0600) with the site's name and new random secrets
# (the database password, the secret key, the metrics token, the backup key),
# then builds and starts Caddy, the server and PostgreSQL. Safe to run again:
# values already in .env are kept (a new database password would lock the
# server out of its own database), only missing ones are added, and the mode
# is put back to 0600. Secrets are read from /dev/urandom and never printed.
#
# ATALAIA_ENV_FILE picks another file than server/.env and COMPOSE_PROJECT_NAME
# another Compose project (the deployment test uses both). Any user who may
# run Docker can run this; it does not need root and does not refuse it
# (decision S22-5): membership of the docker group is root-equivalent anyway.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
env_file=${ATALAIA_ENV_FILE:-$here/.env}
start=1
domain=

usage() {
    echo "usage: sh server/setup.sh DOMAIN [--no-start]   (DOMAIN: the site's name, e.g. campo.example.pt)" >&2
    exit 2
}

for arg in "$@"; do
    case "$arg" in
        --no-start) start=0 ;;
        -h | --help) usage ;;
        -*) echo "setup.sh: unknown option $arg" >&2; usage ;;
        *)
            [ -z "$domain" ] || usage
            domain=$arg
            ;;
    esac
done
[ -n "$domain" ] || usage

domain=$(printf '%s' "$domain" | tr '[:upper:]' '[:lower:]')
# A DNS name: labels of letters, digits and inner hyphens, at least one dot.
if ! printf '%s\n' "$domain" | grep -Eq '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$' \
    || [ "${#domain}" -gt 253 ]; then
    echo "setup.sh: '$domain' is not a domain name (e.g. campo.example.pt; no scheme, port or path)" >&2
    exit 2
fi

if [ ! -r /dev/urandom ]; then
    echo "setup.sh: /dev/urandom cannot be read; no secrets can be made" >&2
    exit 1
fi

# 32 random bytes as 64 hexadecimal digits: safe inside a URL and an env file.
random_hex() {
    value=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    if [ "${#value}" -ne 64 ]; then
        echo "setup.sh: reading /dev/urandom failed" >&2
        exit 1
    fi
    printf '%s' "$value"
}

# The value of KEY in the env file, or nothing.
current() {
    [ -f "$env_file" ] || return 0
    sed -n "s/^$1=//p" "$env_file" | tail -n 1
}

umask 077
if [ -e "$env_file" ] && [ ! -f "$env_file" ]; then
    echo "setup.sh: $env_file exists and is not a file" >&2
    exit 1
fi
if [ -f "$env_file" ]; then
    chmod 600 "$env_file"
    echo "setup.sh: $env_file exists; keeping its values and adding any that are missing"
else
    : > "$env_file"
    chmod 600 "$env_file"
    printf '%s\n' "# The site server's settings and secrets (server/setup.sh). Never commit or share" \
        "# this file; keep a copy of it (above all ATALAIA_SECRET_KEY and ATALAIA_BACKUP_KEY) somewhere" \
        "# safe away from the server: server/docs/DEPLOY.md." >> "$env_file"
fi

old_domain=$(current ATALAIA_DOMAIN)
if [ -n "$old_domain" ] && [ "$old_domain" != "$domain" ]; then
    echo "setup.sh: $env_file is for $old_domain, not $domain; edit ATALAIA_DOMAIN and ATALAIA_PUBLIC_URL" \
        "there to move the site" >&2
    exit 1
fi

added=
add() {  # KEY VALUE: appends KEY=VALUE unless KEY is already set
    if ! grep -q "^$1=" "$env_file"; then
        printf '%s=%s\n' "$1" "$2" >> "$env_file"
        added="$added $1"
    fi
}
add_secret() {
    if ! grep -q "^$1=" "$env_file"; then
        add "$1" "$(random_hex)"
    fi
}

add ATALAIA_DOMAIN "$domain"
add ATALAIA_PUBLIC_URL "https://$domain"
add ATALAIA_TLS acme
add_secret POSTGRES_PASSWORD
add_secret ATALAIA_SECRET_KEY
add_secret ATALAIA_METRICS_TOKEN
add_secret ATALAIA_BACKUP_KEY
add ATALAIA_BACKUP_DAYS 30
add ATALAIA_FIRMWARE_KEYS ""
add ATALAIA_LOG_LEVEL info

if [ -n "$added" ]; then
    echo "setup.sh: wrote$added to $env_file (mode 0600; the secrets are not shown)"
else
    echo "setup.sh: nothing to add to $env_file"
fi

if [ "$start" -eq 0 ]; then
    echo "setup.sh: not starting (--no-start); start with: docker compose --env-file $env_file -f $here/docker-compose.yml up -d --build --wait"
    exit 0
fi

if ! docker compose version > /dev/null 2>&1; then
    echo "setup.sh: Docker with the Compose plugin is needed (docker compose version)" >&2
    exit 1
fi
echo "setup.sh: building and starting Caddy, the site server and PostgreSQL (the first build takes minutes)"
docker compose --env-file "$env_file" -f "$here/docker-compose.yml" up -d --build --wait
echo "setup.sh: up. Check https://$domain/api/v1/health once DNS points here (Caddy gets the certificate"
echo "on the first request). Next: make the first administrator:"
echo "  docker compose --env-file $env_file -f $here/docker-compose.yml exec server python -m atalaia_server create-admin --username NAME"
echo "and schedule server/backup.sh (server/docs/DEPLOY.md)."
