// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's root: the services every screen uses (the phone through the
/// Kotlin plugins, the node runner, storage, the mode catalogue), the
/// settings, the language and the theme.
library;

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/node_runner.dart';
import 'l10n/strings.dart';
import 'modes/mode_catalog.dart';
import 'platform/channels.dart';
import 'platform/services.dart';
import 'player/field_feed.dart';
import 'pod/pod_transports.dart';
import 'storage/app_store.dart';
import 'ui/home_screen.dart';
import 'ui/theme.dart';

/// Builds the GM console's web view (a test replaces it: no WebView there).
typedef ConsoleViewBuilder = Widget Function(BuildContext context, Uri url);

class AppServices {
  AppServices({
    required this.runner,
    required this.device,
    required this.kiosk,
    required this.foreground,
    required this.nfc,
    required this.qr,
    required this.store,
    ModeCatalog? modes,
    this.feedConnect = ioConnect,
    this.consoleView,
    this.usbPods,
    this.blePods,
  }) : modes = modes ?? ModeCatalog.builtin();

  /// The phone's own plugins, the core from the APK.
  factory AppServices.platform(AppStore store, DeviceServices device) =>
      AppServices(
        runner: createNodeRunner(),
        device: device,
        kiosk: ChannelKioskService(),
        foreground: ChannelForegroundService(),
        nfc: ChannelNfcService(),
        qr: ChannelQrScanner(),
        store: store,
        usbPods: ChannelPodTransport.usb,
        blePods: ChannelPodTransport.ble,
      );

  final NodeRunner runner;
  final DeviceServices device;
  final KioskService kiosk;
  final ForegroundService foreground;
  final NfcService nfc;
  final QrScanner qr;
  final AppStore store;
  final ModeCatalog modes;
  final FeedConnect feedConnect;
  final ConsoleViewBuilder? consoleView;
  final ChannelPodTransport? usbPods;
  final ChannelPodTransport? blePods;
}

/// The settings, saved whenever they change.
class AppController extends ChangeNotifier {
  AppController(this.services, this.settings);

  final AppServices services;
  final AppSettings settings;

  Strings get strings => Strings(settings.language);

  Future<void> update(void Function(AppSettings s) change) async {
    change(settings);
    notifyListeners();
    await services.store.saveSettings(settings);
  }
}

class AppScope extends InheritedNotifier<AppController> {
  const AppScope({
    required AppController controller,
    required super.child,
    super.key,
  }) : super(notifier: controller);

  static AppController of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;

  /// Without listening to changes (for callbacks).
  static AppController read(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppScope>()!.notifier!;
}

extension AppContext on BuildContext {
  AppController get app => AppScope.of(this);
  AppServices get services => AppScope.read(this).services;
}

class AtalaiaApp extends StatefulWidget {
  const AtalaiaApp({
    required this.services,
    required this.settings,
    this.home,
    super.key,
  });

  final AppServices services;
  final AppSettings settings;

  /// The first screen (the role selector unless a test says otherwise).
  final Widget? home;

  @override
  State<AtalaiaApp> createState() => _AtalaiaAppState();
}

class _AtalaiaAppState extends State<AtalaiaApp> {
  late final controller = AppController(widget.services, widget.settings);

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AppScope(
    controller: controller,
    child: ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final strings = controller.strings;
        return StringsScope(
          strings: strings,
          child: MaterialApp(
            title: 'Atalaia',
            debugShowCheckedModeBanner: false,
            theme: atalaiaTheme(Brightness.light),
            darkTheme: atalaiaTheme(Brightness.dark),
            themeMode: controller.settings.theme,
            locale: strings.language.locale,
            supportedLocales: [for (final l in AppLanguage.values) l.locale],
            localizationsDelegates: GlobalMaterialLocalizations.delegates,
            builder: (context, child) =>
                StringsScope(strings: strings, child: child!),
            home: widget.home ?? const HomeScreen(),
          ),
        );
      },
    ),
  );
}
