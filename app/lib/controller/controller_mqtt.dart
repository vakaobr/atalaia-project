// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's MQTT topics (ADR-P2-5, spec section 11;
/// decision PE24, slice S2): what the Pi controller's bridge
/// (controller/atalaia_controller/mqtt.py) publishes to Mosquitto, published
/// here on the app's embedded broker (mqtt_broker.dart), with the same
/// topics and payloads, checked by the shared contract cases
/// (protocol/vectors/controller_api.json, the `mqtt` steps).
///
/// Publishes (QoS 1):
///
///     field/v1/{game}/events/{type}         every game event, without gm_only data
///     field/v1/{game}/score                 totals per team (retained)
///     field/v1/{game}/nodes/{node}/state    owner, phase, game time, counters (retained)
///     field/v1/{game}/nodes/{node}/health   battery, RSSI, SNR, last seen (retained)
///
/// Takes commands from clients the broker's ACL lets write there (the `gm`
/// user of [MqttAcl.field]):
///
///     field/v1/{game}/cmd/{node}            {"cmd": "message", "params": {...}}
///     field/v1/{game}/cmd/all
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'controller_engine.dart';
import 'mqtt_broker.dart';

const mqttPrefix = 'field/v1';

/// Where the bridge publishes: [MqttBroker.publish], or a test's recorder.
typedef MqttPublish =
    void Function(String topic, Object payload, {int qos, bool retain});

class ControllerMqtt {
  ControllerMqtt(this.engine, this._publish) {
    engine.addListener(onControllerMessage);
  }

  /// The bridge on [broker]: publishes there and takes the commands its
  /// clients may publish.
  factory ControllerMqtt.onBroker(ControllerEngine engine, MqttBroker broker) {
    final bridge = ControllerMqtt(engine, broker.publish);
    bridge._commands = broker.received.listen(
      (m) => bridge.onCommand(m.$2, m.$3),
    );
    return bridge;
  }

  final ControllerEngine engine;
  final MqttPublish _publish;
  StreamSubscription<Object?>? _commands;

  /// Messages published, and commands taken (accepted or refused).
  int published = 0;
  int commands = 0;

  /// Why the last command was refused (null: it was sent).
  String? lastRefusal;

  void _out(String topic, Map<String, Object?> data, {bool retain = false}) {
    _publish(topic, jsonEncode(data), qos: 1, retain: retain);
    published++;
  }

  /// The engine's listener (mqtt.py `on_controller_message`).
  void onControllerMessage(Map<String, Object?> msg) {
    final game = msg['game'];
    switch (msg['type']) {
      case 'event':
        // Any scoreboard on the field's network may read these topics: no
        // gm_only data (decision M5-1); the GM has it on the stream.
        final ev = publicEvent((msg['event']! as Map).cast<String, Object?>());
        _out('$mqttPrefix/$game/events/${ev['type']}', {'game': game, ...ev});
      case 'score':
        // A tick is a projected total on the stream only: MQTT carries the
        // boxes' reports.
        if (msg['tick'] == true) return;
        _out('$mqttPrefix/$game/score', {
          'game': game,
          'teams': msg['teams'],
          'at': engine.wallSeconds(),
        }, retain: true);
      case 'node':
        final node = (msg['node']! as Map).cast<String, Object?>();
        final base = '$mqttPrefix/$game/nodes/${node['node_id']}';
        _out('$base/state', {
          for (final k in const [
            'node_id',
            'name',
            'role',
            'owner',
            'phase',
            'game_time_ms',
            'score',
          ])
            k: node[k],
        }, retain: true);
        // A link event (node.offline) is news about a box that said nothing:
        // its own last-heard time.
        final ago = node['seen_ms_ago'];
        final now = engine.wallSeconds();
        _out('$base/health', {
          for (final k in const [
            'node_id',
            'battery_pct',
            'rssi',
            'snr',
            'epoch',
            'fw_version',
            'link',
            'battery_low',
          ])
            k: node[k],
          'last_seen': ago is int ? now - ago / 1000 : now,
        }, retain: true);
    }
  }

  /// A message a client published on [topic] (mqtt.py `_on_message`): a
  /// command to a node of the live game, or ignored.
  void onCommand(String topic, Uint8List payload) {
    final parts = topic.split('/');
    if (parts.length != 5 ||
        '${parts[0]}/${parts[1]}' != mqttPrefix ||
        parts[3] != 'cmd') {
      return;
    }
    commands++;
    try {
      final gameId = int.tryParse(parts[2]);
      final target = parts[4] == 'all' ? 0xffff : int.tryParse(parts[4]);
      if (gameId == null || target == null) {
        throw const FormatException('the topic needs a game and a node id');
      }
      final body = jsonDecode(utf8.decode(payload));
      if (body is! Map) {
        throw const FormatException('the payload must be a JSON object');
      }
      final live = engine.liveGame;
      if (live == null || live['id'] != gameId) {
        throw ControllerError('game $gameId is not live');
      }
      engine.sendNodeCmd(target, body['cmd'], body['params']);
      lastRefusal = null;
    } on FormatException catch (e) {
      lastRefusal = e.message;
    } on ControllerError catch (e) {
      lastRefusal = e.message;
    }
  }

  Future<void> close() async {
    engine.removeListener(onControllerMessage);
    await _commands?.cancel();
  }
}
