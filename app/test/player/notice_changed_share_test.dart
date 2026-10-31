// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The position switch after the field's privacy notice moved on (decision
// NV-4): the app says which notice it showed, the controller refuses a stale
// one with 409 notice_version_changed, and the app shows the new text with
// "read and confirm" instead of a raw error. Nothing is shared, and nothing
// is recorded as a yes, until the player has confirmed the new notice.

import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../position/field_bounds_test.dart' show FakeLocation;
import '../support/app_harness.dart';

/// A controller whose notice is version 2.
class _Http implements FieldHttp {
  final puts = <Map<String, Object?>>[];
  final calls = <String>[];

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    calls.add('$method $path');
    switch ('$method $path') {
      case 'GET /checkin':
        return const FieldResponse(200, {
          'field': {'id': 'f1', 'name': 'Campo'},
          'notice': {'version': 2, 'en': 'NEW NOTICE TEXT', 'pt': 'x'},
        });
      case 'PUT /checkin/me/position-sharing':
        final b = (body! as Map).cast<String, Object?>();
        puts.add(b);
        if (b.containsKey('notice_version') && b['notice_version'] != 2) {
          return const FieldResponse(409, {
            'detail':
                'notice_version_changed: the privacy notice changed: read it '
                'again (GET /api/v1/checkin)',
          });
        }
        return const FieldResponse(200, {'position_share': true});
      case 'POST /positions':
        return const FieldResponse(200, {'stored': 1, 'interval_s': 10});
    }
    return const FieldResponse(404, null);
  }
}

void main() {
  Future<(Harness, _Http)> open(WidgetTester tester) async {
    tester.view.physicalSize = const Size(400, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final field = PinnedField(
      fieldId: 'f1',
      fieldName: 'Campo',
      caPem: '',
      caSha256: Uint8List(32),
      urls: const ['https://10.0.0.1:8443'],
    );
    final feed = FieldFeed(
      FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: field),
    );
    addTearDown(feed.dispose);
    feed.onMessage({
      'type': 'hello',
      'game': {
        'id': 1,
        'name': 'Domingo',
        'state': 'running',
        'teams': ['red', 'blue'],
      },
      'me': {'player_id': 'p1', 'role': 'player', 'team': 'red'},
    });
    final http = _Http();
    final h = harness(
      language: AppLanguage.en,
      settings: AppSettings()..noticeSeen = {'f1': 1},
      fieldHttp: (_) => http,
      location: FakeLocation(),
    );
    h.device.granted.add('ACCESS_FINE_LOCATION');
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pump();
    return (h, http);
  }

  testWidgets('a stale notice asks again, then records the yes', (
    tester,
  ) async {
    final (h, http) = await open(tester);
    await tester.tap(find.byKey(const Key('player-share-position')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    // The first try named the notice this phone had shown (1) and was refused.
    expect(http.puts.first, {'share_position': true, 'notice_version': 1});
    expect(find.byKey(const Key('player-notice-changed')), findsOneWidget);
    expect(find.text('NEW NOTICE TEXT'), findsOneWidget);
    expect(
      find.textContaining('The privacy notice changed. Read it and confirm'),
      findsOneWidget,
    );
    expect(find.textContaining('notice_version_changed'), findsNothing);
    expect(http.calls, isNot(contains('POST /positions')));
    expect(h.settings.noticeSeen, {'f1': 1}, reason: 'not yet confirmed');

    await tester.tap(find.byKey(const Key('player-notice-ok')));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(http.puts.last, {'share_position': true, 'notice_version': 2});
    expect(h.settings.noticeSeen, {'f1': 2});
    expect(find.byKey(const Key('player-notice-changed')), findsNothing);
  });

  testWidgets('declining the new notice leaves sharing off', (tester) async {
    final (h, http) = await open(tester);
    await tester.tap(find.byKey(const Key('player-share-position')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    await tester.tap(find.byKey(const Key('player-notice-cancel')));
    for (var i = 0; i < 5; i++) {
      await tester.pump(const Duration(milliseconds: 10));
    }
    expect(http.puts, hasLength(1), reason: 'only the refused try');
    expect(h.settings.noticeSeen, {'f1': 1});
    expect(http.calls, isNot(contains('POST /positions')));
  });
}
