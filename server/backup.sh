#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# An encrypted backup of the site server's database (ADR-P4-10, plan phase 22;
# server/docs/DEPLOY.md). Run it daily from cron:
#   sh server/backup.sh
# pg_dump -Fc runs in the PostgreSQL container and its output goes straight
# through `backup-crypt seal` (AES-256-GCM with ATALAIA_BACKUP_KEY, a container
# with no network; decision S22-3), so the dump is never on disk unencrypted.
# The backup is checked (opened in full) before it gets its name:
#   ATALAIA_BACKUP_DIR/atalaia-YYYYMMDDTHHMMSSZ.backup   (mode 0600, folder 0700)
# then backups older than ATALAIA_BACKUP_DAYS days (30) are deleted; the new one
# never is. Everything the site server keeps is in the database; Caddy's
# certificates are not backed up (it gets new ones). Exit code 0 only when the
# new backup is complete; cron mails anything else.
#
# A hosted hub (ATALAIA_HOSTED=on in the env file; Phase 4 follow-up, decisions
# FU4-*) is backed up the same way, through both Compose files: the one dump
# holds every field's schema, the registry and the hub's audit log, with their
# owners, grants, row-level security and policies (pg_dump keeps them all;
# PostgreSQL's superuser reads past the row-level security). The roles
# themselves are not in a database dump: restore.sh makes them again from .env.
#
# Settings: ATALAIA_ENV_FILE (server/.env), ATALAIA_BACKUP_DIR (server/backups),
# ATALAIA_BACKUP_DAYS (from the environment or the env file), COMPOSE_PROJECT_NAME.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
env_file=${ATALAIA_ENV_FILE:-$here/.env}

fail() {
    echo "backup.sh: $*" >&2
    exit 1
}

[ -f "$env_file" ] || fail "$env_file is missing (run server/setup.sh first)"

# A setting from the environment, else from the env file, else $2.
setting() {
    eval "value=\${$1:-}"
    if [ -z "$value" ]; then
        value=$(sed -n "s/^$1=//p" "$env_file" | tail -n 1)
    fi
    printf '%s' "${value:-$2}"
}

hosted=$(sed -n 's/^ATALAIA_HOSTED=//p' "$env_file" | tail -n 1)
dc() {
    if [ "$hosted" = on ]; then
        docker compose --env-file "$env_file" -f "$here/docker-compose.yml" -f "$here/docker-compose.hosted.yml" "$@"
    else
        docker compose --env-file "$env_file" -f "$here/docker-compose.yml" "$@"
    fi
}

backup_dir=$(setting ATALAIA_BACKUP_DIR "$here/backups")
days=$(setting ATALAIA_BACKUP_DAYS 30)
case "$days" in
    '' | *[!0-9]*) fail "ATALAIA_BACKUP_DAYS must be a number of days, not '$days'" ;;
esac
[ "$days" -ge 1 ] || fail "ATALAIA_BACKUP_DAYS must be at least 1"
[ -n "$(setting ATALAIA_BACKUP_KEY '')" ] || fail "ATALAIA_BACKUP_KEY is not set in $env_file (run server/setup.sh)"

umask 077
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"

# One backup at a time; a lock left by a backup that was killed is taken over.
lock="$backup_dir/.lock"
if ! mkdir "$lock" 2> /dev/null; then
    pid=$(cat "$lock/pid" 2> /dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2> /dev/null; then
        fail "another backup is running (process $pid)"
    fi
    rm -rf "$lock"
    mkdir "$lock" || fail "cannot take the lock $lock"
fi
echo "$$" > "$lock/pid"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$backup_dir/atalaia-$stamp.backup"
tmp="$out.partial"
trap 'rm -rf "$lock" "$tmp"' EXIT
trap 'exit 130' INT TERM
[ ! -e "$out" ] || fail "$out exists already"

# POSIX sh has no pipefail: pg_dump's exit code goes through a file.
sealed=1
{
    rc=0
    dc exec -T postgres pg_dump -U atalaia -d atalaia -Fc || rc=$?
    echo "$rc" > "$lock/dump"
} | dc run --rm -T backup-crypt seal > "$tmp" || sealed=0
dumped=$(cat "$lock/dump" 2> /dev/null || echo missing)
[ "$dumped" = 0 ] || fail "pg_dump failed (exit code $dumped); no backup was made"
[ "$sealed" -eq 1 ] || fail "encrypting the dump failed; no backup was made"

# A backup that cannot be opened is no backup.
dc run --rm -T backup-crypt open < "$tmp" > /dev/null || fail "the new backup does not open; no backup was made"
chmod 600 "$tmp"
mv "$tmp" "$out"
size=$(wc -c < "$out" | tr -d ' ')
if [ "$hosted" = on ]; then
    echo "backup.sh: $out ($size bytes, encrypted; the hosted hub: every field, the registry, the hub's audit log)"
else
    echo "backup.sh: $out ($size bytes, encrypted)"
fi

for old in "$backup_dir"/atalaia-*.backup; do
    if [ ! -f "$old" ] || [ "$old" = "$out" ]; then
        continue
    fi
    if [ -n "$(find "$old" -prune -mtime +"$days")" ]; then
        rm -f "$old"
        echo "backup.sh: deleted $old (older than $days days)"
    fi
done
