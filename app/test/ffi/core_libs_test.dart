// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The tests' own way of finding the core: the file name a shared library has
// on each machine (test/support/core_libs.dart), so that a Mac, which builds
// .dylib files, finds what `cmake -DATALAIA_SHARED=ON` made there.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

void main() {
  test('Linux (and other Unix) looks for .so, macOS for .dylib', () {
    expect(sharedLibraryNames('atalaia_core', os: 'linux'), [
      'libatalaia_core.so',
    ]);
    expect(sharedLibraryNames('atalaia_core_stub', os: 'android'), [
      'libatalaia_core_stub.so',
    ]);
    expect(sharedLibraryNames('atalaia_core', os: 'macos'), [
      'libatalaia_core.dylib',
    ]);
    expect(sharedLibraryNames('atalaia_core_stub', os: 'macos'), [
      'libatalaia_core_stub.dylib',
    ]);
  });

  test('Windows tries MSVC\'s name, then MinGW\'s', () {
    expect(sharedLibraryNames('atalaia_core', os: 'windows'), [
      'atalaia_core.dll',
      'libatalaia_core.dll',
    ]);
  });

  test('on this machine the libraries are the ones the tests load', () {
    final core = coreLibraryPath();
    final stub = stubLibraryPath();
    final names = sharedLibraryNames(
      'atalaia_core',
      os: Platform.operatingSystem,
    );
    expect(names.any(core.endsWith), isTrue, reason: core);
    expect(File(core).existsSync(), isTrue);
    expect(File(stub).existsSync(), isTrue);
  });
}
