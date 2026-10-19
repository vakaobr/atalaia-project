// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The two links to an I/O pod (protocol/capability-proxy.md): USB-OTG (a
/// CDC ACM serial device, preferred) and Bluetooth LE (the pod's GATT
/// service). Each is a Kotlin plugin (UsbPodPlugin.kt, BlePodPlugin.kt)
/// reached over a method channel for control and an event channel for the
/// bytes the pod sends. Android only (ADR-P3-10).
library;

import 'dart:async';

import 'package:flutter/services.dart';

import 'pod_client.dart';

/// A pod the phone can see.
final class PodDevice {
  const PodDevice({required this.kind, required this.id, required this.name});

  /// "usb" or "ble".
  final String kind;

  /// The USB device name or the Bluetooth address.
  final String id;
  final String name;
}

class ChannelPodTransport implements PodTransport {
  ChannelPodTransport._(this.kind)
    : _ch = MethodChannel('org.atalaia.app/pod/$kind'),
      _bytes = EventChannel('org.atalaia.app/pod/$kind/bytes');

  static final usb = ChannelPodTransport._('usb');
  static final ble = ChannelPodTransport._('ble');

  @override
  final String kind;
  final MethodChannel _ch;
  final EventChannel _bytes;
  Stream<Uint8List>? _incoming;

  /// The pods in reach: USB devices with a CDC ACM interface, or Bluetooth
  /// devices advertising the pod service (a scan of [scanFor]).
  Future<List<PodDevice>> find({
    Duration scanFor = const Duration(seconds: 4),
  }) async {
    try {
      final list = await _ch.invokeListMethod<Map<Object?, Object?>>('find', {
        'scan_ms': scanFor.inMilliseconds,
      });
      return [
        for (final m in list ?? const <Map<Object?, Object?>>[])
          PodDevice(kind: kind, id: '${m['id']}', name: '${m['name']}'),
      ];
    } on MissingPluginException {
      return const [];
    } on PlatformException {
      return const [];
    }
  }

  /// Opens the link (asking Android for the USB permission, or connecting
  /// and asking for a 247-byte MTU over Bluetooth).
  Future<bool> open(PodDevice device) async {
    try {
      return await _ch.invokeMethod<bool>('open', {'id': device.id}) ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  @override
  Stream<Uint8List> get incoming => _incoming ??= _bytes
      .receiveBroadcastStream()
      .map((e) => e as Uint8List)
      .asBroadcastStream();

  @override
  Future<void> send(Uint8List bytes) async {
    try {
      await _ch.invokeMethod<void>('write', {'bytes': bytes});
    } on MissingPluginException {
      // no link
    }
  }

  @override
  Future<void> close() async {
    try {
      await _ch.invokeMethod<void>('close');
    } on MissingPluginException {
      // nothing to close
    }
  }
}
