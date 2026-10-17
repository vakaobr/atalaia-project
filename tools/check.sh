#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Checks the generated protocol files, the project page and the formatting, builds the core, runs its tests, the
# simulator's tests and every game mode's tests: the same checks as CI
# (apart from the JSON Schema and licensing checks, which need extra tools).
# Run from the repository root, natively or in the dev container (see
# tools/dev/Dockerfile).
set -eu
BUILD="${BUILD:-build}"
python3 tools/protogen.py --check
python3 tools/build_site.py --check
if command -v clang-format > /dev/null 2>&1 && command -v stylua > /dev/null 2>&1; then
    sh tools/format.sh --check
else
    echo "check.sh: skipping the formatting check (clang-format or stylua missing; the dev container has both)"
fi
cmake -S core -B "$BUILD" -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON
cmake --build "$BUILD"
ctest --test-dir "$BUILD" --output-on-failure
export ATALAIA_CORE_LIB="$(cd "$BUILD" && pwd)/libatalaia_core.so"
cd simulator
python3 -m unittest discover -s tests
python3 -m atalaia_sim test
