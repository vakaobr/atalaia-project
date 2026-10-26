// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The check-in form's layout on a narrow phone with large text, in every
// language: a field's helper text is shown whole (not cut to one line with an
// ellipsis) and never drawn over the next field's floating label, and nothing
// overflows. Found on an iPhone: the name hint was truncated and overlapped
// the "preferred team" label below it.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';
import '../support/fonts.dart';

void main() {
  // Real fonts: the test font's glyphs are as wide as they are tall, which
  // would wrap every text far more than a phone does.
  setUpAll(loadAppFonts);

  for (final lang in AppLanguage.values) {
    for (final scale in [1.0, 1.3]) {
      testWidgets('form at 360 dp, text x$scale, ${lang.name}', (tester) async {
        tester.view.physicalSize = const Size(360, 2400);
        tester.view.devicePixelRatio = 1;
        tester.platformDispatcher.textScaleFactorTestValue = scale;
        addTearDown(tester.view.reset);
        addTearDown(tester.platformDispatcher.clearAllTestValues);
        final errors = <FlutterErrorDetails>[];
        final previous = FlutterError.onError;
        FlutterError.onError = errors.add;

        final field = FakeField()..federation = 'required';
        final h = harness(
          language: lang,
          qr: FakeQr(field.posterText()),
          fieldHttp: field.http,
          caFetch: field.fetchCa,
        );
        await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('player-checkin')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('checkin-scan')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('checkin-notice-ok')));
        await tester.pumpAndSettle();

        // Text in the fields makes their labels float, as in the report.
        await tester.enterText(find.byKey(const Key('checkin-name')), 'Falcao');
        await tester.enterText(
          find.byKey(const Key('checkin-federation')),
          '1',
        );
        await tester.pumpAndSettle();

        // Back to the test's own handler before asserting: a failed expect
        // is reported through it.
        FlutterError.onError = previous;

        final s = Strings(lang);
        String labelOf(String key) => switch (key) {
          'checkin-name' => s.t('checkin.name'),
          'checkin-federation' => s.t('checkin.federation_required', {
            'label': 'FPA',
          }),
          _ => s.t('checkin.team_pref'),
        };
        const order = ['checkin-name', 'checkin-federation', 'checkin-team'];
        final helpers = {
          'checkin-name': s.t('checkin.name_hint'),
          'checkin-federation': s.t('checkin.federation_hint'),
        };

        for (var i = 0; i < helpers.length; i++) {
          final key = order[i];
          final helper = find.descendant(
            of: find.byKey(Key(key)),
            matching: find.text(helpers[key]!),
          );
          expect(helper, findsOneWidget, reason: '$key helper');
          final paragraph = tester.renderObject<RenderParagraph>(helper);
          expect(
            paragraph.didExceedMaxLines,
            isFalse,
            reason: '$key helper cut',
          );
          final next = find.descendant(
            of: find.byKey(Key(order[i + 1])),
            matching: find.text(labelOf(order[i + 1])),
          );
          expect(next, findsWidgets, reason: '${order[i + 1]} label');
          final a = tester.getRect(helper);
          final b = tester.getRect(next.first);
          expect(
            a.overlaps(b),
            isFalse,
            reason: '$key helper $a over ${order[i + 1]} label $b',
          );
        }
        expect(errors, isEmpty, reason: errors.join('\n'));
      });
    }
  }
}
