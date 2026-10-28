#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The app's checks, run inside ghcr.io/cirruslabs/flutter:3.44.0 by
# tools/docker_app.py and by CI's flutter-test, core-android-ndk and
# flutter-build-android jobs:
#
#   sh app/tool/check.sh [check]      pub get from the lockfile, flutter analyze,
#                                     dart format check, flutter test
#   sh app/tool/check.sh test [ARGS]  only flutter test (ARGS: paths, --name, ...)
#   sh app/tool/check.sh ndk          cross-compile the core with the Android NDK
#                                     for arm64-v8a, armeabi-v7a and x86_64
#                                     (core/CMakePresets.json) and check the libraries
#   sh app/tool/check.sh apk          flutter build apk --debug (Gradle builds the
#                                     core with the NDK) and check the APK's libraries,
#                                     and that it carries no Google Play services
#   sh app/tool/check.sh format       format lib/, test/, integration_test/ and tool/ in place
#   sh app/tool/check.sh lock         resolve pubspec.yaml again and write pubspec.lock
#   sh app/tool/check.sh gen          write lib/modes/builtin_modes.g.dart from modes/
#   sh app/tool/check.sh goldens      draw the golden images of test/goldens/ again
#
# check and test need the core and the FFI stub built for this machine as
# shared libraries, named by ATALAIA_CORE_LIB and ATALAIA_CORE_STUB_LIB, and
# the host pod, host modem and host box programs, named by ATALAIA_POD_HOST,
# ATALAIA_MODEM_HOST and ATALAIA_BOX_HOST (this image has no CMake;
# docker_app.py builds them in the atalaia-dev image, CI on the runner): the
# bridge tests load the stub, every mode's tests in modes/*/tests/ run on the
# real core through the Dart bridge, the pod and radio-link tests run the pod
# firmware's own code, and the phone controller's end-to-end tests the pod's
# and the Field Box's (slice S4 of PE24).
#
# The repository is at $ATALAIA_SRC (default /src), mounted read-only except
# for format, lock, gen and goldens: the work happens on a copy of app/,
# core/, modes/, protocol/ and the GM console (controller/console/src,
# controller/templates), so nothing is written into the checkout. Those four
# copy their results back and need it writable. The console and the check-in
# notices go into the app's assets with tool/sync_console.dart first (slice
# S6 of PE24: the phone controller serves them; decision PE24-61).
set -eu
SRC="${ATALAIA_SRC:-/src}"
MODE="${1:-check}"
[ $# -gt 0 ] && shift
W=/tmp/atalaia-app
export FLUTTER_SUPPRESS_ANALYTICS=true

# Pinned Android build tools (the same in android/app/build.gradle.kts).
NDK_VERSION=28.2.13676358
CMAKE_VERSION=3.22.1
ABIS="arm64-v8a armeabi-v7a x86_64"

# The Dart folders the formatter checks and formats.
DART_DIRS="lib test integration_test tool"

rm -rf "$W"
mkdir -p "$W"
cp -r "$SRC/app" "$SRC/core" "$SRC/modes" "$SRC/protocol" "$W/"
mkdir -p "$W/controller/console"
cp -r "$SRC/controller/console/src" "$W/controller/console/"
cp -r "$SRC/controller/templates" "$W/controller/"
mkdir -p "$W/registry"
cp -r "$SRC/registry/apds" "$W/registry/"
# console_bundle_test.dart compares the field-map page's origins with the Pi's api.py (MF-64).
mkdir -p "$W/controller/atalaia_controller"
cp "$SRC/controller/atalaia_controller/api.py" "$W/controller/atalaia_controller/"
# The phone controller's slice S7b tests read the Pi's branding images and its
# example scenarios (the scenario compiler itself is the core's, core/scenario/).
mkdir -p "$W/controller/tests"
cp -r "$SRC/controller/tests/fixtures" "$SRC/controller/tests/scenarios" "$W/controller/tests/"
rm -rf "$W/app/.dart_tool" "$W/app/build" "$W/app/android/.gradle" "$W/app/android/app/.cxx" \
    "$W/core/build"
cd "$W/app"
# The GM console and the check-in notices into assets/ (never committed).
dart tool/sync_console.dart

need_core_libs() {
    for var in ATALAIA_CORE_LIB ATALAIA_CORE_STUB_LIB ATALAIA_POD_HOST ATALAIA_MODEM_HOST ATALAIA_BOX_HOST; do
        eval "path=\${$var:-}"
        if [ -z "$path" ] || [ ! -f "$path" ]; then
            echo "check.sh: $var must name the library or program built from core/ or" \
                "firmware/esp32/test/ (now: '${path}')." >&2
            echo "  Build them with: cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON" \
                "-DATALAIA_MBEDTLS=OFF && cmake --build build, and cmake -S" \
                "firmware/esp32/test/pod_host (and modem_host, box_host) (tools/docker_app.py does this)" >&2
            exit 2
        fi
        echo "$var=$path"
    done
    # A missing host program fails the tests that need it here (Docker and CI): the Dart
    # tests skip them only on a machine that opted in, e.g. a Mac (test/support/pod_host.dart).
    export ATALAIA_ALLOW_MISSING_HOSTS=0
}

# The NDK and CMake from the Android SDK manager, at the pinned versions
# (Gradle would fetch the same ones; docker_app.py keeps them in volumes).
android_tools() {
    sdk="${ANDROID_HOME:?ANDROID_HOME is not set}"
    if [ ! -f "$sdk/ndk/$NDK_VERSION/source.properties" ] || [ ! -x "$sdk/cmake/$CMAKE_VERSION/bin/cmake" ]; then
        echo "Installing NDK $NDK_VERSION and CMake $CMAKE_VERSION (Android SDK manager)..."
        yes | sdkmanager --install "ndk;$NDK_VERSION" "cmake;$CMAKE_VERSION" > /tmp/sdkmanager.log 2>&1 \
            || { tail -20 /tmp/sdkmanager.log; exit 1; }
    fi
    NDK="$sdk/ndk/$NDK_VERSION"
    grep '^Pkg.Revision' "$NDK/source.properties"
    "$sdk/cmake/$CMAKE_VERSION/bin/cmake" --version | head -1
}

# Checks one Android build of the core: right machine, 16 KB pages (Android 15+),
# the node.h entry points exported, and nothing it would need from outside the NDK.
check_android_lib() {
    lib="$1"
    abi="$2"
    tools="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
    case "$abi" in
        arm64-v8a) machine=AArch64 ;;
        armeabi-v7a) machine=ARM ;;
        x86_64) machine=X86-64 ;;
    esac
    "$tools/llvm-readelf" -h "$lib" | grep -q "Machine:.*$machine" \
        || { echo "check.sh: $lib is not built for $abi" >&2; exit 1; }
    for sym in atalaia_version atalaia_node_create atalaia_node_destroy atalaia_node_load \
        atalaia_node_set_teams atalaia_node_set_params atalaia_node_input atalaia_node_advance \
        atalaia_node_status atalaia_node_mem_used atalaia_tag_event_json atalaia_tpl_parse \
        atalaia_scenario_check atalaia_scenario_compile atalaia_scenario_free; do
        "$tools/llvm-nm" -D --defined-only "$lib" | grep -q " T $sym\$" \
            || { echo "check.sh: $lib does not export $sym" >&2; exit 1; }
    done
    needed=$("$tools/llvm-readelf" -d "$lib" | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort | tr '\n' ' ')
    for so in $needed; do
        case "$so" in
            libc.so | libm.so | libdl.so) ;;
            *) echo "check.sh: $lib needs $so, which an APK does not provide" >&2; exit 1 ;;
        esac
    done
    if [ "$abi" != armeabi-v7a ] \
        && "$tools/llvm-readelf" -l "$lib" | awk '$1 == "LOAD" { print $NF }' | grep -qv '^0x4000$'; then
        echo "check.sh: $lib has LOAD segments not aligned to 16 KB" >&2
        exit 1
    fi
    echo "ok   $abi  $(wc -c < "$lib") bytes, needs: $needed"
}

