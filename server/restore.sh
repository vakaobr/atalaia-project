#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Restores a backup made by server/backup.sh into a fresh database (ADR-P4-10,
# plan phase 22; server/docs/DEPLOY.md):
#   sh server/restore.sh server/backups/atalaia-YYYYMMDDTHHMMSSZ.backup --yes
# 1. opens the whole backup once (AES-256-GCM: any damage or the wrong
#    ATALAIA_BACKUP_KEY stops here, before anything changes);
# 2. stops the server, drops the database and creates it again, empty;
# 3. pipes the backup through `backup-crypt open` into pg_restore, in one
#    transaction that stops at the first error;
# 4. starts the server, which runs the migrations (a backup from an older
#    version is brought up to date), and waits until it is healthy.
# The current database is deleted: --yes is required. The server needs the
# same ATALAIA_SECRET_KEY as when the backup was made, or every TOTP
# enrolment and every session is lost (keep .env with the backups' key).
# Settings: ATALAIA_ENV_FILE (server/.env), COMPOSE_PROJECT_NAME.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
env_file=${ATALAIA_ENV_FILE:-$here/.env}
file=
yes=0

fail() {
    echo "restore.sh: $*" >&2
    exit 1
}
usage() {
    echo "usage: sh server/restore.sh BACKUP_FILE --yes   (deletes the current database)" >&2
    exit 2
}

for arg in "$@"; do
    case "$arg" in
        --yes) yes=1 ;;
        -h | --help) usage ;;
        -*) echo "restore.sh: unknown option $arg" >&2; usage ;;
        *)
            [ -z "$file" ] || usage
            file=$arg
            ;;
    esac
done
[ -n "$file" ] || usage
if [ ! -f "$file" ] || [ ! -r "$file" ]; then
    fail "cannot read $file"
fi
[ -f "$env_file" ] || fail "$env_file is missing (server/setup.sh makes it; on a new machine, put back your copy)"
[ "$yes" -eq 1 ] || fail "this deletes the current database and replaces it with $file; add --yes to go on"

dc() {
    docker compose --env-file "$env_file" -f "$here/docker-compose.yml" "$@"
}
psql_admin() {
    dc exec -T postgres psql -U atalaia -d postgres -v ON_ERROR_STOP=1 -q "$@"
}

echo "restore.sh: checking $file"
dc run --rm -T backup-crypt open < "$file" > /dev/null \
    || fail "$file does not open (damaged, cut short, or made with another ATALAIA_BACKUP_KEY); nothing was changed"

dc up -d --wait postgres
echo "restore.sh: stopping the server and replacing the database"
dc stop server
psql_admin -c "DROP DATABASE IF EXISTS atalaia WITH (FORCE)" -c "CREATE DATABASE atalaia OWNER atalaia"

status=$(mktemp)
trap 'rm -f "$status"' EXIT
restored=1
{
    rc=0
    dc run --rm -T backup-crypt open < "$file" || rc=$?
    echo "$rc" > "$status"
} | dc exec -T postgres pg_restore -U atalaia -d atalaia --no-owner --exit-on-error --single-transaction \
    || restored=0
opened=$(cat "$status")
if [ "$restored" -ne 1 ] || [ "$opened" != 0 ]; then
    fail "the restore failed (pg_restore ok: $restored, opened: exit code $opened); the database is empty" \
        "and the server is stopped: fix the cause and run restore.sh again"
fi

echo "restore.sh: starting the server (it runs the migrations)"
dc up -d --wait server caddy
echo "restore.sh: restored $file"
