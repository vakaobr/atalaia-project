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
#
# One deployment is one mode: the backup's table of contents says whether it
# is a single-field server's or a hosted hub's, and a backup of the other mode
# than the env file's (ATALAIA_HOSTED) is refused before anything changes.
# A hosted hub's restore (Phase 4 follow-up, decisions FU4-*) keeps the
# ownership: it makes the two roles again from .env (hosted-roles.sh), creates
# the database owned by atalaia_owner and restores without --no-owner, so every
# schema and table belongs to atalaia_owner again. It restores with --no-acl:
# every field has a database role of its own (decision S2113-1), roles belong to
# the cluster and not to the backup, so on a new machine the backup's grants to
# them would fail; `hosted migrate` makes the roles again from the registry and
# gives every grant back, after hosted-roles.sh has restricted set_config in the
# new database. Then `hosted check` (as the owner) must find FORCE ROW LEVEL
# SECURITY and the one policy on every table and every role's privileges as they
# should be, or the server stays stopped. Starting runs `hosted migrate` (hub)
# again, and the check runs once more.
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

hosted=$(sed -n 's/^ATALAIA_HOSTED=//p' "$env_file" | tail -n 1)
dc() {
    if [ "$hosted" = on ]; then
        docker compose --env-file "$env_file" -f "$here/docker-compose.yml" -f "$here/docker-compose.hosted.yml" "$@"
    else
        docker compose --env-file "$env_file" -f "$here/docker-compose.yml" "$@"
    fi
}
psql_admin() {
    dc exec -T postgres psql -U atalaia -d postgres -v ON_ERROR_STOP=1 -q "$@"
}

echo "restore.sh: checking $file"
dc run --rm -T backup-crypt open < "$file" > /dev/null \
    || fail "$file does not open (damaged, cut short, or made with another ATALAIA_BACKUP_KEY); nothing was changed"

dc up -d --wait postgres
status=$(mktemp)
toc=$(mktemp)
trap 'rm -f "$status" "$toc"' EXIT

# Which mode the backup is of: its table of contents (pg_restore -l stops reading after it).
dc run --rm -T backup-crypt open < "$file" 2> /dev/null | dc exec -T postgres pg_restore -l > "$toc" \
    || fail "$file has no table of contents pg_restore can read; nothing was changed"
if grep -q ' TABLE public atalaia_tenants ' "$toc"; then
    kind=hosted
elif grep -q ' TABLE public fields ' "$toc"; then
    kind=single
else
    fail "$file is not a backup of a site server's database; nothing was changed"
fi
if [ "$kind" = hosted ] && [ "$hosted" != on ]; then
    fail "$file is a hosted hub's backup and $env_file a single-field server's: restore it into a hosted" \
        "deployment (setup.sh DOMAIN --hosted); nothing was changed"
fi
if [ "$kind" = single ] && [ "$hosted" = on ]; then
    fail "$file is a single-field server's backup and $env_file a hosted hub's: restore it into a" \
        "single-field deployment; nothing was changed"
fi

if [ "$hosted" = on ]; then
    ATALAIA_ENV_FILE=$env_file sh "$here/hosted-roles.sh"
    echo "restore.sh: stopping the server and replacing the hub's database"
    dc stop server tls-ask
    psql_admin -c "DROP DATABASE IF EXISTS atalaia WITH (FORCE)" -c "CREATE DATABASE atalaia OWNER atalaia_owner"
    owner_option=--no-acl
else
    echo "restore.sh: stopping the server and replacing the database"
    dc stop server
    psql_admin -c "DROP DATABASE IF EXISTS atalaia WITH (FORCE)" -c "CREATE DATABASE atalaia OWNER atalaia"
    owner_option=--no-owner
fi

restored=1
{
    rc=0
    dc run --rm -T backup-crypt open < "$file" || rc=$?
    echo "$rc" > "$status"
} | dc exec -T postgres pg_restore -U atalaia -d atalaia $owner_option --exit-on-error --single-transaction \
    || restored=0
opened=$(cat "$status")
if [ "$restored" -ne 1 ] || [ "$opened" != 0 ]; then
    fail "the restore failed (pg_restore ok: $restored, opened: exit code $opened); the database is empty" \
        "and the server is stopped: fix the cause and run restore.sh again"
fi

if [ "$hosted" = on ]; then
    echo "restore.sh: giving the restored hub's fields their database roles and grants (hosted migrate)"
    ATALAIA_ENV_FILE=$env_file sh "$here/hosted-roles.sh"
    dc run --rm -T hub hosted migrate \
        || fail "hosted migrate failed after the restore; the server stays stopped: see above"
    echo "restore.sh: checking the restored hub's isolation (hosted check, as the owner role)"
    dc run --rm -T hub hosted check \
        || fail "the restored hub fails the isolation check; the server stays stopped: see above"
    echo "restore.sh: starting the hub (hub migrates every field, then the server and its ask endpoint)"
    dc up -d --wait caddy server tls-ask
    if ! dc run --rm -T hub hosted check; then
        dc stop server tls-ask
        fail "after the migrations the hub fails the isolation check; the server is stopped: see above"
    fi
else
    echo "restore.sh: starting the server (it runs the migrations)"
    dc up -d --wait server caddy
fi
echo "restore.sh: restored $file"
