// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Stand-ins for the phone (the Kotlin plugins) and for a running node, for
/// widget tests and view-model tests.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/platform/services.dart';

class FakeDevice implements DeviceServices {
  FakeDevice({
    this.features_ = const DeviceFeatures(
      nfc: true,
      nfcEnabled: true,
      camera: true,
      vibrator: true,
    ),
    this.maker = 'samsung',
    this.dir,
  });

  DeviceFeatures features_;
  final String maker;
  final String? dir;
  final calls = <String>[];
  bool batteryExempt = false;
  final granted = <String>{};

  @override
  Future<String?> filesDir() async => dir;

  @override
  Future<String> manufacturer() async => maker;

  @override
  Future<DeviceFeatures> features() async => features_;

  @override
  Future<void> vibrate(List<int> pattern) async =>
      calls.add('vibrate $pattern');

  @override
  Future<void> tone(DeviceTone tone, int ms) async =>
      calls.add('tone ${tone.name} $ms');

  @override
  Future<void> keepScreenOn(bool on) async => calls.add('keepScreenOn $on');

  @override
  Future<void> setBrightness(double? level) async =>
      calls.add('brightness $level');

  @override
  Future<bool> ignoringBatteryOptimizations() async => batteryExempt;

  @override
  Future<void> requestIgnoreBatteryOptimizations() async =>
      calls.add('requestBattery');

  @override
  Future<void> openBatterySettings() async => calls.add('batterySettings');

  @override
  Future<bool> requestPermission(String name) async {
    calls.add('permission $name');
    return granted.contains(name);
  }
}

class FakeKiosk implements KioskService {
  bool active = false;
  bool owner = false;
  final calls = <String>[];

  @override
  Future<bool> start() async {
    calls.add('start');
    active = true;
    return true;
  }

  @override
  Future<void> stop() async {
    calls.add('stop');
    active = false;
  }

  @override
  Future<bool> isActive() async => active;

  @override
  Future<bool> isDeviceOwner() async => owner;
}

class FakeForeground implements ForegroundService {
  final calls = <String>[];

  @override
  Future<bool> start({required String title, required String text}) async {
    calls.add('start $title | $text');
    return true;
  }

  @override
  Future<void> update({required String title, required String text}) async =>
      calls.add('update $title | $text');

  @override
  Future<void> stop() async => calls.add('stop');
}

class FakeNfc implements NfcService {
  NfcState current = NfcState.ready;
  final _reads = StreamController<NfcRead>.broadcast();
  final calls = <String>[];
  final written = <Uint8List>[];
  Completer<Uint8List>? _write;

  void tap(NfcRead read) => _reads.add(read);

  /// Completes a pending write as if a tag with [uid] were held to the phone.
  void tapToWrite(Uint8List uid) {
    final w = _write;
    _write = null;
    w?.complete(uid);
  }

  @override
  Future<NfcState> state() async => current;

  @override
  Stream<NfcRead> get reads => _reads.stream;

  @override
  Future<void> startReading() async => calls.add('start');

  @override
  Future<void> stopReading() async => calls.add('stop');

  @override
  Future<Uint8List> writeNext(Uint8List ndefMessage) {
    written.add(ndefMessage);
    _write = Completer<Uint8List>();
    return _write!.future;
  }

  @override
  Future<void> cancelWrite() async {
    final w = _write;
    _write = null;
    w?.completeError(NfcWriteException('cancelled'));
  }
}

class FakeQr implements QrScanner {
  FakeQr([this.next]);
  String? next;
  final hints = <String>[];

  @override
  Future<bool> get available async => true;

  @override
  Future<String?> scan({required String hint, required String cancel}) async {
    hints.add(hint);
    return next;
  }
}

/// A node that only does what the test tells it: [emit] sends outputs,
/// inputs are recorded and accepted.
class FakeRunningNode implements RunningNode {
  final _outputs = StreamController<NodeOutput>.broadcast(sync: true);
  final inputs = <(String, Map<String, Object?>?)>[];
  NodeStatus status = NodeStatus.running;
  bool paused = false;
  int timeMs = 0;
  Map<String, int> scoreMap = const {'red': 0, 'blue': 0};
  bool closed = false;

  @override
  bool loaded = true;

  @override
  final List<NodeOutput> startupOutputs = [];

  void emit(NodeOutput o) => _outputs.add(o);

  void screen(String name, [Map<String, Object?> data = const {}]) => emit(
    NodeCommandOutput(
      NodeCommand(
        tMs: timeMs,
        target: 'ui',
        method: 'screen',
        argsJson: jsonEncode([name, data]),
      ),
    ),
  );

  @override
  Stream<NodeOutput> get outputs => _outputs.stream;

  @override
  Future<bool> input(String type, [Map<String, Object?>? data]) async {
    inputs.add((type, data));
    if (type == 'game.end') status = NodeStatus.ended;
    if (type == 'game.pause') paused = true;
    if (type == 'game.resume') paused = false;
    return true;
  }

  @override
  Future<void> advanceTo(int ms) async => timeMs = ms;

  @override
  Future<NodeSnapshot> snapshot() async => NodeSnapshot(
    status: status,
    paused: paused,
    timeMs: timeMs,
    memUsed: 1000,
    lastError: '',
    scores: scoreMap,
  );

  @override
  Future<void> close() async => closed = true;
}

class FakeNodeRunner implements NodeRunner {
  FakeNodeRunner([FakeRunningNode? node]) : node = node ?? FakeRunningNode();

  final FakeRunningNode node;
  NodeSpec? spec;

  @override
  bool get supported => true;

  @override
  String? get coreVersion => '0.0.0-test';

  @override
  Future<RunningNode> start(
    NodeSpec spec, {
    GameClock clock = GameClock.realTime,
  }) async {
    this.spec = spec;
    return node;
  }
}

/// Tags as the NFC plugin reports them.
abstract final class NfcReadFake {
  /// A tag holding the NDEF message [ndef].
  static NfcRead card(List<int> ndef, [List<int> uid = const [4, 1, 2, 3]]) =>
      NfcRead(uid: Uint8List.fromList(uid), ndef: Uint8List.fromList(ndef));
}
