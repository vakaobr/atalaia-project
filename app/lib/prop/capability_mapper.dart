// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What an Android prop can do, as capability descriptors (design
/// specification section 7: `{"id": ..., "type": ..., ...}`): the phone's
/// own hardware (the touchscreen gives team buttons, a keypad, a display and
/// an on-screen team light; the speaker audio; NFC, GPS, the accelerometer,
/// the camera and the vibrator when present), plus an I/O pod's
/// capabilities when one is linked. A mode's role says which types it
/// requires; [CapabilityMap.missingFor] says what this phone lacks.
library;

import '../modes/mode_catalog.dart';
import '../platform/services.dart';
import '../pod/pod_codec.dart';
import '../protocol/capability_types.g.dart';

class CapabilityMap {
  CapabilityMap(this.descriptors);

  /// The phone's (and its pod's) capabilities.
  factory CapabilityMap.of(DeviceFeatures f, {PodIdent? pod}) {
    final out = <Map<String, Object?>>[
      if (f.touchscreen) ...[
        {'id': 'touch.teams', 'type': 'team_input', 'source': 'screen'},
        {'id': 'touch.keypad', 'type': 'keypad', 'source': 'screen'},
        {'id': 'screen', 'type': 'display', 'source': 'screen'},
        {'id': 'team_display', 'type': 'team_display', 'source': 'screen'},
        {'id': 'ring', 'type': 'led', 'source': 'screen'},
      ],
      {'id': 'speaker', 'type': 'audio', 'source': 'phone'},
      if (f.vibrator) {'id': 'vibrator', 'type': 'haptic', 'source': 'phone'},
      if (f.nfc) {'id': 'nfc', 'type': 'nfc', 'source': 'phone'},
      if (f.location) {'id': 'gps', 'type': 'gps', 'source': 'phone'},
      if (f.accelerometer) {'id': 'imu', 'type': 'imu', 'source': 'phone'},
      if (f.camera) {'id': 'camera', 'type': 'qr_scanner', 'source': 'phone'},
      for (final c in pod?.capabilities ?? const <Map<String, Object?>>[])
        {...c, 'source': 'pod'},
    ];
    return CapabilityMap(out);
  }

  final List<Map<String, Object?>> descriptors;

  Set<String> get types => {for (final d in descriptors) '${d['type']}'};

  /// Mode capability names this map provides: the descriptor types, and
  /// `team_input` for a pod's team buttons.
  bool has(String capability) {
    if (types.contains(capability)) return true;
    if (capability == 'team_input') {
      return descriptors.any((d) => d['type'] == 'button' && d['team'] != null);
    }
    return false;
  }

  /// HELLO's capability type ids (key 6; protocol/schema/capabilities.yaml),
  /// in id order: the types this prop really gives a mode, so the
  /// controllers' start check takes it as it takes a box (decisions PROPC-1
  /// to PROPC-4). The screen's team buttons are `button`, its team light
  /// `led`; a pod's parts count by their type, its outputs and hit sensors
  /// only while its IDENT lends them. Left out: what the prop shell gives no
  /// mode (the vibrator, the camera, the accelerometer, a pod's case switch
  /// and battery gauge), as a box lists only its game's parts.
  List<int> get helloTypes {
    final ids = <int>{};
    for (final d in descriptors) {
      final type = _helloType['${d['type']}'];
      final id = type == null ? null : capabilityTypeIds[type];
      if (id != null) ids.add(id);
    }
    return ids.toList()..sort();
  }

  /// A descriptor's type as HELLO names it; absent: not listed.
  static const _helloType = {
    'team_input': 'button',
    'button': 'button',
    'keypad': 'keypad',
    'display': 'display',
    'team_display': 'led',
    'led': 'led',
    'audio': 'audio',
    'nfc': 'nfc',
    'gps': 'gps',
    'hit': 'hit',
    'output': 'output',
  };

  /// The capabilities [role] requires that this phone (and pod) lacks.
  List<String> missingFor(ModeRole role) => [
    for (final c in role.requires)
      if (!has(c)) c,
  ];

  /// Whether the role's optional [capability] is there (to show a keypad,
  /// to listen for tags...).
  bool offers(ModeRole role, String capability) =>
      role.uses(capability) && has(capability);
}
