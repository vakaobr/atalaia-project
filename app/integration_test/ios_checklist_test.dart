// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The automatable part of the iPhone checklist (docs/ios-on-a-mac.md, "What
// to try on the iPhone", items 1 to 11), for a real iPhone or the iOS
// simulator:
//
//   flutter test integration_test/ios_checklist_test.dart -d <udid> \
//     --dart-define=ATALAIA_TEST_CONTROLLER=http://192.168.1.183:8080 \
//     --dart-define=ATALAIA_TEST_READ_TOKEN=<read token> \
//     --dart-define=ATALAIA_TEST_GM_TOKEN=<GM token>
//
// The three defines are optional: a test that needs one is skipped, with
// its reason, when it is missing. Everything else needs nothing from the
// network but the phone's own loopback address.
//
// It also runs on an Android emulator (CI's flutter-integration job: where a
// check is about iOS only it is skipped, with the reason) and on the
// development machine, where the app pretends to be an iPhone
// (debugDefaultTargetPlatformOverride) and what needs a device is skipped.
// It checks without golden images: layout overflows are caught as they are
// reported (FlutterError.onError) and the texts are the app's own tables.
//
// What is left to the human on the iPhone (checklist 4, the look of the
// Chinese text, a buzz's feel, the lock screen, switching apps, the Wi-Fi's
// "no internet" and the Local Network prompt) is in the document.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_identity.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/controller/field_tls.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/platform/platform_check.dart';
import 'package:atalaia_app/player/field_buzz.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:atalaia_app/version.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'support.dart';

/// A field controller to follow (http://host:8080) and its read token; the
/// GM token for the marshal list. Empty: not given.
const _controller = String.fromEnvironment('ATALAIA_TEST_CONTROLLER');
const _readToken = String.fromEnvironment('ATALAIA_TEST_READ_TOKEN');
const _gmToken = String.fromEnvironment('ATALAIA_TEST_GM_TOKEN');

/// The game to check in to, when the controller has several open (default:
/// the first one the controller lists).
const _gameId = String.fromEnvironment('ATALAIA_TEST_GAME');

const _noController = 'ATALAIA_TEST_CONTROLLER is not given';
const _noRead =
    'ATALAIA_TEST_CONTROLLER and ATALAIA_TEST_READ_TOKEN are not both given';
const _noGm =
    'ATALAIA_TEST_CONTROLLER and ATALAIA_TEST_GM_TOKEN are not both given';

String? _needs(bool ok, String reason) => ok ? null : reason;

/// flutter_test's skip takes no reason, so a test that cannot run says why
/// and ends: the run shows it as skipped, with the reason in its output.
bool _skipped(String? reason) {
  if (reason == null) return false;
  markTestSkipped(reason);
  return true;
}

/// The checks about what iOS lacks run on iOS and on the host (which plays
/// an iPhone); Android has those features, and CI's emulator has no camera
/// or location to refuse with.
String? get _androidHasIt =>
    onAndroidDevice ? 'Android has this feature; the check is for iOS' : null;

/// A real web view exists on a phone only.
String? get _needsDevice => onHost ? 'needs a device web view' : null;

/// A throwaway CA, made at run time like check_in_test.dart's (a fixed PEM
/// would expire, and iOS refuses long-lived server certificates). The checks
/// here use plain http, so it only has to be a valid certificate.
String? _caPem;
String _testCaPem() {
  if (_caPem != null) return _caPem!;
  final dir = Directory.systemTemp.createTempSync('atalaia-test-tls-');
  try {
    return _caPem = FieldTls.ensure(
      dir.path,
      certificateNames(const []),
      fieldName: 'Atalaia on-device test (not a real field)',
    ).caPem;
  } finally {
    dir.deleteSync(recursive: true);
  }
}

Strings _s(AppLanguage l) => Strings(l);

/// A folder of this run's own inside the app's private folder (the test is
/// the installed app: its own settings.json must not be touched).
Future<Directory> _scratch(String name) async {
  final base = await ChannelDeviceServices().filesDir();
  final root = base == null
      ? await Directory.systemTemp.createTemp('atalaia-itest-')
      : Directory('$base/itest-$name-${DateTime.now().millisecondsSinceEpoch}');
  await root.create(recursive: true);
  addTearDown(() async {
    if (await root.exists()) await root.delete(recursive: true);
  });
  return root;
}

