// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's root: the services every screen uses (the phone through the
/// Kotlin plugins, the node runner, storage, the mode catalogue), the
/// settings, the language and the theme.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'branding/field_branding.dart';
import 'checkin/checkin_client.dart';
import 'checkin/field_trust.dart';
import 'checkin/my_replicas.dart';
import 'controller/prop_link.dart';
import 'core/node_runner.dart';
import 'l10n/strings.dart';
import 'modes/mode_catalog.dart';
import 'platform/channels.dart';
import 'platform/location.dart';
import 'platform/services.dart';
import 'platform/links.dart';
import 'player/field_feed.dart';
import 'pod/pod_transports.dart';
import 'site/site_api.dart';
import 'site/site_client.dart';
import 'site/site_link.dart';
import 'site/site_screens.dart';
import 'storage/app_store.dart';
import 'ui/home_screen.dart';
import 'ui/theme.dart';

/// Builds the GM console's web view (a test replaces it: no WebView there).
typedef ConsoleViewBuilder = Widget Function(BuildContext context, Uri url);

/// Where a field's branding comes from: its addresses, over its pinned CA
/// when there is one (a check-in or a join payload), else plain HTTP(S).
typedef BrandingSourceFor =
    BrandingSource Function(List<String> urls, PinnedField? field);

BrandingSource ioBrandingSource(List<String> urls, PinnedField? field) =>
    IoBrandingSource(
      urls,
      field?.client() ??
          (HttpClient()..connectionTimeout = const Duration(seconds: 8)),
    );

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
    FieldHttp Function(PinnedField field)? fieldHttp,
    CaFetcher? caFetch,
    this.location,
    this.linkConnect,
    BrandingSourceFor? brandingSource,
    SiteHttp Function(Uri origin)? siteHttp,
    this.links,
  }) : modes = modes ?? ModeCatalog.builtin(),
       brandingSource = brandingSource ?? ioBrandingSource,
       branding = BrandingCache(store),
       fieldHttp = fieldHttp ?? IoFieldHttp.new,
       trust = FieldTrust(store, fetch: caFetch),
       checkins = CheckinStore(store),
       sites = SiteSessions(store, siteHttp ?? IoSiteHttp.new),
       tickets = TicketStore(store);

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
        location: ChannelLocationService(),
        links: ChannelAppLinks(),
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

  /// Field check-in (ADR-P3-13): the field controller's API over its pinned
  /// CA (tests give a fake controller), the pinned fields, the player's
  /// replicas and check-ins.
  final FieldHttp Function(PinnedField field) fieldHttp;
  final FieldTrust trust;
  final CheckinStore checkins;

  /// The phone's location, for position reports (null: not available).
  final LocationService? location;

  /// How a prop links to the controller over Wi-Fi (tests give a fake; null:
  /// wss:// with the CA the join payload names, prop_link.dart).
  final LinkConnect? linkConnect;

  /// Field and team branding (decisions BR1-BR24): what the app keeps per
  /// field, and how it asks a controller for it (tests give a fake).
  final BrandingCache branding;
  final BrandingSourceFor brandingSource;

  /// Online registration on a field's site server (decision S16-13): a
  /// session per site (tests give a fake server), the tickets kept, and the
  /// links that open the app at a field's games (null: none).
  final SiteSessions sites;
  final TicketStore tickets;
  final AppLinks? links;
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
  final _navigator = GlobalKey<NavigatorState>();
  StreamSubscription<String>? _links;

  @override
  void initState() {
    super.initState();
    final links = widget.services.links;
    if (links != null) {
      _links = links.links.listen(_open);
      unawaited(links.initial().then((l) => l == null ? null : _open(l)));
    }
  }

  /// A link to a field's games (`atalaia://register?...`): its screen on
  /// top of whatever is open; anything else is ignored.
  void _open(String text) {
    final link = SiteGameLink.parse(text);
    final nav = _navigator.currentState;
    if (link == null || nav == null) return;
    unawaited(
      nav.push(MaterialPageRoute<void>(builder: (_) => SiteScreen(link: link))),
    );
  }

  @override
  void dispose() {
    unawaited(_links?.cancel());
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
            navigatorKey: _navigator,
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
