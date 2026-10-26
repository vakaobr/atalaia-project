// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Which addresses the check-in poster lists and the certificate covers
// (field_addresses.dart, decisions check-R8 and check-R9): the shared cases of
// protocol/vectors/checkin.json ("poster_addresses", the Pi's
// controller/tests/test_poster_addresses.py runs them too), and the phone
// controller's use of them: a stale address dropped and warned about, a
// current one listed, a name kept, the saved poster re-derived.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/field_addresses.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';
import '../support/vectors.dart';

List<String> _strings(Object? v) => (v! as List).cast<String>();

void main() {
  final all = loadVectors('checkin.json')['poster_addresses'] as Map;
  final vectorCases = (all['cases'] as List).cast<Map<String, dynamic>>();

  final change = loadVectors('checkin.json')['poster_change'] as Map;
  final changeCases = (change['cases'] as List).cast<Map<String, dynamic>>();

  group('shared cases of "the poster changed" (check-R8)', () {
    test('are all here', () {
      expect(changeCases.length, greaterThanOrEqualTo(8));
    });
    for (final c in changeCases) {
      test('${c['name']}', () {
        final i = c['input'] as Map<String, dynamic>;
        expect(
          posterChange(
            i['printed'] as Map<String, Object?>?,
            _strings(i['urls']),
            i['ca_sha256'] as String?,
          ),
          c['expected'],
        );
      });
    }
  });

  test('the shared cases are all here', () {
    expect(vectorCases.length, greaterThanOrEqualTo(10));
  });

  group('shared cases', () {
    for (final c in vectorCases) {
      test('${c['name']}', () {
        final i = c['input'] as Map<String, dynamic>;
        final want = c['expected'] as Map<String, dynamic>;
        final plan =
            FieldAddresses(
              tlsNames: _strings(i['tls_names']),
              found: _strings(i['found']),
              interfaces: _strings(i['interfaces']),
              tlsPort: i['tls_port'] as int,
              container: i['container'] as bool,
            ).plan(
              saved: _strings(i['saved_urls']),
              checkinUrls: _strings(i['checkin_urls']),
            );
        expect(plan.poster, _strings(want['poster']));
        expect(plan.dropped, _strings(want['dropped']));
        expect([...plan.san]..sort(), _strings(want['san']));
        // check-R9: the certificate covers every host on the poster.
        expect(plan.san.toSet().containsAll(plan.poster.map(urlHost)), isTrue);
      });
    }
  });

  group('the phone controller', () {
    final limits = File(
      'lib/chrono/limit_templates/portugal.yaml',
    ).readAsStringSync();
    late ControllerEngine engine;
    late ControllerCheckin svc;
    late List<String> warnings;
    const mine = ['10.42.0.1'];

    FieldAddresses now([List<String> a = mine]) =>
        FieldAddresses(found: a, interfaces: a);

    ControllerCheckin make({List<String> urls = const []}) {
      final s = ControllerCheckin(
        engine,
        CheckinConfig(limitsYaml: limits, urls: urls),
      )..warn = warnings.add;
      s.defaultUrls = now().plan().defaultUrls;
      return s;
    }

    setUp(() {
      warnings = [];
      engine = ControllerEngine(
        transport: RecordingRadio(),
        wallSeconds: () => 1800007200.0,
      );
      svc = make();
    });

    Map<String, Object?> saved() =>
        jsonDecode(engine.store.getSetting('checkin.poster') ?? '{}')
            as Map<String, Object?>;

    test('a current address is on the poster', () {
      svc.useAddresses(now());
      expect(svc.posterFields()['urls'], ['https://10.42.0.1:8443']);
      expect(warnings, isEmpty);
    });

    test('a saved poster is re-derived at start: stale dropped, warned', () {
      engine.store.setSetting(
        'checkin.poster',
        jsonEncode({
          'urls': ['https://192.168.1.50:8443', 'https://campo.lan:8443'],
          'wifi_ssid': 'CAMPO',
          'game_id': 7,
          'field_name': 'Campo Norte',
        }),
      );
      svc.useAddresses(now());
      expect(warnings.single, contains('192.168.1.50'));
      final p = svc.posterFields();
      expect(p['urls'], ['https://campo.lan:8443']); // the name stays
      expect(p['wifi_ssid'], 'CAMPO');
      expect(p['game_id'], 7);
      expect(p['field_name'], 'Campo Norte');
      expect(saved()['urls'], ['https://campo.lan:8443']); // and the setting
    });

    test('only stale addresses saved: the poster is the default again', () {
      engine.store.setSetting(
        'checkin.poster',
        jsonEncode({
          'urls': ['https://192.168.1.50:8443'],
          'game_id': 7,
        }),
      );
      svc.useAddresses(now());
      final p = svc.posterFields();
      expect(p['urls'], ['https://10.42.0.1:8443']);
      expect(p['game_id'], 7);
      expect(saved().containsKey('urls'), isFalse);
    });

    test('config.urls: an IP not on an interface is dropped, a name stays', () {
      svc = make(urls: ['https://172.16.9.9:8443', 'https://campo.lan']);
      svc.useAddresses(now());
      expect(warnings.single, contains('172.16.9.9'));
      expect(svc.posterFields()['urls'], ['https://campo.lan']);
    });

    test(
      'a change of the phone\'s addresses drops what is no longer there',
      () {
        engine.store.setSetting(
          'checkin.poster',
          jsonEncode({
            'urls': ['https://10.42.0.1:8443'],
          }),
        );
        svc.useAddresses(now());
        expect(svc.posterFields()['urls'], ['https://10.42.0.1:8443']);
        expect(warnings, isEmpty);
        svc.defaultUrls = now(['192.168.43.1']).plan().defaultUrls;
        svc.useAddresses(now(['192.168.43.1']));
        expect(warnings.single, contains('10.42.0.1'));
        expect(svc.posterFields()['urls'], ['https://192.168.43.1:8443']);
      },
    );

    test('PUT with a stale address leaves it out', () {
      svc.useAddresses(now());
      final out = svc.setPoster({
        'urls': ['https://192.168.1.50:8443', 'https://10.42.0.1:8443'],
        'game_id': 3,
      });
      expect(out['urls'], ['https://10.42.0.1:8443']);
      expect(saved()['urls'], ['https://10.42.0.1:8443']);
      expect(warnings.single, contains('192.168.1.50'));
      final again = svc.setPoster({
        'urls': ['https://192.168.1.50:8443'],
      });
      expect(again['urls'], ['https://10.42.0.1:8443']);
      expect(saved().containsKey('urls'), isFalse);
    });

    test('the poster changed since it was printed: said, and quiet after', () {
      svc.caSha256 = Uint8List.fromList(List.filled(32, 7));
      svc.useAddresses(now());
      var p = svc.poster();
      expect([p['printed'], p['changed']], [null, null]);
      p = svc.markPosterPrinted();
      expect((p['printed']! as Map)['urls'], ['https://10.42.0.1:8443']);
      expect(p['changed'], isNull);
      svc.defaultUrls = now(['192.168.43.1']).plan().defaultUrls;
      svc.useAddresses(now(['192.168.43.1']));
      final c = svc.poster()['changed']! as Map;
      expect(c['removed'], ['https://10.42.0.1:8443']);
      expect(c['added'], ['https://192.168.43.1:8443']);
      expect(c['still_works'], isFalse);
      expect(svc.markPosterPrinted()['changed'], isNull);
    });

    test('without addresses (tests) the lists are used as given', () {
      engine.store.setSetting(
        'checkin.poster',
        jsonEncode({
          'urls': ['https://192.168.1.50:8443'],
        }),
      );
      expect(svc.posterFields()['urls'], ['https://192.168.1.50:8443']);
    });
  });
}
