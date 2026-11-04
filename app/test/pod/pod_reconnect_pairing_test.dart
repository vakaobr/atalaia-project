// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Reconnecting to a Bluetooth I/O pod whose pairing goes wrong
// (lib/pod/pod_reconnect.dart, decisions PODPK-4, PODPK-8 and ROB-1 to
// ROB-4), with the Bluetooth plugin faked: a pod that refuses the phone's
// bond (HCI 0x05, "repair") is paired again once by itself, at once; a wrong
// passkey, a pairing that ran out of time, a second "repair" or an Android
// that refuses to remove the bond stop the tries with a message, so no
// pairing dialog is asked for again; a pod out of reach is tried as before,
// and USB never asks the plugin.

import 'dart:async';

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_pairing.dart';
import 'package:atalaia_app/pod/pod_reconnect.dart';
import 'package:atalaia_app/pod/pod_transports.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_pod_link.dart';

const pod = PodDevice(
  kind: 'ble',
  id: 'AA:BB:CC:DD:1A:2B',
  name: 'atalaia-pod-1A2B',
);

Duration quick(PodClient c) => const Duration(milliseconds: 80);

/// A linked Bluetooth pod: its client, started and identified.
Future<(PodClient, FakePodLink)> linked({String kind = 'ble'}) async {
  final link = FakePodLink(kind: kind);
  final client = PodClient(
    link,
    device: kind == 'ble'
        ? pod
        : const PodDevice(kind: 'usb', id: '/dev/x', name: 'pod'),
  );
  await client.start();
  await until(() => client.ident != null);
  return (client, link);
}

/// A reconnector over [client] whose tries fail [failures] times (no link
/// opened), then open a pod that identifies; the waits it asked for are in
/// [waits].
({PodReconnector r, List<int> waits, List<int> tries}) reconnector(
  PodClient client, {
  required int failures,
  PodBonds? bonds,
  void Function()? onRepair,
}) {
  final waits = <int>[];
  final tries = <int>[];
  final r = PodReconnector(
    client: client,
    backoff: (attempt) {
      waits.add(attempt);
      return const Duration(milliseconds: 10);
    },
    identTimeout: quick,
    bonds: bonds,
    onRepair: onRepair,
    reopen: (lost) async {
      tries.add(tries.length + 1);
      if (tries.length <= failures) return null;
      return PodClient(FakePodLink(kind: lost.transport.kind), device: pod);
    },
  );
  addTearDown(r.dispose);
  return (r: r, waits: waits, tries: tries);
}

