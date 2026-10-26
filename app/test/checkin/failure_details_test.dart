// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The "details" line under "the field controller does not answer" (decision
// check-R5): in the four languages, from a scan whose addresses all refuse,
// from the live feed's closed state, and nothing for an answer that is not
// about reaching the controller.

import 'dart:io';

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/checkin/failure_details.dart';
import 'package:atalaia_app/checkin/field_route.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

const kinds = {
  AppLanguage.en: ('Details', 'connection refused'),
  AppLanguage.pt: ('Detalhes', 'ligação recusada'),
  AppLanguage.de: ('Details', 'Verbindung abgelehnt'),
  AppLanguage.zhTw: ('連線資訊', '連線被拒絕'),
};

void main() {
  for (final entry in kinds.entries) {
    testWidgets('a scan nobody answers shows why, in ${entry.key.name}', (
      tester,
    ) async {
      final field = FakeField()..urls.addAll(['https://192.168.1.158:8443']);
      final h = harness(
        language: entry.key,
        qr: FakeQr(field.posterText()),
        fieldHttp: field.http,
        caFetch: (u) async => throw const SocketException(
          'x',
          osError: OSError('Connection refused', 111),
        ),
      );
      await tester.pumpWidget(h.app(home: const CheckinScreen()));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('checkin-scan')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('checkin-error')), findsOneWidget);
      expect(find.byKey(const Key('failure-details')), findsOneWidget);
      expect(find.text(entry.value.$1), findsOneWidget);
      expect(
        find.textContaining('${entry.value.$2} · https://10.0.2.2:8443 · '),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          '${entry.value.$2} · https://192.168.1.158:8443 · ',
        ),
        findsOneWidget,
      );
    });
  }

  testWidgets('nothing is shown when no failure is kept, or an HTTP 4xx', (
    tester,
  ) async {
    final routes = FieldRoutes();
    final h = harness(routes: routes);
    await tester.pumpWidget(
      h.app(
        home: const Scaffold(body: FailureDetails(routeKey: 'campo')),
      ),
    );
    expect(find.byKey(const Key('failure-details')), findsNothing);

    routes.noteFailure(
      'campo',
      routes.failure(
        'https://a',
        RouteError(FailKind.http, 'HTTP 409', status: 409),
      ),
    );
    await tester.pumpWidget(
      h.app(
        home: const Scaffold(body: FailureDetails(routeKey: 'campo')),
      ),
    );
    expect(find.byKey(const Key('failure-details')), findsNothing);

    routes.noteFailure(
      'campo',
      routes.failure(
        'https://a',
        RouteError(FailKind.http, 'HTTP 502', status: 502),
      ),
    );
    await tester.pumpWidget(
      h.app(
        home: const Scaffold(body: FailureDetails(routeKey: 'campo')),
      ),
    );
    expect(find.textContaining('HTTP 502 · https://a · '), findsOneWidget);
  });

  testWidgets('the player view says why the feed is offline', (tester) async {
    final routes = FieldRoutes(stagger: const Duration(milliseconds: 10));
    final feed = FieldFeed(
      FieldLink.parse('10.0.0.1', 'code')!,
      connect: (uri) async => throw const SocketException(
        'x',
        osError: OSError('No route to host', 113),
      ),
      routes: routes,
    );
    addTearDown(feed.dispose);
    final h = harness(language: AppLanguage.en);
    await tester.runAsync(() async {
      await feed.start();
    });
    expect(feed.state, FeedState.closed);
    await tester.pumpWidget(
      h.app(
        home: Scaffold(body: PlayerView(feed: feed)),
      ),
    );
    await tester.pump();
    expect(find.text('Offline. Reconnecting…'), findsOneWidget);
    expect(
      find.textContaining('no route to the address · http://10.0.0.1:8080 · '),
      findsOneWidget,
    );
  });
}
