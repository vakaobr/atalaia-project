// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The two shared libraries the bridge tests load: the real core and the FFI
/// stub, both built from core/ for this machine.
///
///     cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF
///     cmake --build build
///
/// `$ATALAIA_CORE_LIB` and `$ATALAIA_CORE_STUB_LIB` name them (tools/docker_app.py
/// and CI set both); otherwise ../build/ is tried, as the simulator does. A
/// missing library fails the tests that need it: nothing is skipped.
library;

import 'dart:io';

String _find(String variable, String fileName) {
  final env = Platform.environment[variable];
  if (env != null && env.isNotEmpty) {
    if (!File(env).existsSync()) {
      throw StateError('\$$variable is $env, which does not exist');
    }
    return env;
  }
  for (final folder in ['../build', '../build/core', '../core/build']) {
    final candidate = File('$folder/$fileName');
    if (candidate.existsSync()) return candidate.absolute.path;
  }
  throw StateError(
    '$fileName not found: set \$$variable, or build it with\n'
    '  cmake -S core -B build -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF\n'
    '  cmake --build build\n'
    '(python tools/docker_app.py does all of this in Docker)',
  );
}

/// The real core (libatalaia_core).
String coreLibraryPath() => _find('ATALAIA_CORE_LIB', 'libatalaia_core.so');

/// The FFI stub (libatalaia_core_stub, core/tests/stub.c).
String stubLibraryPath() =>
    _find('ATALAIA_CORE_STUB_LIB', 'libatalaia_core_stub.so');
