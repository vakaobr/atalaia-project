// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Trusting a field's controller (ADR-P3-13, protocol/checkin.md "Trust"):
/// on the first scan of a field's poster, fetch its CA certificate from
/// `GET /api/v1/controller/ca`, check its SHA-256 against the poster's
/// fingerprint, and keep it for that field. From then on the app talks to
/// that field over HTTPS trusting that CA alone, for the poster's addresses
/// only, never through the phone's trust store. A later poster for the same
/// field with another fingerprint is refused; the player removes the field
/// first to accept it.
///
/// The fetch itself cannot check the server (the CA is not known yet), so it
/// accepts the connection's certificate for that one request; the
/// fingerprint check on the answer is what makes the trust. A forged poster
/// can only fool a phone that never saw the real one.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../protocol/checkin_poster.dart';
import '../security/bytes.dart';
import '../storage/app_store.dart';
import 'field_route.dart';

/// Fetches the PEM text at [url] (the CA endpoint), however its TLS looks.
typedef CaFetcher = Future<String> Function(Uri url);

enum TrustFailure { unreachable, notACertificate, mismatch, changed }

class TrustException implements Exception {
  TrustException(this.reason, this.message, {this.knownShort, this.newShort});
  final TrustFailure reason;
  final String message;

  /// For [TrustFailure.changed]: the pinned and the poster's short forms.
  final String? knownShort;
  final String? newShort;

  @override
  String toString() => 'TrustException(${reason.name}): $message';
}

/// A field the app trusts: its CA, its addresses, its name.
final class PinnedField {
  PinnedField({
    required this.fieldId,
    required this.fieldName,
    required this.caPem,
    required this.caSha256,
    required this.urls,
    this.wifiSsid,
    this.lastUrl,
  });

  final String fieldId;
  final String fieldName;
  final String caPem;
  final Uint8List caSha256;
  final List<String> urls;
  final String? wifiSsid;

  /// The address that answered last (decision check-R3): tried first.
  final String? lastUrl;

  PinnedField withLastUrl(String? url) => PinnedField(
    fieldId: fieldId,
    fieldName: fieldName,
    caPem: caPem,
    caSha256: caSha256,
    urls: urls,
    wifiSsid: wifiSsid,
    lastUrl: url,
  );

  String get caShort => shortFingerprint(caSha256);

  Map<String, Object?> toJson() => {
    'field_id': fieldId,
    'field_name': fieldName,
    'ca_pem': caPem,
    'ca_sha256': hexEncode(caSha256),
    'urls': urls,
    'wifi_ssid': wifiSsid,
    if (lastUrl != null) 'last_url': lastUrl,
  };

  static PinnedField? fromJson(Map<String, Object?> j) {
    try {
      return PinnedField(
        fieldId: j['field_id']! as String,
        fieldName: j['field_name']! as String,
        caPem: j['ca_pem']! as String,
        caSha256: hexDecode(j['ca_sha256']! as String),
        urls: (j['urls']! as List).cast<String>(),
        wifiSsid: j['wifi_ssid'] as String?,
        lastUrl: j['last_url'] as String?,
      );
    } on Object {
      return null;
    }
  }

  /// The TLS context that trusts this field's CA and nothing else: the one
  /// every connection to the field uses, the race's probes included.
  SecurityContext securityContext() =>
      SecurityContext(withTrustedRoots: false)
        ..setTrustedCertificatesBytes(utf8.encode(caPem));

  /// An HTTP client that trusts this field's CA and nothing else.
  HttpClient client() {
    return HttpClient(context: securityContext())
      ..connectionTimeout = const Duration(seconds: 8)
      ..idleTimeout = const Duration(seconds: 15);
  }
}

/// The DER bytes of the first certificate in [pem], or null.
Uint8List? pemToDer(String pem) {
  final m = RegExp(
    r'-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]+)-----END CERTIFICATE-----',
  ).firstMatch(pem);
  if (m == null) return null;
  try {
    return base64.decode(m.group(1)!.replaceAll(RegExp(r'\s'), ''));
  } on FormatException {
    return null;
  }
}

/// The CA endpoint's PEM, over a TLS connection whose certificate is not
/// checked (see the library's note); 64 KB at most.
Future<String> ioFetchCa(Uri url) async {
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 8)
    ..badCertificateCallback = (cert, host, port) => true;
  try {
    final req = await client.getUrl(url);
    final res = await req.close().timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) {
      throw RouteError(
        FailKind.http,
        '${url.host}: HTTP ${res.statusCode}',
        status: res.statusCode,
      );
    }
    final bytes = <int>[];
    await for (final chunk in res) {
      bytes.addAll(chunk);
      if (bytes.length > 65536) {
        throw TrustException(TrustFailure.notACertificate, 'too long');
      }
    }
    return utf8.decode(bytes, allowMalformed: true);
  } finally {
    client.close(force: true);
  }
}

