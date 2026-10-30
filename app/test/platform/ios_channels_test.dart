// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The Dart sides of the platform channels that have a Swift twin on iOS
// (ios/Runner/QrScanPlugin.swift, LinkPlugin.swift, LocationPlugin.swift,
// BrowserPlugin.swift, PasskeyPlugin.swift, decisions iOS-13 to iOS-15, IOSL-1
// to IOSL-9): the contract both platforms keep (method
// names, arguments, results, errors), as the Swift code answers it, and what
// the app does when a channel is missing (the simulator has no camera; a
// phone without the plugin answers MissingPluginException). The Swift is
// not run here: these tests pin the contract it must meet.

import 'dart:async';

import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/platform/links.dart';
import 'package:atalaia_app/platform/location.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/site/site_auth.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

TestDefaultBinaryMessenger get messenger =>
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

class RecordedCalls {
  final log = <MethodCall>[];
}

RecordedCalls mockMethods(
  String name,
  Future<Object?> Function(MethodCall call) answer,
) {
  final calls = RecordedCalls();
  messenger.setMockMethodCallHandler(MethodChannel(name), (call) {
    calls.log.add(call);
    return answer(call);
  });
  addTearDown(
    () => messenger.setMockMethodCallHandler(MethodChannel(name), null),
  );
  return calls;
}

class _FakeLocation implements LocationService {
  @override
  Future<bool> available() async => true;
  @override
  Future<bool> granted() async => false;
  @override
  Stream<LocationFix> fixes(Duration interval) => const Stream.empty();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('QR scanner channel (org.atalaia.app/qr)', () {
    test('available and scan pass the texts and return the code', () async {
      final calls = mockMethods('org.atalaia.app/qr', (call) async {
        return switch (call.method) {
          'available' => true,
          'scan' => 'atalaia:join:ABC',
          _ => throw MissingPluginException(),
        };
      });
      final qr = ChannelQrScanner();
      expect(await qr.available, isTrue);
      expect(
        await qr.scan(hint: 'Point at the code', cancel: 'Cancel'),
        'atalaia:join:ABC',
      );
      expect(calls.log.last.method, 'scan');
      expect(calls.log.last.arguments, {
        'hint': 'Point at the code',
        'cancel': 'Cancel',
      });
    });

    test('cancel, a refused camera and no camera all read null', () async {
      // The Swift side answers null for each: no error to handle.
      mockMethods('org.atalaia.app/qr', (call) async => null);
      final qr = ChannelQrScanner();
      expect(await qr.scan(hint: 'h', cancel: 'c'), isNull);
      // "available" null (never sent by the Swift side) is not a camera.
      expect(await qr.available, isFalse);
    });

    test('no camera on the simulator: available is false', () async {
      mockMethods('org.atalaia.app/qr', (call) async => false);
      expect(await ChannelQrScanner().available, isFalse);
    });

    test('without the plugin: not available, nothing scanned', () async {
      final qr = ChannelQrScanner();
      expect(await qr.available, isFalse);
      expect(await qr.scan(hint: 'h', cancel: 'c'), isNull);
    });
  });

  group('links channel (org.atalaia.app/links)', () {
    test('the link that started the app is handed over once', () async {
      var first = true;
      mockMethods('org.atalaia.app/links', (call) async {
        if (call.method != 'initial') throw MissingPluginException();
        final r = first ? 'atalaia://register?site=https%3A%2F%2Fa.pt' : null;
        first = false;
        return r;
      });
      final links = ChannelAppLinks();
      expect(
        await links.initial(),
        'atalaia://register?site=https%3A%2F%2Fa.pt',
      );
      expect(await links.initial(), isNull);
    });

    test(
      'a link while the app runs arrives as "link"; others are ignored',
      () async {
        mockMethods('org.atalaia.app/links', (call) async => null);
        final links = ChannelAppLinks();
        final got = <String>[];
        final sub = links.links.listen(got.add);
        addTearDown(sub.cancel);
        Future<void> fromNative(Object? arguments) async {
          await messenger.handlePlatformMessage(
            'org.atalaia.app/links',
            const StandardMethodCodec().encodeMethodCall(
              MethodCall('link', arguments),
            ),
            (_) {},
          );
        }

        await fromNative('atalaia://register?field=campo');
        await fromNative(42);
        await fromNative(null);
        await Future<void>.delayed(Duration.zero);
        expect(got, ['atalaia://register?field=campo']);
      },
    );

    test('without the plugin: no initial link', () async {
      expect(await ChannelAppLinks().initial(), isNull);
    });
  });