/// A vibration service that records instead of buzzing, for the haptics
/// checks. Everything else is the phone's own device channel.
class _RecordingDevice extends ChannelDeviceServices {
  final vibrations = <List<int>>[];

  @override
  Future<void> vibrate(List<int> pattern) async =>
      vibrations.add(List.of(pattern));
}

/// A stand-in field controller's stream on the loopback address: a hello
/// (with [events] as its snapshot), then whatever the test sends.
class _StandInStream {
  _StandInStream._(this._server);

  final HttpServer _server;
  final _socket = Completer<WebSocket>();

  int get port => _server.port;

  static Future<_StandInStream> start({
    List<Map<String, Object?>> snapshot = const [],
    String gameState = 'running',
  }) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final stream = _StandInStream._(server);
    server.listen((req) async {
      if (!WebSocketTransformer.isUpgradeRequest(req)) {
        req.response.statusCode = 404;
        await req.response.close();
        return;
      }
      final ws = await WebSocketTransformer.upgrade(req);
      ws.add(
        jsonEncode({
          'type': 'hello',
          'game': {
            'id': 7,
            'name': 'Stand-in game',
            'teams': ['red', 'blue'],
            'state': gameState,
            'duration_ms': 3600000,
            'game_time_ms': 1000,
            'live': true,
          },
          'events': snapshot,
        }),
      );
      if (!stream._socket.isCompleted) stream._socket.complete(ws);
    });
    addTearDown(() async {
      final ws = stream._socket.isCompleted
          ? await stream._socket.future
          : null;
      await ws?.close();
      await server.close(force: true);
    });
    return stream;
  }

  Future<WebSocket> connected(WidgetTester tester) async {
    await waitUntil(
      tester,
      () => _socket.isCompleted,
      reason: 'the app to open the stream',
    );
    return _socket.future;
  }
}

Map<String, Object?> _live(
  String type, {
  String? team,
  Map<String, Object?> data = const {},
}) => {
  'type': 'event',
  'game': 7,
  'event': {'node': 1, 't': 9000, 'type': type, 'team': ?team, 'data': data},
};

/// A tiny HTTP stand-in for a controller's console page.
Future<HttpServer> _consoleServer(List<String> hits) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  server.listen((req) async {
    hits.add('${req.method} ${req.uri.path}');
    req.response
      ..headers.contentType = ContentType.html
      ..write(
        '<!doctype html><html><head><title>Atalaia test console</title>'
        '<meta name="viewport" content="width=device-width"></head>'
        '<body><h1>console</h1></body></html>',
      );
    await req.response.close();
  });
  addTearDown(() => server.close(force: true));
  return server;
}

/// One call to the controller's API: status and JSON body.
Future<(int, Object?)> _api(
  HttpClient http,
  String method,
  String path, {
  String? token,
  Object? body,
}) async {
  final req = await http.openUrl(method, Uri.parse('$_controller$path'));
  req.headers.set('Accept', 'application/json');
  if (token != null) req.headers.set('Authorization', 'Bearer $token');
  if (body != null) {
    req.headers.contentType = ContentType.json;
    req.add(utf8.encode(jsonEncode(body)));
  }
  final res = await req.close().timeout(const Duration(seconds: 15));
  final text = await utf8.decodeStream(res);
  try {
    return (res.statusCode, text.isEmpty ? null : jsonDecode(text));
  } on FormatException {
    return (res.statusCode, text);
  }
}

/// A test player checked in at the controller, with what the app keeps of a
/// check-in. [leave] takes it out again.
class _TestPlayer {
  _TestPlayer(this.checkin, this.field, this.http);

  final FieldCheckin checkin;
  final PinnedField field;
  final CheckinClient http;

  String get playerId => checkin.playerId;

  /// What the app has after a check-in: the field trusted, the check-in kept.
  Future<AppStore> store(AppSettings settings) async {
    final store = MemoryAppStore(settings);
    await store.saveList('trusted_fields', [field.toJson()]);
    await store.saveList('checkins', [checkin.toJson()]);
    return store;
  }

  Future<void> leave() async {
    try {
      await http.leave(checkin.token);
    } on Object {
      // a refused token (the GM changed the role): ask for a new one
      try {
        checkin.update(await http.refresh(checkin.token));
        await http.leave(checkin.token);
      } on Object {
        // best effort: the controller erases it after the game
      }
    }
  }
}

