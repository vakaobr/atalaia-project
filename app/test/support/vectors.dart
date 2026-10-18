// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The shared test vectors in protocol/vectors/ (the app's tests run from app/).
library;

import 'dart:convert';
import 'dart:io';

/// The decoded JSON of protocol/vectors/[name].
Map<String, dynamic> loadVectors(String name) {
  final file = File('../protocol/vectors/$name');
  if (!file.existsSync()) {
    throw StateError('${file.path} not found: run the tests from app/');
  }
  return jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
}

/// The items of the list [key] in [vectors], as JSON objects.
List<Map<String, dynamic>> cases(Map<String, dynamic> vectors, String key) =>
    (vectors[key] as List<dynamic>).cast<Map<String, dynamic>>();
