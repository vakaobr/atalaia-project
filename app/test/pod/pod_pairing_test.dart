// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Pairing with an I/O pod over Bluetooth (lib/pod/pod_pairing.dart,
// decisions PODPK-1 to PODPK-11), with the Bluetooth plugin faked: a wrong
// passkey, a pairing that ran out of time and a pod that needs pairing again
// each get their message; the last is paired again once by itself (the
// phone's bond removed, one more try), and asks the person to forget the pod
// when Android refuses or the pod refuses again; USB is never asked.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_pairing.dart';
import 'package:atalaia_app/pod/pod_transports.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_pod_link.dart';

const ble = PodDevice(
  kind: 'ble',
  id: 'AA:BB:CC:DD:1A:2B',
  name: 'atalaia-pod-1A2B',
);
const usb = PodDevice(
  kind: 'usb',
  id: '/dev/bus/usb/001/002',
  name: 'Atalaia pod',
);

/// The plugin's side of the bonds: what each try's pairing said, in order.
class FakeBonds implements PodBonds {
  FakeBonds(this.errors, {this.canForget = true});

  final List<PodPairError?> errors;
  final bool canForget;
  final log = <String>[];
  var _tries = 0;

  /// Called by the fake try: the next try's error becomes the last one.
  void tried() => _tries++;

  @override
  Future<PodPairError?> lastPairError() async {
    log.add('last_error');
    final i = _tries - 1;
    return i >= 0 && i < errors.length ? errors[i] : null;
  }

  @override
  Future<bool> forgetBond(PodDevice device) async {
    log.add('forget ${device.id}');
    return canForget;
  }
}

/// Tries that fail [failures] times with [why], then link.
PodLinkTry<String> tries(
  FakeBonds? bonds,
  int failures, {
  String why = 'pod.no_ident',
}) {
  var n = 0;
  return () async {
    bonds?.tried();
    n++;
    return n > failures ? ('linked on try $n', '') : (null, why);
  };
}

