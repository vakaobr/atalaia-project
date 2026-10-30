// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A CA kept as exactly one certificate (security review APP-1). A pin is the
/// hash of one certificate; a PEM with a second one behind it would be trusted
/// whole by a [SecurityContext] though only the first was ever hashed.
library;

import 'dart:convert';
import 'dart:typed_data';

final _block = RegExp(
  r'-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]*)-----END CERTIFICATE-----',
);

/// The DER bytes of every certificate in [pem], in order; null when anything
/// but whitespace sits between them (a key, a label, a half block) or a block
/// is not base64.
List<Uint8List>? pemCertificates(String pem) {
  final out = <Uint8List>[];
  var end = 0;
  for (final m in _block.allMatches(pem)) {
    if (pem.substring(end, m.start).trim().isNotEmpty) return null;
    end = m.end;
    try {
      final der = base64.decode(m.group(1)!.replaceAll(RegExp(r'\s'), ''));
      if (der.isEmpty) return null;
      out.add(der);
    } on FormatException {
      return null;
    }
  }
  if (pem.substring(end).trim().isNotEmpty) return null;
  return out;
}

/// The DER bytes of the first certificate in [pem], or null. (To decide what
/// is trusted use [singleCertificate]: this one ignores what follows.)
Uint8List? pemToDer(String pem) {
  final m = _block.firstMatch(pem);
  if (m == null) return null;
  try {
    return base64.decode(m.group(1)!.replaceAll(RegExp(r'\s'), ''));
  } on FormatException {
    return null;
  }
}

/// [der] as a PEM certificate (64 characters a line).
String derToPem(List<int> der) {
  final b64 = base64.encode(der);
  final lines = [
    for (var i = 0; i < b64.length; i += 64)
      b64.substring(i, i + 64 > b64.length ? b64.length : i + 64),
  ];
  return '-----BEGIN CERTIFICATE-----\n${lines.join('\n')}\n-----END CERTIFICATE-----\n';
}

/// The one certificate in [pem] (its DER), or null when there are none, more
/// than one, or anything else in the text.
Uint8List? singleCertificate(String pem) {
  final all = pemCertificates(pem);
  return all != null && all.length == 1 ? all.single : null;
}
