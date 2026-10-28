// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A pod simulated at the transport, for the tests of reconnecting
/// (lib/pod/pod_reconnect.dart): it answers the phone's IDENT request with
/// [ident] (or stays silent), sends what a test tells it to, and can drop
/// the link as a pod that goes out of reach does.
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';

const podIdent = PodIdent(
  fwVersion: '0.3.0',
  capabilities: [
    {'id': 'btn.red', 'type': 'button', 'team': 'red'},
    {'id': 'btn.blue', 'type': 'button', 'team': 'blue'},
    {'id': 'ring', 'type': 'led', 'count': 24, 'rgb': true},
  ],
  hasRadio: false,
);

/// A pod that is not the one above (other capabilities).
const otherPodIdent = PodIdent(
  fwVersion: '0.3.0',
  capabilities: [
    {'id': 'nfc', 'type': 'nfc'},
  ],
  hasRadio: false,
);

class FakePodLink implements PodTransport {
  FakePodLink({this.ident = podIdent, this.kind = 'usb', this.log});

  /// What the pod says when asked; null: it never answers.
  final PodIdent? ident;
  @override
  final String kind;

  /// Shared by the links of a test: "open", "close" lines, in order.
  final List<String>? log;

  final _in = StreamController<Uint8List>.broadcast();
  final _decoder = FrameDecoder();
  final sent = <Frame>[];
  var closed = false;

  @override
  Stream<Uint8List> get incoming => _in.stream;

  @override
  Future<void> send(Uint8List bytes) async {
    for (final f in _decoder.feed(bytes)) {
      sent.add(f);
      final id = ident;
      if (f.type == FrameType.radioCmd &&
          f.payload.first == RadioOp.ident &&
          f.payload.length == 1 &&
          id != null &&
          !_in.isClosed) {
        _in.add(encodeFrame(FrameType.ident, encodeIdent(id)));
      }
      if (f.type == FrameType.cmd) {
        // Acknowledge a command, as a pod does.
        _in.add(
          encodeFrame(FrameType.ack, encodeAck(decodeMessage(f.payload).seq)),
        );
      }
    }
  }

  /// The pod sends an event of a capability.
  void event(String cap, String name, int seq, [Map<String, Object?>? data]) {
    _in.add(
      encodeFrame(
        FrameType.evt,
        encodeMessage(
          ProxyMessage(
            capId: cap,
            name: name,
            data: data ?? const {},
            seq: seq,
          ),
        ),
      ),
    );
  }

  /// The pod goes out of reach: the link ends.
  Future<void> drop() => _in.close();

  @override
  Future<void> close() async {
    if (closed) return;
    closed = true;
    log?.add('close');
    if (!_in.isClosed) await _in.close();
  }
}

Future<void> until(bool Function() ok, {int ms = 3000}) async {
  final end = DateTime.now().add(Duration(milliseconds: ms));
  while (!ok()) {
    if (DateTime.now().isAfter(end)) throw TimeoutException('condition');
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}
