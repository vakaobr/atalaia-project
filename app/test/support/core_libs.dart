// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The two shared libraries the bridge tests load: the real core and the FFI
/// stub, both built from core/ for this machine.
///
///     cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF
///     cmake --build build
///
/// `$ATALAIA_CORE_LIB` and `$ATALAIA_CORE_STUB_LIB` name them (tools/docker_app.py
/// and CI set both); otherwise ../build/ is tried, as the simulator does, for the
/// file name the machine's CMake gives a shared library: `.so` on Linux, `.dylib`
/// on macOS, `.dll` on Windows (app/README.md, "Tests on a Mac"). A missing
/// library fails the tests that need it: nothing is skipped.
library;

import 'dart:io';

/// The file names CMake gives the shared library [stem] (the target's name
/// without "lib") on [os] (a `Platform.operatingSystem` value), the likeliest
/// first: libatalaia_core.so on Linux (and any other Unix), libatalaia_core.dylib
/// on macOS, atalaia_core.dll (MSVC) or libatalaia_core.dll (MinGW) on Windows.
List<String> sharedLibraryNames(String stem, {required String os}) {
  switch (os) {
    case 'macos':
      return ['lib$stem.dylib'];
    case 'windows':
      return ['$stem.dll', 'lib$stem.dll'];
    default:
      return ['lib$stem.so'];
  }
}

String _find(String variable, String stem) {
  final env = Platform.environment[variable];
  if (env != null && env.isNotEmpty) {
    if (!File(env).existsSync()) {
      throw StateError('\$$variable is $env, which does not exist');
    }
    return env;
  }
  final fileNames = sharedLibraryNames(stem, os: Platform.operatingSystem);
  for (final folder in ['../build', '../build/core', '../core/build']) {
    for (final fileName in fileNames) {
      final candidate = File('$folder/$fileName');
      if (candidate.existsSync()) return candidate.absolute.path;
    }
  }
  throw StateError(
    '${fileNames.join(' or ')} not found: set \$$variable, or build it with\n'
    '  cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF\n'
    '  cmake --build build\n'
    '(python tools/docker_app.py does all of this in Docker)',
  );
}

/// The real core (libatalaia_core).
String coreLibraryPath() => _find('ATALAIA_CORE_LIB', 'atalaia_core');

/// The FFI stub (libatalaia_core_stub, core/tests/stub.c).
String stubLibraryPath() => _find('ATALAIA_CORE_STUB_LIB', 'atalaia_core_stub');
