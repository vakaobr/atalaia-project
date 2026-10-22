# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Runs the on-device tests (integration_test/) on an emulator or phone from
# Windows, as CI's emulator job does, with Flutter installed on Windows:
#
#   powershell -ExecutionPolicy Bypass -File app\tool\emulator_tests.ps1 [-Device emulator-5554] [-Test integration_test]
#
# Android 13 and later ask before an app may post notifications, and a prop
# asks when its game starts. Flutter cannot tap a system dialog, so while the
# tests run this grants the permission as soon as `flutter test` has installed
# the app; the app then finds it granted and asks nothing.

param(
    [string]$Device = 'emulator-5554',
    [string]$Test = 'integration_test'
)

$ErrorActionPreference = 'Stop'
$adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
$app = Split-Path -Parent $PSScriptRoot

$grant = Start-Job -ArgumentList $adb, $Device -ScriptBlock {
    param($adb, $device)
    while ($true) {
        & $adb -s $device shell pm grant org.atalaia.app android.permission.POST_NOTIFICATIONS 2>$null
        Start-Sleep -Milliseconds 300
    }
}
try {
    Push-Location $app
    # The GM console and the check-in notices into assets/ (decision PE24-61).
    dart tool/sync_console.dart
    if ($LASTEXITCODE -ne 0) { throw 'sync_console failed' }
    flutter test $Test -d $Device
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    Stop-Job $grant; Remove-Job $grant
}
exit $code
