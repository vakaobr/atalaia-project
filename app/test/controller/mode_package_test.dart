// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Signed mode packages on the Android controller (lib/controller/
/// mode_package.dart) against protocol/vectors/mode_package.json, every
/// group, as controller/tests/test_mode_package.py checks them in Python.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/mode_package.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

final vectors = loadVectors('mode_package.json');
final key = (vectors['signing_key'] as Map)['public_key_b64'] as String;
final otherKey = (vectors['other_key'] as Map)['public_key_b64'] as String;
final signingKeyId = (vectors['signing_key'] as Map)['key_id'] as String;
final archiveVectors = vectors['archive'] as Map<String, dynamic>;
final archiveFiles = (archiveVectors['files'] as Map).cast<String, String>();

Matcher throwsCode(String code) =>
    throwsA(isA<ModePackageError>().having((e) => e.code, 'code', code));

ModeRelease releaseOf(Map<String, dynamic> c) => ModeRelease(
  c['id'] as String,
  c['version'] as String,
  c['kind'] as String,
  c['min_tier'] as String,
  c['size'] as int,
  c['sha256'] as String,
  c['signature'] as String,
);

List<String> strings(Object? list) => (list as List).cast<String>();

void main() {
  test(
    'rfc8032: the RFC test signatures verify, and only for their message',
    () async {
      final rfc = cases(vectors, 'rfc8032');
      expect(rfc, hasLength(2));
      for (final c in rfc) {
        final pub = hexDecode(c['public_key'] as String);
        final sig = hexDecode(c['signature'] as String);
        expect(
          await verifyEd25519(pub, hexDecode(c['message'] as String), sig),
          isTrue,
          reason: c['name'] as String,
        );
        expect(await verifyEd25519(pub, utf8.encode('x'), sig), isFalse);
      }
    },
  );

  test('key ids', () {
    for (final name in ['signing_key', 'other_key']) {
      final k = vectors[name] as Map;
      expect(keyId(k['public_key_b64'] as String), k['key_id']);
      expect(hexEncode(publicKeyBytes(k['public_key_b64'])!), k['public_key']);
    }
  });

  test('archive: the canonical archive packs and unpacks', () {
    final archive = hexDecode(archiveVectors['hex'] as String);
    final modeId = archiveVectors['mode_id'] as String;
    expect(packArchive(modeId, archiveFiles), archive);
    final (root, files) = unpackArchive(archive);
    expect(root, modeId);
    expect(files, archiveFiles);
    expect(unpackArchive(archive, modeId: modeId).$2, archiveFiles);
    expect(archive.length, archiveVectors['size']);
    expect(sha256Hex(archive), archiveVectors['sha256']);
    expect(
      () => unpackArchive(archive, modeId: 'org.example.other'),
      throwsCode('mismatch'),
    );
    // The same files in another order give the same bytes.
    final reversed = Map.fromEntries(archiveFiles.entries.toList().reversed);
    expect(packArchive(modeId, reversed), archive);
  });

  test('archives_invalid: every reader refuses them', () {
    final invalid = cases(vectors, 'archives_invalid');
    expect(invalid.length, greaterThanOrEqualTo(25));
    for (final c in invalid) {
      expect(
        () => unpackArchive(hexDecode(c['hex'] as String)),
        throwsCode(c['code'] as String),
        reason: c['name'] as String,
      );
    }
  });

  test('releases: manifests, release texts and their signer', () async {
    for (final c in cases(vectors, 'releases')) {
      final name = c['name'] as String;
      final release = releaseOf(c);
      expect(utf8.decode(release.manifest()), c['manifest'], reason: name);
      expect(utf8.decode(release.text()), c['release_text'], reason: name);
      expect(
        parseReleaseText(utf8.encode(c['release_text'] as String)),
        release,
        reason: name,
      );
      expect(releaseFrom(c), release, reason: name);
      final signed = await releaseSigner([key], release) != null;
      expect(
        signed,
        name == 'release' || name == 'lies_about_version',
        reason: name,
      );
      expect(await releaseSigner([otherKey], release), isNull, reason: name);
    }
  });

  test('release_texts_invalid: refused as bad_release', () {
    for (final c in cases(vectors, 'release_texts_invalid')) {
      expect(
        () => parseReleaseText(utf8.encode(c['text'] as String)),
        throwsCode('bad_release'),
        reason: c['name'] as String,
      );
    }
  });

  test('verify: whole checks give their result', () async {
    final releases = {
      for (final c in cases(vectors, 'releases'))
        c['name'] as String: releaseOf(c),
    };
    final archives = {
      'archive': hexDecode(archiveVectors['hex'] as String),
      'tampered': hexDecode(archiveVectors['tampered_hex'] as String),
    };
    for (final c in cases(vectors, 'verify')) {
      final name = c['name'] as String;
      final archive = archives[c['archive'] ?? 'archive']!;
      final release = releases[c['release']]!;
      final run = verifyModePackage(
        archive,
        release,
        strings(c['keys']),
        revoked: strings(c['revoked']),
        namedKey: c['named_key'] as String?,
      );
      if (c['result'] == 'ok') {
        final package = await run;
        expect(package.keyId, signingKeyId, reason: name);
        expect(package.files, archiveFiles, reason: name);
        expect(package.license, 'MIT', reason: name);
        expect(package.release, release, reason: name);
      } else {
        await expectLater(run, throwsCode(c['result'] as String), reason: name);
      }
    }
  });

  test('index and index_invalid', () {
    final entries = parseModeIndex(vectors['index']);
    expect(entries, hasLength(1));
    final entry = entries.single;
    expect(entry.release.id, 'org.example.relay');
    expect(entry.license, 'MIT');
    expect(entry.verified, isTrue);
    expect(entry.name, 'Relay');
    expect(entry.keyId, signingKeyId);
    expect(entry.url, 'packages/org.example.relay-1.2.0-rc.1.tar');
    expect(entry.release, releaseOf(cases(vectors, 'releases').first));
    for (final c in cases(vectors, 'index_invalid')) {
      expect(
        () => parseModeIndex(c['index']),
        throwsCode('bad_index'),
        reason: c['name'] as String,
      );
    }
  });

  test('revoked: the revocation list', () {
    expect(parseRevoked(vectors['revoked']), {signingKeyId: 'test key'});
    for (final bad in <Object>[
      {'schema_version': 1},
      {
        'schema_version': 1,
        'keys': [
          {'key_id': 'x'},
        ],
      },
      {
        'schema_version': 1,
        'keys': [
          {'key_id': '0' * 16, 'date': '22/10/2026'},
        ],
      },
    ]) {
      expect(() => parseRevoked(bad), throwsCode('bad_index'));
    }
  });

  test('box_limits', () {
    final limits = vectors['box_limits'] as Map;
    expect(limits['max_package_bytes'], boxMaxPackageBytes);
    expect(limits['max_fetched'], boxMaxFetched);
    expect(limits['max_fetched_bytes'], boxMaxFetchedBytes);
    expect(
      [boxMaxPackageBytes, boxMaxFetched, boxMaxFetchedBytes],
      [256 * 1024, 8, 512 * 1024],
    );
  });

  test("box_checks: a box's checks in its order", () async {
    final valid = hexDecode(archiveVectors['hex'] as String);
    final archives = {
      'archive': valid,
      'tampered': hexDecode(archiveVectors['tampered_hex'] as String),
      'truncated': Uint8List.sublistView(valid, 0, valid.length - 512),
    };
    final all = cases(vectors, 'box_checks');
    expect(all.map((c) => c['result']).toSet(), {
      'ok',
      'no_key',
      'bad_release',
      'bad_signature',
      'kind',
      'tier',
      'builtin',
      'too_big',
      'bad_hash',
      'bad_archive',
    });
    for (final c in all) {
      final name = c['name'] as String;
      Future<(String, Map<String, String>)> run() async {
        final (release, who) = await boxCheckRelease(
          utf8.encode(c['release_text'] as String),
          c['wanted_id'] as String,
          strings(c['keys']),
          c['tier'] as String,
          builtin: strings(c['builtin']),
        );
        final data = c['archive'] != null
            ? archives[c['archive']]!
            : hexDecode(c['archive_hex'] as String);
        return (who, boxCheckArchive(data, release));
      }

      if (c['result'] == 'ok') {
        final (who, kept) = await run();
        expect(who, c['key_id'], reason: name);
        expect(kept.keys.toList()..sort(), c['kept'], reason: name);
        expect(kept['node.lua'], archiveFiles['node.lua'], reason: name);
      } else {
        await expectLater(
          run(),
          throwsCode(c['result'] as String),
          reason: name,
        );
      }
    }
  });

  test("reports: a box's report bodies, MACs and the bodies to refuse", () {
    final reports = vectors['reports'] as Map<String, dynamic>;
    final gameKey = hexDecode(reports['game_key'] as String);
    for (final v in cases(reports, 'valid')) {
      final kept = (v['kept'] as Map).cast<String, String>();
      final body = modeReportBody(
        v['game'] as int,
        v['node'] as int,
        v['mode'] as String,
        v['version'] as String?,
        v['result'] as String,
        kept,
      );
      expect(utf8.decode(body), v['body']);
      expect(reportMac(gameKey, body), v['mac']);
      final got = parseModeReport(body);
      expect(got['game'], v['game']);
      expect(got['node'], v['node']);
      expect(got['mode'], v['mode']);
      expect(got['version'], v['version']);
      expect(got['result'], v['result']);
      expect(got['kept'], kept);
    }
    for (final v in cases(reports, 'invalid')) {
      expect(
        () => parseModeReport(utf8.encode(v['body'] as String)),
        throwsCode('bad_report'),
        reason: v['name'] as String,
      );
    }
    expect(boxResults, contains('installed'));
    expect(boxResults.toSet(), hasLength(boxResults.length));
  });

  group('helpers as firmware_release.py', () {
    test('versions sort as Semantic Versioning', () {
      const ordered = [
        '0.9.9',
        '1.0.0-alpha',
        '1.0.0-alpha.1',
        '1.0.0-alpha.beta',
        '1.0.0-rc.2',
        '1.0.0-rc.10',
        '1.0.0',
        '1.0.1',
        '1.10.0',
      ];
      for (var i = 0; i + 1 < ordered.length; i++) {
        expect(compareVersions(ordered[i], ordered[i + 1]), -1);
        expect(compareVersions(ordered[i + 1], ordered[i]), 1);
        expect(compareVersions(ordered[i], ordered[i]), 0);
      }
      for (final bad in [
        '1.2',
        '1.2.3-',
        '1.2.3-rc..1',
        '12345.0.0',
        ' 1.2.3',
        '1.2.3\n',
      ]) {
        expect(versionKey(bad), isNull, reason: bad);
      }
      // Python's \d takes any decimal digit.
      expect(compareVersions('١.٢.٣', '1.2.3'), 0);
      expect(versionKey('1.0.0-99999999999999999999'), isNotNull);
    });

    test('base64 is strict, as b64decode(validate=True)', () {
      final sig = cases(vectors, 'releases').first['signature'] as String;
      expect(signatureBytes(sig), hasLength(64));
      expect(signatureBytes(sig.replaceFirst('u', '-')), isNull);
      expect(signatureBytes('${sig.substring(0, 86)}A='), isNull);
      expect(signatureBytes(sig.substring(1)), isNull);
      expect(publicKeyBytes('$key\n'), isNull);
      expect(publicKeyBytes(key.replaceAll('=', '')), isNull);
      expect(publicKeyBytes(42), isNull);
    });

    test('manifestFields reads mode.yaml as Python does', () {
      Map<String, String> files(String yaml) => {'mode.yaml': yaml};
      final own = manifestFields(
        files('id: org.club.test\nversion: 0.1.0\nlicense: MIT\n'),
      );
      expect(
        [own.id, own.version, own.kind, own.minTier, own.license],
        ['org.club.test', '0.1.0', 'mode', 'reduced', 'MIT'],
      );
      expect(
        () => manifestFields(
          files('id: org.club.test\nversion: 1.5\nlicense: MIT\n'),
        ),
        throwsCode('bad_manifest'),
      );
      expect(
        () => manifestFields(
          files('id: org.club.test\nversion: 0.1.0\nlicense: WTFPL\n'),
        ),
        throwsCode('licence'),
      );
      expect(
        () => manifestFields(
          files('id: org.club.test\nversion: 0.1.0\nkind:\nlicense: MIT\n'),
        ),
        throwsCode('bad_manifest'),
      );
      expect(() => manifestFields(files('')), throwsCode('bad_manifest'));
      expect(() => manifestFields(files('[1, 2]')), throwsCode('bad_manifest'));
      expect(() => manifestFields({}), throwsCode('bad_manifest'));
    });

    test('packArchive refuses what pack refuses', () {
      for (final name in [
        '../evil.lua',
        '/etc/passwd',
        'tests/basic.yaml',
        'assets/../node.lua',
        'assets/.hidden/x',
        'assets//x',
        'NODE.lua',
        'assets/${'x' * 90}',
      ]) {
        expect(
          () =>
              packArchive('org.club.test', {'mode.yaml': 'id: x\n', name: 'x'}),
          throwsCode('bad_archive'),
          reason: name,
        );
      }
      for (final id in [
        'Org.Club',
        'club',
        'org.club.x${'x' * 60}',
        '../org.x',
      ]) {
        expect(
          () => packArchive(id, {'mode.yaml': 'id: x\n'}),
          throwsCode('bad_archive'),
          reason: id,
        );
      }
      expect(
        () => packArchive('org.club.test', {
          'mode.yaml': 'x',
          'assets/big.txt': 'x' * modePackageMaxBytes,
        }),
        throwsCode('too_big'),
      );
      final archive = hexDecode(archiveVectors['hex'] as String);
      expect(
        () => unpackArchive(
          Uint8List.fromList([...archive, ...Uint8List(modePackageMaxBytes)]),
        ),
        throwsCode('too_big'),
      );
    });
  });
}
