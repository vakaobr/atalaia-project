// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android prop's game (plan phase D, the "Android prop shell"): what a
/// Field Box's shell does, for a phone. It runs the mode on the shared core
/// in a game loop isolate (lib/core/), turns the touchscreen's team buttons
/// and keypad, NFC tags and an I/O pod's events into the mode's inputs,
/// draws the mode's screens (ui.screen) with the template renderer, plays
/// its sounds, keeps the game's length and sends game.end when it runs out
/// (decision PC6), and holds the foreground service, the screen manager and
/// kiosk mode while the game runs (ADR-P3-5).
///
/// With a [PropLink] (plan phase E, decision PD12) the prop takes part in the
/// controller's game over Wi-Fi as a box does over the radio: its events and
/// STATE go to the controller, the controller's commands and TIME beacons
/// start, pause, resume and end it, and a kiosk-mode loss is reported as
/// node.tamper. A linked I/O pod with a radio adds the field's radio
/// ([PodRadioLink], decision PF9): both go through a [DualLink], which keeps
/// the radio for when the Wi-Fi link is down; an opened pod is node.tamper
/// too (reason pod_opened).
///
/// A [ChangeNotifier]: the game screen rebuilds when it changes. It has no
/// widgets and no platform code of its own (the services are injected), so
/// the tests drive it on the real core with a manual clock.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../controller/dual_link.dart';
import '../controller/prop_link.dart';
import '../core/node_types.dart';
import '../modes/mode_catalog.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../pod/pod_codec.dart';
import '../protocol/join_payload.dart';
import '../radio/pod_radio_link.dart';
import '../security/ndef.dart';
import '../security/nfc_tag_signer.dart';
import '../ui/template/screen_template.dart';
import 'button_tracker.dart';
import 'game_timer.dart';
import 'screen_manager.dart';
import 'shell_screens.dart';

/// How a prop's game is set up: picked on the phone, or from a join
/// payload (decision P3-10).
final class PropSetup {
  const PropSetup({
    required this.mode,
    required this.role,
    required this.teams,
    required this.params,
    this.durationMs = 0,
    this.nodeId = 1,
    this.gameSeed = 1,
    this.join,
  });

  final GameMode mode;
  final String role;
  final List<String> teams;
  final Map<String, Object?> params;

  /// The game's length; 0 for none.
  final int durationMs;
  final int nodeId;
  final int gameSeed;

  /// The join payload the prop joined with, if any: it brings the game's id
  /// and key, which player tags are checked with. Without one, tags are
  /// refused with `no_game` (decision A4: tag modes are controller games).
  final JoinPayload? join;

  int get gameId => join?.gameId ?? 0;
  Uint8List? get gameKey => join?.gameKey;
}

enum PropPhase { loading, ready, running, paused, ended, halted, failed }

/// The texts the session needs from the interface's language.
final class PropTexts {
  const PropTexts({
    required this.notificationTitle,
    required this.notificationRunning,
    required this.notificationLeft,
  });

  /// {mode}
  final String notificationTitle;
  final String notificationRunning;

  /// {time}
  final String notificationLeft;
}

