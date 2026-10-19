// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A prop with both ways to the controller (decision PF9): the field's Wi-Fi
/// ([PropLink]) when the join payload names the controller, and the field's
/// radio through an I/O pod ([PodRadioLink]) when a pod with a radio is
/// linked. The rule:
///
///   - while the Wi-Fi link is up, everything goes on it and the radio
///     stays quiet (the field's airtime is shared and duty-cycled); the
///     controller's word is taken from Wi-Fi only;
///   - while it is down, events and STATE go on the radio as well, and TIME
///     and commands come from the radio;
///   - every event still goes to the Wi-Fi link, which keeps it until the
///     controller acknowledges it and sends it again after a reconnect: an
///     event heard on both arrives twice and is logged once (the
///     controller's log drops (node, seq, game time, type) duplicates;
///     scores merge by maximum).
///
/// The radio's HELLO goes out once when the pod's radio is configured, and
/// both HELLOs say "lora and wifi" in their transports.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../radio/pod_radio_link.dart';
import '../radio/rf_codec.dart';
import 'prop_link.dart';

class DualLink extends ChangeNotifier implements ControllerLink {
  DualLink({this.wifi});

  final PropLink? wifi;
  PodRadioLink? _radio;
  final _messages = StreamController<LinkMessage>.broadcast();
  StreamSubscription<LinkMessage>? _wifiSub, _radioSub;
  var _started = false;

  PodRadioLink? get radio => _radio;

  bool get _wifiUp => wifi?.linked ?? false;

  /// HELLO's transports: Wi-Fi when there is a Wi-Fi link, LoRa with a radio.
  int get transports =>
      (wifi != null ? RfTransport.wifi : 0) |
      (_radio != null ? RfTransport.lora : 0);

  @override
  Stream<LinkMessage> get messages => _messages.stream;

  @override
  bool get linked => _wifiUp || (_radio?.linked ?? false);

  @override
  void start() {
    if (_started) return;
    _started = true;
    final w = wifi;
    if (w != null) {
      w.addListener(notifyListeners);
      _wifiSub = w.messages.listen(_messages.add);
      w.start();
    }
    _radio?.start();
  }

  /// A pod with a radio was linked: its radio link joins this one.
  Future<void> attachRadio(
    PodRadioLink radio, {
    Map<String, Object?> hello = const {},
  }) async {
    final old = _radio;
    if (old != null) {
      old.removeListener(notifyListeners);
      await _radioSub?.cancel();
      await old.close();
    }
    _radio = radio;
    radio.addListener(notifyListeners);
    _radioSub = radio.messages.listen((m) {
      if (!_wifiUp) _messages.add(m);
    });
    final fields = {...radio.hello, ...hello, 'transports': transports};
    radio.updateHello(fields);
    wifi?.updateHello({...?wifi?.hello, 'transports': transports});
    if (_started) radio.start();
    notifyListeners();
  }

  @override
  void sendEvent({
    required int seq,
    required int tMs,
    required String type,
    int team = 0,
    int squad = 0,
    String? prio,
    Map<String, Object?> data = const {},
    String? dataJson,
  }) {
    final viaRadio = !_wifiUp;
    wifi?.sendEvent(
      seq: seq,
      tMs: tMs,
      type: type,
      team: team,
      squad: squad,
      prio: prio,
      data: data,
    );
    if (viaRadio) {
      _radio?.sendEvent(
        seq: seq,
        tMs: tMs,
        type: type,
        team: team,
        squad: squad,
        prio: prio,
        data: data,
        dataJson: dataJson,
      );
    }
  }

  @override
  void sendState(Map<String, Object?> fields) {
    wifi?.sendState(fields);
    if (!_wifiUp) _radio?.sendState(fields);
  }

  @override
  Future<void> close() async {
    wifi?.removeListener(notifyListeners);
    _radio?.removeListener(notifyListeners);
    await _wifiSub?.cancel();
    await _radioSub?.cancel();
    await wifi?.close();
    await _radio?.close();
    if (!_messages.isClosed) await _messages.close();
  }
}
