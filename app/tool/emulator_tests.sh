#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Runs the on-device tests (integration_test/) on an emulator or phone from
# Linux or WSL, as CI's emulator job does, with Flutter installed natively:
#
#   sh app/tool/emulator_tests.sh [device] [test path]     (default: emulator-5554 integration_test)
#
# In WSL, the emulator usually runs on Windows: start the Windows adb server
# with `adb -a nodaemon server start` and point this side at it, e.g.
# `export ADB_SERVER_SOCKET=tcp:$(ip route show default | awk '{print $3}'):5037`.
#
# Android 13 and later ask before an app may post notifications, and a prop
# asks when its game starts. Flutter cannot tap a system dialog, so while the
# tests run this grants the permission as soon as `flutter test` has installed
# the app; the app then finds it granted and asks nothing.
set -u
DEVICE=${1:-emulator-5554}
TEST=${2:-integration_test}
cd "$(dirname "$0")/.."
# The GM console and the check-in notices into assets/ (decision PE24-61).
dart tool/sync_console.dart || exit 1
(while true; do adb -s "$DEVICE" shell pm grant org.atalaia.app android.permission.POST_NOTIFICATIONS; sleep 0.3; done) >/dev/null 2>&1 &
grant=$!
flutter test "$TEST" -d "$DEVICE"
code=$?
kill "$grant" 2>/dev/null
exit $code
