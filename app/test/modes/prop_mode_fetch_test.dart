// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// An Android prop fetches the signed mode packages a game needs from its
// controller (lib/modes/prop_mode_fetch.dart, decisions PKF-*): the box's
// checks in the box's order (the shared vectors protocol/vectors/
// mode_package.json run through the same functions in
// test/controller/mode_package_test.dart), refusing an unsigned or badly
// signed package before anything runs, the cache, and the setup screen.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/mode_package.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/modes/prop_mode_fetch.dart';
import 'package:atalaia_app/prop/prop_setup.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:cryptography/dart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';
import '../support/vectors.dart';

final vectors = loadVectors('mode_package.json');
final trusted = (vectors['signing_key'] as Map)['public_key_b64'] as String;
final seed = hexDecode((vectors['signing_key'] as Map)['seed'] as String);
final otherKey = (vectors['other_key'] as Map)['public_key_b64'] as String;

const modeId = 'org.test.relay';
const game = 77;
final gameKey = Uint8List.fromList(List.generate(16, (i) => i + 1));
final ca = Uint8List.fromList(List.generate(32, (i) => i));

String modeYaml({
  String id = modeId,
  String version = '1.0.0',
  String tier = 'reduced',
}) =>
    '''
id: $id
version: $version
license: MIT
min_tier: $tier
name: Relay
description: A test relay.
roles:
  zone: { requires: [team_input] }
''';

const nodeLua = 'ui.screen("main", {})\n';

/// A package for [id] signed by the RFC 8032 test key (a public test key,
/// never a mode key), the release text and the archive.
Future<(Uint8List, Uint8List)> package({
  String id = modeId,
  String version = '1.0.0',
  String kind = 'mode',
  String tier = 'reduced',
  Map<String, String>? files,
  Uint8List? tamper,
}) async {
  final archive = packArchive(
    id,
    files ??
        {
          'mode.yaml': modeYaml(id: id, version: version, tier: tier),
          'node.lua': nodeLua,
        },
  );
  final manifest = modeManifest(
    id,
    version,
    kind,
    tier,
    archive.length,
    sha256Hex(archive),
  );
  final sig = await DartEd25519().sign(
    manifest,
    keyPair: await DartEd25519().newKeyPairFromSeed(seed),
  );
  final release = ModeRelease(
    id,
    version,
    kind,
    tier,
    archive.length,
    sha256Hex(archive),
    base64.encode(sig.bytes),
  );
  return (release.text(), tamper ?? archive);
}

/// What the fake controller says: release and archive by id.
class FakeController implements ModeHttp {
  final releases = <String, Uint8List>{};
  final archives = <String, Uint8List>{};
  final requests = <String>[];
  final reports = <String>[];
  var closed = false;

  @override
  Future<ModeHttpReply> get(
    Uri url, {
    required int maxBytes,
    int? length,
  }) async {
    requests.add(url.path);
    final m = RegExp(
      r'^/api/v1/mode-packages/([^/]+)/(release|package)$',
    ).firstMatch(url.path)!;
    final body = (m.group(2) == 'release' ? releases : archives)[m.group(1)];
    if (body == null) return ModeHttpReply(404, Uint8List(0));
    if (length != null && body.length != length) {
      throw ModeFetchException('download', 'length');
    }
    return ModeHttpReply(200, body);
  }

  @override
  Future<int> post(Uri url, List<int> body, Map<String, String> headers) async {
    expect(url.path, '/api/v1/mode-packages/report');
    expect(headers['X-Atalaia-Mac'], reportMac(gameKey, body));
    reports.add(utf8.decode(body));
    return 200;
  }

  @override
  void close() => closed = true;
}

JoinPayload join({
  String mode = modeId,
  bool fetch = true,
  bool forget = false,
}) => JoinPayload(
  gameId: game,
  gameKey: gameKey,
  nodeId: 5,
  controllerId: 1,
  channelHz: 868100000,
  maxHops: 3,
  teams: const ['red', 'blue'],
  modeId: mode,
  role: 'zone',
  gameSeed: 9,
  params: null,
  kind: JoinKind.node,
  caSha256: ca,
  urls: const ['https://192.168.4.1:8443'],
  fetchModes: fetch,
  forgetModes: forget,
);

Matcher refusedWith(String code) =>
    throwsA(isA<ModeFetchException>().having((e) => e.code, 'code', code));

({PropModeFetcher fetcher, MemoryAppStore store, FakeNodeRunner runner}) setup(
  FakeController c,
) {
  final store = MemoryAppStore(AppSettings());
  final runner = FakeNodeRunner();
  return (
    fetcher: PropModeFetcher(
      cache: PropModeCache(store),
      runner: runner,
      open: (_, _) async => c,
    ),
    store: store,
    runner: runner,
  );
}

