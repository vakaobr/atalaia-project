// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Which of a field's addresses to use (decisions check-R1 to check-R6): the
// happy-eyeballs race with fake attempts (a dead address first, all dead and
// the kinds of failure, the loser cancelled, the winner remembered), and the
// same over real sockets: a TLS server pinned with the field's CA next to a
// closed port and a server with another CA.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_route.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/controller/field_tls.dart';
import 'package:flutter_test/flutter_test.dart';

const _stagger = Duration(milliseconds: 30);

SocketException refused() =>
    const SocketException('x', osError: OSError('Connection refused', 111));
SocketException noRoute() =>
    const SocketException('x', osError: OSError('No route to host', 113));

void main() {
  group('the race', () {
    test('a dead first address: the second wins after the stagger', () async {
      final started = <String>[];
      final cancels = <String, RaceCancel>{};
      final sw = Stopwatch()..start();
      final (url, v) = await raceUrls<String>(
        ['https://dead', 'https://live'],
        (u, c) async {
          started.add(u);
          cancels[u] = c;
          if (u == 'https://dead') return Completer<String>().future; // hangs
          return 'ok $u';
        },
        stagger: _stagger,
        attemptTimeout: const Duration(seconds: 5),
      );
      expect((url, v), ('https://live', 'ok https://live'));
      expect(started, ['https://dead', 'https://live']);
      expect(sw.elapsed, greaterThanOrEqualTo(_stagger));
      expect(sw.elapsed, lessThan(const Duration(seconds: 2)));
      expect(cancels['https://dead']!.cancelled, isTrue);
      expect(cancels['https://live']!.cancelled, isFalse);
    });

    test('a first address that fails starts the next at once', () async {
      final sw = Stopwatch()..start();
      final (url, _) = await raceUrls<int>(['a', 'b', 'c'], (u, c) async {
        if (u == 'a') throw refused();
        return 1;
      }, stagger: const Duration(seconds: 10));
      expect(url, 'b'); // nobody waited for the stagger
      expect(sw.elapsed, lessThan(const Duration(seconds: 2)));
    });

    test('a healthy first address wins and the others never start', () async {
      final started = <String>[];
      final (url, _) = await raceUrls<int>(['a', 'b'], (u, c) async {
        started.add(u);
        return 1;
      }, stagger: _stagger);
      expect(url, 'a');
      await Future<void>.delayed(_stagger * 3);
      expect(started, ['a']);
    });

    test('a slow winner that arrives late is disposed', () async {
      final disposed = <String>[];
      final slow = Completer<String>();
      final (url, _) = await raceUrls<String>(
        ['slow', 'fast'],
        (u, c) => u == 'slow' ? slow.future : Future.value(u),
        stagger: _stagger,
        dispose: disposed.add,
      );
      expect(url, 'fast');
      slow.complete('slow');
      await Future<void>.delayed(Duration.zero);
      expect(disposed, ['slow']);
    });

    test('all dead: the kind of each failure', () async {
      final at = DateTime(2026, 10, 26, 14, 2, 11);
      final errors = <String, Object>{
        'a': refused(),
        'b': noRoute(),
        'c': const HandshakeException('CERTIFICATE_VERIFY_FAILED'),
        'd': RouteError(FailKind.http, 'HTTP 502', status: 502),
        'e': StateError('odd'),
      };
      try {
        await raceUrls<void>(
          errors.keys.toList(),
          (u, c) async => throw errors[u]!,
          stagger: _stagger,
          now: () => at,
        );
        fail('should have failed');
      } on RaceFailed catch (e) {
        expect(
          {for (final f in e.failures) f.url: f.kind},
          {
            'a': FailKind.refused,
            'b': FailKind.unreachable,
            'c': FailKind.tls,
            'd': FailKind.http,
            'e': FailKind.other,
          },
        );
        expect(e.failures.every((f) => f.at == at), isTrue);
        expect(e.failures[3].status, 502);
      }
    });

    test('no answer in time is a timeout, and cancels the attempt', () async {
      late RaceCancel seen;
      try {
        await raceUrls<void>(['a'], (u, c) {
          seen = c;
          return Completer<void>().future;
        }, attemptTimeout: const Duration(milliseconds: 50));
        fail('should have failed');
      } on RaceFailed catch (e) {
        expect(e.failures.single.kind, FailKind.timeout);
        expect(seen.cancelled, isTrue);
      }
    });

    test('the kinds from the system error codes of the platforms', () {
      FailKind k(int code, [String m = '']) =>
          classifyError(SocketException('x', osError: OSError(m, code)));
      expect(k(61), FailKind.refused); // iOS, macOS
      expect(k(10061), FailKind.refused);
      expect(k(65), FailKind.unreachable);
      expect(k(101), FailKind.unreachable);
      expect(k(110), FailKind.timeout);
      expect(k(0, 'Network is unreachable'), FailKind.unreachable);
      expect(classifyError(TimeoutException('t')), FailKind.timeout);
    });
  });

  group('the winner is remembered', () {
    test('first next time; the failures clear; the pin keeps it', () async {
      final kept = <String>[];
      final routes = FieldRoutes(
        stagger: _stagger,
        persist: (k, u) async => kept.add('$k $u'),
      );
      final urls = ['https://a', 'https://b', 'https://c'];
      expect(routes.order('f', urls), urls);

      final tried = <String>[];
      Future<void> attempt(String u, RaceCancel c) async {
        tried.add(u);
        if (u != 'https://c') throw refused();
      }

      final (w, _) = await routes.choose<void>('f', urls, attempt);
      expect(w, 'https://c');
      expect(routes.winner('f'), 'https://c');
      expect(kept, ['f https://c']);
      expect(routes.failures('f'), isEmpty);
      expect(routes.order('f', urls), ['https://c', 'https://a', 'https://b']);

      // Next time it goes first and nothing else is tried.
      tried.clear();
      await routes.choose<void>('f', urls, attempt);
      expect(tried, ['https://c']);
      expect(kept, hasLength(1)); // the same winner is not saved again

      // It dies: the race falls back to the others, the dead one last.
      final fallback = <String>[];
      final (w2, _) = await routes.choose<void>('f', urls, (u, c) async {
        fallback.add(u);
        if (u != 'https://b') throw noRoute();
      }, avoid: 'https://c');
      expect(w2, 'https://b');
      expect(fallback, ['https://a', 'https://b']);
      expect(kept.last, 'f https://b');
    });

    test('a failed race keeps the failures, with the time', () async {
      final routes = FieldRoutes(
        stagger: _stagger,
        now: () => DateTime(2026, 10, 26, 9, 30),
      );
      await expectLater(
        routes.choose<void>('f', ['a', 'b'], (u, c) async => throw refused()),
        throwsA(isA<RaceFailed>()),
      );
      final f = routes.failures('f');
      expect(f.map((x) => (x.kind, x.url)), [
        (FailKind.refused, 'a'),
        (FailKind.refused, 'b'),
      ]);
      expect(routes.last('f')!.at, DateTime(2026, 10, 26, 9, 30));
      expect(routes.failures('other'), isEmpty);
    });

    test("the pinned field's kept address is the seed", () {
      final routes = FieldRoutes();
      expect(routes.order('f', ['a', 'b'], seed: 'b'), ['b', 'a']);
      expect(routes.order('f', ['a', 'b'], seed: 'gone'), ['a', 'b']);
    });
  });

  group('over real sockets, with the field CA pinned', () {
    late Directory tmp;
    late FieldTls tls;
    late FieldTls stranger;
    final servers = <HttpServer>[];

    setUpAll(() {
      tmp = Directory.systemTemp.createTempSync('atalaia_route');
      tls = FieldTls.ensure('${tmp.path}/a', ['127.0.0.1']);
      stranger = FieldTls.ensure('${tmp.path}/b', ['127.0.0.1']);
    });

    tearDownAll(() => tmp.deleteSync(recursive: true));

    tearDown(() async {
      for (final s in servers) {
        await s.close(force: true);
      }
      servers.clear();
    });

    Future<String> serve(FieldTls t, {int status = 200}) async {
      final s = await HttpServer.bindSecure('127.0.0.1', 0, t.context());
      servers.add(s);
      s.listen((req) async {
        req.response.statusCode = status;
        req.response.headers.contentType = ContentType.json;
        req.response.write(jsonEncode({'ok': true, 'port': s.port}));
        await req.response.close();
      });
      return 'https://127.0.0.1:${s.port}';
    }

    Future<String> closedPort() async {
      final s = await ServerSocket.bind('127.0.0.1', 0);
      final p = s.port;
      await s.close();
      return 'https://127.0.0.1:$p';
    }

    PinnedField fieldOf(List<String> urls, {String? lastUrl}) => PinnedField(
      fieldId: 'campo',
      fieldName: 'Campo',
      caPem: tls.caPem,
      caSha256: tls.caSha256,
      urls: urls,
      lastUrl: lastUrl,
    );

    test(
      'a closed port first, the controller second: fast, and kept',
      () async {
        final dead = await closedPort();
        final live = await serve(tls);
        final routes = FieldRoutes(stagger: _stagger);
        final kept = <String>[];
        routes.persist = (k, u) async => kept.add(u);
        final http = IoFieldHttp(fieldOf([dead, live]), routes: routes);
        final sw = Stopwatch()..start();
        final r = await http.send('GET', '/checkin');
        expect(r.ok, isTrue);
        expect(r.json['ok'], isTrue);
        expect(sw.elapsed, lessThan(const Duration(seconds: 3)));
        expect(routes.winner('campo'), live);
        expect(kept, [live]);

        // The next request goes straight to it.
        final again = await http.send('GET', '/checkin');
        expect(again.ok, isTrue);
        http.close();
      },
    );

    test(
      'the winner dies: the race finds another, the dead one last',
      () async {
        final a = await serve(tls);
        final b = await serve(tls);
        final routes = FieldRoutes(stagger: _stagger);
        final http = IoFieldHttp(fieldOf([a, b]), routes: routes);
        await http.send('GET', '/checkin');
        expect(routes.winner('campo'), a);
        await servers.first.close(force: true);
        final r = await http.send('GET', '/checkin');
        expect(r.ok, isTrue);
        expect(routes.winner('campo'), b);
        http.close();
      },
    );

    test('a server with another CA is refused, never trusted', () async {
      final fake = await serve(stranger);
      final live = await serve(tls);
      final routes = FieldRoutes(stagger: _stagger);
      final http = IoFieldHttp(fieldOf([fake, live]), routes: routes);
      final r = await http.send('GET', '/checkin');
      expect(r.json['port'], Uri.parse(live).port);
      expect(routes.winner('campo'), live);
      http.close();

      // Alone, it is a TLS failure and the field is out of reach.
      final routes2 = FieldRoutes(stagger: _stagger);
      final only = IoFieldHttp(fieldOf([fake]), routes: routes2);
      await expectLater(
        only.send('GET', '/checkin'),
        throwsA(
          isA<CheckinException>().having((e) => e.offline, 'offline', true),
        ),
      );
      expect(routes2.last('campo')!.kind, FailKind.tls);
      only.close();
    });

    test('all dead: the controller is out of reach, with the kinds', () async {
      final d1 = await closedPort();
      final d2 = await closedPort();
      final routes = FieldRoutes(stagger: _stagger);
      final http = IoFieldHttp(fieldOf([d1, d2]), routes: routes);
      await expectLater(
        http.send('GET', '/checkin'),
        throwsA(
          isA<CheckinException>().having((e) => e.offline, 'offline', true),
        ),
      );
      final f = routes.failures('campo');
      expect(f.map((x) => x.url).toSet(), {d1, d2});
      expect(f.every((x) => x.kind == FailKind.refused), isTrue);
      http.close();
    });

    test('an HTTP error status is kept as a failure of kind http', () async {
      final live = await serve(tls, status: 503);
      final routes = FieldRoutes(stagger: _stagger);
      final http = IoFieldHttp(fieldOf([live]), routes: routes);
      final r = await http.send('GET', '/checkin');
      expect(r.status, 503);
      expect(routes.last('campo')!.kind, FailKind.http);
      expect(routes.last('campo')!.status, 503);
      http.close();
    });

    test('the pinned address kept in the record is tried first', () async {
      final live = await serve(tls);
      final dead = await closedPort();
      final tried = <String>[];
      final http = IoFieldHttp(
        fieldOf([dead, live], lastUrl: live),
        routes: FieldRoutes(stagger: const Duration(seconds: 5)),
        probe: (f, u, c) async {
          tried.add('$u');
          await ioProbe(f, u, c);
        },
      );
      final r = await http.send('GET', '/checkin');
      expect(r.ok, isTrue);
      expect(tried, isEmpty); // straight to it: no probe, the dead one unused
      http.close();
    });
  });
}
