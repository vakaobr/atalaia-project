// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Which of a field's addresses to use (decisions check-R1 to check-R6): a
/// poster lists up to three https addresses of its controller, and one may be
/// stale (the controller's old DHCP address), which costs a full timeout when
/// the addresses are tried one after the other. [raceUrls] is a "happy
/// eyeballs" race: the first address starts at once, the next after a short
/// stagger or at the failure of the one before, the first that completes (the
/// TLS handshake with the field's pinned CA, or the stream's upgrade) wins and
/// the others are cancelled. [FieldRoutes] remembers the winner per field (and
/// hands it to be kept in the pinned field's record) and the last failures per
/// field, with their kind, address and time, which the screens that say "the
/// field controller does not answer" show as a details line.
///
/// The race changes only which address is used; every attempt still trusts the
/// field's CA alone, as before (field_trust.dart).
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// Why an address did not answer.
enum FailKind { timeout, refused, unreachable, tls, http, other }

/// One failed attempt: what kind, at which address, when.
final class FieldFailure {
  const FieldFailure(
    this.kind,
    this.url,
    this.at, {
    this.status,
    this.detail = '',
  });

  final FailKind kind;
  final String url;
  final DateTime at;

  /// The HTTP status of [FailKind.http].
  final int? status;

  /// The error's own text, for the log.
  final String detail;

  @override
  String toString() =>
      'FieldFailure(${kind.name}${status != null ? ' $status' : ''} $url '
      '${at.toIso8601String()}: $detail)';
}

/// An attempt's own account of why it failed (a kind the exception types
/// of dart:io do not say).
class RouteError implements Exception {
  RouteError(this.kind, this.message, {this.status});
  final FailKind kind;
  final String message;
  final int? status;

  @override
  String toString() => 'RouteError(${kind.name}): $message';
}

/// Every address failed.
class RaceFailed implements Exception {
  RaceFailed(this.failures);
  final List<FieldFailure> failures;

  @override
  String toString() =>
      'RaceFailed(${failures.map((f) => '${f.kind.name} ${f.url}').join(', ')})';
}

const _refused = {111, 61, 10061};
const _unreachable = {101, 113, 51, 65, 10051, 10065};
const _timedOut = {110, 60, 10060};

/// The kind of a failure from what dart:io throws.
FailKind classifyError(Object e) {
  if (e is RouteError) return e.kind;
  if (e is TimeoutException) return FailKind.timeout;
  if (e is TlsException) return FailKind.tls; // handshake, certificate
  if (e is SocketException) {
    final code = e.osError?.errorCode;
    if (code != null) {
      if (_refused.contains(code)) return FailKind.refused;
      if (_unreachable.contains(code)) return FailKind.unreachable;
      if (_timedOut.contains(code)) return FailKind.timeout;
    }
    final m = '${e.message} ${e.osError?.message}'.toLowerCase();
    if (m.contains('refused')) return FailKind.refused;
    if (m.contains('unreachable') || m.contains('no route')) {
      return FailKind.unreachable;
    }
    if (m.contains('timed out')) return FailKind.timeout;
  }
  return FailKind.other;
}

FieldFailure failureOf(String url, Object e, DateTime at) => FieldFailure(
  classifyError(e),
  url,
  at,
  status: e is RouteError ? e.status : null,
  detail: '$e',
);

/// Lets an attempt stop what it started (close its socket) when the race is
/// won by another address.
final class RaceCancel {
  bool _cancelled = false;
  final _callbacks = <void Function()>[];

  bool get cancelled => _cancelled;

  void onCancel(void Function() f) {
    if (_cancelled) {
      f();
    } else {
      _callbacks.add(f);
    }
  }

  void cancel() {
    if (_cancelled) return;
    _cancelled = true;
    for (final f in _callbacks) {
      try {
        f();
      } on Object {
        // a socket already closed
      }
    }
    _callbacks.clear();
  }
}

const defaultStagger = Duration(milliseconds: 250);
const defaultAttemptTimeout = Duration(seconds: 8);