/// Checks a new test player in at the controller through the app's own
/// client (the controller's field is trusted by address, not by a CA: the
/// address is plain http, so no certificate is involved). Null, with the
/// reason, when the controller has no game open for check-in.
Future<(_TestPlayer?, String?)> _checkIn() async {
  final probe = PinnedField(
    fieldId: 'probe',
    fieldName: 'probe',
    caPem: _testCaPem(),
    caSha256: Uint8List(32),
    urls: [_controller.replaceAll(RegExp(r'/+$'), '')],
  );
  final client = CheckinClient(IoFieldHttp(probe));
  final info = await client.info();
  final games = info.games;
  if (games.isEmpty) return (null, 'the controller has no game open');
  final game = _gameId.isEmpty
      ? games.first
      : games.firstWhere(
          (g) => '${g['game_id']}' == _gameId,
          orElse: () => games.first,
        );
  final field = PinnedField(
    fieldId: info.fieldId,
    fieldName: info.fieldName,
    caPem: _testCaPem(),
    caSha256: Uint8List(32),
    urls: probe.urls,
  );
  final id = FieldIdentity(info.fieldId, newPlayerId(), newPlayerSecret());
  final api = CheckinClient(IoFieldHttp(field));
  final ticket = await api.checkIn(
    gameId: game['game_id']! as int,
    playerId: id.playerId,
    secret: id.secret,
    displayName: 'itest-ios',
    noticeVersion: info.noticeVersion,
  );
  final c = FieldCheckin(
    fieldId: info.fieldId,
    gameId: ticket.gameId,
    gameName: '${game['name'] ?? ''}',
    playerId: ticket.playerId,
    token: '',
    exp: 0,
    status: 'pending',
    role: 'player',
  )..update(ticket);
  return (_TestPlayer(c, field, api), null);
}