flutter --version
case "$MODE" in
    check)
        need_core_libs
        flutter pub get --enforce-lockfile
        flutter analyze --fatal-infos
        dart format --output=none --set-exit-if-changed $DART_DIRS
        flutter test "$@"
        ;;
    test)
        need_core_libs
        flutter pub get --enforce-lockfile
        flutter test "$@"
        ;;
    ndk)
        android_tools
        # core/CMakePresets.json finds the NDK's toolchain file through ANDROID_NDK_HOME.
        export ANDROID_NDK_HOME="$NDK"
        export PATH="$ANDROID_HOME/cmake/$CMAKE_VERSION/bin:$PATH"
        cd "$W/core"
        for abi in $ABIS; do
            preset="android-$abi"
            cmake --preset "$preset" > "/tmp/$preset.log" 2>&1 || { cat "/tmp/$preset.log"; exit 1; }
            cmake --build --preset "$preset" >> "/tmp/$preset.log" 2>&1 || { cat "/tmp/$preset.log"; exit 1; }
            if grep -q 'warning:' "/tmp/$preset.log"; then
                grep 'warning:' "/tmp/$preset.log" >&2
                echo "check.sh: the $abi build has warnings" >&2
                exit 1
            fi
            check_android_lib "$W/build/$preset/libatalaia_core.so" "$abi"
        done
        ;;
    apk)
        android_tools
        flutter pub get --enforce-lockfile
        flutter build apk --debug
        apk=build/app/outputs/flutter-apk/app-debug.apk
        listing=$(unzip -l "$apk")
        for abi in $ABIS; do
            echo "$listing" | grep -q "lib/$abi/libatalaia_core.so" \
                || { echo "check.sh: $apk has no lib/$abi/libatalaia_core.so" >&2; exit 1; }
            mkdir -p "/tmp/apk-lib/$abi"
            unzip -o -q "$apk" "lib/$abi/libatalaia_core.so" -d "/tmp/apk-lib/$abi"
            check_android_lib "/tmp/apk-lib/$abi/lib/$abi/libatalaia_core.so" "$abi"
        done
        # The GM console the phone controller serves: every file of controller/console/src
        # (and the check-in notices) in the APK's assets (decision PE24-61).
        n=0
        for f in $(cd assets && find console notices -type f); do
            echo "$listing" | grep -q " assets/flutter_assets/assets/$f\$" \
                || { echo "check.sh: $apk has no assets/$f" >&2; exit 1; }
            n=$((n + 1))
        done
        echo "ok   the GM console and the check-in notices in the APK ($n files)"
        # No proprietary SDKs (decision PD5): no Google Play services or ML Kit classes.
        mkdir -p /tmp/apk-dex
        unzip -o -q "$apk" 'classes*.dex' -d /tmp/apk-dex
        # (ZXing's classes must be found: proof that the search reads the classes.)
        cat /tmp/apk-dex/classes*.dex | grep -a -q 'Lcom/google/zxing/qrcode/QRCodeReader;'             || { echo "check.sh: cannot read the classes of $apk" >&2; exit 1; }
        if cat /tmp/apk-dex/classes*.dex | grep -a -q -E 'Lcom/google/android/gms/|Lcom/google/mlkit/'; then
            echo "check.sh: $apk contains Google Play services or ML Kit classes" >&2
            exit 1
        fi
        echo "ok   no Google Play services or ML Kit classes in the APK"
        echo "ok   $apk ($(wc -c < "$apk") bytes)"
        # A writable folder to put the APK in (tools/docker_app.py mounts app/build/).
        if [ -n "${ATALAIA_APK_OUT:-}" ]; then
            cp "$apk" "$ATALAIA_APK_OUT/atalaia-debug.apk"
            echo "ok   copied to app/build/atalaia-debug.apk"
        fi
        ;;
    format)
        flutter pub get --enforce-lockfile
        dart format $DART_DIRS
        cp -r $DART_DIRS "$SRC/app/"
        ;;
    gen)
        flutter pub get --enforce-lockfile
        dart run tool/gen_modes.dart ../modes
        dart format lib/modes/builtin_modes.g.dart
        cp lib/modes/builtin_modes.g.dart "$SRC/app/lib/modes/"
        ;;
    goldens)
        flutter pub get --enforce-lockfile
        flutter test --update-goldens test/goldens "$@"
        rm -rf "$SRC/app/test/goldens/images"
        cp -r test/goldens/images "$SRC/app/test/goldens/"
        ;;
    lock)
        flutter pub get
        cp pubspec.lock "$SRC/app/pubspec.lock"
        ;;
    *)
        echo "check.sh: unknown mode '$MODE' (check, test, ndk, apk, format, lock, gen or goldens)" >&2
        exit 2
        ;;
esac