  group('site login channels (BrowserPlugin.swift, PasskeyPlugin.swift)', () {
    test(
      'the browser opens an https address and says whether it did',
      () async {
        final calls = mockMethods('org.atalaia.app/browser', (call) async {
          return call.method == 'open' ? true : throw MissingPluginException();
        });
        final browser = ChannelAuthBrowser();
        expect(await browser.open(Uri.parse('https://club.example/x')), isTrue);
        expect(calls.log.single.arguments, {'url': 'https://club.example/x'});
        // Dart never sends anything but https: the Swift side would say false.
        expect(await browser.open(Uri.parse('http://club.example/x')), isFalse);
        expect(calls.log, hasLength(1));
      },
    );

    test('before iOS 17.4 the browser answers false: not available', () async {
      mockMethods('org.atalaia.app/browser', (call) async => false);
      expect(
        await ChannelAuthBrowser().open(Uri.parse('https://club.example/x')),
        isFalse,
      );
    });

    test('without the plugin: the browser is not available', () async {
      expect(
        await ChannelAuthBrowser().open(Uri.parse('https://club.example/x')),
        isFalse,
      );
    });

    test(
      'the callback the browser session ends on is read as a social login return',
      () {
        // What BrowserPlugin hands to LinkPlugin.deliver, which sends it as "link".
        final back = OidcReturn.parse(
          'https://club.example/app/oidc?s=AAAAAAAAAAAAAAAAAAAA#oidc=ticket123',
        );
        expect(back, isNotNull);
        expect(back!.site, Uri.parse('https://club.example'));
        expect(back.nonce, 'AAAAAAAAAAAAAAAAAAAA');
        expect(back.ticket, 'ticket123');
      },
    );

    test('passkeys: available, create and get pass the request JSON', () async {
      final calls = mockMethods('org.atalaia.app/passkeys', (call) async {
        return switch (call.method) {
          'available' => true,
          'create' => '{"id":"a","rawId":"a","type":"public-key"}',
          'get' => '{"id":"b","rawId":"b","type":"public-key"}',
          _ => throw MissingPluginException(),
        };
      });
      final passkeys = ChannelPasskeyService();
      expect(await passkeys.available(), isTrue);
      expect(await passkeys.create('{"challenge":"c"}'), contains('"a"'));
      expect(await passkeys.get('{"challenge":"d"}'), contains('"b"'));
      expect(calls.log[1].arguments, {'request': '{"challenge":"c"}'});
      expect(calls.log[2].arguments, {'request': '{"challenge":"d"}'});
    });

    test('passkeys: the Swift error codes become the reasons', () async {
      for (final code in ['cancelled', 'unsupported', 'failed']) {
        mockMethods(
          'org.atalaia.app/passkeys',
          (call) async => throw PlatformException(code: code),
        );
        await expectLater(
          ChannelPasskeyService().get('{}'),
          throwsA(
            isA<PasskeyException>().having((e) => e.reason, 'reason', code),
          ),
        );
      }
    });

    test('passkeys without the plugin are unsupported', () async {
      final passkeys = ChannelPasskeyService();
      expect(await passkeys.available(), isFalse);
      await expectLater(
        passkeys.create('{}'),
        throwsA(
          isA<PasskeyException>().having(
            (e) => e.reason,
            'reason',
            'unsupported',
          ),
        ),
      );
    });
  });

