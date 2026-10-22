// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The prop's screens with a node that does what the test says: setting up
// a game, the start behind the admin PIN, the mode's screen drawn from its
// template, team buttons held and let go, the keypad, tags, the admin
// controls and the back button, and the battery guide.

import 'dart:convert';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/prop/battery_guide.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_home.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/prop/prop_setup.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';

final catalog = ModeCatalog.builtin();

PropSetup setupFor(String id, String role, {int minutes = 0}) {
  final mode = catalog.compose(id);
  const teams = ['red', 'blue'];
  return PropSetup(
    mode: mode,
    role: role,
    teams: teams,
    params: mode.resolveParams(const {}, teams),
    durationMs: minutes * 60000,
  );
}

/// A dialog's main button (the screen behind may have one that says the same).
Finder inDialog(String text) => find.descendant(
  of: find.byType(AlertDialog),
  matching: find.widgetWithText(FilledButton, text),
);

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(400, 840);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

void main() {
  testWidgets('start, the mode screen, team buttons, admin end', (
    tester,
  ) async {
    await phone(tester);
    final runner = FakeNodeRunner();
    final h = harness(runner: runner, settings: AppSettings()..setPin('1234'));
    await tester.pumpWidget(
      h.app(
        home: PropGameScreen(
          setup: setupFor('org.atalaia.bomb', 'bomb', minutes: 10),
          modeName: 'Bomba',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(runner.spec!.chunkName, '@bomb/node.lua');
    expect(find.text('À espera do início'), findsOneWidget);

    // Start: the PIN, then the confirmation.
    await tester.tap(find.byKey(const Key('prop-start')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('pin-field')), '0000');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(find.text('PIN errado.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('pin-field')), '1234');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(inDialog('Começar'));
    await tester.pumpAndSettle();
    expect(runner.node.inputs.first.$1, 'game.start');
    expect(h.foreground.calls.first, startsWith('start Atalaia: Bomba'));
    expect(h.device.calls, contains('permission POST_NOTIFICATIONS'));

    // The mode draws its standby screen.
    runner.node.screen('standby', {'arm': 'red'});
    await tester.pump();
    expect(find.text('Hold to arm'), findsOneWidget);
    expect(find.text('RED'), findsOneWidget);

    // Hold the red button for a second.
    final g = await tester.startGesture(
      tester.getCenter(find.byKey(const Key('team-button-red'))),
    );
    await tester.pump(const Duration(milliseconds: 1000));
    await g.up();
    await tester.pump(const Duration(milliseconds: 100));
    final types = runner.node.inputs.map((i) => i.$1).toList();
    expect(types, contains('team_input.press'));
    expect(types.where((t) => t == 'team_input.hold').length, greaterThan(2));
    expect(types.last, 'team_input.release');

    // The clock counts down the 10 minutes from the node's game time.
    runner.node.timeMs = 60000;
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('9:00'), findsOneWidget);

    // A ring command lights the bar.
    runner.node.emit(
      NodeCommandOutput(
        NodeCommand(
          tMs: 0,
          target: 'ring',
          method: 'fill',
          argsJson: jsonEncode(['blue']),
        ),
      ),
    );
    await tester.pump();
    final light = tester.widget<AnimatedContainer>(
      find.byKey(const Key('prop-light')),
    );
    expect(
      (light.decoration! as BoxDecoration).color,
      AtalaiaColors.team('blue'),
    );

    // The admin ends the game.
    await tester.tap(find.byKey(const Key('prop-admin')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('pin-field')), '1234');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('admin-end')));
    await tester.pumpAndSettle();
    await tester.tap(inDialog('Terminar o jogo'));
    await tester.pumpAndSettle();
    expect(runner.node.inputs.last.$1, 'game.end');
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('Fim do jogo'), findsOneWidget);

    // Leaving needs the PIN too; then the node is closed.
    await tester.tap(find.byKey(const Key('prop-leave')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('pin-field')), '1234');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    expect(runner.node.closed, isTrue);
    expect(h.foreground.calls.last, 'stop');
  });

  testWidgets('the back button asks for the PIN', (tester) async {
    await phone(tester);
    final h = harness(settings: AppSettings()..setPin('1234'));
    await tester.pumpWidget(
      h.app(
        home: Builder(
          builder: (context) => FilledButton(
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => PropGameScreen(
                  setup: setupFor('org.atalaia.domination', 'zone'),
                ),
              ),
            ),
            child: const Text('go'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    final nav = tester.state<NavigatorState>(find.byType(Navigator));
    await nav.maybePop();
    await tester.pumpAndSettle();
    expect(find.text('PIN da organização'), findsOneWidget);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(find.byType(PropGameScreen), findsOneWidget);
  });

  testWidgets('a role that reads tags listens to NFC; the keypad sends keys', (
    tester,
  ) async {
    await phone(tester);
    final runner = FakeNodeRunner();
    final h = harness(runner: runner);
    await tester.pumpWidget(
      h.app(
        home: PropGameScreen(setup: setupFor('org.atalaia.respawn', 'respawn')),
      ),
    );
    await tester.pumpAndSettle();
    expect(h.nfc.calls, contains('start'));
    await tester.tap(find.byKey(const Key('prop-start')));
    await tester.pumpAndSettle();
    await tester.tap(inDialog('Começar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Encosta a etiqueta às costas do telemóvel.'),
      findsOneWidget,
    );
    h.nfc.tap(NfcReadFake.card(const [0xd0, 0, 0]));
    await tester.pump();
    final tag = runner.node.inputs.last;
    expect(tag.$1, 'nfc.tag');
    expect(tag.$2!['reason'], 'unsigned');

    final bomb = FakeNodeRunner();
    final h2 = harness(runner: bomb);
    await tester.pumpWidget(
      h2.app(home: PropGameScreen(setup: setupFor('org.atalaia.bomb', 'bomb'))),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('prop-start')));
    await tester.pumpAndSettle();
    await tester.tap(inDialog('Começar'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('prop-keypad')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('key-7')));
    await tester.pump();
    expect(bomb.node.inputs.last.$1, 'keypad.key');
    expect(bomb.node.inputs.last.$2, {'key': '7'});
  });

  testWidgets('a role that requires the keypad shows it from the start', (
    tester,
  ) async {
    await phone(tester);
    final runner = FakeNodeRunner();
    final h = harness(runner: runner);
    await tester.pumpWidget(
      h.app(
        home: PropGameScreen(
          setup: setupFor('org.atalaia.hacking_terminal', 'terminal'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('prop-start')));
    await tester.pumpAndSettle();
    await tester.tap(inDialog('Começar'));
    await tester.pumpAndSettle();
    // No tap on the keypad button: it is already shown (and can be hidden).
    await tester.tap(find.byKey(const Key('key-4')));
    await tester.pump();
    expect(runner.node.inputs.last.$1, 'keypad.key');
    expect(runner.node.inputs.last.$2, {'key': '4'});
    expect(find.text('Esconder o teclado'), findsOneWidget);
  });

  testWidgets('setting up: the mode, teams, the length, then the game', (
    tester,
  ) async {
    await phone(tester);
    final runner = FakeNodeRunner();
    final h = harness(runner: runner);
    await tester.pumpWidget(h.app(home: const PropSetupScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Domínio'), findsWidgets);
    await tester.tap(find.byKey(const Key('team-green')));
    await tester.pump();
    await tester.scrollUntilVisible(
      find.byKey(const Key('setup-duration')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.enterText(find.byKey(const Key('setup-duration')), '15');
    await tester.scrollUntilVisible(
      find.byKey(const Key('setup-go')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byKey(const Key('setup-go')));
    await tester.pumpAndSettle();
    expect(find.byType(PropGameScreen), findsOneWidget);
    expect(runner.spec!.teams, ['red', 'blue', 'green']);
    expect(runner.spec!.params['capture_hold_ms'], 3000);
  });

  testWidgets('a phone without NFC cannot be a respawn point on its own', (
    tester,
  ) async {
    await phone(tester);
    final h = harness();
    h.device.features_ = const DeviceFeatures();
    await tester.pumpWidget(h.app(home: const PropSetupScreen()));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('setup-mode')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Reentradas e Vidas').last);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('setup-missing')), findsOneWidget);
    expect(find.textContaining('NFC'), findsWidgets);
    await tester.scrollUntilVisible(
      find.byKey(const Key('setup-go')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    final go = tester.widget<FilledButton>(find.byKey(const Key('setup-go')));
    expect(go.onPressed, isNull);
  });

  testWidgets('the prop home asks for the battery exemption once', (
    tester,
  ) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const PropHomeScreen()));
    await tester.pumpAndSettle();
    expect(h.device.calls.where((c) => c == 'requestBattery').length, 1);
    expect(h.settings.batteryAsked, isTrue);
    expect(find.textContaining('otimização de bateria'), findsWidgets);
    await tester.pumpWidget(h.app(home: const SizedBox()));
    await tester.pumpWidget(h.app(home: const PropHomeScreen()));
    await tester.pumpAndSettle();
    expect(h.device.calls.where((c) => c == 'requestBattery').length, 1);
  });

  test('battery guides by maker', () {
    expect(batteryGuideFor('samsung'), 'samsung');
    expect(batteryGuideFor('Xiaomi'), 'xiaomi');
    expect(batteryGuideFor('POCO'), 'xiaomi');
    expect(batteryGuideFor('HONOR'), 'huawei');
    expect(batteryGuideFor('OnePlus'), 'oneplus');
    expect(batteryGuideFor('realme'), 'oneplus');
    expect(batteryGuideFor('Google'), 'generic');
  });

  testWidgets('the battery guide shows the steps for the phone\'s maker', (
    tester,
  ) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const BatteryGuideScreen()));
    await tester.pumpAndSettle();
    expect(find.text('Samsung'), findsOneWidget);
    await tester.tap(find.text('Pedir a isenção'));
    await tester.pumpAndSettle();
    expect(h.device.calls, contains('requestBattery'));
  });

  test('prop texts come from the language', () {
    expect(
      propTexts(const Strings(AppLanguage.en)).notificationLeft,
      '{time} left',
    );
    expect(
      propTexts(const Strings(AppLanguage.pt)).notificationLeft,
      'Faltam {time}',
    );
  });
}
