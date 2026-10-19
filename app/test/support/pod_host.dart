// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The I/O pod's own C code and the controller's radio modem, as host
/// programs the Dart tests drive (firmware/esp32/test/pod_host and
/// modem_host, built by tools/docker_app.py and CI's flutter-test job;
/// `$ATALAIA_POD_HOST` and `$ATALAIA_MODEM_HOST` name them). A missing
/// program fails the tests that need it: nothing is skipped.
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
    Duration timeout = const Duration(seconds: 5),
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
      _out.wait(
        prefix,
        from: from ?? 0,
        timeout: timeout ?? const Duration(seconds: 5),
      );

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
      const Duration(seconds: 5),
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
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final end = DateTime.now().add(timeout);
    while (true) {
      for (var i = from; i < frames.length; i++) {
        final f = frames[i];
        if (f.type == type && (match == null || match(f.payload))) return f;
      }
      final left = end.difference(DateTime.now());
      if (left.isNegative) {
        throw TimeoutException('no modem frame of type $type');
      }
      await _changed.stream.first.timeout(left, onTimeout: () {});
    }
  }

  Future<void> close() async => _socket.destroy();
}