void main() {
  final builtin = ModeCatalog.builtin();

  test('the keys: built in and the settings, valid, once each', () {
    final s = AppSettings()..modeKeys = [trusted, 'nonsense', otherKey];
    // The default build carries the project's two registry keys
    // (docs/community/keys.md), first.
    expect(builtInModeKeys.split(' '), [
      'I+m3rO++TcVNhvDHzI28pkNA8UGoTJSi84IWQguq4Mo=',
      '0nMp0OGboGJZUMsbc/ykqkxQFNdmI/a2k4nQ6YsdTIY=',
    ]);
    expect(propModeKeys(s), [...builtInModeKeys.split(' '), trusted, otherKey]);
    expect(propModeKeys(s, builtIn: ''), [trusted, otherKey]);
    expect(propModeKeys(s, builtIn: '$otherKey $trusted'), [otherKey, trusted]);
    expect(propModeKeys(AppSettings(), builtIn: ''), isEmpty);
  });

  test(
    'fetches, checks, keeps and reports a signed package, then runs it',
    () async {
      final c = FakeController();
      final (text, archive) = await package();
      c.releases[modeId] = text;
      c.archives[modeId] = archive;
      final t = setup(c);
      final catalog = await t.fetcher.resolve(join(), builtin, [trusted]);
      final g = catalog.compose(modeId);
      expect(g.main.version, '1.0.0');
      expect(g.main.nodeScript, nodeLua);
      expect(g.main.role('zone'), isNotNull);
      expect(c.requests, [
        '/api/v1/mode-packages/$modeId/release',
        '/api/v1/mode-packages/$modeId/package',
      ]);
      expect(c.reports.single, contains('result=installed'));
      expect(c.reports.single, contains('kept=$modeId@1.0.0'));
      expect(c.closed, isTrue);
      // It loaded in the core's sandbox before it was kept.
      expect(t.runner.spec!.chunkName, '@$modeId/node.lua');
      // Built-in modes stay as they were.
      expect(catalog.byId('org.atalaia.domination'), isNotNull);

      // Kept: the next game needs no controller, but the keys are checked
      // again each time it is read.
      final c2 = FakeController();
      final f2 = PropModeFetcher(
        cache: PropModeCache(t.store),
        runner: t.runner,
        open: (_, _) async => c2,
      );
      final catalog2 = await f2.resolve(join(fetch: false), builtin, [trusted]);
      expect(catalog2.compose(modeId).main.id, modeId);
      expect(c2.requests, isEmpty);
      // A key taken away drops what it signed.
      await expectLater(
        f2.resolve(join(fetch: false), builtin, [otherKey]),
        refusedWith('not_offered'),
      );
      expect(await t.store.loadList('prop_modes'), isEmpty);
    },
  );

  test('key 17 forgets what was fetched', () async {
    final c = FakeController();
    final (text, archive) = await package();
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    final t = setup(c);
    await t.fetcher.resolve(join(), builtin, [trusted]);
    expect(await t.store.loadList('prop_modes'), hasLength(1));
    c.requests.clear();
    await t.fetcher.resolve(join(forget: true), builtin, [trusted]);
    expect(c.requests, hasLength(2), reason: 'fetched again');
  });

  test('without key 16 nothing is fetched', () async {
    final c = FakeController();
    final t = setup(c);
    await expectLater(
      t.fetcher.resolve(join(fetch: false), builtin, [trusted]),
      refusedWith('not_offered'),
    );
    expect(c.requests, isEmpty);
  });

  test('with no mode key nothing is fetched', () async {
    final c = FakeController();
    final t = setup(c);
    await expectLater(
      t.fetcher.resolve(join(), builtin, const []),
      refusedWith('no_key'),
    );
    expect(c.requests, isEmpty);
  });

  test(
    'a package signed by a key the prop does not trust is refused',
    () async {
      final c = FakeController();
      final (text, archive) = await package();
      c.releases[modeId] = text;
      c.archives[modeId] = archive;
      final t = setup(c);
      await expectLater(
        t.fetcher.resolve(join(), builtin, [otherKey]),
        refusedWith('bad_signature'),
      );
      // Refused before the download, reported, nothing kept, nothing run.
      expect(c.requests, ['/api/v1/mode-packages/$modeId/release']);
      expect(c.reports.single, contains('result=bad_signature'));
      expect(await t.store.loadList('prop_modes'), isEmpty);
      expect(t.runner.spec, isNull);
    },
  );

  test('an unsigned release is refused', () async {
    final c = FakeController();
    final (text, archive) = await package();
    final unsigned = utf8
        .decode(text)
        .split('\n')
        .where((l) => !l.startsWith('signature='))
        .join('\n');
    c.releases[modeId] = utf8.encode(unsigned);
    c.archives[modeId] = archive;
    final t = setup(c);
    await expectLater(
      t.fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('bad_release'),
    );
    expect(t.runner.spec, isNull);
  });

  test('a release for another mode is refused', () async {
    final c = FakeController();
    final (text, archive) = await package(id: 'org.test.other');
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    await expectLater(
      setup(c).fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('bad_release'),
    );
  });

  test('a scenario, a package for a bigger device, a built-in id', () async {
    for (final (kind, tier, code) in [
      ('scenario', 'reduced', 'kind'),
      ('mode', 'full', 'ok'), // a phone is a Full device
    ]) {
      final c = FakeController();
      final (text, archive) = await package(kind: kind, tier: tier);
      c.releases[modeId] = text;
      c.archives[modeId] = archive;
      final run = setup(c).fetcher.resolve(join(), builtin, [trusted]);
      if (code == 'ok') {
        expect((await run).byId(modeId), isNotNull);
      } else {
        await expectLater(run, refusedWith(code), reason: code);
      }
    }
    // The app owns the ids it carries: a package never replaces one.
    final (text, _) = await package(id: 'org.atalaia.domination');
    await expectLater(
      PropModeCache.check(
        releaseText: text,
        wantedId: 'org.atalaia.domination',
        archive: null,
        keys: [trusted],
        builtin: [for (final m in builtin.modes) m.id],
        now: 0,
      ),
      refusedWith('builtin'),
    );
  });

  test('an archive that is not the one signed is refused', () async {
    final c = FakeController();
    final (text, archive) = await package();
    final bad = Uint8List.fromList(archive)..[600] ^= 1;
    c.releases[modeId] = text;
    c.archives[modeId] = bad;
    final t = setup(c);
    await expectLater(
      t.fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('bad_hash'),
    );
    expect(await t.store.loadList('prop_modes'), isEmpty);
    expect(t.runner.spec, isNull);
  });

  test('a package whose mode.yaml says something else is refused', () async {
    final c = FakeController();
    final (text, archive) = await package(
      files: {
        'mode.yaml': modeYaml(version: '2.0.0'),
        'node.lua': nodeLua,
      },
    );
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    await expectLater(
      setup(c).fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('bad_archive'),
    );
  });

  test('a package without node.lua, or a download of another size', () async {
    final c = FakeController();
    final (text, archive) = await package(
      files: {'mode.yaml': modeYaml(), 'assets/screens/a.yaml': 'x: 1\n'},
    );
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    await expectLater(
      setup(c).fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('bad_archive'),
    );
    final (text2, archive2) = await package();
    c.releases[modeId] = text2;
    c.archives[modeId] = Uint8List.sublistView(archive2, 0, 512);
    await expectLater(
      setup(c).fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('download'),
    );
  });

  test('a script that does not load in the sandbox is not kept', () async {
    final c = FakeController();
    final (text, archive) = await package();
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    final t = setup(c);
    t.runner.node.loaded = false;
    await expectLater(
      t.fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('load'),
    );
  });

  test('the controller does not offer it', () async {
    final c = FakeController();
    final t = setup(c);
    await expectLater(
      t.fetcher.resolve(join(), builtin, [trusted]),
      refusedWith('not_offered'),
    );
  });

  test(
    'the cache drops the least recently used, never the game\'s own',
    () async {
      final store = MemoryAppStore(AppSettings());
      final cache = PropModeCache(store);
      var kept = <CachedMode>[];
      for (var i = 0; i < 9; i++) {
        final id = 'org.test.m$i';
        final (text, archive) = await package(id: id);
        final c = (await PropModeCache.check(
          releaseText: text,
          wantedId: id,
          archive: archive,
          keys: [trusted],
          builtin: const [],
          now: i,
        ))!;
        kept = await cache.put(kept, c, {'org.test.m0'});
        expect(kept.length, lessThanOrEqualTo(boxMaxFetched));
      }
      final ids = kept.map((c) => c.id).toSet();
      expect(ids, contains('org.test.m0'), reason: 'protected');
      expect(
        ids,
        isNot(contains('org.test.m1')),
        reason: 'least recently used',
      );
      expect(ids, contains('org.test.m8'));
    },
  );

  testWidgets('the setup screen fetches the mode of a join and shows it', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(400, 840);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final c = FakeController();
    final (text, archive) = await package();
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    final h = harness(
      settings: AppSettings()..modeKeys = [trusted],
      modeHttp: (_, _) async => c,
    );
    await tester.pumpWidget(h.app(home: PropSetupScreen(join: join())));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('setup-fetch-error')), findsNothing);
    expect(find.text('Relay'), findsWidgets);
    expect(c.reports, isNotEmpty);
  });

  testWidgets('the setup screen refuses a package signed by an unknown key', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(400, 840);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final c = FakeController();
    final (text, archive) = await package();
    c.releases[modeId] = text;
    c.archives[modeId] = archive;
    final runner = FakeNodeRunner();
    final h = harness(
      runner: runner,
      settings: AppSettings()..modeKeys = [otherKey],
      modeHttp: (_, _) async => c,
    );
    await tester.pumpWidget(h.app(home: PropSetupScreen(join: join())));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('setup-fetch-error')), findsOneWidget);
    expect(find.textContaining('não está assinado'), findsOneWidget);
    expect(runner.spec, isNull);
    // The game cannot be prepared.
    final go = tester.widget<FilledButton>(find.byKey(const Key('setup-go')));
    expect(go.onPressed, isNull);
  });
}
