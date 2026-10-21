#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs the staff pages' browser tests (server/tests_browser/) inside the image of
# tools/dev/server-browser/Dockerfile, with the repository at /src (read-only) and
# ATALAIA_DATABASE_URL pointing at PostgreSQL 16: python3 tools/docker_server.py browser
# does both; with arguments, only those tests (tests_browser.test_staff_browser.RemoteGmTests). Builds the core library (for the scenario check) in $BUILD first. With
# ATALAIA_REQUIRE_BROWSER=1 a missing Playwright or Chromium is an error, never a skip.
set -eu
export ATALAIA_REQUIRE_ALL=1
export ATALAIA_REQUIRE_BROWSER="${ATALAIA_REQUIRE_BROWSER:-1}"
BUILD="${BUILD:-/tmp/server-browser-build}"
cd "$(dirname "$0")/../.."
cmake -S core -B "$BUILD/core" -DCMAKE_BUILD_TYPE=Release -DATALAIA_SHARED=ON -DATALAIA_MBEDTLS=OFF \
    -DBUILD_TESTING=OFF > /dev/null
cmake --build "$BUILD/core" --parallel > /dev/null
export ATALAIA_CORE_LIB="$(cd "$BUILD/core" && pwd)/libatalaia_core.so"
export PYTHONPATH="$PWD/server:$PWD/controller:$PWD/simulator"
cd server
if [ $# -eq 0 ]; then
    exec python3 -m unittest discover -s tests_browser -t . -v
fi
exec python3 -m unittest -v "$@"