void main() {
  test('a pod that refuses the bond is paired again once, at once', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([PodPairError.needsRepair]);
    var repairs = 0;
    final seen = <(PodLinkPhase, bool)>[];
    final t = reconnector(
      client,
      failures: 1,
      bonds: bonds,
      onRepair: () => repairs++,
    );
    t.r.addListener(() => seen.add((t.r.phase, t.r.repairing)));
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.linked && t.tries.length == 2);
    expect(bonds.log, ['last_error needsRepair', 'forget ${pod.id}']);
    expect(repairs, 1);
    // The second try did not wait: only the first asked for a wait.
    expect(t.waits, [1]);
    expect(seen, contains((PodLinkPhase.reconnecting, true)));
    expect((t.r.repairing, t.r.relinkMessage), (false, null));
    await t.r.client.close();
  });

  test('a pod that drops the opened link with 0x05 before its IDENT is '
      'paired again too', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([PodPairError.needsRepair]);
    var tries = 0;
    final r = PodReconnector(
      client: client,
      backoff: (_) => const Duration(milliseconds: 10),
      identTimeout: quick,
      bonds: bonds,
      reopen: (lost) async {
        tries++;
        if (tries == 1) {
          // Opened, then the pod drops it: it does not trust this bond.
          final refusing = FakePodLink(kind: 'ble', ident: null);
          unawaited(
            Future<void>.delayed(
              const Duration(milliseconds: 5),
              refusing.drop,
            ),
          );
          return PodClient(refusing, device: pod);
        }
        return PodClient(FakePodLink(kind: 'ble'), device: pod);
      },
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => r.phase == PodLinkPhase.linked && tries == 2);
    expect(bonds.log, ['last_error needsRepair', 'forget ${pod.id}']);
    await r.client.close();
  });

  for (final (error, key) in [
    (PodPairError.wrongPasskey, 'pod.wrong_passkey'),
    (PodPairError.timeout, 'pod.pair_timeout'),
  ]) {
    test(
      '${error.name}: the tries stop with $key, nothing forgotten',
      () async {
        final (client, link) = await linked();
        final bonds = ScriptedBonds([error]);
        final t = reconnector(client, failures: 99, bonds: bonds);
        await link.drop();
        await until(() => t.r.phase == PodLinkPhase.relink);
        await Future<void>.delayed(const Duration(milliseconds: 100));
        expect(t.tries, [1]);
        expect(bonds.log, ['last_error ${error.name}']);
        expect(t.r.relinkMessage, key);
        expect((t.r.stopped, t.r.retryAt, t.r.repairing), (true, null, false));
      },
    );
  }

  test('a second refusal after pairing again stops: forget the pod in the '
      'settings', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([
      PodPairError.needsRepair,
      PodPairError.needsRepair,
    ]);
    final t = reconnector(client, failures: 99, bonds: bonds);
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.relink);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(t.tries, [1, 2]);
    expect(bonds.log, [
      'last_error needsRepair',
      'forget ${pod.id}',
      'last_error needsRepair',
    ]);
    expect(t.r.relinkMessage, 'pod.repair_manual');
  });

  test('pairing again, then a wrong passkey: stops after one dialog', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([
      PodPairError.needsRepair,
      PodPairError.wrongPasskey,
    ]);
    final t = reconnector(client, failures: 99, bonds: bonds);
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.relink);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(t.tries, [1, 2]);
    expect(t.r.relinkMessage, 'pod.wrong_passkey');
  });

  test('Android refusing to remove the bond stops', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([PodPairError.needsRepair], canForget: false);
    var repairs = 0;
    final t = reconnector(
      client,
      failures: 99,
      bonds: bonds,
      onRepair: () => repairs++,
    );
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.relink);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect((t.tries.length, repairs), (1, 0));
    expect(t.r.relinkMessage, 'pod.repair_manual');
  });

  test('out of reach (no word on the pairing): tried with the waits, as '
      'before', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds(const []);
    final t = reconnector(client, failures: 2, bonds: bonds);
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.linked && t.tries.length == 3);
    expect(t.waits, [1, 2, 3]);
    expect(bonds.log, ['last_error null', 'last_error null']);
    await t.r.client.close();
  });

  test('a refusal after a while out of reach is still paired again once; '
      'a link broken later starts afresh', () async {
    final (client, link) = await linked();
    final bonds = ScriptedBonds([
      null,
      PodPairError.needsRepair,
      // The next time the link breaks: a refusal is paired again again.
      PodPairError.needsRepair,
    ]);
    var tries = 0;
    late FakePodLink second;
    final r = PodReconnector(
      client: client,
      backoff: (_) => const Duration(milliseconds: 10),
      identTimeout: quick,
      bonds: bonds,
      reopen: (lost) async {
        tries++;
        if (tries == 3) {
          return PodClient(second = FakePodLink(kind: 'ble'), device: pod);
        }
        if (tries == 5) {
          return PodClient(FakePodLink(kind: 'ble'), device: pod);
        }
        return null;
      },
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => r.phase == PodLinkPhase.linked && tries == 3);
    await second.drop();
    await until(() => r.phase == PodLinkPhase.linked && tries == 5);
    expect(
      bonds.log.where((l) => l.startsWith('forget')).length,
      2,
      reason: 'once for each time the link broke',
    );
    await r.client.close();
  });

  test('the plugin is the transport when none is given', () async {
    final bonds = ScriptedBonds([PodPairError.timeout]);
    final first = FakeBleLink(bonds);
    final client = PodClient(first, device: pod);
    await client.start();
    await until(() => client.ident != null);
    final r = PodReconnector(
      client: client,
      backoff: (_) => const Duration(milliseconds: 10),
      identTimeout: quick,
      reopen: (lost) async => null,
    );
    addTearDown(r.dispose);
    expect(r.bonds, same(first));
    await first.drop();
    await until(() => r.phase == PodLinkPhase.relink);
    expect(r.relinkMessage, 'pod.pair_timeout');
  });

  test('over USB the plugin is never asked', () async {
    final (client, link) = await linked(kind: 'usb');
    final bonds = ScriptedBonds([PodPairError.needsRepair]);
    final t = reconnector(client, failures: 2, bonds: bonds);
    await link.drop();
    await until(() => t.r.phase == PodLinkPhase.linked && t.tries.length == 3);
    expect(bonds.log, isEmpty);
    await t.r.client.close();
  });

  test(
    'the person unlinking while it pairs again: nothing more is tried',
    () async {
      final (client, link) = await linked();
      final bonds = ScriptedBonds([PodPairError.needsRepair]);
      final gate = Completer<PodClient?>();
      var tries = 0;
      final r = PodReconnector(
        client: client,
        backoff: (_) => const Duration(milliseconds: 10),
        identTimeout: quick,
        bonds: bonds,
        reopen: (lost) async {
          tries++;
          return tries == 1 ? null : gate.future;
        },
      );
      addTearDown(r.dispose);
      await link.drop();
      await until(() => tries == 2);
      expect(r.repairing, isTrue);
      await r.unlink();
      final late = FakePodLink(kind: 'ble');
      gate.complete(PodClient(late, device: pod));
      await until(() => late.closed);
      expect(r.phase, PodLinkPhase.unlinked);
      expect(tries, 2);
    },
  );

  test('the messages exist in every language', () {
    for (final lang in AppLanguage.values) {
      for (final key in [
        'pod.relink',
        'pod.repair',
        'pod.wrong_passkey',
        'pod.pair_timeout',
        'pod.repair_manual',
      ]) {
        expect(lang.table[key], isNotEmpty, reason: '$key in ${lang.code}');
      }
      expect(lang.table['pod.relink'], contains('{why}'));
    }
  });
}
