// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Buzzes with the app closed (decision APX-3, amending VB-9): while the
// player view is open on a live game, the Android foreground service runs
// with its ongoing notification (in the app's language); it stops when the
// game ends, the buzzes go off, the player is a spectator, or the view is
// left.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_de.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/l10n/strings_zh_tw.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

FieldFeed _feed(String state, {Map<String, Object?>? me}) {
  final feed = FieldFeed(
    FieldLink.parse('10.0.0.1', 'c')!,
    connect: (_) => Future.error(StateError('offline')),
    now: () => DateTime(2026, 10, 28, 15),
  );
  return feed
    ..state = FeedState.open
    ..onMessage({
      'type': 'hello',
      'game': {
        'id': 7,
        'name': 'G',
        'teams': ['red', 'blue'],
        'state': state,
        'duration_ms': 3600000,
        'game_time_ms': 1000,
        'live': true,
      },
      'events': <Object?>[],
      'me': ?me,
    });
}

Map<String, Object?> _game(String state) => {
  'type': 'game',
  'game': {
    'id': 7,
    'name': 'G',
    'teams': ['red', 'blue'],
    'state': state,
    'duration_ms': 3600000,
    'game_time_ms': 1000,
    'live': true,
  },
};

Future<Harness> _show(
  WidgetTester tester,
  FieldFeed feed, {
  AppSettings? settings,
  AppLanguage lang = AppLanguage.en,
}) async {
  tester.view.physicalSize = const Size(360, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  addTearDown(feed.dispose);
  final h = harness(language: lang, settings: settings);
  await tester.pumpWidget(
    h.app(
      home: PlayerScreen(link: feed.link, feed: feed),
    ),
  );
  await tester.pumpAndSettle();
  return h;
}

void main() {
  testWidgets('starts on a live game, stops when it ends', (tester) async {
    final feed = _feed('running');
    final h = await _show(tester, feed);
    expect(h.foreground.calls, [
      'start ${enStrings['player.buzz_title']} | '
          '${enStrings['player.buzz_text']}',
    ]);
    feed.onMessage(_game('paused'));
    await tester.pumpAndSettle();
    expect(h.foreground.calls, hasLength(1)); // still the same service
    feed.onMessage(_game('ended'));
    await tester.pumpAndSettle();
    expect(h.foreground.calls.last, 'stop');
    expect(h.foreground.calls, hasLength(2));
  });

  testWidgets('leaving the view stops it', (tester) async {
    final feed = _feed('running');
    final h = await _show(tester, feed);
    await tester.pumpWidget(const SizedBox());
    expect(h.foreground.calls.last, 'stop');
  });

  testWidgets('not with the buzzes off, nor for a spectator, nor ended', (
    tester,
  ) async {
    var h = await _show(
      tester,
      _feed('running'),
      settings: AppSettings()..vibrateOnEvents = false,
    );
    expect(h.foreground.calls, isEmpty);
    h = await _show(tester, _feed('ended'));
    expect(h.foreground.calls, isEmpty);
    h = await _show(tester, _feed('running', me: {'role': 'spectator'}));
    expect(h.foreground.calls, isEmpty);
  });

  test('the notification is in all four languages', () {
    for (final m in [enStrings, ptStrings, deStrings, zhTwStrings]) {
      expect(m['player.buzz_title'], isNotNull);
      expect(m['player.buzz_text'], isNotNull);
      expect(m['player.saved'], isNotNull);
      expect(m['player.saved_forget'], isNotNull);
    }
  });
}
