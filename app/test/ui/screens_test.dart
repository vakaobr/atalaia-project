// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The other roles' screens: the settings (language, join key, PIN), the
// player's view following a live feed, the GM console's address, the
// marshal's chrono check-in.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart' show FieldInfo;
import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/chrono/chrono_ui.dart';
import 'package:atalaia_app/marshal/marshal_home.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/gm_screen.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';
import '../support/marshal_trust.dart';

class ScriptedSocket implements FeedSocket {
  ScriptedSocket(this.lines);
  final List<Map<String, Object?>> lines;
  final _c = StreamController<String>();

  @override
  Stream<String> get messages {
    for (final l in lines) {
      _c.add(jsonEncode(l));
    }
    return _c.stream;
  }

  @override
  int? get closeCode => null;

  @override
  Future<void> close() => _c.close();
}

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(420, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

final liveGame = <Map<String, Object?>>[
  {
    'type': 'hello',
    'game': {
      'id': 7,
      'name': 'Domingo no Moinho',
      'teams': ['red', 'blue'],
      'state': 'running',
      'duration_ms': 1800000,
      'game_time_ms': 600000,
      'live': true,
    },
    'score': {
      'game': 7,
      'teams': {'red': 12, 'blue': 20},
    },
    'nodes': [
      {'node_id': 2, 'name': 'Moinho', 'owner': 'blue'},
      {'node_id': 3, 'name': 'Ponte', 'owner': null},
    ],
  },
  {
    'type': 'event',
    'game': 7,
    'event': {
      'node': 2,
      't': 590000,
      'type': 'zone.captured',
      'team': 'blue',
      'data': {'zone': 'Moinho'},
    },
  },
  {
    'type': 'event',
    'game': 7,
    'event': {
      'node': 1,
      't': 595000,
      'type': 'gm.message',
      'data': {'text': 'Faltam 20 minutos'},
    },
  },
];

void main() {
  testWidgets('settings: the language changes the whole app', (tester) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const SettingsScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Definições'), findsOneWidget);
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();
    expect(find.text('Settings'), findsOneWidget);
    expect(h.settings.language.code, 'en');
    expect((await h.store.loadSettings()).language.code, 'en');
    // Traditional Chinese: its code is zh-tw, kept as such (plan phase 11).
    await tester.tap(find.text('中文（台灣）'));
    await tester.pumpAndSettle();
    expect(find.text('設定'), findsOneWidget);
    expect((await h.store.loadSettings()).language.code, 'zh-tw');
  });

  testWidgets('settings: the join key and the PIN', (tester) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const SettingsScreen()));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('join-key')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('join-key-field')), '12' * 32);
    await tester.tap(find.text('Guardar'));
    await tester.pumpAndSettle();
    expect(h.settings.joinKeyHex, '12' * 32);
    expect(find.text('Definida (termina em …12121212)'), findsOneWidget);

    await tester.tap(find.byKey(const Key('admin-pin')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('new-pin-field')), '4321');
    await tester.tap(find.text('Guardar'));
    await tester.pumpAndSettle();
    expect(h.settings.checkPin('4321'), isTrue);
    // Changing it needs the old one.
    await tester.tap(find.byKey(const Key('admin-pin')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pin-field')), findsOneWidget);
  });

  testWidgets('the player follows the game', (tester) async {
    await phone(tester);
    final h = harness(
      feedConnect: (uri) async => ScriptedSocket(liveGame),
      settings: AppSettings()..myTeam = 'blue',
    );
    await tester.pumpWidget(
      h.app(home: PlayerScreen(link: FieldLink.parse('10.0.0.1', 'c')!)),
    );
    await tester.pumpAndSettle();
    expect(find.text('Domingo no Moinho'), findsOneWidget);
    expect(find.byKey(const Key('player-points-blue')), findsOneWidget);
    expect(find.text('20'), findsOneWidget);
    expect(find.text('a tua equipa'), findsOneWidget);
    expect(find.text('20:00'), findsOneWidget); // 30 min - 10 min
    expect(find.text('Organização: Faltam 20 minutos'), findsWidgets);
    expect(find.text('A equipa azul capturou Moinho'), findsOneWidget);
    await tester.tap(find.byKey(const Key('player-team-red')));
    await tester.pumpAndSettle();
    expect(h.settings.myTeam, 'red');
  });

  test("the Medic Kit's events in words, in both languages", () {
    const heal = FeedEvent(
      'medic.heal',
      'blue',
      {'player': 'b1', 'remaining': 4, 'player_heals_used': 1},
      597000,
      5,
    );
    const empty = FeedEvent('medic.empty', null, {}, 598000, 6);
    const pt = Strings(AppLanguage.pt);
    const en = Strings(AppLanguage.en);
    expect(eventText(pt, heal), 'b1 recebeu tratamento (ligaduras no kit: 4)');
    expect(eventText(en, heal), 'b1 was healed (heals left in the kit: 4)');
    expect(eventText(pt, empty), 'Um kit de ligaduras ficou vazio');
    expect(eventText(en, empty), 'A medic kit is empty');
  });

  test("Money Factory's events in words, in both languages", () {
    const collected = FeedEvent(
      'money.collected',
      'red',
      {'player': 'r1', 'amount': 12},
      60000,
      9,
    );
    const banked = FeedEvent(
      'money.deposited',
      'red',
      {'player': 'r1', 'amount': 12},
      90000,
      10,
    );
    const pt = Strings(AppLanguage.pt);
    const en = Strings(AppLanguage.en);
    expect(eventText(pt, collected), 'r1 recolheu 12 de dinheiro');
    expect(eventText(en, collected), 'r1 collected 12 money');
    expect(eventText(pt, banked), 'r1 depositou 12 para a equipa vermelha');
    expect(eventText(en, banked), 'r1 banked 12 for red');
  });

  test("Progressive Domination's events in words, in the four languages", () {
    const activated = FeedEvent(
      'progressive.activated',
      null,
      {'zone': 'Moinho', 'step': 2},
      60000,
      0,
    );
    const completed = FeedEvent(
      'progressive.completed',
      'red',
      {'zone': 'Moinho', 'step': 2},
      90000,
      0,
    );
    const pt = Strings(AppLanguage.pt);
    const en = Strings(AppLanguage.en);
    const de = Strings(AppLanguage.de);
    const zh = Strings(AppLanguage.zhTw);
    expect(
      eventText(pt, activated),
      'A caixa Moinho está ativa (n.º 2): é a única que pode ser capturada',
    );
    expect(
      eventText(en, activated),
      'Box Moinho is active now (number 2): the only one that can be captured',
    );
    expect(
      eventText(de, activated),
      'Box Moinho ist jetzt aktiv (Nr. 2): nur sie kann eingenommen werden',
    );
    expect(eventText(zh, activated), '盒子「Moinho」現已啟用（第 2 個）：只有它能被佔領');
    expect(
      eventText(pt, completed),
      'A equipa vermelha completou a caixa Moinho (n.º 2)',
    );
    expect(eventText(en, completed), 'red completed box Moinho (number 2)');
    expect(
      eventText(de, completed),
      'Team Rot hat Box Moinho abgeschlossen (Nr. 2)',
    );
    expect(eventText(zh, completed), '紅隊完成了盒子「Moinho」（第 2 個）');
  });

  test("the Hacking Terminal's event in words, with and without a team", () {
    const solved = FeedEvent(
      'hacking.solved',
      'red',
      {'puzzle': 'wires', 'code': '4711'},
      95000,
      7,
    );
    const nobody = FeedEvent(
      'hacking.solved',
      null,
      {'puzzle': 'code'},
      96000,
      8,
    );
    const pt = Strings(AppLanguage.pt);
    const en = Strings(AppLanguage.en);
    expect(eventText(pt, solved), 'A equipa vermelha hackeou um terminal');
    expect(eventText(en, solved), 'red hacked a terminal');
    expect(eventText(pt, nobody), 'Um terminal foi hackeado');
    expect(eventText(en, nobody), 'A terminal was hacked');
    // The code the terminal reveals is not in the players' feed.
    expect(eventText(en, solved), isNot(contains('4711')));
  });

  testWidgets('the player connects with the scoreboard QR code', (
    tester,
  ) async {
    await phone(tester);
    final uris = <Uri>[];
    final h = harness(
      qr: FakeQr('http://10.1.1.1:8080/scoreboard#token=read-1'),
      feedConnect: (uri) async {
        uris.add(uri);
        return ScriptedSocket(const []);
      },
    );
    await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('player-scan')));
    await tester.pumpAndSettle();
    expect(
      uris.single.toString(),
      'ws://10.1.1.1:8080/api/v1/stream?token=read-1',
    );
    expect(h.settings.readToken, 'read-1');
  });

  testWidgets('the GM console opens at its address', (tester) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const GmScreen()));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('gm-url')), '10.0.0.5');
    await tester.tap(find.byKey(const Key('gm-open')));
    await tester.pumpAndSettle();
    expect(find.text('console http://10.0.0.5:8080/console/'), findsOneWidget);
    expect(
      consoleUrl('https://campo.pt/console/')!.toString(),
      'https://campo.pt:8080/console/',
    );
    expect(consoleUrl(''), isNull);
  });

  testWidgets('the marshal checks a replica in: PASS', (tester) async {
    await phone(tester);
    tester.view.physicalSize = const Size(420, 1800); // the whole form at once
    final settings = AppSettings()
      ..marshalName = 'Ana'
      ..marshalId = 'm-1';
    final h = harness(settings: settings);
    final records = MarshalRecords(h.store, settings);
    await tester.runAsync(() async {
      await records.load();
      await records.newKey();
      trustMarshal(records);
      await records.addReplica(
        Replica(
          replicaId: newUuid(),
          ownerPlayerId: 'p-17',
          type: ReplicaType.aeg,
          replicaClass: 'rifle',
          makeModel: 'M4',
          registeredAt: '2026-10-19T09:00:00Z',
          tagType: TagType.nfc,
          tagUid: '04:A1:B2:C3',
        ),
      );
    });
    final templates = [
      LimitTemplate.parse(
        File('lib/chrono/limit_templates/portugal.yaml').readAsStringSync(),
      ),
    ];
    await tester.pumpWidget(
      h.app(
        home: ChronoScreen(records: records, templates: templates),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chrono-unverified')), findsOneWidget);
    // The replica, by its NFC sticker.
    h.nfc.tap(NfcRead(uid: Uint8List.fromList([0x04, 0xa1, 0xb2, 0xc3])));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chrono-limit')), findsOneWidget);
    for (final k in ['9', '5', '.', '5']) {
      final key = find.byKey(Key('chrono-key-$k'));
      await tester.ensureVisible(key);
      await tester.pumpAndSettle();
      await tester.tap(key);
      await tester.pump();
    }
    await tester.pump();
    expect(find.text('95.5', skipOffstage: false), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const Key('chrono-record')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const Key('chrono-record')));
      await Future<void>.delayed(const Duration(milliseconds: 200));
    });
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chrono-result-pass')), findsOneWidget);
    expect(records.readings.single.velocityMps, 95.5);
  });

  group("the chrono screen and the field controller's limits", () {
    List<LimitTemplate> templates() => [
      for (final n in ['portugal', 'uk'])
        LimitTemplate.parse(
          File('lib/chrono/limit_templates/$n.yaml').readAsStringSync(),
        ),
    ];

    Future<void> open(
      WidgetTester tester,
      Future<FieldInfo> Function()? info,
    ) async {
      await phone(tester);
      final h = harness();
      final records = MarshalRecords(h.store, h.settings);
      await tester.pumpWidget(
        h.app(
          home: ChronoScreen(
            records: records,
            templates: templates(),
            fieldInfo: info,
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('not connected: the list is a preview and says so', (
      tester,
    ) async {
      await open(tester, null);
      expect(find.textContaining('veredicto'), findsOneWidget);
      // the template's name in the app's language, not the file's English
      expect(find.text('Portugal'), findsWidgets);
      final dd = tester.widget<DropdownButtonFormField<LimitTemplate>>(
        find.byKey(const Key('chrono-template')),
      );
      expect(dd.onChanged, isNotNull);
    });

    testWidgets("connected: the controller's template is used, locked", (
      tester,
    ) async {
      await open(
        tester,
        () async => FieldInfo({
          'limits': {'id': 'uk', 'name': 'United Kingdom'},
        }),
      );
      expect(find.text('Reino Unido'), findsOneWidget);
      expect(find.text('Definidos pelo controlador do campo.'), findsOneWidget);
      final dd = tester.widget<DropdownButtonFormField<LimitTemplate>>(
        find.byKey(const Key('chrono-template')),
      );
      expect(dd.onChanged, isNull);
    });

    testWidgets("connected, limits this app lacks: the controller's counts", (
      tester,
    ) async {
      await open(
        tester,
        () async => FieldInfo({
          'limits': {'id': 'my_field', 'name': 'My field'},
        }),
      );
      expect(find.byKey(const Key('chrono-limits-unknown')), findsOneWidget);
      expect(find.textContaining('My field'), findsOneWidget);
    });

    testWidgets('the controller cannot be reached: the preview stays', (
      tester,
    ) async {
      await open(tester, () async => throw const SocketException('down'));
      expect(find.byKey(const Key('chrono-limits-unknown')), findsNothing);
      expect(find.textContaining('veredicto'), findsOneWidget);
    });
  });

  testWidgets('the marshal home: no check-in, no marshal tools', (
    tester,
  ) async {
    await phone(tester);
    final h = harness();
    final records = MarshalRecords(h.store, h.settings);
    await tester.pumpWidget(h.app(home: MarshalHomeScreen(records: records)));
    await tester.pumpAndSettle();
    // No controller to ask (MR-2): the tools stay shut, whatever was typed.
    expect(find.textContaining('Primeiro faz o check-in'), findsOneWidget);
    expect(find.byKey(const Key('queue-go-checkin')), findsOneWidget);
    expect(find.byKey(const Key('marshal-chrono')), findsNothing);
    expect(find.byKey(const Key('marshal-tags')), findsNothing);
    expect(find.byKey(const Key('marshal-id')), findsNothing);
  });
}
