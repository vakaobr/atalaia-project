// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Reconnecting to an I/O pod by itself (decision PF15 left it out: the app
/// reported the lost link and the person linked again by hand).
///
/// A [PodReconnector] watches a linked [PodClient]. When the link breaks it
/// opens the same pod again, with a growing wait between tries (1 s, 2 s, 4 s,
/// 8 s, 16 s, then every 30 s) for as long as it is kept, and shows its state.
/// The safety rules of the first link stay:
///
///   - the same pod only: the one the link was opened to, and its IDENT must
///     list the capabilities the lost link's did, else the link is refused
///     ([PodLinkPhase.refused]) and not tried again;
///   - the same wait for the IDENT as the first link: 3 s over USB, 30 s over
///     Bluetooth (Android's pairing question; the pod's encrypted link, PF4);
///     a link that does not identify itself is closed and tried again;
///   - a new link is a new [PodClient] (its commands and events start clean);
///     whoever uses it hears of it in [onReplaced] and configures its radio
///     again (a new epoch, so a nonce never repeats under the game key);
///   - the old link is closed before the new one is opened (both links of a
///     kind share one platform channel);
///   - [unlink] (the person's choice), [suspend] and [dispose] stop it:
///     nothing is opened after them, also not by a try already waiting;
///   - over Bluetooth, a try that fails is explained by the pairing, as
///     [linkPod] explains the first link (decisions PODPK-4, PODPK-8 and
///     ROB-1 to ROB-4): a pod that says the phone's bond is no good (HCI
///     0x05, "repair") is paired again once by itself (the phone's bond
///     removed, [onRepair] called, the next try at once, without a wait);
///     a wrong passkey, a cancelled or too slow pairing, a second "repair"
///     or an Android that refuses to remove the bond stop the tries
///     ([PodLinkPhase.relink], with [relinkMessage]): the person links the
///     pod again by hand, so a pairing dialog is never asked for twice
///     unasked.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'pod_client.dart';
import 'pod_codec.dart';
import 'pod_pairing.dart';

enum PodLinkPhase {
  /// The link is up.
  linked,

  /// The link broke; the app opens it again with a growing wait.
  reconnecting,

  /// The person unlinked the pod: nothing is tried again.
  unlinked,

  /// The pod that answered is not the one that was linked: not tried again.
  refused,

  /// The pairing went wrong while the link was opened again (a wrong or no
  /// passkey, too slow, or a bond the pod still refuses): not tried again,
  /// the person links the pod again ([PodReconnector.relinkMessage] says why).
  relink,
}

/// Opens the link to the pod again; the client it returns is open and not
/// started. Null: it could not be opened (the pod is out of reach).
typedef PodReopen = Future<PodClient?> Function(PodClient lost);

/// The wait before try [attempt] (1 for the first).
typedef PodBackoff = Duration Function(int attempt);

Duration defaultPodBackoff(int attempt) {
  const waits = [1, 2, 4, 8, 16, 30];
  return Duration(seconds: waits[(attempt - 1).clamp(0, waits.length - 1)]);
}

/// How long a new link has to say who it is: as the first link's.
Duration podIdentTimeout(PodClient c) => c.transport.kind == 'usb'
    ? const Duration(seconds: 3)
    : const Duration(seconds: 30);

class PodReconnector extends ChangeNotifier {
  PodReconnector({
    required PodClient client,
    required this.reopen,
    this.onReplaced,
    this.backoff = defaultPodBackoff,
    this.identTimeout = podIdentTimeout,
    PodBonds? bonds,
    this.onRepair,
  }) : bonds = bonds ?? _bondsOf(client) {
    _client = client;
    _watch();
  }

  /// The plugin's side of the bonds: given, or the link's own transport
  /// when it keeps them (ChannelPodTransport over Bluetooth).
  static PodBonds? _bondsOf(PodClient c) {
    final t = c.transport;
    return t is PodBonds ? t as PodBonds : null;
  }

  final PodReopen reopen;

  /// Called with the new client once it has identified itself as the same pod
  /// (its [PodClient.ident] is set) and the old one is closed.
  final void Function(PodClient old, PodClient next)? onReplaced;
  final PodBackoff backoff;
  final Duration Function(PodClient) identTimeout;

  /// How a Bluetooth try's pairing ended (null: not asked, as over USB).
  final PodBonds? bonds;

  /// Called when the phone's bond was removed for the pod to pair anew: a
  /// new passkey is on the pod's screen and Android asks for it.
  final void Function()? onRepair;

  /// Why the tries stopped in [PodLinkPhase.relink]: a message key of
  /// lib/l10n/strings_*.dart ("pod.wrong_passkey", "pod.pair_timeout",
  /// "pod.repair_manual"); null in the other phases.
  String? relinkMessage;

  /// The phone's bond was removed and the pod is pairing anew (Android's
  /// dialog asks for the passkey), until the link is up or the tries stop.
  bool repairing = false;

  /// Paired again once by itself since the link broke: a second "repair"
  /// stops.
  var _repaired = false;

  /// The next try starts at once (after the bond was removed).
  var _now = false;

  late PodClient _client;
  PodLinkPhase phase = PodLinkPhase.linked;

  /// Tries made since the link broke (0 while it is up).
  int attempt = 0;

  /// When the next try starts, while waiting for it (for the screen).
  DateTime? retryAt;

  StreamSubscription<PodEvent>? _sub;
  Timer? _timer;
  Completer<void>? _wait;
  var _running = false;
  var _suspended = false;
  var _disposed = false;