/// Runs [attempt] on [urls] in order, the next one after [stagger] or when
/// the one before fails; the first to succeed wins and cancels the others
/// (a loser that succeeds later is handed to [dispose]). When all fail,
/// throws [RaceFailed] with each one's kind.
Future<(String, T)> raceUrls<T>(
  List<String> urls,
  Future<T> Function(String url, RaceCancel cancel) attempt, {
  Duration stagger = defaultStagger,
  Duration attemptTimeout = defaultAttemptTimeout,
  void Function(T value)? dispose,
  DateTime Function() now = DateTime.now,
}) {
  final done = Completer<(String, T)>();
  final failures = <FieldFailure>[];
  final cancels = <RaceCancel>[];
  var next = 0;
  var running = 0;
  var finished = false;
  Timer? timer;

  void startNext() {
    timer?.cancel();
    timer = null;
    if (finished || next >= urls.length) return;
    final url = urls[next++];
    final cancel = RaceCancel();
    cancels.add(cancel);
    running++;
    if (next < urls.length) timer = Timer(stagger, startNext);
    Future<T> run;
    try {
      run = attempt(url, cancel);
    } on Object catch (e) {
      run = Future<T>.error(e);
    }
    run
        .timeout(
          attemptTimeout,
          onTimeout: () {
            cancel.cancel();
            throw TimeoutException('no answer from $url', attemptTimeout);
          },
        )
        .then(
          (value) {
            running--;
            if (finished) {
              dispose?.call(value);
              return;
            }
            finished = true;
            timer?.cancel();
            for (final c in cancels) {
              if (!identical(c, cancel)) c.cancel();
            }
            done.complete((url, value));
          },
          onError: (Object e) {
            running--;
            if (finished) return;
            failures.add(failureOf(url, e, now()));
            if (next < urls.length) {
              startNext();
            } else if (running == 0) {
              finished = true;
              done.completeError(RaceFailed(failures));
            }
          },
        );
  }

  if (urls.isEmpty) return Future.error(RaceFailed(failures));
  startNext();
  return done.future;
}

/// The winners and the failures, per field (or per link: any key).
class FieldRoutes {
  FieldRoutes({
    this.stagger = defaultStagger,
    this.attemptTimeout = defaultAttemptTimeout,
    this.persist,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final Duration stagger;
  final Duration attemptTimeout;

  /// Called when a field's winning address changes: the pinned field keeps it.
  Future<void> Function(String key, String url)? persist;
  final DateTime Function() _now;

  final _winner = <String, String>{};
  final _failures = <String, List<FieldFailure>>{};

  /// The address that answered last for [key], else [seed] (the pinned
  /// field's kept one).
  String? winner(String key, [String? seed]) => _winner[key] ?? seed;

  /// [urls] with the remembered winner first (when it is among them) and
  /// [avoid] last.
  List<String> order(
    String key,
    List<String> urls, {
    String? seed,
    String? avoid,
  }) {
    final w = winner(key, seed);
    final first = w != null && urls.contains(w) ? w : null;
    final out = [
      ?first,
      for (final u in urls)
        if (u != first) u,
    ];
    if (avoid != null && out.length > 1 && out.remove(avoid)) out.add(avoid);
    return out;
  }

  /// The failures of the last round for [key], oldest first.
  List<FieldFailure> failures(String key) =>
      List.unmodifiable(_failures[key] ?? const []);

  /// The latest failure for [key], or null (none since the last success).
  FieldFailure? last(String key) {
    final f = _failures[key];
    return f == null || f.isEmpty ? null : f.last;
  }

  void succeeded(String key, String url) {
    _failures.remove(key);
    if (_winner[key] != url) {
      _winner[key] = url;
      final p = persist;
      if (p != null) unawaited(p(key, url).catchError((Object _) {}));
    }
  }

  void failed(String key, List<FieldFailure> failures) {
    _failures[key] = List.of(failures);
    for (final f in failures) {
      debugPrint('field $key: ${f.kind.name} at ${f.url}: ${f.detail}');
    }
  }

  /// One failure after the address answered (an HTTP status, a request that
  /// broke off).
  void noteFailure(String key, FieldFailure f) => failed(key, [f]);

  FieldFailure failure(String url, Object e) => failureOf(url, e, _now());

  /// Races [attempt] on [urls] (the remembered winner first), remembers the
  /// winner and clears the failures; on failure keeps them and rethrows.
  Future<(String, T)> choose<T>(
    String key,
    List<String> urls,
    Future<T> Function(String url, RaceCancel cancel) attempt, {
    String? seed,
    String? avoid,
    void Function(T value)? dispose,
  }) async {
    try {
      final r = await raceUrls<T>(
        order(key, urls, seed: seed, avoid: avoid),
        attempt,
        stagger: stagger,
        attemptTimeout: attemptTimeout,
        dispose: dispose,
        now: _now,
      );
      succeeded(key, r.$1);
      return r;
    } on RaceFailed catch (e) {
      failed(key, e.failures);
      rethrow;
    }
  }
}
