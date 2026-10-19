#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs inside the site server's test image (server/Dockerfile, target test),
# with ATALAIA_DATABASE_URL pointing at a PostgreSQL 16 server:
#   sh tests/run.sh test [unittest names...]   every test, or only these (tests.test_health ...)
#   sh tests/run.sh migrations                 upgrade head, downgrade base, upgrade head, check
# tools/docker_server.py runs it with an ephemeral postgres:16-alpine (Docker
# Compose, server/docker-compose.test.yml); CI's server job runs the very same
# commands against a postgres:16-alpine service container.
set -eu
cd "$(dirname "$0")/.."
if [ -z "${ATALAIA_DATABASE_URL:-}" ]; then
    echo "run.sh: ATALAIA_DATABASE_URL is not set" >&2
    exit 2
fi
what="${1:-test}"
[ $# -gt 0 ] && shift
case "$what" in
    test)
        if [ $# -eq 0 ]; then
            exec python -m unittest discover -s tests -t . -v
        fi
        exec python -m unittest -v "$@"
        ;;
    migrations)
        set -x
        alembic upgrade head
        alembic downgrade base
        alembic upgrade head
        alembic check
        ;;
    *)
        echo "run.sh: unknown command '$what' (test or migrations)" >&2
        exit 2
        ;;
esac
