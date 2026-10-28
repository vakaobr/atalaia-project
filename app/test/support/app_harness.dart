// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The whole app for widget tests, with the phone replaced by fakes and
/// settings kept in memory.
library;

import 'dart:typed_data';

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/branding/field_branding.dart';
import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/controller/controller_host.dart';
import 'package:atalaia_app/controller/controller_isolate.dart';
import 'package:atalaia_app/controller/controller_shell.dart';
import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/modes/prop_mode_fetch.dart';
import 'package:atalaia_app/platform/links.dart';
import 'package:atalaia_app/platform/beacon_scan.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:atalaia_app/checkin/field_route.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';

import 'fakes.dart';

class Harness {
  Harness({
    required this.settings,
    required this.runner,
    this.feedConnect,
    FakeQr? qr,
    this.fieldHttp,
    this.caFetch,
    this.linkConnect,
    this.brandingSource,
    this.siteHttp,
    this.links,
    this.authBrowser,
    this.passkeys,
    this.share,
    this.picker,
    this.location,
    this.beacons,
    this.controllerLauncher,
    this.controllerAssets,
    this.routes,
    this.modeHttp,
  }) : qr = qr ?? FakeQr();

  /// The phone's location (none: not available).
  final LocationService? location;

  /// The phone's iBeacon scanner (none: not available).
  final BeaconScanService? beacons;

  /// The phone controller's isolate (slice S6); none: a [FakeControllerRun].
  final ControllerLauncher? controllerLauncher;
  final ControllerAssetsLoader? controllerAssets;

  /// The addresses' winners and failures (none: the app's own).
  final FieldRoutes? routes;

  /// The controller's mode packages for a joined prop (none: the real client).
  final Future<ModeHttp> Function(List<String> urls, Uint8List ca)? modeHttp;
  final wifi = FakeFieldWifi();
  final controllerRuns = <FakeControllerRun>[];
  final controllerBoots = <ControllerBoot>[];

  /// A fake site server (test/support/fake_site.dart); none: offline.
  final SiteHttp Function(Uri origin)? siteHttp;
  final AppLinks? links;
  final AuthBrowser? authBrowser;
  final PasskeyService? passkeys;
  final FileSharer? share;
  final FilePicker? picker;

  /// A fake field controller for check-in (test/support/fake_field.dart).
  final FieldHttp Function(PinnedField field)? fieldHttp;
  final CaFetcher? caFetch;
  final LinkConnect? linkConnect;

  /// A fake controller's branding endpoints (none: every request fails).
  final BrandingSourceFor? brandingSource;

  final AppSettings settings;
  final NodeRunner runner;
  final FeedConnect? feedConnect;
  final device = FakeDevice();
  final kiosk = FakeKiosk();
  final foreground = FakeForeground();
  final nfc = FakeNfc();
  final FakeQr qr;
  late final store = MemoryAppStore(settings);

  late final AppServices services = AppServices(
    runner: runner,
    device: device,
    kiosk: kiosk,
    foreground: foreground,
    nfc: nfc,
    qr: qr,
    store: store,
    feedConnect: feedConnect ?? _noFeed,
    consoleView: (context, url) =>
        Center(child: Text('console $url', key: const Key('console-view'))),
    fieldHttp: fieldHttp,
    routes: routes,
    modeHttp: modeHttp,
    caFetch: caFetch ?? _noCa,
    linkConnect: linkConnect,
    brandingSource: brandingSource ?? (_, _) => const _NoBranding(),
    siteHttp: siteHttp ?? (_) => const _NoSite(),
    links: links,
    authBrowser: authBrowser,
    passkeys: passkeys,
    share: share,
    picker: picker,
    location: location,
    beacons: beacons,
    wifi: wifi,
    controllerLauncher: controllerLauncher ?? _fakeLaunch,
    controllerAssets:
        controllerAssets ??
        (_) async => ControllerAssets(
          console: {
            'index.html': Uint8List.fromList(const [60]),
          },
          limitsYaml: 'x',
        ),
    controllerDir: '/controller',
  );

  Future<ControllerRun> _fakeLaunch(
    ControllerBoot boot, {
    PodTransport? pod,
  }) async {
    controllerBoots.add(boot);
    final run = FakeControllerRun(boot);
    controllerRuns.add(run);
    return run;
  }

  /// The app; a new harness is a new app (its own state), even when pumped
  /// over another one in the same test.
  Widget app({Widget? home}) => AtalaiaApp(
    key: ObjectKey(this),
    services: services,
    settings: settings,
    home: home,
  );
}

Future<FeedSocket> _noFeed(Uri uri) => Future.error(StateError('no network'));
Future<String> _noCa(Uri uri) => Future.error(StateError('no network'));

class _NoBranding implements BrandingSource {
  const _NoBranding();

  @override
  Future<BrandingResponse> get(String path, {String? ifNoneMatch}) =>
      Future.error(StateError('no network'));
}

class _NoSite implements SiteHttp {
  const _NoSite();

  @override
  Future<SiteResponse> send(
    String method,
    String path, {
    Object? body,
    String? bearer,
    String? refreshToken,
  }) => Future.error(SiteException(0, 'offline'));
}

Harness harness({
  AppLanguage language = AppLanguage.pt,
  NodeRunner? runner,
  FeedConnect? feedConnect,
  AppSettings? settings,
  FakeQr? qr,
  FieldHttp Function(PinnedField field)? fieldHttp,
  CaFetcher? caFetch,
  LinkConnect? linkConnect,
  BrandingSourceFor? brandingSource,
  SiteHttp Function(Uri origin)? siteHttp,
  AppLinks? links,
  AuthBrowser? authBrowser,
  PasskeyService? passkeys,
  FileSharer? share,
  FilePicker? picker,
  LocationService? location,
  BeaconScanService? beacons,
  ControllerLauncher? controllerLauncher,
  FieldRoutes? routes,
  Future<ModeHttp> Function(List<String> urls, Uint8List ca)? modeHttp,
}) => Harness(
  settings: (settings ?? AppSettings())..language = language,
  runner: runner ?? FakeNodeRunner(),
  feedConnect: feedConnect,
  qr: qr,
  fieldHttp: fieldHttp,
  caFetch: caFetch,
  linkConnect: linkConnect,
  brandingSource: brandingSource,
  siteHttp: siteHttp,
  links: links,
  authBrowser: authBrowser,
  passkeys: passkeys,
  share: share,
  picker: picker,
  location: location,
  beacons: beacons,
  controllerLauncher: controllerLauncher,
  routes: routes,
  modeHttp: modeHttp,
);
