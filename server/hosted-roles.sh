#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# A hosted hub's two database roles (ADR-P4-4 as built, plan phase 21; Phase 4
# follow-up, decisions FU4-*; server/docs/DEPLOY.md, "Hosted mode"):
#   sh server/hosted-roles.sh
# server/setup.sh --hosted and server/restore.sh run it; it is safe to run
# again. In the PostgreSQL container, as its superuser, it:
#   - makes atalaia_owner (owns the database, the field schemas and the hub's
#     tables; runs the migrations and the operator's commands) and atalaia_app
#     (the server's role) if they are missing: both LOGIN, NOSUPERUSER,
#     NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOINHERIT;
#   - sets their passwords to ATALAIA_OWNER_DB_PASSWORD and
#     ATALAIA_APP_DB_PASSWORD from the env file, so the file and the database
#     always agree (a restore on a new machine, a rotated password);
#   - makes atalaia_owner the owner of the database atalaia.
# The SQL, passwords included, goes to psql on standard input, never on a
# command line, with statement logging off for that session; PostgreSQL keeps
# only the passwords' SCRAM hashes. Nothing secret is printed.
# Settings: ATALAIA_ENV_FILE (server/.env), COMPOSE_PROJECT_NAME.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
env_file=${ATALAIA_ENV_FILE:-$here/.env}

fail() {
    echo "hosted-roles.sh: $*" >&2
    exit 1
}

[ -f "$env_file" ] || fail "$env_file is missing (run server/setup.sh DOMAIN --hosted first)"

# A value from the env file only: the roles belong to the deployment, not to a shell.
current() {
    sed -n "s/^$1=//p" "$env_file" | tail -n 1
}

[ "$(current ATALAIA_HOSTED)" = on ] || fail "$env_file is not a hosted hub's (ATALAIA_HOSTED=on; server/setup.sh --hosted)"
owner_pw=$(current ATALAIA_OWNER_DB_PASSWORD)
app_pw=$(current ATALAIA_APP_DB_PASSWORD)
for pw in "$owner_pw" "$app_pw"; do
    # Letters, digits, - and _ only (setup.sh makes 64 hex digits): safe in a URL and an SQL literal.
    if ! printf '%s\n' "$pw" | grep -Eq '^[A-Za-z0-9_-]{32,128}$'; then
        fail "ATALAIA_OWNER_DB_PASSWORD and ATALAIA_APP_DB_PASSWORD must be 32-128 letters, digits, - or _" \
            "(server/setup.sh --hosted makes them)"
    fi
done
[ "$owner_pw" != "$app_pw" ] || fail "the owner's and the server's database passwords must differ"

dc() {
    docker compose --env-file "$env_file" -f "$here/docker-compose.yml" -f "$here/docker-compose.hosted.yml" "$@"
}

dc up -d --wait postgres
{
    printf '%s\n' "SET log_statement TO none;" "SET log_min_error_statement TO panic;" \
        "SET log_min_duration_statement TO -1;" \
        "DO \$\$ BEGIN" \
        "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atalaia_owner') THEN CREATE ROLE atalaia_owner; END IF;" \
        "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atalaia_app') THEN CREATE ROLE atalaia_app; END IF;" \
        "END \$\$;"
    for role in atalaia_owner atalaia_app; do
        if [ "$role" = atalaia_owner ]; then pw=$owner_pw; else pw=$app_pw; fi
        printf "ALTER ROLE %s LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD '%s';\n" \
            "$role" "$pw"
    done
    printf '%s\n' "ALTER DATABASE atalaia OWNER TO atalaia_owner;"
} | dc exec -T postgres psql -U atalaia -d postgres -v ON_ERROR_STOP=1 -q -X > /dev/null \
    || fail "making the roles failed"
echo "hosted-roles.sh: the roles atalaia_owner and atalaia_app are set up (passwords from $env_file, not shown)"
