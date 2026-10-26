// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller on its own isolate (slice S6 of PE24, constraint 1;
// lib/controller/controller_isolate.dart): spawned with the real core, it
// serves the API and the console while this (the UI) isolate only reads its
// status; an I/O pod linked on this isolate is its radio through the relay;
// a stop ends the isolate and frees its ports; a start that cannot work
// says why.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_host.dart';
import 'package:atalaia_app/controller/controller_isolate.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/pod_host.dart';

final joinKey = Uint8List.fromList(List.generate(32, (i) => i));
final limits = File(
  'lib/chrono/limit_templates/portugal.yaml',
).readAsStringSync();

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('atalaia-iso-'));
  tearDown(() => tmp.deleteSync(recursive: true));

  ControllerBoot boot({bool pod = false, String? core}) => ControllerBoot(
    dir: '${tmp.path}/controller',
    joinKey: joinKey,
    limitsYaml: limits,
    console: {'index.html': Uint8List.fromList(utf8.encode('<!DOCTYPE html>'))},
    coreLibrary: core ?? coreLibraryPath(),
    pod: pod,
    httpPort: 0,
    httpsPort: 0,
    mqttPort: 0,
    openAddress: '127.0.0.1',
    addresses: const ['127.0.0.1'],
  );

  test(
    'it serves from its own isolate, then stops and frees its ports',
    () async {
      final run = await ControllerIsolate.spawn(boot());
      final st = run.status;
      expect(st.running, isTrue);
      expect(st.hasConsole, isTrue);
      expect(
        st.consoleUrl.toString(),
        'http://127.0.0.1:${st.httpPort}/console/',
      );
      expect(st.urls, ['https://127.0.0.1:${st.httpsPort}']);
      expect(st.caShort, hasLength(19));
      final c = HttpClient();
      addTearDown(c.close);
      final req = await c.getUrl(st.consoleUrl!);
      final res = await req.close();
      expect(res.statusCode, 200);
      expect(await utf8.decodeStream(res), '<!DOCTYPE html>');
      // A status a second.
      final next = await run.changes.first.timeout(const Duration(seconds: 3));
      expect(next.gmToken, st.gmToken);
      await run.stop();
      expect(
        await run.ended.timeout(
          const Duration(seconds: 1),
          onTimeout: () => null,
        ),
        isNull,
      );
      await expectLater(
        Socket.connect('127.0.0.1', st.httpPort!),
        throwsA(isA<SocketException>()),
      );
    },
  );

  test(
    'an I/O pod linked on the UI isolate is its radio',
    skip: hostSkip(['ATALAIA_POD_HOST']),
    () async {
      final hub = await AirHub.start();
      addTearDown(hub.close);
      final pod = await HostPod.start(airPeer: hub.port);
      addTearDown(pod.stop);
      hub.members.add(pod.airPort);
      final link = await SocketPodTransport.usb(pod);
      final run = await ControllerIsolate.spawn(boot(pod: true), pod: link);
      addTearDown(run.stop);
      expect(run.status.pod, isTrue);
      final up = await run.changes
          .firstWhere((s) => s.radio == 'up')
          .timeout(const Duration(seconds: 8));
      expect(up.radio, 'up');
    },
  );

  test('a start that cannot work says why', () async {
    await expectLater(
      ControllerIsolate.spawn(boot(core: '/nowhere/libatalaia_core.so')),
      throwsA(
        isA<ControllerStartException>().having(
          (e) => e.message,
          'message',
          contains('the core did not load'),
        ),
      ),
    );
  });
}
