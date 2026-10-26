// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The address fields (the GM console's, the player's controller, the site's):
// a clear button that keeps the focus, and on iOS the first focus selecting
// the whole prefilled address, so typing replaces it (a tap in a URL there
// puts the cursor at the word's edge).

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/gm_screen.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

const _url = 'http://192.168.4.1:8080/console/';

EditableTextState _editable(WidgetTester tester, String key) =>
    tester.state<EditableTextState>(
      find.descendant(
        of: find.byKey(Key(key)),
        matching: find.byType(EditableText),
      ),
    );

TextSelection _selection(WidgetTester tester, String key) =>
    _editable(tester, key).widget.controller.selection;

bool _focused(WidgetTester tester, String key) =>
    _editable(tester, key).widget.focusNode.hasFocus;

void _phone(WidgetTester tester) {
  tester.view.physicalSize = const Size(420, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

/// One prefilled address field on its screen.
class _Case {
  const _Case(this.name, this.key, this.screen);
  final String name;
  final String key;
  final Widget screen;
  String get clearKey => '$key-clear';
}

AppSettings _settings() => AppSettings()
  ..consoleUrl = _url
  ..controllerUrl = 'http://192.168.4.1:8080';

void main() {
  final cases = [
    const _Case('GM console', 'gm-url', GmScreen()),
    const _Case('player', 'player-address', PlayerStartScreen()),
  ];

  for (final c in cases) {
    group('${c.name} address', () {
      testWidgets('the clear button empties it and keeps the focus', (
        tester,
      ) async {
        _phone(tester);
        final h = harness(settings: _settings());
        await tester.pumpWidget(h.app(home: c.screen));
        await tester.pumpAndSettle();
        expect(find.byKey(Key(c.clearKey)), findsOneWidget);
        await tester.tap(find.byKey(Key(c.clearKey)));
        await tester.pump();
        expect(_editable(tester, c.key).widget.controller.text, '');
        expect(_focused(tester, c.key), isTrue);
        // Nothing to clear: no button.
        expect(find.byKey(Key(c.clearKey)), findsNothing);
        // Typing goes on in the same field, and the button comes back.
        await tester.enterText(find.byKey(Key(c.key)), '10.0.0.5');
        await tester.pump();
        expect(find.byKey(Key(c.clearKey)), findsOneWidget);
      });

      testWidgets('the clear button has a label, in each language', (
        tester,
      ) async {
        _phone(tester);
        for (final (lang, label) in [
          (AppLanguage.pt, 'Apagar o texto'),
          (AppLanguage.en, 'Clear the text'),
          (AppLanguage.de, 'Text löschen'),
          (AppLanguage.zhTw, '清除文字'),
        ]) {
          final h = harness(language: lang, settings: _settings());
          await tester.pumpWidget(h.app(home: c.screen));
          await tester.pumpAndSettle();
          expect(find.byTooltip(label), findsOneWidget, reason: '$lang');
          await tester.pumpWidget(const SizedBox());
        }
      });

      testWidgets('on iOS the first focus selects all, the second tap does '
          'not', (tester) async {
        debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
        _phone(tester);
        final h = harness(settings: _settings());
        await tester.pumpWidget(h.app(home: c.screen));
        await tester.pumpAndSettle();
        final text = _editable(tester, c.key).widget.controller.text;
        expect(text, isNotEmpty);
        await tester.tap(find.byKey(Key(c.key)));
        await tester.pumpAndSettle();
        expect(
          _selection(tester, c.key),
          TextSelection(baseOffset: 0, extentOffset: text.length),
        );
        // The person moves the cursor (a tap inside a selection keeps it on
        // iOS); a later tap then places it, and selects nothing.
        _editable(tester, c.key).widget.controller.selection =
            const TextSelection.collapsed(offset: 3);
        await tester.pump();
        final box = tester.getRect(find.byKey(Key(c.key)));
        await tester.tapAt(Offset(box.left + 40, box.center.dy));
        await tester.pumpAndSettle();
        expect(_selection(tester, c.key).isCollapsed, isTrue);
        // Leaving the field and coming back does not select all again.
        FocusManager.instance.primaryFocus!.unfocus();
        await tester.pump();
        await tester.tapAt(Offset(box.left + 40, box.center.dy));
        await tester.pumpAndSettle();
        expect(_focused(tester, c.key), isTrue);
        expect(_selection(tester, c.key).isCollapsed, isTrue);
        debugDefaultTargetPlatformOverride = null;
      });

      testWidgets('on Android a tap just places the cursor', (tester) async {
        debugDefaultTargetPlatformOverride = TargetPlatform.android;
        _phone(tester);
        final h = harness(settings: _settings());
        await tester.pumpWidget(h.app(home: c.screen));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(Key(c.key)));
        await tester.pumpAndSettle();
        expect(_focused(tester, c.key), isTrue);
        expect(_selection(tester, c.key).isCollapsed, isTrue);
        debugDefaultTargetPlatformOverride = null;
      });
    });
  }

  group('site address', () {
    testWidgets('the clear button empties it and keeps the focus', (
      tester,
    ) async {
      _phone(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const SiteScreen()));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('site-address-clear')), findsNothing);
      await tester.enterText(
        find.byKey(const Key('site-address')),
        'http://campo.example.pt/f/campo',
      );
      await tester.pump();
      await tester.tap(find.byKey(const Key('site-address-clear')));
      await tester.pump();
      expect(_editable(tester, 'site-address').widget.controller.text, '');
      expect(_focused(tester, 'site-address'), isTrue);
      expect(find.byKey(const Key('site-address-clear')), findsNothing);
    });

    testWidgets('on iOS a field with text, focused for the first time, '
        'selects all; the second tap does not', (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      _phone(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const SiteScreen()));
      await tester.pumpAndSettle();
      // The screen starts empty: put an address in without focusing the
      // field, as a screen that comes back to its address step would have it.
      _editable(tester, 'site-address').widget.controller.text =
          'https://campo.example.pt/f/campo';
      await tester.pump();
      await tester.tap(find.byKey(const Key('site-address')));
      await tester.pumpAndSettle();
      expect(
        _selection(tester, 'site-address'),
        const TextSelection(baseOffset: 0, extentOffset: 32),
      );
      _editable(tester, 'site-address').widget.controller.selection =
          const TextSelection.collapsed(offset: 3);
      await tester.pump();
      final box = tester.getRect(find.byKey(const Key('site-address')));
      await tester.tapAt(Offset(box.left + 40, box.center.dy));
      await tester.pumpAndSettle();
      expect(_selection(tester, 'site-address').isCollapsed, isTrue);
      debugDefaultTargetPlatformOverride = null;
    });
  });
}
