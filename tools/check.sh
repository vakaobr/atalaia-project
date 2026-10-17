#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Builds the core, runs its tests and runs every game mode's tests in the
# simulator: the same checks as CI. Run from the repository root, natively
# or in the dev container (see tools/dev/Dockerfile).
set -eu
BUILD="${BUILD:-build}"
cmake -S core -B "$BUILD" -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON
cmake --build "$BUILD"
ctest --test-dir "$BUILD" --output-on-failure
LIB="$(cd "$BUILD" && pwd)/libatalaia_core.so"
cd simulator && python3 -m atalaia_sim --lib "$LIB" test