  /// The link in use: the one given, or the latest that replaced it.
  PodClient get client => _client;

  bool get stopped =>
      phase == PodLinkPhase.unlinked ||
      phase == PodLinkPhase.refused ||
      phase == PodLinkPhase.relink;

  bool get _halt => _disposed || stopped || _suspended;

  void _watch() {
    unawaited(_sub?.cancel());
    final c = _client;
    _sub = c.events.listen((e) {
      if (e is PodLinkBroken && identical(c, _client)) _broke();
    });
    if (c.broken) _broke();
  }

  void _broke() {
    if (_halt || _running) return;
    phase = PodLinkPhase.reconnecting;
    attempt = 0;
    _repaired = false;
    repairing = false;
    _now = false;
    notifyListeners();
    unawaited(_loop());
  }

  Future<void> _loop() async {
    _running = true;
    try {
      // Closed once, before the first try: the platform channel of a kind
      // holds one link at a time.
      await _client.close();
      while (!_halt) {
        attempt++;
        if (_now) {
          _now = false;
        } else {
          final wait = backoff(attempt);
          retryAt = DateTime.now().add(wait);
          notifyListeners();
          await _sleep(wait);
          if (_halt) return;
          retryAt = null;
        }
        notifyListeners();
        if (await _try()) return;
      }
    } finally {
      _running = false;
      retryAt = null;
    }
  }

  Future<void> _sleep(Duration d) {
    final w = _wait = Completer<void>();
    _timer = Timer(d, () {
      if (!w.isCompleted) w.complete();
    });
    return w.future;
  }

  void _wake() {
    _timer?.cancel();
    final w = _wait;
    if (w != null && !w.isCompleted) w.complete();
  }

  /// One try; true when it ends the loop (linked, refused or stopped).
  Future<bool> _try() async {
    final old = _client;
    final PodClient? next;
    try {
      next = await reopen(old);
    } on Object {
      return _failed(old);
    }
    if (next == null) return _failed(old);
    if (_halt) {
      await next.close();
      return true;
    }
    final identified = Completer<void>();
    final sub = next.events.listen((e) {
      if (e is PodIdentified && !identified.isCompleted) identified.complete();
      if (e is PodLinkBroken && !identified.isCompleted) {
        identified.completeError(StateError('broken'));
      }
    });
    var ok = false;
    try {
      await next.start();
      await identified.future.timeout(identTimeout(next));
      ok = true;
    } on Object {
      ok = false;
    }
    await sub.cancel();
    if (!ok || _halt) {
      await next.close();
      return _halt || await _failed(old);
    }
    if (!_samePod(old.ident, next.ident)) {
      await next.close();
      phase = PodLinkPhase.refused;
      notifyListeners();
      return true;
    }
    _client = next;
    phase = PodLinkPhase.linked;
    attempt = 0;
    repairing = false;
    _watch();
    notifyListeners();
    onReplaced?.call(old, next);
    return true;
  }

  /// After a try that did not link [old]'s pod again: what its pairing said
  /// (over Bluetooth). True when the tries stop ([PodLinkPhase.relink]);
  /// false to try again, at once after the bond was removed. As [linkPod].
  Future<bool> _failed(PodClient old) async {
    final b = bonds;
    final device = old.device;
    // A link not opened from a scan has no device to open or forget (and
    // the plugin's word would be about some other link).
    if (b == null || device == null || old.transport.kind != 'ble') {
      return false;
    }
    final PodPairError? error;
    try {
      error = await b.lastPairError();
    } on Object {
      return false;
    }
    if (_halt) return true;
    // Out of reach, or a link that ended without a word on the pairing.
    if (error == null) return false;
    if (error != PodPairError.needsRepair || _repaired) {
      return _stop(podPairMessage(error));
    }
    bool forgot;
    try {
      forgot = await b.forgetBond(device);
    } on Object {
      forgot = false;
    }
    if (_halt) return true;
    if (!forgot) return _stop('pod.repair_manual');
    _repaired = true;
    repairing = true;
    _now = true;
    notifyListeners();
    onRepair?.call();
    return false;
  }

  bool _stop(String messageKey) {
    phase = PodLinkPhase.relink;
    relinkMessage = messageKey;
    repairing = false;
    retryAt = null;
    notifyListeners();
    return true;
  }

  /// The same pod: the same capabilities (ids and types), radio or not. A
  /// link that never identified has nothing to compare.
  static bool _samePod(PodIdent? before, PodIdent? after) {
    if (after == null) return false;
    if (before == null) return true;
    if (before.hasRadio != after.hasRadio) return false;
    String key(PodIdent i) =>
        [for (final c in i.capabilities) '${c['id']}:${c['type']}'].join(',');
    return key(before) == key(after);
  }

  /// The person unlinked the pod: stops for good and closes the link.
  Future<void> unlink() async {
    if (_disposed || phase == PodLinkPhase.unlinked) return;
    phase = PodLinkPhase.unlinked;
    retryAt = null;
    _wake();
    notifyListeners();
    await _client.close();
  }

  /// Stops trying for now (the pod is handed to another screen); [resume]
  /// starts again if the link is broken.
  void suspend() {
    _suspended = true;
    _wake();
  }

  void resume() {
    if (!_suspended) return;
    _suspended = false;
    if (_running) return;
    if (_client.broken) {
      _broke();
    }
  }

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _wake();
    unawaited(_sub?.cancel());
    super.dispose();
  }
}