  group('location channels (org.atalaia.app/location)', () {
    test('available and granted are plain booleans', () async {
      var granted = false;
      mockMethods('org.atalaia.app/location', (call) async {
        return switch (call.method) {
          'available' => true,
          'granted' => granted,
          'enabled' => true,
          _ => throw MissingPluginException(),
        };
      });
      final loc = ChannelLocationService();
      expect(await loc.available(), isTrue);
      expect(await loc.granted(), isFalse);
      granted = true;
      expect(await loc.granted(), isTrue);
    });

    test('without the plugin: not available, not granted', () async {
      final loc = ChannelLocationService();
      expect(await loc.available(), isFalse);
      expect(await loc.granted(), isFalse);
    });

    test('fixes: the interval goes as interval_ms, a fix as the Swift side '
        'sends it', () async {
      Object? listenedWith;
      final channel = EventChannel('org.atalaia.app/location/fixes');
      messenger.setMockStreamHandler(
        channel,
        MockStreamHandler.inline(
          onListen: (arguments, sink) {
            listenedWith = arguments;
            // A full fix, then one with only what the phone knows (no
            // altitude, course or speed: the Swift side omits them).
            sink.success({
              'lat': 38.7223,
              'lon': -9.1393,
              'accuracy_m': 4.5,
              'altitude_m': 12.0,
              'heading_deg': 270.0,
              'speed_mps': 1.2,
              't': 1790000000000,
            });
            sink.success({
              'lat': 38.7224,
              'lon': -9.1394,
              'accuracy_m': 65,
              't': 1790000010000,
            });
          },
        ),
      );
      addTearDown(() => messenger.setMockStreamHandler(channel, null));
      final fixes = await ChannelLocationService()
          .fixes(const Duration(seconds: 10))
          .take(2)
          .toList();
      expect(listenedWith, {'interval_ms': 10000});
      expect(fixes[0].lat, 38.7223);
      expect(fixes[0].accuracyM, 4.5);
      expect(fixes[0].headingDeg, 270);
      expect(fixes[0].tMs, 1790000000000);
      expect(fixes[1].altitudeM, isNull);
      expect(fixes[1].headingDeg, isNull);
      expect(fixes[1].speedMps, isNull);
      expect(fixes[1].accuracyM, 65);
      // A fix with only what the phone knows is still a valid report.
      expect(
        fixes[1].toReport().keys,
        containsAll(['source', 'lat', 'lon', 't']),
      );
      expect(fixes[1].toReport().containsKey('speed_mps'), isFalse);
    });

    test('no permission: the stream fails with "unavailable"', () async {
      final channel = EventChannel('org.atalaia.app/location/fixes');
      messenger.setMockStreamHandler(
        channel,
        MockStreamHandler.inline(
          onListen: (arguments, sink) => sink.error(
            code: 'unavailable',
            message: 'no location permission',
          ),
        ),
      );
      addTearDown(() => messenger.setMockStreamHandler(channel, null));
      await expectLater(
        ChannelLocationService().fixes(const Duration(seconds: 5)),
        emitsError(
          isA<PlatformException>().having((e) => e.code, 'code', 'unavailable'),
        ),
      );
    });

    test('a map without a position is dropped, not a crash', () {
      expect(LocationFix.fromMap({'lat': 1.0}), isNull);
      expect(LocationFix.fromMap('nope'), isNull);
    });
  });

  group('the location permission goes through the device channel', () {
    test(
      'requestPermission names the Android permission and reads a bool',
      () async {
        final calls = mockMethods('org.atalaia.app/device', (call) async {
          return call.method == 'requestPermission' ? true : null;
        });
        expect(
          await ChannelDeviceServices().requestPermission(
            'ACCESS_FINE_LOCATION',
          ),
          isTrue,
        );
        expect(calls.log.single.arguments, {'name': 'ACCESS_FINE_LOCATION'});
      },
    );

    test('a permission iOS does not know reads as refused', () async {
      // The Swift side answers FlutterMethodNotImplemented for those.
      expect(
        await ChannelDeviceServices().requestPermission('POST_NOTIFICATIONS'),
        isFalse,
      );
    });
  });

  group(
    'the player screen says position sharing needs the app in front on iOS',
    () {
      PinnedField field() => PinnedField(
        fieldId: 'f1',
        fieldName: 'Campo',
        caPem: '',
        caSha256: Uint8List(32),
        urls: const ['https://10.0.0.1:8443'],
      );

      Future<Harness> open(WidgetTester tester) async {
        final feed = FieldFeed(
          FieldLink(Uri.parse('https://10.0.0.1:8443'), 'tok', field: field()),
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
        final h = harness(
          language: AppLanguage.en,
          settings: AppSettings(),
          location: _FakeLocation(),
        );
        await tester.pumpWidget(
          h.app(
            home: PlayerScreen(link: feed.link, feed: feed),
          ),
        );
        await tester.pump();
        return h;
      }

      testWidgets(
        'on iOS: the note, and the iOS way to allow it when refused',
        (tester) async {
          debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
          await open(tester);
          expect(
            find.byKey(const Key('player-share-ios-note')),
            findsOneWidget,
          );
          expect(
            find.textContaining('only while Atalaia is open'),
            findsOneWidget,
          );
          // The permission is refused (FakeDevice grants nothing): the message
          // points at iOS's Settings, not at Android's permission.
          await tester.tap(find.byKey(const Key('player-share-position')));
          for (var i = 0; i < 5; i++) {
            await tester.pump(const Duration(milliseconds: 10));
          }
          expect(
            find.textContaining('Settings > Atalaia > Location'),
            findsOneWidget,
          );
          debugDefaultTargetPlatformOverride = null;
          await tester.pumpWidget(const SizedBox());
        },
      );

      testWidgets('on Android: no note, the usual refusal', (tester) async {
        debugDefaultTargetPlatformOverride = TargetPlatform.android;
        await open(tester);
        expect(find.byKey(const Key('player-share-ios-note')), findsNothing);
        await tester.tap(find.byKey(const Key('player-share-position')));
        for (var i = 0; i < 5; i++) {
          await tester.pump(const Duration(milliseconds: 10));
        }
        expect(find.text('No permission for the location.'), findsOneWidget);
        debugDefaultTargetPlatformOverride = null;
        await tester.pumpWidget(const SizedBox());
      });
    },
  );
}
