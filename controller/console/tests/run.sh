#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs the GM console's browser tests: builds the core library, the C host
# modem and the C host box (as tools/check.sh does), then the tests in this folder with
# headless Chromium. Run from the repository root inside the image of
# tools/dev/console/Dockerfile (python tools/docker_console.py does that,
# and so does CI's console job). With ATALAIA_REQUIRE_BROWSER=1 a missing
# browser, Playwright or zbarimg is an error, never a skip.
set -eu
export ATALAIA_REQUIRE_ALL=1
export ATALAIA_REQUIRE_BROWSER="${ATALAIA_REQUIRE_BROWSER:-1}"
BUILD="${BUILD:-/tmp/console-build}"
cmake -S core -B "$BUILD/core" -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON -DBUILD_TESTING=OFF > /dev/null
cmake --build "$BUILD/core" > /dev/null
cmake -S firmware/esp32/test/modem_host -B "$BUILD/modem_host" -DCMAKE_BUILD_TYPE=Debug > /dev/null
cmake --build "$BUILD/modem_host" > /dev/null
export ATALAIA_CORE_LIB="$(cd "$BUILD/core" && pwd)/libatalaia_core.so"
export ATALAIA_MODEM_HOST="$(cd "$BUILD/modem_host" && pwd)/modem_host"
# The tests share controller/tests/support.py, which needs the host box and
# the host pod too.
cmake -S firmware/esp32/test/box_host -B "$BUILD/box_host" -DCMAKE_BUILD_TYPE=Debug > /dev/null
cmake --build "$BUILD/box_host" > /dev/null
export ATALAIA_BOX_HOST="$(cd "$BUILD/box_host" && pwd)/box_host"
cmake -S firmware/esp32/test/pod_host -B "$BUILD/pod_host" -DCMAKE_BUILD_TYPE=Debug > /dev/null
cmake --build "$BUILD/pod_host" > /dev/null
export ATALAIA_POD_HOST="$(cd "$BUILD/pod_host" && pwd)/pod_host"
cd controller
python3 -m unittest discover -s console/tests -v "$@"
