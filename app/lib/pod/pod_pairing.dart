// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Pairing with an I/O pod over Bluetooth LE (decisions PODPK-1 to
/// PODPK-11). The pod shows a 6-digit passkey on its OLED; Android's own
/// pairing dialog asks for it (the app does not pair by itself: the pod
/// asks to pair when the link opens, and Android answers). What the app
/// adds is a hint before, a clear message after, and pairing again once
/// when the pod says the phone's bond is no good.
///
/// How a bond that needs pairing again is found: the pod checks, when the
/// link is encrypted, that the key was made with a passkey (MITM-protected;
/// a Just Works bond from a pod firmware before 0.8 is not) and that it
/// still has its side (the PRG button clears every bond). If not, it forgets
/// its side and drops the link with HCI reason 0x05, Authentication Failure.
/// The Bluetooth plugin (BlePodPlugin.kt) reports that as "repair"; the app
/// then removes Android's side of the bond and opens the link again, so
/// Android pairs anew with the passkey. Once: a second "repair" in a row, or
/// an Android that refuses to remove the bond, asks the person to forget
/// the pod in the Bluetooth settings.
library;

import 'dart:async';

import 'pod_client.dart';
import 'pod_reconnect.dart' show podIdentTimeout;
import 'pod_transports.dart' show PodDevice;

/// How a pairing went wrong, as the Bluetooth plugin saw it.
enum PodPairError {
  /// Android's bond went from bonding to none: a wrong passkey, or Cancel.
  wrongPasskey,

  /// The pairing ran out of time (the Security Manager's 30 s).
  timeout,

  /// The pod dropped the link: it does not trust this phone's bond.
  needsRepair;

  /// The plugin's code ("pair_failed", "pair_timeout", "repair"), or null.
  static PodPairError? fromCode(String? code) => switch (code) {
    'pair_failed' => wrongPasskey,
    'pair_timeout' => timeout,
    'repair' => needsRepair,
    _ => null,
  };
}

/// The phone's side of a pod's bond: what the last pairing said, and
/// removing the bond.
abstract interface class PodBonds {
  /// How the last link's pairing ended badly, or null.
  Future<PodPairError?> lastPairError();

  /// Removes Android's bond with [device]; false when Android refuses.
  Future<bool> forgetBond(PodDevice device);
}

/// One try at linking: what the caller links (a [PodClient] that has said
/// who it is, or the open transport), else null and the message key of what
/// went wrong when the pairing does not say more ("pod.open_failed",
/// "pod.no_ident").
typedef PodLinkTry<T> = Future<(T?, String)> Function();

/// The outcome of [linkPod].
sealed class PodLinkOutcome<T> {
  const PodLinkOutcome();
}

final class PodLinked<T> extends PodLinkOutcome<T> {
  const PodLinked(this.link, {this.repaired = false});
  final T link;

  /// The phone's old bond was removed and the pod paired anew.
  final bool repaired;
}

final class PodLinkFailed<T> extends PodLinkOutcome<T> {
  const PodLinkFailed(this.messageKey);

  /// The message to show (lib/l10n/strings_*.dart).
  final String messageKey;
}

/// The message key for [e].
String podPairMessage(PodPairError e) => switch (e) {
  PodPairError.wrongPasskey => 'pod.wrong_passkey',
  PodPairError.timeout => 'pod.pair_timeout',
  PodPairError.needsRepair => 'pod.repair_manual',
};

/// Links [device] with [attempt]; over Bluetooth, a failed try is explained
/// from [bonds], and a pod that needs pairing again gets it once: the bond
/// removed, [onRepair] called (to tell the person a new passkey comes),
/// then one more try.
Future<PodLinkOutcome<T>> linkPod<T>(
  PodDevice device,
  PodLinkTry<T> attempt, {
  PodBonds? bonds,
  void Function()? onRepair,
}) async {
  var repaired = false;
  for (;;) {
    final (link, failure) = await attempt();
    if (link != null) return PodLinked(link, repaired: repaired);
    if (device.kind != 'ble' || bonds == null) return PodLinkFailed(failure);
    final error = await bonds.lastPairError();
    if (error == null) return PodLinkFailed(failure);
    if (error != PodPairError.needsRepair || repaired) {
      return PodLinkFailed(podPairMessage(error));
    }
    if (!await bonds.forgetBond(device)) {
      return PodLinkFailed('pod.repair_manual');
    }
    repaired = true;
    onRepair?.call();
  }
}

/// One try for [linkPod]: opens [d] with [open], then waits for the pod's
/// IDENT on [transport] (3 s over USB, 30 s over Bluetooth: the person types
/// the passkey meanwhile). A link that ends first (a pairing that failed, a
/// pod that refused the bond) ends the wait at once.
Future<(PodClient?, String)> linkAndIdentify(
  PodTransport transport,
  PodDevice d,
  Future<bool> Function(PodDevice d) open,
) async {
  if (!await open(d)) return (null, 'pod.open_failed');
  final client = PodClient(transport, device: d);
  final done = Completer<bool>();
  final sub = client.events.listen((e) {
    if (done.isCompleted) return;
    if (e is PodIdentified) done.complete(true);
    if (e is PodLinkBroken) done.complete(false);
  });
  await client.start();
  bool identified;
  try {
    identified = await done.future.timeout(podIdentTimeout(client));
  } on TimeoutException {
    identified = false;
  }
  await sub.cancel();
  if (identified) return (client, '');
  await client.close();
  return (null, 'pod.no_ident');
}
