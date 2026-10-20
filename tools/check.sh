#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Checks the generated protocol files, the project page and the formatting, builds the core, runs its tests, the
# simulator's tests, every game mode's tests, the field controller's tests
# (against the C host modem, the C host box, the C host pod and a private Mosquitto) and
# the site server's tests that need no database (settings, ids, the shared Python): the same
# checks as CI (apart from the JSON Schema and licensing checks, which need
# extra tools, the firmware jobs: tools/docker_fw.py, the site server on
# PostgreSQL: tools/docker_server.py, the GM console's
# browser tests: tools/docker_console.py, and the app's Dart checks and
# Android builds: tools/docker_app.py, since this image has no Dart; the
# controller's tests below do check the Python side of the app's shared chrono
# and token vectors, and the simulator's tests its ctypes structs against the FFI stub).
# Run from the repository root, natively or in the dev container (see
# tools/dev/Dockerfile).
set -eu
export ATALAIA_REQUIRE_ALL=1
BUILD="${BUILD:-build}"
python3 tools/protogen.py --check
python3 tools/build_site.py --check
python3 tools/check_wiring.py
if command -v clang-format > /dev/null 2>&1 && command -v stylua > /dev/null 2>&1; then
    sh tools/format.sh --check
else
    echo "check.sh: skipping the formatting check (clang-format or stylua missing; the dev container has both)"
fi
cmake -S core -B "$BUILD" -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON -DATALAIA_STUB=ON
cmake --build "$BUILD"
ctest --test-dir "$BUILD" --output-on-failure
export ATALAIA_CORE_LIB="$(cd "$BUILD" && pwd)/libatalaia_core.so"
# The FFI stub: the simulator's ctypes structs are checked against its layout report.
export ATALAIA_CORE_STUB_LIB="$(cd "$BUILD" && pwd)/libatalaia_core_stub.so"
cmake -S firmware/esp32/test/modem_host -B "$BUILD/modem_host" -DCMAKE_BUILD_TYPE=Debug
cmake --build "$BUILD/modem_host"
export ATALAIA_MODEM_HOST="$(cd "$BUILD/modem_host" && pwd)/modem_host"
cmake -S firmware/esp32/test/box_host -B "$BUILD/box_host" -DCMAKE_BUILD_TYPE=Debug
cmake --build "$BUILD/box_host"
export ATALAIA_BOX_HOST="$(cd "$BUILD/box_host" && pwd)/box_host"
cmake -S firmware/esp32/test/pod_host -B "$BUILD/pod_host" -DCMAKE_BUILD_TYPE=Debug
cmake --build "$BUILD/pod_host"
export ATALAIA_POD_HOST="$(cd "$BUILD/pod_host" && pwd)/pod_host"
cd simulator
python3 -m unittest discover -s tests
python3 -m atalaia_sim test
cd ../controller
python3 -m unittest discover -s tests
# The site server's plain-Python tests (decision P4R17); the rest need PostgreSQL 16
# and the server's own image: python3 tools/docker_server.py test.
cd ../server
python3 -m unittest tests.test_config tests.test_ids tests.test_shared_imports tests.test_chrono_verify tests.test_feeds \
    tests.test_import_format tests.test_firmware
