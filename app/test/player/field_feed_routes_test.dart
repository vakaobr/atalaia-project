// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The feed over a pinned field's addresses (decisions check-R1, check-R4): it
// races them like the check-in client instead of using the first only, the
// winner is tried first on every reconnect, a dead address never holds it,
// and what failed is kept for the "does not answer" line. Also the trust's
// CA fetch (first scan) racing the poster's addresses.

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/field_route.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/protocol/checkin_poster.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_field.dart';
import 'field_feed_test.dart' show FakeSocket;

const _stagger = Duration(milliseconds: 30);

SocketException refused() =>
    const SocketException('x', osError: OSError('Connection refused', 111));

PinnedField pinned(List<String> urls, {String? lastUrl}) => PinnedField(
  fieldId: 'campo-norte',
  fieldName: 'Campo Norte',
  caPem: 'pem',
  caSha256: Uint8List(32),
  urls: urls,
  lastUrl: lastUrl,
);

void main() {
  const dead = 'https://192.168.1.158:8443';
  const dead2 = 'https://192.168.1.233:8443';
  const live = 'https://192.168.1.183:8443';

  group('the feed', () {
    Future<void> settle() =>
        Future<void>.delayed(const Duration(milliseconds: 5));

    test('uses a live address behind dead ones, not urls.first', () async {
      final asked = <String>[];
      final sockets = <FakeSocket>[];
      final routes = FieldRoutes(stagger: _stagger);
      final f = FieldFeed(
        FieldLink(Uri.parse(dead), 'tok', field: pinned([dead, dead2, live])),
        connect: (uri) async {
          asked.add(uri.host);
          if (uri.host != '192.168.1.183') throw refused();
          final s = FakeSocket();
          sockets.add(s);
          return s;
        },
        routes: routes,
      );
      addTearDown(f.dispose);
      unawaited(f.start());
      await settle();
      expect(f.state, FeedState.open);
      expect(asked.toSet(), {
        '192.168.1.158',
        '192.168.1.233',
        '192.168.1.183',
      });
      expect(routes.winner('campo-norte'), live);
      expect(routes.failures('campo-norte'), isEmpty);
    });

    test(
      'a reconnect tries the winner first; if it is gone, races again',
      () async {
        final asked = <String>[];
        final sockets = <FakeSocket>[];
        var liveUp = true;
        final routes = FieldRoutes(stagger: const Duration(seconds: 5));
        final f = FieldFeed(
          FieldLink(Uri.parse(dead), 'tok', field: pinned([dead, live])),
          connect: (uri) async {
            asked.add(uri.host);
            if (uri.host == '192.168.1.158' || !liveUp) throw refused();
            final s = FakeSocket();
            sockets.add(s);
            return s;
          },
          routes: routes,
        );
        addTearDown(f.dispose);
        unawaited(f.start());
        await settle();
        expect(f.state, FeedState.open);
        expect(asked, ['192.168.1.158', '192.168.1.183']);

        // The link drops: the reconnect goes to the winner, and only to it.
        asked.clear();
        await sockets.last.drop(1006);
        await Future<void>.delayed(const Duration(milliseconds: 1100));
        expect(asked, ['192.168.1.183']);
        expect(f.state, FeedState.open);

        // Everything is down: the kinds and addresses are kept, the feed retries.
        liveUp = false;
        asked.clear();
        await sockets.last.drop(1006);
        await Future<void>.delayed(const Duration(milliseconds: 2100));
        expect(f.state, FeedState.closed);
        expect(asked.toSet(), {'192.168.1.158', '192.168.1.183'});
        final fails = routes.failures(f.routeKey);
        expect(fails.map((x) => x.kind).toSet(), {FailKind.refused});
        expect(fails.map((x) => x.url).toSet(), {dead, live});
      },
    );

    test('a plain scoreboard link has its own key and one address', () async {
      final routes = FieldRoutes(stagger: _stagger);
      final f = FieldFeed(
        FieldLink.parse('10.0.0.1', 'code')!,
        connect: (uri) async => throw refused(),
        routes: routes,
      );
      addTearDown(f.dispose);
      unawaited(f.start());
      await settle();
      expect(f.state, FeedState.closed);
      expect(f.routeKey, 'link:http://10.0.0.1:8080');
      expect(routes.last(f.routeKey)!.url, 'http://10.0.0.1:8080');
    });
  });

  group('the first scan', () {
    CheckinPoster posterOf(FakeField f, List<String> urls) => CheckinPoster(
      fieldId: f.fieldId,
      fieldName: f.fieldName,
      urls: urls,
      caSha256: f.sha256Bytes,
    );

    test('races the poster addresses and pins the winner', () async {
      final field = FakeField();
      final store = MemoryAppStore();
      final routes = FieldRoutes(stagger: _stagger);
      final trust = FieldTrust(
        store,
        routes: routes,
        fetch: (u) async {
          if (u.host != '192.168.1.183') throw refused();
          return field.pem;
        },
      );
      routes.persist = trust.remember;
      final pinnedField = await trust.pin(posterOf(field, [dead, dead2, live]));
      expect(pinnedField.lastUrl, live);
      expect((await trust.known(field.fieldId))!.lastUrl, live);
      // The next scan of the same poster keeps it, and the next failure
      // after the winner changes is saved by the routes' persist hook.
      final again = await trust.pin(posterOf(field, [dead, live]));
      expect(again.lastUrl, live);
      final other = await trust.pin(posterOf(field, [dead, dead2]));
      expect(other.lastUrl, isNull); // no longer on the poster
      await trust.remember(field.fieldId, dead2);
      expect((await trust.known(field.fieldId))!.lastUrl, dead2);
    });

    test(
      'a device of another certificate on a stale address is skipped',
      () async {
        final field = FakeField();
        final stranger = FakeField(der: Uint8List.fromList([1, 2, 3, 4]));
        final trust = FieldTrust(
          MemoryAppStore(),
          routes: FieldRoutes(stagger: _stagger),
          fetch: (u) async =>
              u.host == '192.168.1.158' ? stranger.pem : field.pem,
        );
        final p = await trust.pin(posterOf(field, [dead, live]));
        expect(p.caSha256, field.sha256Bytes);
      },
    );

    test(
      'only the wrong certificate answers: a mismatch; nothing: unreachable',
      () async {
        final field = FakeField();
        final stranger = FakeField(der: Uint8List.fromList([1, 2, 3, 4]));
        final mismatch = FieldTrust(
          MemoryAppStore(),
          routes: FieldRoutes(stagger: _stagger),
          fetch: (u) async => stranger.pem,
        );
        await expectLater(
          mismatch.pin(posterOf(field, [dead, live])),
          throwsA(
            isA<TrustException>().having(
              (e) => e.reason,
              'reason',
              TrustFailure.mismatch,
            ),
          ),
        );

        final routes = FieldRoutes(stagger: _stagger);
        final down = FieldTrust(
          MemoryAppStore(),
          routes: routes,
          fetch: (u) async => throw refused(),
        );
        await expectLater(
          down.pin(posterOf(field, [dead, live])),
          throwsA(
            isA<TrustException>().having(
              (e) => e.reason,
              'reason',
              TrustFailure.unreachable,
            ),
          ),
        );
        expect(routes.failures(field.fieldId).map((x) => x.kind), [
          FailKind.refused,
          FailKind.refused,
        ]);
      },
    );
  });
}
