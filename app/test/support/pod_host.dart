// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The I/O pod's own C code and the controller's radio modem, as host
/// programs the Dart tests drive (firmware/esp32/test/pod_host and
/// modem_host, built by tools/docker_app.py and CI's flutter-test job;
/// `$ATALAIA_POD_HOST` and `$ATALAIA_MODEM_HOST` name them). A missing
/// program fails the tests that need it, except on a machine that has said it
/// cannot have them (see [hostSkip]): a broken setup is never skipped on the
/// Linux runs.
///
/// The pod's USB link is a TCP socket carrying the raw frames; its
/// Bluetooth link a socket where every message is a 2-byte length and one
/// notification or one write (cut to the MTU, as Android does); the radio is
/// UDP "air" between the pod and the modem.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:flutter_test/flutter_test.dart' show test;

/// How long a test waits for a host program (the pod, the modem) to do what
/// it was asked: a program that is working answers in milliseconds, but one
/// that shares the machine with several Docker suites is scheduled seconds
/// late, never early. A wait that ends is a real failure, so the deadline
/// costs nothing when all is well.
const hostDeadline = Duration(seconds: 60);

/// Waits until [ok], polling, for [timeout]; the failure names [what] and
/// shows [detail] (the host program's latest lines, say).
Future<void> eventually(
  bool Function() ok,
  String what, {
  Duration timeout = hostDeadline,
  String Function()? detail,
}) async {
  final end = DateTime.now().add(timeout);
  while (!ok()) {
    if (DateTime.now().isAfter(end)) {
      throw TimeoutException('no $what after $timeout ${detail?.call() ?? ''}');
    }
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

bool _missing(String variable) {
  final env = Platform.environment[variable];
  return env == null || env.isEmpty || !File(env).existsSync();
}

/// Why the tests that need the host programs named by [variables] (their
/// environment variables, `ATALAIA_POD_HOST`...) are skipped here, or null:
/// run them. They are skipped only when one program is missing AND either
/// `ATALAIA_ALLOW_MISSING_HOSTS=1` is set, or the machine is not Linux and
/// that variable is unset (a Mac or a Windows PC that has not built them:
/// firmware/esp32/test/*_host, app/README.md, "Tests on a Mac").
/// `ATALAIA_ALLOW_MISSING_HOSTS=0` never skips; app/tool/check.sh sets it, so
/// `python tools/docker_app.py` and CI's flutter-test fail on a missing
/// program, as does any Linux run without the opt-in.
String? hostSkip(Iterable<String> variables) {
  final missing = variables.where(_missing).toList();
  if (missing.isEmpty) return null;
  final allow = Platform.environment['ATALAIA_ALLOW_MISSING_HOSTS'];
  if (allow == '0') return null;
  if (allow != '1' && Platform.isLinux) return null;
  return '${missing.map((v) => '\$$v').join(', ')} not set to a built host '
      'program (firmware/esp32/test/*_host; app/README.md, "Tests on a Mac")';
}

/// For a file whose every test needs the host programs [variables]: when they
/// are to be skipped ([hostSkip]), registers one skipped test saying why and
/// returns true, and `main` returns; else false. Call it first in `main`.
bool skipFileWithoutHosts(Iterable<String> variables) {
  final reason = hostSkip(variables);
  if (reason == null) return false;
  test('needs the firmware host programs', () {}, skip: reason);
  return true;
}

String _program(String variable) {
  final env = Platform.environment[variable];
  if (env == null || env.isEmpty || !File(env).existsSync()) {
    throw StateError(
      '\$$variable must name the program (now: "${env ?? ''}"): '
      'python tools/docker_app.py builds it, CI builds it for flutter-test',
    );
  }
  return env;
}

String podHostPath() => _program('ATALAIA_POD_HOST');
String modemHostPath() => _program('ATALAIA_MODEM_HOST');
String boxHostPath() => _program('ATALAIA_BOX_HOST');

/// The host box (firmware/esp32/test/box_host): a Field Box's game and
/// radio code (main/box_game.c, main/radio/field_link.c, the node runner and
/// the core, with mbedtls AES-CCM), as controller/tests/support.py's BoxHost.
/// It shares the hub's air; its NVS and flash are files in [stateDir], so
/// [kill] then [boot] again is a battery pull.
class HostBox {
  HostBox._(
    this.hub,
    this.stateDir,
    this.joinKey,
    this.name,
    this.stateMs,
    this.args,
  );

  /// [joinKey] empty: an unadopted box (no `--join-key`); [args]: more of
  /// box_host's options (`--announce-ms`, `--pair`, `--as-box`...).
  static Future<HostBox> start(
    AirHub hub,
    String stateDir,
    List<int> joinKey, {
    String name = 'box',
    int stateMs = 500,
    List<String> args = const [],
  }) async {
    final b = HostBox._(hub, stateDir, joinKey, name, stateMs, args);
    await b.boot();
    return b;
  }

  final AirHub hub;
  final String stateDir;
  final List<int> joinKey;
  final String name;
  final int stateMs;
  final List<String> args;
  Process? _process;
  _Lines? _out;
  var airPort = 0;

  List<String> get lines => _out?.lines ?? const [];

  /// Starts the program (again, after [kill]): it rejoins a stored game.
  Future<void> boot() async {
    final p = await Process.start(boxHostPath(), [
      '--state-dir',
      stateDir,
      '--modes',
      '../modes',
      '--air-peer',
      '${hub.port}',
      if (joinKey.isNotEmpty) ...[
        '--join-key',
        [for (final b in joinKey) b.toRadixString(16).padLeft(2, '0')].join(),
      ],
      '--state-ms',
      '$stateMs',
      '--name',
      name,
      ...args,
    ]);
    final out = _Lines(p);
    final ready = await out.wait('READY ');
    airPort = _ports(ready)['air']!;
    hub.members.add(airPort);
    _process = p;
    _out = out;
  }

  void send(String line) => _process!.stdin.writeln(line);

  /// Types the join text on the box's console.
  void join(String text) => send('@join $text');

  void hold(int button, int ms) => send('hold $button $ms');

  bool logged(String needle) => lines.any((l) => l.contains(needle));

  Future<Map<String, Object?>> status() async {
    final from = lines.length;
    send('status');
    final line = await _out!.wait('STATUS ', from: from);
    return (jsonDecode(line.substring(7)) as Map).cast<String, Object?>();
  }

  /// A battery pull: no goodbye.
  Future<void> kill() async {
    final p = _process;
    if (p == null) return;
    hub.members.remove(airPort);
    p.kill();
    await p.exitCode;
    _process = null;
  }
}

/// A host program's stdout lines, as they come.
class _Lines {
  _Lines(Process p) {
    p.stdout.transform(utf8.decoder).transform(const LineSplitter()).listen((
      l,
    ) {
      lines.add(l);
      _changed.add(null);
    });
    p.stderr.transform(utf8.decoder).listen(stderrText.write);
  }

  final lines = <String>[];
  final stderrText = StringBuffer();
  final _changed = StreamController<void>.broadcast();

  /// The first line from index [from] that starts with [prefix].
  Future<String> wait(
    String prefix, {
    int from = 0,
    Duration timeout = hostDeadline,
  }) async {
    final end = DateTime.now().add(timeout);
    while (true) {
      for (var i = from; i < lines.length; i++) {
        if (lines[i].startsWith(prefix)) return lines[i];
      }
      final left = end.difference(DateTime.now());
      if (left.isNegative) {
        throw TimeoutException(
          'no "$prefix" line; got ${lines.length > 20 ? lines.sublist(lines.length - 20) : lines}'
          '\n$stderrText',
        );
      }
      await _changed.stream.first.timeout(left, onTimeout: () {});
    }
  }
}

Map<String, int> _ports(String ready) => {
  for (final part in ready.split(' ').skip(1))
    part.split('=')[0]: int.parse(part.split('=')[1]),
};

/// The host pod: the pod firmware's proxy and radio code.
class HostPod {
  HostPod._(this.process, this._out, this.usbPort, this.blePort, this.airPort);

  static Future<HostPod> start({
    int? airPeer,
    List<String> args = const [],
  }) async {
    final p = await Process.start(podHostPath(), [
      if (airPeer != null) ...['--air-peer', '$airPeer'],
      ...args,
    ]);
    final out = _Lines(p);
    final ports = _ports(await out.wait('READY '));
    return HostPod._(p, out, ports['usb']!, ports['ble']!, ports['air']!);
  }

  final Process process;
  final _Lines _out;
  final int usbPort, blePort, airPort;

  List<String> get lines => _out.lines;

  /// A hardware line on stdin (`press 1`, `tag <uid> <record>`, `case open`...).
  void send(String line) => process.stdin.writeln(line);

  Future<String> wait(String prefix, {int? from, Duration? timeout}) =>
      _out.wait(prefix, from: from ?? 0, timeout: timeout ?? hostDeadline);

  /// The pod's enclosure switch is armed once it has read the case closed
  /// for POD_TAMPER_DEBOUNCE_MS (50 ms on its own clock, main/pod/pod_caps.h):
  /// a `case open` before that is a pod that booted open, and is not
  /// reported. The pod's clock is not seen from here, so this runs STATUS
  /// round trips (each one is a turn of the pod's loop, which also polls its
  /// switch) over three times that debounce, then one more.
  Future<void> caseArmed() async {
    final since = Stopwatch()..start();
    do {
      await status();
    } while (since.elapsed < const Duration(milliseconds: 3 * 50));
    await status();
  }

  /// The next line with [prefix] after the lines so far.
  int get mark => _out.lines.length;

  Future<Map<String, Object?>> status() async {
    final from = mark;
    send('status');
    final line = await wait('STATUS ', from: from);
    return (jsonDecode(line.substring(7)) as Map).cast<String, Object?>();
  }

  Future<void> stop() async {
    send('quit');
    await process.exitCode.timeout(
      hostDeadline,
      onTimeout: () {
        process.kill();
        return -1;
      },
    );
  }
}

/// The controller's radio: the host modem (main/modem/modem.c with AES-CCM).
class HostModem {
  HostModem._(this.process, this.serialPort, this.airPort);

  static Future<HostModem> start({int? airPeer}) async {
    final p = await Process.start(modemHostPath(), [
      if (airPeer != null) ...['--air-peer', '$airPeer'],
    ]);
    final out = _Lines(p);
    final ports = _ports(await out.wait('READY '));
    return HostModem._(p, ports['serial']!, ports['air']!);
  }

  final Process process;
  final int serialPort, airPort;

  Future<void> stop() async {
    process.kill();
    await process.exitCode;
  }
}

/// The pod's USB link: the raw bytes on a socket.
class SocketPodTransport implements PodTransport {
  SocketPodTransport._(this._socket) : incoming = _socket.asBroadcastStream();

  static Future<SocketPodTransport> usb(HostPod pod) async =>
      SocketPodTransport._(
        await Socket.connect(InternetAddress.loopbackIPv4, pod.usbPort),
      );

  /// The host modem's serial link, as the phone's USB-OTG link to a USB
  /// radio modem would carry it (serial_modem.dart; slice S7c).
  static Future<SocketPodTransport> modem(HostModem modem) async =>
      SocketPodTransport._(
        await Socket.connect(InternetAddress.loopbackIPv4, modem.serialPort),
      );

  final Socket _socket;

  @override
  final Stream<Uint8List> incoming;

  @override
  String get kind => 'usb';

  @override
  Future<void> send(Uint8List bytes) async => _socket.add(bytes);

  @override
  Future<void> close() async => _socket.destroy();
}

/// The pod's Bluetooth link as the host pod offers it: every notification
/// and every write is a 2-byte length and its bytes; writes are cut to the
/// MTU less 3, as the app's BLE plugin does (BlePodPlugin.kt).
class BleSocketPodTransport implements PodTransport {
  BleSocketPodTransport._(this._socket, this.mtu) {
    _socket.listen(
      _onBytes,
      onDone: () => _notes.close(),
      onError: (Object e) => _notes.addError(e),
    );
  }

  static Future<BleSocketPodTransport> connect(
    HostPod pod, {
    int mtu = 247,
  }) async => BleSocketPodTransport._(
    await Socket.connect(InternetAddress.loopbackIPv4, pod.blePort),
    mtu,
  );

  final Socket _socket;
  final int mtu;
  final _notes = StreamController<Uint8List>.broadcast();
  final _buf = BytesBuilder();

  /// Every notification's length, in order (to see the MTU at work).
  final notificationSizes = <int>[];

  @override
  String get kind => 'ble';

  @override
  Stream<Uint8List> get incoming => _notes.stream;

  void _onBytes(Uint8List data) {
    _buf.add(data);
    var bytes = _buf.takeBytes();
    while (bytes.length >= 2) {
      final n = bytes[0] << 8 | bytes[1];
      if (bytes.length < 2 + n) break;
      final note = Uint8List.fromList(bytes.sublist(2, 2 + n));
      notificationSizes.add(n);
      _notes.add(note);
      bytes = bytes.sublist(2 + n);
    }
    _buf.add(bytes);
  }

  @override
  Future<void> send(Uint8List bytes) async {
    final piece = mtu - 3;
    for (var i = 0; i < bytes.length; i += piece) {
      final end = i + piece < bytes.length ? i + piece : bytes.length;
      final n = end - i;
      _socket.add([n >> 8, n & 0xff, ...bytes.sublist(i, end)]);
    }
  }

  @override
  Future<void> close() async => _socket.destroy();
}

/// A shared "air" for the host programs, as controller/tests/support.py's
/// AirHub: each sends what it transmits here, and every other member hears it.
class AirHub {
  AirHub._(this._socket) {
    _socket.listen((e) {
      if (e != RawSocketEvent.read) return;
      final d = _socket.receive();
      if (d == null) return;
      heard.add(d.data);
      for (final port in members) {
        if (port != d.port && !mute) {
          _socket.send(d.data, InternetAddress.loopbackIPv4, port);
        }
      }
    });
  }

  static Future<AirHub> start() async =>
      AirHub._(await RawDatagramSocket.bind(InternetAddress.loopbackIPv4, 0));

  final RawDatagramSocket _socket;
  final members = <int>[];
  final heard = <Uint8List>[];

  /// True: nothing gets through (out of radio range).
  var mute = false;

  int get port => _socket.port;

  void close() => _socket.close();
}

/// The controller's end of the host modem's serial link: modem frames
/// (protocol/usb-modem.md: the same framing as the capability proxy).
class ModemLink {
  ModemLink._(this._socket) {
    _socket.listen((d) {
      frames.addAll(_dec.feed(d));
      _changed.add(null);
    });
  }

  static Future<ModemLink> connect(HostModem modem) async => ModemLink._(
    await Socket.connect(InternetAddress.loopbackIPv4, modem.serialPort),
  );

  static const rx = 0x02, tx = 0x03, txAck = 0x04, cmd = 0x05, status = 0x06;

  final Socket _socket;
  final _dec = FrameDecoder();
  final frames = <Frame>[];
  final _changed = StreamController<void>.broadcast();

  void send(int type, List<int> payload) =>
      _socket.add(encodeFrame(type, payload));

  /// The first frame of [type] from index [from] that [match] accepts.
  Future<Frame> wait(
    int type, {
    bool Function(Uint8List payload)? match,
    int from = 0,
    Duration timeout = hostDeadline,
  }) async {
    final end = DateTime.now().add(timeout);
    while (true) {
      for (var i = from; i < frames.length; i++) {
        final f = frames[i];
        if (f.type == type && (match == null || match(f.payload))) return f;
      }
      final left = end.difference(DateTime.now());
      if (left.isNegative) {
        throw TimeoutException(
          'no modem frame of type $type after $timeout; the frames are '
          '${[for (final f in frames.reversed.take(8)) f.type]} (latest first)',
        );
      }
      await _changed.stream.first.timeout(left, onTimeout: () {});
    }
  }

  Future<void> close() async => _socket.destroy();
}
