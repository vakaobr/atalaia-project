#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Runs the mode editor's browser tests (phase 5 plan phase A): builds the
# core library (as tools/check.sh does), then the tests in this folder with
# headless Chromium. Run from the repository root inside the image of
# tools/dev/console/Dockerfile (python tools/docker_editor.py does that, and
# so does CI's editor job). With ATALAIA_REQUIRE_BROWSER=1 a missing browser,
# Playwright or core library is an error, never a skip.
set -eu
export ATALAIA_REQUIRE_BROWSER="${ATALAIA_REQUIRE_BROWSER:-1}"
BUILD="${BUILD:-/tmp/console-build}"
cmake -S core -B "$BUILD/core" -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON -DBUILD_TESTING=OFF > /dev/null
cmake --build "$BUILD/core" > /dev/null
export ATALAIA_CORE_LIB="$(cd "$BUILD/core" && pwd)/libatalaia_core.so"
cd simulator
python3 -m unittest discover -s editor_tests -v "$@"
