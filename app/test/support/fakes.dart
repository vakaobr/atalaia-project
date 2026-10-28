// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Stand-ins for the phone (the Kotlin plugins) and for a running node, for
/// widget tests and view-model tests.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_host.dart';
import 'package:atalaia_app/controller/controller_isolate.dart';
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
  Future<bool> start({
    required String title,
    required String text,
    bool location = false,
  }) async {
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

/// The share sheet: records what it was given.
class FakeSharer implements FileSharer {
  FakeSharer({this.isAvailable = true, this.opens = true});
  final bool isAvailable;
  final bool opens;
  final shared = <List<SharedFile>>[];

  @override
  Future<bool> get available async => isAvailable;

  @override
  Future<bool> sharePng(List<SharedFile> files, {String title = ''}) async {
    shared.add(files);
    return opens;
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

/// The field's Wi-Fi (FieldWifiPlugin.kt) for the controller's screen.
class FakeFieldWifi implements FieldWifiService {
  FieldWifiInfo current = const FieldWifiInfo(
    available: true,
    wifiEnabled: true,
    ssid: 'Campo',
    hotspot: HotspotState.off,
  );
  LocalHotspot next = const LocalHotspot(
    ssid: 'AndroidShare_1234',
    passphrase: 'abc;def',
  );
  final calls = <String>[];

  @override
  Future<FieldWifiInfo> info() async => current;

  @override
  Future<bool> openHotspotSettings() async {
    calls.add('hotspotSettings');
    return true;
  }

  @override
  Future<bool> openWifiSettings() async {
    calls.add('wifiSettings');
    return true;
  }

  @override
  Future<LocalHotspot> startLocalHotspot() async {
    calls.add('startLocal');
    return next;
  }

  @override
  Future<void> stopLocalHotspot() async => calls.add('stopLocal');
}

/// A phone controller that runs nowhere: its status is what a test says.
class FakeControllerRun implements ControllerRun {
  FakeControllerRun(this.boot)
    : _status = ControllerStatus({
        'running': true,
        'open': boot.open,
        'http_port': 8080,
        'https_port': boot.open ? 8443 : null,
        'mqtt_port': 1883,
        'addresses': boot.open ? ['192.168.43.1'] : <String>[],
        'urls': boot.open ? ['https://192.168.43.1:8443'] : <String>[],
        'ca_sha256': 'ab' * 32,
        'ca_short': 'ABAB ABAB ABAB ABAB',
        'gm_token': 'gm-secret-token',
        'read_token': 'rd-read-token',
        'radio': boot.pod ? 'up' : 'none',
        'pod': boot.pod,
        'game': null,
        'stream_clients': 1,
        'mqtt_clients': 0,
        'props': 0,
        'console': boot.console.isNotEmpty,
      });

  final ControllerBoot boot;
  ControllerStatus _status;
  final _changes = StreamController<ControllerStatus>.broadcast();
  final _ended = Completer<String?>();
  bool stopped = false;

  /// A new status, as the controller's isolate sends one.
  void emit(Map<String, Object?> changes) {
    _status = ControllerStatus({..._status.raw, ...changes});
    _changes.add(_status);
  }

  /// The isolate ending by itself.
  void crash(String why) {
    if (!_ended.isCompleted) _ended.complete(why);
  }

  @override
  ControllerStatus get status => _status;

  @override
  Stream<ControllerStatus> get changes => _changes.stream;

  @override
  Future<String?> get ended => _ended.future;

  @override
  Future<void> stop() async {
    stopped = true;
    if (!_ended.isCompleted) _ended.complete(null);
    await _changes.close();
  }
}

/// The phone's browser for a social login: remembers what was opened and
/// lets a test play the return (what the site's `/app/oidc` link does).
class FakeAuthBrowser implements AuthBrowser {
  final opened = <Uri>[];
  bool works = true;

  /// Called when an address is opened; a test makes the return happen here.
  void Function(Uri url)? onOpen;

  @override
  Future<bool> open(Uri url) async {
    if (!works) return false;
    opened.add(url);
    onOpen?.call(url);
    return true;
  }
}

/// Android's Credential Manager: answers with the credential JSON a test
/// gives, or throws [PasskeyException].
class FakePasskeys implements PasskeyService {
  bool present = true;
  String? failWith;
  final requests = <String>[];
  String credentialId = 'cred-1';

  @override
  Future<bool> available() async => present;

  Future<String> _answer(String request) async {
    requests.add(request);
    final f = failWith;
    if (f != null) throw PasskeyException(f);
    return '{"id":"$credentialId","rawId":"$credentialId","type":"public-key",'
        '"response":{}}';
  }

  @override
  Future<String> create(String optionsJson) => _answer(optionsJson);

  @override
  Future<String> get(String optionsJson) => _answer(optionsJson);
}
