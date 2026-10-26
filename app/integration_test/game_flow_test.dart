// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator (CI's flutter-integration job), in real
// time: a Bomb prop on the APK's own core, armed by holding the red button
// and then exploding; a game joined with a join text; and the player's
// view following a field controller over a WebSocket (a stand-in served on
// the phone itself), with the score changing as events arrive; and a
// scenario's objectives (phase 4 plan phase 8): a hidden one appears when
// the controller sends the game again with it, in progress once revealed.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_home.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

/// protocol/vectors/join.json: its join key and the "node_domination_zone"
/// payload's text form (the files are not on the phone).
const joinKey =
    '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';
const joinText =
    'atalaia:join:AasBGRCSAlArfhUWKK7Spqv3FYgJz088AwcEAAUaM9PmCAYCB4JjcmVkZGJsdW'
    'UIdm9yZy5hdGFsYWlhLmRvbWluYXRpb24JZHpvbmUKGTA5DABTPb_iVQNhRBI4c-CumM5lJXJdqh'
    'E3cFgVeFUzs9sh_Q';

Finder inDialog(String text) => find.descendant(
  of: find.byType(AlertDialog),
  matching: find.widgetWithText(FilledButton, text),
);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('a Bomb prop: hold to arm, then it explodes', (tester) async {
    final catalog = ModeCatalog.builtin();
    final mode = catalog.compose('org.atalaia.bomb');
    const teams = ['red', 'blue'];
    final setup = PropSetup(
      mode: mode,
      role: 'bomb',
      teams: teams,
      params: mode.resolveParams({'fuse_s': 10, 'arm_hold_ms': 2000}, teams),
    );
    await tester.pumpWidget(
      deviceApp(
        home: PropGameScreen(setup: setup, modeName: 'Bomba'),
      ),
    );
    await waitFor(tester, find.byKey(const Key('prop-start')));
    await tester.tap(find.byKey(const Key('prop-start')));
    await waitFor(tester, inDialog('Começar'));
    await tester.tap(inDialog('Começar'));
    await waitFor(tester, find.text('Hold to arm'));

    final hold = await tester.startGesture(
      tester.getCenter(find.byKey(const Key('team-button-red'))),
    );
    await pass(tester, const Duration(milliseconds: 2600));
    await hold.up();
    await waitFor(tester, find.text('until detonation'));
    await waitFor(
      tester,
      find.text('EXPLODED'),
      timeout: const Duration(seconds: 20),
    );
  });

  testWidgets('joining with the join text prepares that game', (tester) async {
    await tester.pumpWidget(
      deviceApp(
        settings: AppSettings()..joinKeyHex = joinKey,
        home: const PropHomeScreen(),
      ),
    );
    await waitFor(tester, find.byKey(const Key('prop-join')));
    await tester.tap(find.byKey(const Key('prop-join')));
    await waitFor(tester, find.byKey(const Key('join-text')));
    await tester.enterText(find.byKey(const Key('join-text')), joinText);
    await tester.tap(find.byKey(const Key('join-use-text')));
    await waitFor(tester, find.text('Jogo do controlador'));
    expect(find.textContaining('Jogo 4242'), findsOneWidget);
    expect(find.text('Domínio'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('setup-go')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('setup-go')));
    await waitFor(tester, find.byKey(const Key('prop-start')));
  });

  testWidgets('the player view follows the controller over a WebSocket', (
    tester,
  ) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final socket = Completer<WebSocket>();
    server.listen((req) async {
      if (req.uri.path == '/api/v1/stream' &&
          req.uri.queryParameters['token'] == 'read-code') {
        socket.complete(await WebSocketTransformer.upgrade(req));
      } else {
        req.response.statusCode = 404;
        await req.response.close();
      }
    });
    final link = FieldLink.parse('127.0.0.1:${server.port}', 'read-code')!;
    await tester.pumpWidget(deviceApp(home: PlayerScreen(link: link)));
    final ws = await socket.future.timeout(const Duration(seconds: 20));
    ws.add(
      jsonEncode({
        'type': 'hello',
        'game': {
          'id': 3,
          'name': 'Jogo de teste',
          'teams': ['red', 'blue'],
          'state': 'running',
          'game_time_ms': 1000,
          'live': true,
        },
        'score': {
          'game': 3,
          'teams': {'red': 0, 'blue': 0},
        },
        'nodes': [
          {'node_id': 2, 'name': 'Moinho', 'owner': null},
        ],
      }),
    );
    await waitFor(tester, find.text('Jogo de teste'));
    ws
      ..add(
        jsonEncode({
          'type': 'event',
          'game': 3,
          'event': {
            'node': 2,
            't': 5000,
            'type': 'zone.captured',
            'team': 'red',
            'data': {'zone': 'Moinho'},
          },
        }),
      )
      ..add(
        jsonEncode({
          'type': 'score',
          'game': 3,
          'teams': {'red': 5, 'blue': 0},
        }),
      );
    await waitFor(tester, find.text('A equipa vermelha capturou Moinho'));
    await waitFor(
      tester,
      find.byWidgetPredicate(
        (w) =>
            w is Text &&
            w.key == const Key('player-points-red') &&
            w.data == '5',
      ),
    );
    await ws.close();
  });

  testWidgets('the player view shows a scenario objective once revealed', (
    tester,
  ) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final socket = Completer<WebSocket>();
    server.listen((req) async {
      if (req.uri.path == '/api/v1/stream' &&
          req.uri.queryParameters['token'] == 'read-code') {
        socket.complete(await WebSocketTransformer.upgrade(req));
      } else {
        req.response.statusCode = 404;
        await req.response.close();
      }
    });
    Map<String, Object?> objective(String id, String name, String pt) => {
      'id': id,
      'type': 'enter_code',
      'name': name,
      'i18n': {
        'pt': {'name': pt},
      },
      'team': 'red',
      'visibility': id == 'vault' ? 'hidden' : 'team',
    };
    Map<String, Object?> game(List<Map<String, Object?>> objectives) => {
      'id': 4,
      'name': 'Jogo do cofre',
      'teams': ['red', 'blue'],
      'state': 'running',
      'game_time_ms': 1000,
      'live': true,
      'scenario': {
        'id': 'org.club.cofre',
        'name': 'Vault',
        'objectives': objectives,
      },
    };
    final bridge = objective('bridge', 'Take the bridge', 'Tomar a ponte');
    final link = FieldLink.parse('127.0.0.1:${server.port}', 'read-code')!;
    await tester.pumpWidget(deviceApp(home: PlayerScreen(link: link)));
    final ws = await socket.future.timeout(const Duration(seconds: 20));
    ws.add(
      jsonEncode({
        'type': 'hello',
        'game': game([bridge]),
        'score': {
          'game': 4,
          'teams': {'red': 0, 'blue': 0},
        },
        'nodes': <Object?>[],
      }),
    );
    await waitFor(tester, find.text('Tomar a ponte'));
    expect(find.text('Abrir o cofre'), findsNothing);
    ws
      ..add(
        jsonEncode({
          'type': 'game',
          'game': game([
            bridge,
            objective('vault', 'Open the vault', 'Abrir o cofre'),
          ]),
        }),
      )
      ..add(
        jsonEncode({
          'type': 'event',
          'game': 4,
          'event': {
            'node': 1,
            't': 5000,
            'type': 'scenario.objective.revealed',
            'team': 'red',
            'data': {'objective': 'vault', 'team': 'red'},
          },
        }),
      );
    await waitFor(tester, find.text('Abrir o cofre'));
    expect(find.text('Em curso · Para a equipa vermelha'), findsNWidgets(2));
    await ws.close();
  });
}
