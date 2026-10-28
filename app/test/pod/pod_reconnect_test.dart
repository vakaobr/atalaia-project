// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Reconnecting to an I/O pod by itself (lib/pod/pod_reconnect.dart, decision
// PF15): a lost link is opened again with a growing wait, the same pod only,
// with the first link's wait for its IDENT, the old link closed first, and
// nothing opened after the person unlinks.

import 'dart:async';

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_reconnect.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_pod_link.dart';

Duration fast(int attempt) => const Duration(milliseconds: 10);
Duration quick(PodClient c) => const Duration(milliseconds: 80);

/// A linked pod: its client, started and identified.
Future<(PodClient, FakePodLink)> linked({List<String>? log}) async {
  final link = FakePodLink(log: log);
  final client = PodClient(link);
  await client.start();
  await until(() => client.ident != null);
  return (client, link);
}

void main() {
  test('the waits grow, then stay at 30 s', () {
    expect(
      [for (var i = 1; i <= 8; i++) defaultPodBackoff(i).inSeconds],
      [1, 2, 4, 8, 16, 30, 30, 30],
    );
    expect(
      podIdentTimeout(PodClient(FakePodLink())),
      const Duration(seconds: 3),
    );
    expect(
      podIdentTimeout(PodClient(FakePodLink(kind: 'ble'))),
      const Duration(seconds: 30),
    );
  });

  test('a lost link is opened again: out of reach for a while, then back, the '
      'same pod', () async {
    final log = <String>[];
    final (client, link) = await linked(log: log);
    var tries = 0;
    PodClient? replaced;
    final phases = <PodLinkPhase>[];
    late final PodReconnector r;
    r = PodReconnector(
      client: client,
      backoff: fast,
      identTimeout: quick,
      reopen: (lost) async {
        tries++;
        log.add('open $tries');
        // The pod is out of reach for the first two tries.
        return tries < 3 ? null : PodClient(FakePodLink(log: log));
      },
      onReplaced: (old, next) => replaced = next,
    )..addListener(() => phases.add(r.phase));
    addTearDown(r.dispose);
    expect(r.phase, PodLinkPhase.linked);

    await link.drop();
    await until(() => replaced != null);
    expect(tries, 3);
    expect(r.phase, PodLinkPhase.linked);
    expect(r.client, same(replaced));
    expect(r.client.ident, isNotNull);
    expect(r.attempt, 0);
    expect(phases, contains(PodLinkPhase.reconnecting));
    // The lost link was closed before anything was opened.
    expect(log.first, 'close');
    expect(log.indexOf('open 1'), greaterThan(log.indexOf('close')));
    await r.client.close();
  });

  test('a link that breaks again is opened again', () async {
    final (client, link) = await linked();
    final seen = <PodClient>[];
    late FakePodLink second;
    final r = PodReconnector(
      client: client,
      backoff: fast,
      identTimeout: quick,
      reopen: (lost) async => PodClient(second = FakePodLink()),
      onReplaced: (old, next) => seen.add(next),
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => seen.length == 1);
    await second.drop();
    await until(() => seen.length == 2);
    expect(r.phase, PodLinkPhase.linked);
    expect(seen.first.broken, isTrue);
    await r.client.close();
  });

  test(
    'a link that does not say who it is is closed and tried again',
    () async {
      final (client, link) = await linked();
      final silent = FakePodLink(ident: null);
      var tries = 0;
      PodClient? replaced;
      final r = PodReconnector(
        client: client,
        backoff: fast,
        identTimeout: quick,
        reopen: (lost) async {
          tries++;
          return PodClient(tries == 1 ? silent : FakePodLink());
        },
        onReplaced: (old, next) => replaced = next,
      );
      addTearDown(r.dispose);
      await link.drop();
      await until(() => replaced != null);
      expect(tries, 2);
      expect(silent.closed, isTrue);
      await r.client.close();
    },
  );

  test('another pod answering is refused, and not tried again', () async {
    final (client, link) = await linked();
    final other = FakePodLink(ident: otherPodIdent);
    var tries = 0;
    var replaced = false;
    final r = PodReconnector(
      client: client,
      backoff: fast,
      identTimeout: quick,
      reopen: (lost) async {
        tries++;
        return PodClient(other);
      },
      onReplaced: (old, next) => replaced = true,
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => r.phase == PodLinkPhase.refused);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect((tries, replaced, other.closed), (1, false, true));
    expect(r.stopped, isTrue);
  });

  test('the person unlinking stops it, also a try that is waiting', () async {
    final (client, link) = await linked();
    var tries = 0;
    final r = PodReconnector(
      client: client,
      backoff: (_) => const Duration(milliseconds: 300),
      identTimeout: quick,
      reopen: (lost) async {
        tries++;
        return null;
      },
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => r.retryAt != null);
    expect(r.phase, PodLinkPhase.reconnecting);
    await r.unlink();
    expect(r.phase, PodLinkPhase.unlinked);
    await Future<void>.delayed(const Duration(milliseconds: 500));
    expect(tries, 0);
    expect(r.phase, PodLinkPhase.unlinked);
    expect(r.retryAt, isNull);
  });

  test('unlinking a working link closes it and nothing reopens it', () async {
    final (client, _) = await linked();
    var tries = 0;
    final r = PodReconnector(
      client: client,
      backoff: fast,
      reopen: (lost) async {
        tries++;
        return PodClient(FakePodLink());
      },
    );
    addTearDown(r.dispose);
    await r.unlink();
    expect(client.broken, isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect((tries, r.phase), (0, PodLinkPhase.unlinked));
  });

  test('a link opened while the person unlinks is closed, not used', () async {
    final (client, link) = await linked();
    final gate = Completer<PodClient?>();
    var replaced = false;
    final r = PodReconnector(
      client: client,
      backoff: fast,
      identTimeout: quick,
      reopen: (lost) => gate.future,
      onReplaced: (old, next) => replaced = true,
    );
    addTearDown(r.dispose);
    await link.drop();
    await until(() => r.attempt == 1 && r.retryAt == null);
    final late = FakePodLink();
    await r.unlink();
    gate.complete(PodClient(late));
    await until(() => late.closed);
    expect(replaced, isFalse);
  });

  test('suspended: no tries; resumed: it goes on', () async {
    final (client, link) = await linked();
    var tries = 0;
    PodClient? replaced;
    final r = PodReconnector(
      client: client,
      backoff: fast,
      identTimeout: quick,
      reopen: (lost) async {
        tries++;
        return PodClient(FakePodLink());
      },
      onReplaced: (old, next) => replaced = next,
    );
    addTearDown(r.dispose);
    r.suspend();
    await link.drop();
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect((tries, replaced), (0, null));
    r.resume();
    await until(() => replaced != null);
    expect(tries, 1);
    await r.client.close();
  });
}