class FieldTrust {
  FieldTrust(this.store, {CaFetcher? fetch, FieldRoutes? routes})
    : _fetch = fetch ?? ioFetchCa,
      routes = routes ?? FieldRoutes();

  final AppStore store;

  /// The addresses' winners and failures (the CA fetch races them too).
  final FieldRoutes routes;
  final CaFetcher _fetch;
  static const _list = 'trusted_fields';

  Future<List<PinnedField>> all() async => [
    for (final j in await store.loadList(_list)) ?PinnedField.fromJson(j),
  ];

  Future<PinnedField?> known(String fieldId) async {
    for (final f in await all()) {
      if (f.fieldId == fieldId) return f;
    }
    return null;
  }

  /// The field of [poster], pinned now on the first scan or checked against
  /// the pin. The addresses and name follow the latest poster.
  Future<PinnedField> pin(CheckinPoster poster) async {
    final old = await known(poster.fieldId);
    if (old != null) {
      if (!constantTimeEquals(old.caSha256, poster.caSha256)) {
        throw TrustException(
          TrustFailure.changed,
          'this field was trusted with another certificate',
          knownShort: old.caShort,
          newShort: poster.caShort,
        );
      }
      final updated = PinnedField(
        fieldId: old.fieldId,
        fieldName: poster.fieldName,
        caPem: old.caPem,
        caSha256: old.caSha256,
        urls: poster.urls,
        wifiSsid: poster.wifiSsid,
        lastUrl: poster.urls.contains(old.lastUrl) ? old.lastUrl : null,
      );
      await _save(updated);
      return updated;
    }
    final (pem, got) = await _fetchCa(
      poster.fieldId,
      poster.urls,
      poster.caSha256,
      'the poster',
    );
    final f = PinnedField(
      fieldId: poster.fieldId,
      fieldName: poster.fieldName,
      caPem: pem,
      caSha256: got,
      urls: poster.urls,
      wifiSsid: poster.wifiSsid,
      lastUrl: routes.winner(poster.fieldId),
    );
    await _save(f);
    return f;
  }

  /// The CA from the first of [urls] that answers with the certificate whose
  /// fingerprint is [expected] (a race, check-R1): an address held by another
  /// device (another certificate) counts as a failed one and the race goes
  /// on; when none matches, the certificate that did not is what is reported.
  Future<(String, Uint8List)> _fetchCa(
    String key,
    List<String> urls,
    Uint8List expected,
    String what,
  ) async {
    TrustException? definite;
    try {
      final (_, r) = await routes.choose<(String, Uint8List)>(key, urls, (
        u,
        cancel,
      ) async {
        final pem = await _fetch(Uri.parse('$u/api/v1/controller/ca'));
        final der = pemToDer(pem);
        if (der == null) {
          definite ??= TrustException(
            TrustFailure.notACertificate,
            'the controller did not send a certificate',
          );
          throw RouteError(FailKind.tls, 'not a certificate');
        }
        final got = Uint8List.fromList(sha256.convert(der).bytes);
        if (!constantTimeEquals(got, expected)) {
          definite ??= TrustException(
            TrustFailure.mismatch,
            "the controller's certificate is not the one on $what",
            knownShort: shortFingerprint(expected),
            newShort: shortFingerprint(got),
          );
          throw RouteError(FailKind.tls, 'another certificate');
        }
        return (pem, got);
      });
      return r;
    } on RaceFailed catch (e) {
      throw definite ??
          TrustException(
            TrustFailure.unreachable,
            'no address of $what answered (${e.failures.map((f) => '${f.kind.name} ${f.url}').join(', ')})',
          );
    }
  }

  /// A prop's trust for one game (ADR-P3-9): the CA from [urls] checked
  /// against the join payload's fingerprint; not kept after the game.
  Future<PinnedField> forGame(List<String> urls, Uint8List caSha256) async {
    final (pem, got) = await _fetchCa(
      'game',
      urls,
      caSha256,
      'the join payload',
    );
    return PinnedField(
      fieldId: 'game',
      fieldName: '',
      caPem: pem,
      caSha256: got,
      urls: urls,
    );
  }

  /// Keeps [url] as the address that answered for [fieldId] (a field not
  /// pinned, or a game's prop, has none to keep).
  Future<void> remember(String fieldId, String url) async {
    final f = await known(fieldId);
    if (f == null || f.lastUrl == url || !f.urls.contains(url)) return;
    await _save(f.withLastUrl(url));
  }

  Future<void> _save(PinnedField f) async {
    final rest = [
      for (final j in await store.loadList(_list))
        if (j['field_id'] != f.fieldId) j,
    ];
    await store.saveList(_list, [...rest, f.toJson()]);
  }

  /// Forgets a field (to accept a new certificate, or on the player's request).
  Future<void> forget(String fieldId) async {
    await store.saveList(_list, [
      for (final j in await store.loadList(_list))
        if (j['field_id'] != fieldId) j,
    ]);
  }
}
