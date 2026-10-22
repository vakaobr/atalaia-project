// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Position reports while a player shares their position (ADR-P3-6): the
/// phone's fixes, sent to the field controller every [interval] (the
/// controller says how often; 10 s by default), at most 5 per request. The
/// controller decides who sees them; the phone keeps nothing. Stops by
/// itself when the controller says the game is not running (409) or the
/// token is no longer valid (401).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../checkin/checkin_client.dart';
import '../platform/location.dart';

typedef SendReports =
    Future<Map<String, Object?>> Function(List<Map<String, Object?>> reports);

class PositionReporter extends ChangeNotifier {
  PositionReporter({
    required this.location,
    required this.send,
    this.interval = const Duration(seconds: 10),
    this.onFix,
  });

  final LocationService location;
  final SendReports send;
  Duration interval;

  /// Each fix as it arrives, for the out-of-bounds warning (field_bounds.dart,
  /// decision MF-31): the same fixes the reports carry, no extra GPS.
  void Function(LocationFix fix)? onFix;

  StreamSubscription<LocationFix>? _sub;
  Timer? _timer;
  final _pending = <LocationFix>[];
  bool get running => _sub != null;

  /// Reports the controller stored.
  int sent = 0;
  String? stopReason;

  void start() {
    if (running) return;
    stopReason = null;
    _sub = location
        .fixes(interval)
        .listen(_onFix, onError: (Object e) => stop('$e'));
    _timer = Timer.periodic(interval, (_) => unawaited(flush()));
    notifyListeners();
  }

  void _onFix(LocationFix f) {
    _pending.add(f);
    if (_pending.length > 5) _pending.removeAt(0);
    onFix?.call(f);
  }

  /// Sends what is waiting (tests call it directly).
  Future<void> flush() async {
    if (_pending.isEmpty) return;
    final batch = List.of(_pending);
    _pending.clear();
    try {
      final out = await send([for (final f in batch) f.toReport()]);
      sent += batch.length;
      final s = out['interval_s'];
      if (s is int && s >= 5 && s <= 60 && s != interval.inSeconds) {
        interval = Duration(seconds: s);
        _timer?.cancel();
        _timer = Timer.periodic(interval, (_) => unawaited(flush()));
      }
      notifyListeners();
    } on CheckinException catch (e) {
      if (e.status == 409 || e.status == 401 || e.status == 403) {
        stop(e.message);
      } else {
        _pending.insertAll(0, batch.take(5 - _pending.length));
      }
    }
  }

  void stop([String? reason]) {
    unawaited(_sub?.cancel());
    _sub = null;
    _timer?.cancel();
    _timer = null;
    _pending.clear();
    stopReason = reason;
    notifyListeners();
  }

  @override
  void dispose() {
    stop();
    super.dispose();
  }
}