/// A test of this file: on the host the app plays an iPhone (the roles, the
/// missing plugins and the texts are then the iOS ones, which is what the
/// checks assert); on a device it is what it is.
void itest(
  String name,
  Future<void> Function(WidgetTester tester) body, {
  Timeout? timeout,
}) => testWidgets(name, (tester) async {
  if (onHost) debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
  try {
    await body(tester);
  } finally {
    debugDefaultTargetPlatformOverride = null;
  }
}, timeout: timeout);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // --- 1: the start language, and the four languages ------------------------

  itest('1. the app starts in Portuguese, the default language', (
    tester,
  ) async {
    await tester.pumpWidget(deviceApp());
    await waitFor(tester, find.byKey(const Key('role-player')));
    final pt = _s(AppLanguage.pt);
    expect(find.text(pt.t('home.choose')), findsOneWidget);
    expect(find.text('O que vais fazer neste telemóvel?'), findsOneWidget);
    expect(find.text(pt.t('role.player')), findsOneWidget);
    expect(find.text('Participante'), findsOneWidget);
  });

  itest(
    '1. each language shows its own texts on the main screens, no overflow',
    (tester) async {
      // The small iPhone (SE: 320 x 568 points) is the narrowest to fit.
      tester.view.physicalSize = const Size(640, 1136);
      tester.view.devicePixelRatio = 2;
      addTearDown(tester.view.reset);
      // The titles of Settings, as written, so that a wrong table shows.
      const settingsTitle = {
        AppLanguage.pt: 'Definições',
        AppLanguage.en: 'Settings',
        AppLanguage.de: 'Einstellungen',
        AppLanguage.zhTw: '設定',
      };

      final overflows = await collectOverflows(() async {
        await tester.pumpWidget(deviceApp());
        await waitFor(tester, find.byKey(const Key('role-player')));
        await tester.tap(find.byKey(const Key('open-settings')));
        await tester.pumpAndSettle();

        // Pt, en, de, zh-tw, and back to pt: every change from Settings.
        for (final l in [...AppLanguage.values, AppLanguage.pt]) {
          final s = _s(l);
          await tapVisible(tester, find.byKey(Key('language-${l.code}')));
          await tester.pumpAndSettle();
          expect(find.text(settingsTitle[l]!), findsWidgets, reason: l.code);
          expect(find.text(s.t('settings.title')), findsWidgets);
          // (the list scrolls: a small screen builds only what is near)
          await reveal(tester, find.text(s.t('settings.language')));
          expect(
            find.text(s.t('settings.language')),
            findsOneWidget,
            reason: l.code,
          );
          await reveal(tester, find.text(s.t('settings.vibrate')));
          expect(
            find.text(s.t('settings.vibrate')),
            findsOneWidget,
            reason: l.code,
          );
          // Settings' own list, to its end (the About block).
          await reveal(tester, find.text(s.t('settings.licence')));

          await goBack(tester);
          await tester.pumpAndSettle();
          for (final key in [
            'home.choose',
            'role.player',
            'role.marshal',
            'role.gm',
          ]) {
            await reveal(tester, find.text(s.t(key)));
            expect(
              find.text(s.t(key)),
              findsOneWidget,
              reason: '${l.code} $key',
            );
          }

          // The other main screens, in this language.
          for (final (key, title) in [
            ('role-player', s.t('role.player')),
            ('role-marshal', s.t('role.marshal')),
            ('role-gm', s.t('role.gm')),
          ]) {
            await tapVisible(tester, find.byKey(Key(key)));
            await pass(tester, const Duration(milliseconds: 600));
            if (key == 'role-player') {
              await reveal(tester, find.text(s.t('player.connect')));
              expect(find.text(s.t('player.connect')), findsOneWidget);
            }
            if (key == 'role-gm') {
              await reveal(tester, find.text(s.t('gm.open')));
              expect(find.text(s.t('gm.open')), findsOneWidget);
            }
            expect(find.text(title), findsWidgets, reason: '${l.code} $key');
            await goBack(tester);
            await tester.pumpAndSettle();
          }
          await tester.tap(find.byKey(const Key('open-settings')));
          await tester.pumpAndSettle();
        }
      });
      expect(overflows, isEmpty, reason: 'layout overflows: $overflows');
      expect(tester.takeException(), isNull);
    },
  );

  // --- 2: the roles -----------------------------------------------------------

  itest('2. the roles: player, marshal and GM on iOS; no prop, no '
      'field controller', (tester) async {
    await tester.pumpWidget(deviceApp());
    await waitFor(tester, find.byKey(const Key('role-player')));
    // The list builds only what is on screen, and a small phone shows the
    // first roles only: scroll to each.
    await reveal(tester, find.byKey(const Key('role-marshal')));
    expect(find.byKey(const Key('role-marshal')), findsOneWidget);
    await reveal(tester, find.byKey(const Key('role-gm')));
    expect(find.byKey(const Key('role-gm')), findsOneWidget);
    final note = find.textContaining('só o Android');
    if (isIOS) {
      expect(find.byKey(const Key('role-prop')), findsNothing);
      expect(find.byKey(const Key('role-controller')), findsNothing);
      expect(find.text('Dispositivo de jogo'), findsNothing);
      expect(find.text('Controlador de campo'), findsNothing);
      expect(note, findsOneWidget);
    } else {
      // Android (CI's emulator) keeps both, and has no such note.
      await reveal(tester, find.byKey(const Key('role-prop')));
      expect(find.byKey(const Key('role-prop')), findsOneWidget);
      await reveal(tester, find.byKey(const Key('role-controller')));
      expect(find.byKey(const Key('role-controller')), findsOneWidget);
      expect(note, findsNothing);
    }
  });

  // --- 3: settings across a restart ------------------------------------------

  itest('3. the settings are written in the app\'s private folder and '
      'survive a restart', (tester) async {
    final private = await ChannelDeviceServices().filesDir();
    if (onIosDevice || onAndroidDevice) {
      // The one native piece written for iOS: a real folder of the app's own.
      expect(private, isNotNull, reason: 'the device channel gave no folder');
      expect(Directory(private!).existsSync(), isTrue);
      expect(private, startsWith('/'));
      debugPrint('private folder: $private');
    }
    final dir = await _scratch('settings');
    final key = List.filled(8, 'a1b2c3d4').join();

    // First run: the settings change through the real screens, and are saved.
    final store1 = FileAppStore(dir.path);
    final settings1 = await store1.loadSettings();
    expect(settings1.language, AppLanguage.pt, reason: 'fresh folder');
    await tester.pumpWidget(deviceApp(settings: settings1, store: store1));
    await waitFor(tester, find.byKey(const Key('role-player')));
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('language-en')));
    await tester.pumpAndSettle();
    await tapVisible(tester, find.byKey(const Key('vibrate-on-events')));
    await tester.pumpAndSettle();
    await AppScope.read(
      tester.element(find.byType(SettingsScreen)),
    ).update((x) => x.joinKeyHex = key);
    await tester.pumpAndSettle();
    final file = File('${dir.path}/settings.json');
    expect(file.existsSync(), isTrue, reason: 'settings.json in the folder');
    final saved = jsonDecode(file.readAsStringSync()) as Map;
    expect(saved['language'], 'en');
    expect(saved['vibrate_on_events'], isFalse);
    expect(saved['join_key'], key);

    // "Close the app": the whole widget tree goes. Open it again from the
    // same folder, as main() does.
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpAndSettle();
    final store2 = FileAppStore(dir.path);
    final settings2 = await store2.loadSettings();
    expect(settings2.language, AppLanguage.en);
    expect(settings2.vibrateOnEvents, isFalse);
    expect(settings2.joinKeyHex, key);
    await tester.pumpWidget(deviceApp(settings: settings2, store: store2));
    await waitFor(tester, find.text('What will this phone do?'));
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    final en = _s(AppLanguage.en);
    final chip = tester.widget<ChoiceChip>(
      find.byKey(const Key('language-en')),
    );
    expect(chip.selected, isTrue);
    await reveal(tester, find.byKey(const Key('vibrate-on-events')));
    expect(
      tester
          .widget<SwitchListTile>(find.byKey(const Key('vibrate-on-events')))
          .value,
      isFalse,
    );
    await reveal(tester, find.byKey(const Key('join-key')));
    expect(
      find.text(en.t('settings.join_key_set', {'end': key.substring(56)})),
      findsOneWidget,
    );
  });

  // --- 4 (the one the app can state): the version ---------------------------

  itest('3. About shows the version in lib/version.dart', (tester) async {
    await tester.pumpWidget(deviceApp());
    await waitFor(tester, find.byKey(const Key('open-settings')));
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    final pt = _s(AppLanguage.pt);
    await reveal(
      tester,
      find.text(pt.t('settings.version', {'version': appVersion})),
    );
    expect(find.text('Atalaia $appVersion'), findsOneWidget);
    if (onIosDevice) {
      // No core is built for iOS: the About block says so.
      await reveal(tester, find.text(pt.t('settings.no_core')));
    }
  });

  // --- 5, 7: the player joins a real controller ------------------------------

  itest(
    '5/7. a player joins the controller and the feed shows the game and moves',
    (tester) async {
      if (_skipped(
        _needs(_controller.isNotEmpty && _readToken.isNotEmpty, _noRead),
      )) {
        return;
      }
      // The feed shows a game only when the controller has one: say so
      // rather than wait for a game that is not there.
      final http = HttpClient();
      addTearDown(() => http.close(force: true));
      final (status, body) = await _api(
        http,
        'GET',
        '/api/v1/controller',
        token: _readToken,
      );
      if (status == 200 && body is Map && body['live_game'] == null) {
        markTestSkipped(
          'no game running on the controller (start one, or pass '
          'ATALAIA_TEST_GAME)',
        );
        return;
      }
      await tester.pumpWidget(deviceApp());
      await waitFor(tester, find.byKey(const Key('role-player')));
      await tapVisible(tester, find.byKey(const Key('role-player')));
      await waitFor(tester, find.byKey(const Key('player-connect')));
      await tester.enterText(
        find.byKey(const Key('player-address')),
        _controller,
      );
      await tester.enterText(find.byKey(const Key('player-code')), _readToken);
      await tester.pumpAndSettle();
      await tapVisible(tester, find.byKey(const Key('player-connect')));

      // The Local Network prompt may stand in the way on the first run: the
      // 30 s give a person time to answer Allow.
      await waitFor(tester, find.byKey(const Key('player-game')));
      final feed = tester.widget<PlayerView>(find.byType(PlayerView)).feed;
      expect(feed.state, FeedState.open);
      expect(feed.game?['name'], isNotNull);
      expect(
        find.text('${feed.game!['name']}'),
        findsWidgets,
        reason: 'the game is named on screen',
      );
      final teams = feed.teams;
      for (final t in teams) {
        await reveal(tester, find.byKey(Key('player-team-$t')));
        expect(find.byKey(Key('player-team-$t')), findsOneWidget);
      }
      debugPrint(
        'game "${feed.game!['name']}" ${feed.gameState}, '
        'score ${feed.totals}, ${feed.events.length} events',
      );

      // Something moves within about 20 s: the boxes report every 15 s
      // (SL-*), and each report is a score, node or event message. Only a
      // running game does so.
      if (feed.gameState == 'running') {
        var updates = 0;
        void count() => updates++;
        feed.addListener(count);
        addTearDown(() => feed.removeListener(count));
        await waitUntil(
          tester,
          () => updates > 0,
          reason: 'an update of the feed within 20 s',
          timeout: const Duration(seconds: 20),
        );
        expect(feed.state, FeedState.open);
        expect(find.byKey(const Key('player-clock')), findsOneWidget);
      } else {
        debugPrint(
          'the game is ${feed.gameState}, not running: the update within '
          '20 s is not checked',
        );
      }
      await tester.pumpWidget(const SizedBox.shrink());
    },
    timeout: const Timeout(Duration(minutes: 3)),
  );

  // --- 6: QR ---------------------------------------------------------------------

  itest(
    '6. with no camera (the simulator), scanning is offered as unavailable, '
    'typing stays, no crash',
    (tester) async {
      if (_skipped(_androidHasIt)) {
        return;
      }
      if (await ChannelQrScanner().available) {
        // A phone with a camera (iOS-13): the scanner itself is a person's
        // check (point it at a join card or the field's poster).
        markTestSkipped('this phone has a camera: scan a real code by hand');
        return;
      }
      await tester.pumpWidget(deviceApp());
      await waitFor(tester, find.byKey(const Key('role-player')));
      await tapVisible(tester, find.byKey(const Key('role-player')));
      await waitFor(tester, find.byKey(const Key('player-scan')));
      await tapVisible(tester, find.byKey(const Key('player-scan')));
      await tester.pumpAndSettle();
      expect(
        find.text(_s(AppLanguage.pt).t('join.no_camera')),
        findsOneWidget,
        reason: 'the app says there is no scanner',
      );
      // The typed way is still on the screen.
      expect(find.byKey(const Key('player-address')), findsOneWidget);
      expect(find.byKey(const Key('player-connect')), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  // --- 8: position sharing ------------------------------------------------------

  itest('8. sharing the position: the switch, the iOS note, and sharing '
      'when the phone already allows it', (tester) async {
    if (_skipped(_androidHasIt)) {
      return;
    }
    // iOS-16: positions while the app is in front. A test cannot answer the
    // system's permission prompt, so sharing is only turned on when the phone
    // already allows it (`xcrun simctl privacy booted grant location
    // org.atalaia.app` in the simulator); otherwise refused cleanly.
    final location = ChannelLocationService();
    final allowed = await location.available() && await location.granted();
    final feed =
        FieldFeed(
            FieldLink.parse('127.0.0.1:1', 'x')!,
            connect: (_) => Future.error(StateError('stand-in feed')),
          )
          ..state = FeedState.open
          ..onMessage({
            'type': 'hello',
            'game': {
              'id': 7,
              'name': 'Stand-in game',
              'teams': ['red', 'blue'],
              'state': 'running',
              'duration_ms': 3600000,
              'game_time_ms': 1000,
              'live': true,
            },
          });
    addTearDown(feed.dispose);
    // A check-in's link (a pinned field) is what offers the switch.
    final link = FieldLink(
      Uri.parse('http://127.0.0.1:1'),
      'x',
      field: PinnedField(
        fieldId: 'itest',
        fieldName: 'itest',
        caPem: _testCaPem(),
        caSha256: Uint8List(32),
        urls: const ['http://127.0.0.1:1'],
      ),
    );
    await tester.pumpWidget(
      deviceApp(
        home: PlayerScreen(link: link, feed: feed),
      ),
    );
    await tester.pumpAndSettle();
    final share = find.byKey(const Key('player-share-position'));
    await reveal(tester, share);
    expect(
      find.byKey(const Key('player-share-ios-note')),
      findsOneWidget,
      reason: 'iOS says it shares only while the app is in front',
    );
    if (!allowed) {
      markTestSkipped(
        'location not allowed for the app yet: the prompt is a person\'s '
        'check (or grant it with simctl and run again)',
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      return;
    }
    await tester.tap(share);
    await tester.pumpAndSettle();
    expect(
      tester.widget<SwitchListTile>(share).value,
      isTrue,
      reason: 'sharing started',
    );
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  // --- 9: marshal validation ---------------------------------------------------

  itest(
    '9. a player who is not on the GM\'s marshal list is refused',
    (tester) async {
      if (_skipped(_needs(_controller.isNotEmpty, _noController))) {
        return;
      }
      final (player, why) = await _checkIn();
      if (player == null) {
        markTestSkipped(why!);
        return;
      }
      addTearDown(player.leave);
      final settings = AppSettings();
      await tester.pumpWidget(
        deviceApp(settings: settings, store: await player.store(settings)),
      );
      await waitFor(tester, find.byKey(const Key('role-marshal')));
      await tapVisible(tester, find.byKey(const Key('role-marshal')));
      final pt = _s(AppLanguage.pt);
      await waitFor(tester, find.text(pt.t('marshal.not_listed')));
      expect(find.byKey(const Key('marshal-status')), findsOneWidget);
      expect(
        find.byKey(const Key('marshal-chrono')),
        findsNothing,
        reason: 'the tools stay closed',
      );
      expect(settings.marshalValidation, isNull);
      expect(settings.marshalId, isEmpty);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    timeout: const Timeout(Duration(minutes: 2)),
  );

  itest(
    '9. a player the GM lists is accepted, and refused again once removed',
    (tester) async {
      if (_skipped(
        _needs(_controller.isNotEmpty && _gmToken.isNotEmpty, _noGm),
      )) {
        return;
      }
      final (player, why) = await _checkIn();
      if (player == null) {
        markTestSkipped(why!);
        return;
      }
      final http = HttpClient();
      addTearDown(() => http.close(force: true));
      String? marshalId;
      // However the test ends: off the list, and out of the game.
      addTearDown(() async {
        if (marshalId != null) {
          await _api(
            http,
            'DELETE',
            '/api/v1/marshals/$marshalId',
            token: _gmToken,
          );
        }
        await player.leave();
      });

      final (status, body) = await _api(
        http,
        'POST',
        '/api/v1/marshals',
        token: _gmToken,
        body: {'player_id': player.playerId, 'name': 'itest-ios'},
      );
      expect(status, anyOf(200, 201), reason: 'GM token refused? $body');
      marshalId = (body! as Map)['marshal_id'] as String;

      final settings = AppSettings();
      await tester.pumpWidget(
        deviceApp(settings: settings, store: await player.store(settings)),
      );
      await waitFor(tester, find.byKey(const Key('role-marshal')));
      await tapVisible(tester, find.byKey(const Key('role-marshal')));
      // The token was made before the GM's list: the app asks for a new one.
      await waitFor(
        tester,
        find.byKey(const Key('marshal-chrono')),
        timeout: const Duration(seconds: 60),
      );
      expect(find.byKey(const Key('marshal-status')), findsNothing);
      expect(settings.marshalId, marshalId, reason: 'the id is the list\'s');
      expect(settings.marshalValidation, isNotNull);

      // Off the list: the next ask refuses, and keeps nothing.
      final (gone, _) = await _api(
        http,
        'DELETE',
        '/api/v1/marshals/$marshalId',
        token: _gmToken,
      );
      expect(gone, anyOf(200, 204));
      marshalId = null;
      await goBack(tester);
      await tester.pumpAndSettle();
      await tapVisible(tester, find.byKey(const Key('role-marshal')));
      final pt = _s(AppLanguage.pt);
      await waitFor(tester, find.text(pt.t('marshal.revoked', {'n': 0})));
      expect(find.byKey(const Key('marshal-chrono')), findsNothing);
      expect(settings.marshalValidation, isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
    timeout: const Timeout(Duration(minutes: 3)),
  );

  // --- 10: the GM console in the web view ---------------------------------------

  itest(
    '10. the GM screen opens an address in the web view and the page loads',
    (tester) async {
      if (_skipped(_androidHasIt ?? _needsDevice)) {
        return;
      }
      final hits = <String>[];
      final server = await _consoleServer(hits);
      await _openConsole(tester, '127.0.0.1:${server.port}');
      await _expectTitle(tester, 'Atalaia test console');
      expect(hits, contains('GET /console/'));
      await tester.pumpWidget(const SizedBox.shrink());
    },
    timeout: const Timeout(Duration(minutes: 2)),
  );

  itest(
    '10. the controller\'s own console loads in the web view',
    (tester) async {
      if (_skipped(
        _androidHasIt ??
            _needsDevice ??
            _needs(_controller.isNotEmpty, _noController),
      )) {
        return;
      }
      await _openConsole(tester, _controller);
      // The console's page is titled "Atalaia", and asks for a code itself.
      await _expectTitle(tester, 'Atalaia');
      await tester.pumpWidget(const SizedBox.shrink());
    },
    timeout: const Timeout(Duration(minutes: 2)),
  );

  // --- 11: the haptics ----------------------------------------------------------

  itest('11. the phone buzzes on the key events of a live feed, and only '
      'those', (tester) async {
    // The stream's snapshot holds a GM message from before: no buzz for it.
    final stream = await _StandInStream.start(
      snapshot: [
        {
          'node': 1,
          't': 500,
          'type': 'gm.message',
          'data': {'text': 'before you came'},
        },
      ],
    );
    final device = _RecordingDevice();
    final settings = AppSettings()..myTeam = 'red';
    await tester.pumpWidget(
      deviceApp(
        settings: settings,
        device: device,
        home: PlayerScreen(
          link: FieldLink.parse('127.0.0.1:${stream.port}', 't')!,
        ),
      ),
    );
    final ws = await stream.connected(tester);
    await waitFor(tester, find.byKey(const Key('player-game')));
    await pass(tester, const Duration(milliseconds: 500));
    expect(
      device.vibrations,
      isEmpty,
      reason: 'the snapshot is what happened before: no buzz',
    );

    // One live event at a time, past the rate-limit window (1 s).
    Future<void> send(
      Map<String, Object?> message,
      Buzz? expected, {
      String? reason,
    }) async {
      final before = device.vibrations.length;
      ws.add(jsonEncode(message));
      await pass(tester, const Duration(milliseconds: 1300));
      final played = device.vibrations.skip(before).toList();
      expect(
        played,
        expected == null ? isEmpty : [expected.pattern],
        reason: reason,
      );
    }

    await send(_live('game.start'), Buzz.gameStart, reason: 'game start');
    await send(
      _live('gm.message', data: {'text': 'hello'}),
      Buzz.gmMessage,
      reason: 'a GM message',
    );
    await send(
      _live('zone.captured', team: 'red'),
      Buzz.captured,
      reason: 'a box of my team captured',
    );
    await send(
      _live('zone.captured', team: 'blue', data: {'previous_team': 'red'}),
      Buzz.lost,
      reason: 'a box of my team taken',
    );
    await send(
      _live('zone.captured', team: 'blue'),
      null,
      reason: 'a box of the others taken from nobody',
    );
    await send(_live('game.end'), Buzz.gameEnd, reason: 'game end');

    // The switch in Settings: off, nothing buzzes.
    settings.vibrateOnEvents = false;
    await send(
      _live('gm.message', data: {'text': 'quiet'}),
      null,
      reason: 'the setting is off',
    );
    expect(device.vibrations, hasLength(5));
    await tester.pumpWidget(const SizedBox.shrink());
  });
}

/// Home, the GM role, [address] typed, the console opened: the web view is on
/// screen.
Future<void> _openConsole(WidgetTester tester, String address) async {
  await tester.pumpWidget(deviceApp());
  await waitFor(tester, find.byKey(const Key('role-gm')));
  await tapVisible(tester, find.byKey(const Key('role-gm')));
  await waitFor(tester, find.byKey(const Key('gm-url')));
  // The prefilled address is cleared with the field's own clear button (or
  // is empty at first): then it is typed.
  await tester.enterText(find.byKey(const Key('gm-url')), address);
  await tester.pumpAndSettle();
  await tapVisible(tester, find.byKey(const Key('gm-open')));
  await waitFor(tester, find.byType(WebViewWidget));
}

/// Waits until the web view's page has a title containing [title].
Future<void> _expectTitle(WidgetTester tester, String title) async {
  final web = tester.widget<WebViewWidget>(find.byType(WebViewWidget));
  String? seen;
  await waitUntil(
    tester,
    () {
      unawaited(
        web.platform.params.controller.getTitle().then(
          (t) => seen = t,
          onError: (_) {},
        ),
      );
      return seen != null && seen!.contains(title);
    },
    reason: 'the web view to load a page titled "$title" (last: $seen)',
    timeout: const Duration(seconds: 30),
  );
}