class PropSession extends ChangeNotifier {
  PropSession({
    required this.setup,
    required this.runner,
    required this.device,
    required this.texts,
    this.foreground,
    this.kiosk,
    this.kioskEnabled = false,
    this.clock = GameClock.realTime,
    this.tick = const Duration(milliseconds: 50),
    this.modeName = '',
    this.link,
    this.radioLinkFor,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now,
       timer = GameTimer(setup.durationMs),
       _link = link != null || setup.join != null
           ? DualLink(wifi: link)
           : null {
    tracker = ButtonTracker(_input);
    screenManager = ScreenManager(device, kiosk: kioskEnabled, now: _now);
  }

  final PropSetup setup;
  final NodeRunner runner;
  final DeviceServices device;
  final PropTexts texts;
  final ForegroundService? foreground;
  final KioskService? kiosk;
  final bool kioskEnabled;
  final GameClock clock;
  final Duration tick;
  final String modeName;

  /// The Wi-Fi link to the field controller, when the join payload names it.
  final PropLink? link;

  /// The radio link through a pod with a radio, for a joined game (null:
  /// none; the app gives the core's event codec and the stored epochs).
  final PodRadioLink? Function(PodClient pod)? radioLinkFor;

  /// The links to the controller: Wi-Fi and/or the pod's radio.
  final DualLink? _link;

  /// The radio link through the pod, once one with a radio is linked.
  PodRadioLink? get radio => _link?.radio;
  DualLink? get controllerLink => _link;
  final DateTime Function() _now;
  StreamSubscription<LinkMessage>? _linkSub;
  var _ownerTeam = 0;
  var _shellSeq = 0;
  var _sinceState = 0;

  /// The organisers' last message (CMD message).
  String? gmMessage;

  final GameTimer timer;
  late final ButtonTracker tracker;
  late final ScreenManager screenManager;

  RunningNode? _node;
  StreamSubscription<NodeOutput>? _sub;
  Timer? _ticker;
  var _sinceSnapshot = 0;
  var _sinceSlow = 0;
  var _closed = false;
  PodClient? _pod;
  PodInputs? _podInputs;
  StreamSubscription<PodEvent>? _podSub;

  PropPhase phase = PropPhase.loading;
  String? error;

  /// The mode's current screen (ui.screen), its data and its template;
  /// [template] is null when neither the mode nor the shell has one.
  String? screenName;
  Map<String, Object?> screenData = const {};
  ScreenTemplate? template;
  final _templates = <String, ScreenTemplate?>{};

  /// The team colour of the ring or team display ("ring:fill",
  /// "team_display:show"), or null when off.
  String? light;

  /// Game time and scores from the node's last snapshot.
  int gameTimeMs = 0;
  Map<String, int> scores = const {};

  /// The game's log: events, the script's log lines, errors (newest last).
  final log = <String>[];

  /// Kiosk mode was left while the game ran (ADR-P3-9 tamper detection).
  bool tamper = false;

  /// The pod's enclosure is open (its tamper switch, during the game).
  bool podOpened = false;

  /// The pod linked to this prop, if any.
  PodIdent? get pod => _pod?.ident;

  int? get remainingMs => timer.remainingMs(gameTimeMs);

  bool get running => phase == PropPhase.running || phase == PropPhase.paused;

  /// Starts the node; the game waits for [start].
  Future<void> open() async {
    try {
      final node = await runner.start(
        NodeSpec(
          source: setup.mode.nodeScript,
          chunkName: setup.mode.chunkName,
          nodeId: setup.nodeId,
          gameSeed: setup.gameSeed,
          teams: setup.teams,
          params: setup.params,
        ),
        clock: clock,
      );
      if (_closed) {
        // The screen closed while the node was starting.
        await node.close();
        return;
      }
      _node = node;
      _sub = node.outputs.listen(_onOutput);
      node.startupOutputs.forEach(_onOutput);
      if (!node.loaded) {
        final s = await node.snapshot();
        error = s.lastError;
        phase = PropPhase.failed;
      } else {
        phase = PropPhase.ready;
        final l = _link;
        if (l != null) {
          _linkSub = l.messages.listen(_onLink);
          l.start();
        }
      }
    } on Object catch (e) {
      error = '$e';
      phase = PropPhase.failed;
    }
    if (clock == GameClock.realTime && phase != PropPhase.failed) {
      _ticker = Timer.periodic(tick, (_) => _onTick(tick.inMilliseconds));
    }
    notifyListeners();
  }

  /// Starts the game (the Field Box's "start" after its confirmation).
  Future<void> start() async {
    if (phase != PropPhase.ready) return;
    final ok = await _node?.input('game.start') ?? false;
    if (!ok) return;
    phase = PropPhase.running;
    await screenManager.start();
    await foreground?.start(
      title: _fill(texts.notificationTitle, {'mode': modeName}),
      text: _statusText(),
    );
    if (kioskEnabled) await kiosk?.start();
    notifyListeners();
  }

  Future<void> pause() => _input('game.pause', {'reason': 'admin'});
  Future<void> resume() => _input('game.resume');

  /// Ends the game now (an admin, not the timer).
  Future<void> end() => _input('game.end', {'reason': 'admin'});

  /// A team button on the screen went down or up.
  void pressTeam(String team) {
    unawaited(screenManager.activity());
    tracker.press(team);
  }

  void releaseTeam(String team) => tracker.release(team);

  /// A key of the on-screen keypad: 0-9, * or #.
  void key(String k) {
    unawaited(screenManager.activity());
    unawaited(_input('keypad.key', {'key': k}));
  }

  /// The screen was touched somewhere (keeps it awake).
  void touched() => unawaited(screenManager.activity());

  /// A tag held to the phone's NFC reader: checked with the game's key and
  /// given to the mode as nfc.tag (protocol/nfc-tag.md).
  Future<void> tagRead(NfcRead read) async {
    unawaited(screenManager.activity());
    final record = read.ndef == null
        ? null
        : payloadFromNdefMessage(read.ndef!, tagNdefType);
    final data = tagEventData(
      uid: read.uid,
      payload: record,
      gameId: setup.gameId,
      gameKey: setup.gameKey,
      teams: setup.teams,
    );
    await _input('nfc.tag', data);
  }

  /// Links an I/O pod: its events become inputs, the mode's commands for
  /// its capabilities go to it.
  Future<void> attachPod(PodClient client) async {
    _pod = client;
    _podSub = client.events.listen((e) {
      switch (e) {
        case PodIdentified(:final ident):
          _podInputs = PodInputs(ident, teams: setup.teams);
          _log(
            'pod ${ident.fwVersion}: ${ident.capabilities.length} capabilities',
          );
          _attachRadio(client, ident);
          notifyListeners();
        case PodCapabilityEvent(:final message):
          unawaited(screenManager.activity());
          final inputs = _podInputs;
          if (inputs != null && inputs.caseOpened(message)) {
            unawaited(_podCaseOpened());
            return;
          }
          if (inputs != null && inputs.caseClosed(message)) {
            podOpened = false;
            notifyListeners();
            return;
          }
          final mapped = _podInputs?.input(
            message,
            tagData: (uid, tag) => podTagData(
              uid,
              tag,
              gameId: setup.gameId,
              gameKey: setup.gameKey,
              teams: setup.teams,
            ),
          );
          if (mapped != null) unawaited(_input(mapped.$1, mapped.$2));
        case PodLinkBroken(:final why):
          _log('pod link lost: $why');
          _podInputs = null;
          notifyListeners();
        case PodRadioFrame():
          break; // the radio link (PodRadioLink) reads them
      }
    });
    await client.start();
  }

  /// A pod with a radio in a joined game: the field's radio joins the links.
  void _attachRadio(PodClient client, PodIdent ident) {
    final l = _link;
    final make = radioLinkFor;
    if (!ident.hasRadio || l == null || make == null || l.radio != null) return;
    final r = make(client);
    if (r == null) return;
    _log('radio link through the pod');
    unawaited(l.attachRadio(r, hello: link?.hello ?? const {}));
  }

  /// The pod's enclosure was opened during the game (node.tamper, critical).
  Future<void> _podCaseOpened() async {
    if (!running || podOpened) return;
    podOpened = true;
    _log('node.tamper pod_opened');
    _link?.sendEvent(
      seq: ++_shellSeq,
      tMs: gameTimeMs,
      type: 'node.tamper',
      prio: 'critical',
      data: const {'reason': 'pod_opened'},
    );
    notifyListeners();
    await device.vibrate(const [0, 400, 200, 400]);
  }

  /// Moves game time on by [ms] (GameClock.manual: tests and replays).
  Future<void> advance(int ms) async {
    final node = _node;
    if (node == null || _closed) return;
    try {
      final s = await node.snapshot();
      if (s.status == NodeStatus.running &&
          !s.paused &&
          phase != PropPhase.ready) {
        await node.advanceTo(s.timeMs + ms);
      }
    } on Object {
      // The screen closed the session while the core was answering.
      if (_closed) return;
      rethrow;
    }
    await _onTick(ms, snapshotNow: true);
  }

  Future<void> _onTick(int ms, {bool snapshotNow = false}) async {
    if (_closed) return;
    tracker.tick(ms);
    _sinceSnapshot += ms;
    _sinceSlow += ms;
    _sinceState += ms;
    if (_link != null && _sinceState >= 5000) {
      _sinceState = 0;
      _sendState();
    }
    if (snapshotNow || _sinceSnapshot >= 250) {
      _sinceSnapshot = 0;
      await _refresh();
    }
    if (_sinceSlow >= 1000) {
      _sinceSlow = 0;
      await screenManager.tick();
      if (running) await _slowChecks();
    }
  }

  var _sinceNotification = 0;

  Future<void> _slowChecks() async {
    if (++_sinceNotification >= 10) {
      _sinceNotification = 0;
      await foreground?.update(
        title: _fill(texts.notificationTitle, {'mode': modeName}),
        text: _statusText(),
      );
    }
    if (kioskEnabled && kiosk != null && phase == PropPhase.running) {
      final active = await kiosk!.isActive();
      if (!active && !tamper) {
        tamper = true;
        _log('node.tamper kiosk_broken');
        _link?.sendEvent(
          seq: ++_shellSeq,
          tMs: gameTimeMs,
          type: 'node.tamper',
          prio: 'critical',
          data: const {'reason': 'kiosk_broken'},
        );
        await device.vibrate(const [0, 400, 200, 400]);
        notifyListeners();
      }
    }
  }

  Future<void> _refresh() async {
    final node = _node;
    if (node == null || _closed) return;
    final NodeSnapshot s;
    try {
      s = await node.snapshot();
    } on Object {
      return;
    }
    final before = (gameTimeMs ~/ 1000, scores, phase);
    gameTimeMs = s.timeMs;
    scores = s.scores;
    _phaseFrom(s);
    if (phase == PropPhase.running && timer.update(gameTimeMs)) {
      // The game's length is up: the shell ends the game (decision PC6).
      _log('time is up: game.end');
      await node.input('game.end');
    }
    if (before != (gameTimeMs ~/ 1000, scores, phase)) {
      if (_link != null && before.$2 != scores) _sendState();
      notifyListeners();
    }
  }

  /// STATE for the controller: the owner, the game time, the counters by
  /// team id (1-based), merged by maximum there.
  void _sendState() {
    final l = _link;
    if (l == null) return;
    l.sendState({
      'owner_team': _ownerTeam,
      'phase': phase == PropPhase.running ? 1 : 0,
      'game_time_ms': gameTimeMs,
      'counters': {
        for (var i = 0; i < setup.teams.length; i++)
          if ((scores[setup.teams[i]] ?? 0) > 0)
            '${i + 1}': scores[setup.teams[i]],
      },
      'flags':
          (phase == PropPhase.running ? 1 : 0) |
          (phase == PropPhase.paused ? 2 : 0),
    });
  }

  /// The controller's word, as a box takes it (firmware box_game.c).
  void _onLink(LinkMessage m) {
    switch (m) {
      case LinkCommand(:final cmd, :final params):
        switch (cmd) {
          case 'start':
            unawaited(start());
          case 'pause':
            if (phase == PropPhase.running) {
              unawaited(_input('game.pause', params));
            }
          case 'resume':
            if (phase == PropPhase.paused) unawaited(_input('game.resume'));
          case 'end':
            if (running) unawaited(_input('game.end', params));
          case 'set_owner':
            if (running) unawaited(_input('cmd.set_owner', params));
          case 'mode':
            // A mode command (RFC 0001 Amendment 5): a medic kit's refill
            // from the GM, the controller's count of a player's heals.
            if (running) unawaited(_input('cmd.mode', params));
          case 'message':
            gmMessage = params['text'] is String
                ? params['text']! as String
                : '';
            _log('message from the organisers: $gmMessage');
            if (running) unawaited(_input('gm.message', params));
            notifyListeners();
          default:
            _log('command $cmd from the controller');
        }
      case LinkTime(:final state):
        // A TIME beacon after a missed command: follow the controller.
        if (state == 'running' && phase == PropPhase.ready) unawaited(start());
        if (state == 'paused' && phase == PropPhase.running) {
          unawaited(_input('game.pause', {'reason': 'controller'}));
        }
        if (state == 'running' && phase == PropPhase.paused) {
          unawaited(_input('game.resume'));
        }
        if (state == 'ended' && running) unawaited(_input('game.end'));
    }
  }

  void _phaseFrom(NodeSnapshot s) {
    if (phase == PropPhase.ready || phase == PropPhase.loading) return;
    final next = switch (s.status) {
      NodeStatus.ended => PropPhase.ended,
      NodeStatus.halted => PropPhase.halted,
      NodeStatus.running when s.paused => PropPhase.paused,
      _ => PropPhase.running,
    };
    if (next == phase) return;
    phase = next;
    if (phase == PropPhase.halted) error = s.lastError;
    if (phase == PropPhase.ended || phase == PropPhase.halted) {
      tracker.releaseAll();
      unawaited(foreground?.stop());
    }
  }

  Future<void> _input(String type, [Map<String, Object?>? data]) async {
    final node = _node;
    if (node == null || _closed) return;
    try {
      await node.input(type, data);
    } on Object catch (e) {
      _log('input $type failed: $e');
    }
  }

  void _onOutput(NodeOutput o) {
    switch (o) {
      case NodeCommandOutput(:final command):
        _onCommand(command);
      case NodeEventOutput(:final event):
        _log('${event.type} ${event.dataJson}');
        if (event.type == 'zone.captured') _ownerTeam = event.team;
        if (event.type == 'zone.neutralized') _ownerTeam = 0;
        _link?.sendEvent(
          seq: event.seq,
          tMs: event.tMs,
          type: event.type,
          team: event.team,
          squad: event.squad,
          prio: event.prioName,
          data: event.data,
          dataJson: event.dataJson,
        );
        if (event.prio == 2) unawaited(device.vibrate(const [0, 250]));
      case NodeLogOutput(:final line):
        _log(line);
      case NodeErrorOutput(:final message):
        _log(message);
        error = message;
      case NodeStatusOutput(:final snapshot):
        gameTimeMs = snapshot.timeMs;
        scores = snapshot.scores;
        _phaseFrom(snapshot);
    }
    notifyListeners();
  }

  void _onCommand(NodeCommand c) {
    List<Object?> args;
    try {
      args = c.args;
    } on FormatException {
      args = const [];
    }
    if (c.target == 'ui' && c.method == 'screen' && args.isNotEmpty) {
      final name = '${args[0]}';
      final data = args.length > 1 && args[1] is Map
          ? (args[1]! as Map).cast<String, Object?>()
          : const <String, Object?>{};
      screenName = name;
      screenData = data;
      template = _template(name);
      unawaited(screenManager.activity());
      return;
    }
    if (c.target == 'audio') {
      if (c.method == 'play' && args.isNotEmpty) unawaited(_play('${args[0]}'));
      return;
    }
    if ((c.target == 'ring' && c.method == 'fill') ||
        (c.target == 'team_display' && c.method == 'show')) {
      final team = args.isEmpty ? null : '${args[0]}';
      light = team == null || team == 'none' || team == 'off' ? null : team;
    }
    final podCmd = _podInputs?.command(c.target, c.method, args);
    if (podCmd != null) {
      unawaited(_pod!.command(podCmd.$1, podCmd.$2, podCmd.$3));
    }
  }

  ScreenTemplate? _template(String name) {
    if (_templates.containsKey(name)) return _templates[name];
    final src = setup.mode.screen(name) ?? shellScreens[name];
    ScreenTemplate? t;
    if (src != null) {
      try {
        t = parseScreenTemplate(src);
      } on TemplateException catch (e) {
        _log('screen $name: ${e.message}');
      }
    }
    return _templates[name] = t;
  }

  /// The mode's sounds on the phone: its tones and the vibrator.
  Future<void> _play(String clip) async {
    switch (clip) {
      case 'explosion':
        await device.vibrate(const [0, 1500]);
        await device.tone(DeviceTone.alarm, 2000);
      case 'armed':
        await device.vibrate(const [0, 200, 100, 200]);
        await device.tone(DeviceTone.warning, 600);
      case 'defused':
        await device.vibrate(const [0, 150]);
        await device.tone(DeviceTone.success, 600);
      case 'captured':
        await device.vibrate(const [0, 150]);
        await device.tone(DeviceTone.ack, 300);
      default:
        await device.tone(DeviceTone.beep, 150);
    }
  }

  String _statusText() {
    final left = remainingMs;
    return left == null
        ? texts.notificationRunning
        : _fill(texts.notificationLeft, {'time': clockText(left)});
  }

  static String _fill(String s, Map<String, String> args) {
    var out = s;
    args.forEach((k, v) => out = out.replaceAll('{$k}', v));
    return out;
  }

  void _log(String line) {
    log.add(line);
    if (log.length > 200) log.removeRange(0, log.length - 200);
  }

  /// Ends everything: the node, the ticker, the services. The screen gets
  /// its normal behaviour back and kiosk mode is left.
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    _ticker?.cancel();
    tracker.releaseAll();
    // Not awaited: a cancelled subscription has nothing left to say.
    unawaited(_sub?.cancel());
    unawaited(_podSub?.cancel());
    unawaited(_linkSub?.cancel());
    await _link?.close();
    await _pod?.close();
    await _node?.close();
    await foreground?.stop();
    await screenManager.stop();
    if (kioskEnabled) await kiosk?.stop();
  }

  var _disposed = false;

  /// A tick or a hardware event can still be awaiting the core when the
  /// screen closes and disposes the session: what it would announce then
  /// has no one left to hear it.
  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(close());
    super.dispose();
  }
}