void main() {
  test('the plugin codes', () {
    expect(PodPairError.fromCode('pair_failed'), PodPairError.wrongPasskey);
    expect(PodPairError.fromCode('pair_timeout'), PodPairError.timeout);
    expect(PodPairError.fromCode('repair'), PodPairError.needsRepair);
    expect(PodPairError.fromCode(null), isNull);
    expect(PodPairError.fromCode('other'), isNull);
  });

  test('linked at the first try: nothing asked', () async {
    final bonds = FakeBonds(const []);
    final r = await linkPod(ble, tries(bonds, 0), bonds: bonds);
    expect(r, isA<PodLinked<String>>());
    expect((r as PodLinked<String>).link, 'linked on try 1');
    expect(r.repaired, isFalse);
    expect(bonds.log, isEmpty);
  });

  test(
    'a wrong passkey and a pairing too slow get their messages, no retry',
    () async {
      var bonds = FakeBonds(const [PodPairError.wrongPasskey]);
      var r = await linkPod(ble, tries(bonds, 1), bonds: bonds);
      expect((r as PodLinkFailed).messageKey, 'pod.wrong_passkey');
      expect(bonds.log, ['last_error']);

      bonds = FakeBonds(const [PodPairError.timeout]);
      r = await linkPod(ble, tries(bonds, 1), bonds: bonds);
      expect((r as PodLinkFailed).messageKey, 'pod.pair_timeout');
    },
  );

  test('no word from the pairing: the try\'s own message', () async {
    final bonds = FakeBonds(const [null]);
    final r = await linkPod(
      ble,
      tries(bonds, 1, why: 'pod.open_failed'),
      bonds: bonds,
    );
    expect((r as PodLinkFailed).messageKey, 'pod.open_failed');
  });

  test(
    'a pod that needs pairing again: the bond forgotten, paired again once',
    () async {
      final bonds = FakeBonds(const [PodPairError.needsRepair, null]);
      var told = 0;
      final r = await linkPod(
        ble,
        tries(bonds, 1),
        bonds: bonds,
        onRepair: () => told++,
      );
      expect(r, isA<PodLinked<String>>());
      expect((r as PodLinked<String>).link, 'linked on try 2');
      expect(r.repaired, isTrue);
      expect(told, 1);
      expect(bonds.log, ['last_error', 'forget AA:BB:CC:DD:1A:2B']);
    },
  );

  test('the new pairing fails too: its own message', () async {
    final bonds = FakeBonds(const [
      PodPairError.needsRepair,
      PodPairError.wrongPasskey,
    ]);
    final r = await linkPod(ble, tries(bonds, 5), bonds: bonds);
    expect((r as PodLinkFailed).messageKey, 'pod.wrong_passkey');
    expect(bonds.log, ['last_error', 'forget AA:BB:CC:DD:1A:2B', 'last_error']);
  });

  test(
    'once only: a second refusal asks the person to forget the pod',
    () async {
      final bonds = FakeBonds(const [
        PodPairError.needsRepair,
        PodPairError.needsRepair,
      ]);
      var told = 0;
      final r = await linkPod(
        ble,
        tries(bonds, 5),
        bonds: bonds,
        onRepair: () => told++,
      );
      expect((r as PodLinkFailed).messageKey, 'pod.repair_manual');
      expect(told, 1);
      expect(bonds.log.where((l) => l.startsWith('forget')), hasLength(1));
    },
  );

  test('Android refuses to remove the bond: forget it by hand', () async {
    final bonds = FakeBonds(const [PodPairError.needsRepair], canForget: false);
    var told = 0;
    final r = await linkPod(
      ble,
      tries(bonds, 5),
      bonds: bonds,
      onRepair: () => told++,
    );
    expect((r as PodLinkFailed).messageKey, 'pod.repair_manual');
    expect(told, 0);
  });

  test('USB, or no plugin: never asked', () async {
    final bonds = FakeBonds(const [PodPairError.needsRepair]);
    var r = await linkPod(
      usb,
      tries(bonds, 1, why: 'pod.open_failed'),
      bonds: bonds,
    );
    expect((r as PodLinkFailed).messageKey, 'pod.open_failed');
    expect(bonds.log, isEmpty);
    r = await linkPod(ble, tries(null, 1));
    expect((r as PodLinkFailed).messageKey, 'pod.no_ident');
  });

  test('linkAndIdentify: the IDENT, a link that ends early, a refused open', () async {
    // The pod answers: linked.
    var link = FakePodLink(kind: 'ble');
    var (client, why) = await linkAndIdentify(link, ble, (_) async => true);
    expect(client, isA<PodClient>());
    expect(client!.ident, isNotNull);
    await client.close();

    // The pod drops the link (a failed pairing, a refused bond): no 30 s wait.
    link = FakePodLink(kind: 'ble', ident: null);
    final started = DateTime.now();
    final pending = linkAndIdentify(link, ble, (_) async => true);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    await link.drop();
    (client, why) = await pending;
    expect(client, isNull);
    expect(why, 'pod.no_ident');
    expect(
      DateTime.now().difference(started),
      lessThan(const Duration(seconds: 5)),
    );

    // The plugin could not open the link.
    (client, why) = await linkAndIdentify(
      FakePodLink(kind: 'ble'),
      ble,
      (_) async => false,
    );
    expect(client, isNull);
    expect(why, 'pod.open_failed');
  });

  test('every message is in the four languages', () {
    const keys = [
      'pod.pair_hint',
      'pod.wrong_passkey',
      'pod.pair_timeout',
      'pod.repair',
      'pod.repair_manual',
    ];
    for (final e in PodPairError.values) {
      expect(keys, contains(podPairMessage(e)));
    }
    for (final lang in AppLanguage.values) {
      for (final k in keys) {
        expect(lang.table[k], isNotNull, reason: '$k in ${lang.code}');
        expect(lang.table[k], isNotEmpty);
      }
    }
    // The hint names the 6 digits in every language.
    for (final lang in AppLanguage.values) {
      expect(lang.table['pod.pair_hint'], contains('6'));
    }
  });
}
