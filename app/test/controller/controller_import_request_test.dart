// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The registration import's request to the phone's running controller
// (lib/controller/controller_import_screen.dart, requestRegistrationImport):
// the real API on a loopback port, as the tags' request goes (a plain test:
// a widget test's binding answers every HTTP request itself). A dry run, a
// refusal with the controller's own code, and no controller.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_import_screen.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

const _csv =
    'display_name,external_ref,team_preference\n'
    'Ana,a1,red\n'
    ',b2,blue\n';

void main() {
  late ControllerApi api;
  late int gameId;
  final limits = File(
    'lib/chrono/limit_templates/portugal.yaml',
  ).readAsStringSync();

  setUp(() {
    final engine = ControllerEngine(
      transport: RecordingRadio(),
      wallSeconds: () => 1800007200.0,
    );
    ControllerCheckin(engine, CheckinConfig(limitsYaml: limits, utcDay: true));
    ControllerPositions(engine);
    api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
    final r = api.handle(
      'POST',
      Uri.parse('/api/v1/games'),
      authorization: 'Bearer g',
      body: jsonEncode({
        'name': 'Domingo',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      }),
      client: 'local',
    );
    gameId = (r.body! as Map)['id']! as int;
  });

  test('a dry run, a refusal with its code, and no controller', () async {
    final server = await api.serve();
    addTearDown(() => server.close(force: true));
    final port = server.port;
    final r = await requestRegistrationImport(port, 'g', gameId, {
      'format': 'csv',
      'data': _csv,
      'source': 'csv',
      'dry_run': true,
      'basis_confirmed': false,
    });
    expect((r['counts']! as Map)['created'], 1);
    expect(r['dry_run'], isTrue);
    await expectLater(
      requestRegistrationImport(port, 'g', gameId, {
        'format': 'csv',
        'data': _csv,
        'source': 'csv',
        'dry_run': false,
        'basis_confirmed': false,
      }),
      throwsA(
        isA<ImportRequestError>().having(
          (e) => e.code,
          'code',
          'basis_not_confirmed',
        ),
      ),
    );
    await expectLater(
      requestRegistrationImport(port, 'g', gameId, {
        'format': 'csv',
        'data': 'external_ref\na1\n',
        'source': 'csv',
        'dry_run': true,
        'basis_confirmed': false,
      }),
      throwsA(
        isA<ImportRequestError>().having(
          (e) => e.code,
          'code',
          'display_name_column_missing',
        ),
      ),
    );
    await expectLater(
      requestRegistrationImport(port, 'wrong', gameId, const {}),
      throwsA(isA<ImportRequestError>()),
    );
    final real = await requestRegistrationImport(port, 'g', gameId, {
      'format': 'csv',
      'data': _csv,
      'source': 'csv',
      'dry_run': false,
      'basis_confirmed': true,
    });
    expect((real['counts']! as Map)['created'], 1);
    final again = await requestRegistrationImport(port, 'g', gameId, {
      'format': 'csv',
      'data': _csv,
      'source': 'csv',
      'dry_run': true,
      'basis_confirmed': false,
    });
    expect((again['counts']! as Map)['unchanged'], 1);
    final gone = port;
    await server.close(force: true);
    await expectLater(
      requestRegistrationImport(gone, 'g', gameId, const {}),
      throwsA(
        isA<ImportRequestError>().having((e) => e.code, 'code', 'offline'),
      ),
    );
  });
}
