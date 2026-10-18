#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The app's checks, run inside ghcr.io/cirruslabs/flutter:3.44.0 by
# tools/docker_app.py and by CI's "Player app logic (Dart)" job:
#
#   sh app/tool/check.sh [check]      pub get from the lockfile, flutter analyze,
#                                     dart format check, flutter test
#   sh app/tool/check.sh test [ARGS]  only flutter test (ARGS: paths, --name, ...)
#   sh app/tool/check.sh format       format lib/ and test/ in place
#   sh app/tool/check.sh lock         resolve pubspec.yaml again and write pubspec.lock
#
# The repository is at $ATALAIA_SRC (default /src), mounted read-only for
# check and test: the work happens on a copy of app/ and protocol/ (the tests
# read the shared vectors in protocol/vectors/), so nothing is written into
# the checkout. format and lock copy their results back and need it writable.
set -eu
SRC="${ATALAIA_SRC:-/src}"
MODE="${1:-check}"
[ $# -gt 0 ] && shift
W=/tmp/atalaia-app
export FLUTTER_SUPPRESS_ANALYTICS=true
rm -rf "$W"
mkdir -p "$W"
cp -r "$SRC/app" "$SRC/protocol" "$W/"
rm -rf "$W/app/.dart_tool" "$W/app/build"
cd "$W/app"
flutter --version
case "$MODE" in
    check)
        flutter pub get --enforce-lockfile
        flutter analyze --fatal-infos
        dart format --output=none --set-exit-if-changed lib test
        flutter test "$@"
        ;;
    test)
        flutter pub get --enforce-lockfile
        flutter test "$@"
        ;;
    format)
        flutter pub get --enforce-lockfile
        dart format lib test
        cp -r lib test "$SRC/app/"
        ;;
    lock)
        flutter pub get
        cp pubspec.lock "$SRC/app/pubspec.lock"
        ;;
    *)
        echo "check.sh: unknown mode '$MODE' (check, test, format or lock)" >&2
        exit 2
        ;;
esac
