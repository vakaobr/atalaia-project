// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android prop's game (plan phase D, the "Android prop shell"): what a
/// Field Box's shell does, for a phone. It runs the mode on the shared core
/// in a game loop isolate (lib/core/), turns the touchscreen's team buttons
/// and keypad, NFC tags and an I/O pod's events into the mode's inputs,
/// draws the mode's screens (ui.screen) with the template renderer, plays
/// its sounds, keeps the game's length and sends game.end when it runs out
/// (decision PC6), and holds the foreground service, the screen manager and
/// kiosk mode while the game runs (ADR-P3-5). A role that uses `gps` (VIP /
/// Payload's payload) gets the phone's fixes as `gps.fix` (lat, lon, acc;
/// one without lat and lon when the game starts, before the first fix): they
/// reach the mode's script on the phone only, never the controller (decision
/// P4R6).
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
/// A linked pod's simple outputs (draft RFC "The expansion port", increment
/// 9) are the mode's `cap("siren")` and the controller's CMD 12 (`output`),
/// handled by [outputs] with a box's rules: on only while the game runs (and
/// in the end's 10 s grace), off at its start, a pause, the end and a halted
/// script; each start is an output.switched for the controller.
///
/// HELLO lists the prop's capability types ([helloCapabilities]: the
/// phone's own parts and what its pod lends), so the controllers' start
/// check takes a prop as it takes a box; they are said again whenever the
/// pod's IDENT changes them, the pod's link breaks or the person unlinks it
/// (decisions PROPC-1 to PROPC-4).
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
import '../platform/location.dart';
import '../platform/services.dart';
import '../pod/pod_client.dart';
import '../pod/pod_codec.dart';
import '../pod/pod_reconnect.dart';
import '../pod/pod_transports.dart' show PodDevice;
import '../protocol/join_payload.dart';
import '../radio/pod_radio_link.dart';
import '../security/ndef.dart';
import '../security/nfc_tag_signer.dart';
import '../ui/template/screen_template.dart';
import 'button_tracker.dart';
import 'capability_mapper.dart';
import 'game_timer.dart';
import 'prop_hits.dart';
import 'prop_outputs.dart';
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
    this.reopenPod,
    this.podBackoff = defaultPodBackoff,
    this.podIdentWait = podIdentTimeout,
    this.location,
    this.gpsInterval = const Duration(seconds: 2),
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

  /// Opens the linked pod again after its link broke (null: the link is
  /// not reopened); see [PodReconnector].
  final PodReopen? reopenPod;
  final PodBackoff podBackoff;
  final Duration Function(PodClient) podIdentWait;

  /// The phone's location, for a role that uses `gps` (null: none).
  final LocationService? location;

  /// How often the location service is asked for a fix.
  final Duration gpsInterval;
  StreamSubscription<LocationFix>? _gpsSub;

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
  PodReconnector? _podLink;

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

  /// What STATE carries from the same snapshot: the points gained (counters)
  /// and the points lost to penalties (key 9) per team name.
  Map<String, int> _gained = const {};
  Map<String, int> _lost = const {};

  /// The game's log: events, the script's log lines, errors (newest last).
  final log = <String>[];

  /// The linked pod's simple outputs (prop_outputs.dart).
  late final PropOutputs outputs = PropOutputs(
    send: (cap, method, args) {
      final pod = _pod;
      if (pod != null && !pod.broken) unawaited(pod.command(cap, method, args));
    },
    ping: () =>
        unawaited(_pod?.sendRadio(FrameType.radioCmd, const [RadioOp.ping])),
    onSwitched: _outputSwitched,
    onScriptError: (message) {
      _log(message);
      _link?.sendEvent(
        seq: ++_shellSeq,
        tMs: gameTimeMs,
        type: 'script.error',
        prio: 'normal',
        data: {'message': message},
      );
    },
  );

  /// The linked pod's hit sensors (a target module on its expansion port:
  /// prop_hits.dart).
  late final PropHits hits = PropHits(
    send: (cap, method, args) {
      final pod = _pod;
      if (pod != null && !pod.broken) unawaited(pod.command(cap, method, args));
    },
  );

  /// The node.modules text last told to the controller (the pod's, from its
  /// EVT pod.modules), or null before any.
  String? _modulesTold;

  /// The phone's features (read when the session opens) and the pod whose
  /// IDENT HELLO counts (null: none, or its link is down or unlinked).
  DeviceFeatures? _features;
  PodIdent? _capsPod;

  /// What this prop offers a mode: the phone's parts and its pod's.
  CapabilityMap get capabilities =>
      CapabilityMap.of(_features ?? const DeviceFeatures(), pod: _capsPod);

  /// HELLO's capability type ids (key 6), as the controller last heard them
  /// or will hear them.
  List<int> get helloCapabilities => capabilities.helloTypes;

  /// The controller hears the prop's capability types again when they
  /// changed (DualLink sends nothing when they did not).
  void _tellCapabilities() {
    final l = _link;
    if (l == null) return;
    final ids = helloCapabilities;
    final old = l.capabilities;
    if (old != null && listEquals(old, ids)) return;
    _log('HELLO capabilities ${ids.join(',')}');
    l.updateCapabilities(ids);
  }

  int get _nowMs => _now().millisecondsSinceEpoch;

  /// Kiosk mode was left while the game ran (ADR-P3-9 tamper detection).
  bool tamper = false;

  /// The pod's enclosure is open (its tamper switch, during the game).
  bool podOpened = false;

  /// The pod linked to this prop, if any (none once the person unlinked it).
  PodIdent? get pod => podPhase == PodLinkPhase.unlinked ? null : _pod?.ident;

  /// The pod link's state: up, being opened again, refused (another pod
  /// answered) or unlinked by the person; null without a pod.
  PodLinkPhase? get podPhase =>
      _pod == null ? null : _podLink?.phase ?? PodLinkPhase.linked;

  /// Tries made to open the pod again, and when the next one starts.
  int get podAttempt => _podLink?.attempt ?? 0;
  DateTime? get podRetryAt => _podLink?.retryAt;

  /// Over Bluetooth, while the pod pairs anew by itself (the phone's bond
  /// was removed: Android asks for the passkey on the pod's screen).
  bool get podRepairing => _podLink?.repairing ?? false;

  /// Why the pod has to be linked again by hand ([PodLinkPhase.relink]): a
  /// message key ("pod.wrong_passkey", "pod.pair_timeout",
  /// "pod.repair_manual"), else null.
  String? get podRelinkMessage => _podLink?.relinkMessage;

  /// The pod this prop expects: the one first linked (its name and address,
  /// null for a link not opened from a scan) and what it said it lends. A
  /// [PodLinkPhase.refused] link names it, since another pod answered.
  PodDevice? get podDevice => _pod?.device;
  PodIdent? get podExpected => _pod?.ident;

  /// The admin's "Link the pod again" is offered (decision ROB-9): the
  /// tries stopped or another pod answered.
  bool get canRelinkPod =>
      _podLink != null &&
      (podPhase == PodLinkPhase.relink || podPhase == PodLinkPhase.refused);

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
          gameKey: setup.gameKey,
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
          try {
            _features = await device.features();
          } on Object {
            // Unknown: the screen's parts and the speaker, as a phone has.
          }
          _tellCapabilities();
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
    // The outputs first: what the mode's game.start handlers switch is the
    // game's (as on a box).
    outputs.gameStart(_nowMs);
    hits.gameStart();
    final ok = await _node?.input('game.start') ?? false;
    if (!ok) return;
    phase = PropPhase.running;
    _startGps();
    await screenManager.start();
    await foreground?.start(
      title: _fill(texts.notificationTitle, {'mode': modeName}),
      text: _statusText(),
    );
    if (kioskEnabled) await kiosk?.start();
    notifyListeners();
  }

  /// Whether the role's script takes the phone's position (`gps`).
  bool get usesGps => setup.mode.main.role(setup.role)?.uses('gps') ?? false;

  /// The phone's fixes as gps.fix while the game runs: first one without a
  /// position (the script shows that it is looking), then every fix. The
  /// core drops them while the game is paused.
  void _startGps() {
    final l = location;
    if (l == null || !usesGps || _gpsSub != null) return;
    unawaited(_input('gps.fix', const {}));
    _gpsSub = l
        .fixes(gpsInterval)
        .listen(gpsFix, onError: (Object e) => _log('location: $e'));
  }

  /// A fix from the phone's GPS for the mode's script (tests call it too).
  Future<void> gpsFix(LocationFix f) {
    if (!running) return Future.value();
    return _input('gps.fix', {'lat': f.lat, 'lon': f.lon, 'acc': ?f.accuracyM});
  }

  void _stopGps() {
    unawaited(_gpsSub?.cancel());
    _gpsSub = null;
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
  /// its capabilities go to it. With [reopenPod] a broken link is opened
  /// again by itself (lib/pod/pod_reconnect.dart).
  Future<void> attachPod(PodClient client) async {
    _pod = client;
    _listenPod(client);
    final reopen = reopenPod;
    if (reopen != null) {
      _podLink = PodReconnector(
        client: client,
        reopen: reopen,
        backoff: podBackoff,
        identTimeout: podIdentWait,
        onReplaced: _podReplaced,
        onRepair: () => _log('pod: its bond was refused, pairing again'),
      )..addListener(_podLinkChanged);
    }
    await client.start();
  }

  void _podLinkChanged() {
    final why = _podLink?.relinkMessage;
    if (why != null && why != _podRelinkLogged) {
      _podRelinkLogged = why;
      _log('pod: link it again ($why)');
    }
    notifyListeners();
  }

  String? _podRelinkLogged;

  /// The admin links the same pod again during the game (decision ROB-9):
  /// the reconnect starts again at once, Android's pairing dialog included
  /// and one automatic pairing again at most. The game goes on meanwhile;
  /// once the pod is back, its inputs, outputs, capabilities and radio are
  /// taken again as after a reconnect ([_podReplaced]). False when the pod
  /// is not in a phase that needs it.
  bool relinkPod() {
    final link = _podLink;
    if (link == null || !canRelinkPod || _closed) return false;
    _log('pod: linking it again (admin)');
    _podRelinkLogged = null;
    return link.restart();
  }

  /// The person unlinks the pod: it is closed and not opened again.
  Future<void> unlinkPod() async {
    final pod = _pod;
    if (pod == null) return;
    _log('pod unlinked');
    _podInputs = null;
    outputs.detach(_nowMs);
    hits.detach();
    // Its outputs and modules are gone from this prop: the controller is told.
    if (_modulesTold != null && _modulesTold!.isNotEmpty) _tellModules('');
    _capsPod = null;
    _tellCapabilities();
    final link = _podLink;
    if (link != null) {
      await link.unlink();
    } else {
      await pod.close();
    }
    notifyListeners();
  }

  /// The reconnector opened the pod again (the same one, identified): its
  /// events and the radio through it replace the lost link's.
  void _podReplaced(PodClient old, PodClient next) {
    if (_closed) {
      unawaited(next.close());
      return;
    }
    _pod = next;
    _listenPod(next);
    _log('pod link restored');
    final ident = next.ident;
    if (ident != null) _onPod(next, PodIdentified(ident), reconnected: true);
  }

  void _listenPod(PodClient client) {
    unawaited(_podSub?.cancel());
    _podSub = client.events.listen((e) => _onPod(client, e));
  }

  void _onPod(PodClient client, PodEvent e, {bool reconnected = false}) {
    if (!identical(client, _pod)) return;
    switch (e) {
      case PodIdentified(:final ident):
        _podInputs = PodInputs(ident, teams: setup.teams);
        outputs.attach(ident);
        hits.attach(ident.capabilities);
        _log(
          'pod ${ident.fwVersion}: ${ident.capabilities.length} capabilities',
        );
        // HELLO first, so a radio through this pod starts with them too.
        _capsPod = ident;
        _tellCapabilities();
        _attachRadio(client, ident, replace: reconnected);
        notifyListeners();
      case PodCapabilityEvent(:final message):
        if (message.capId == 'pod' && message.name == 'config') {
          _podSettingsTaken(message.data);
          return;
        }
        if (message.capId == 'pod' && message.name == 'modules') {
          _podModules(message.data);
          return;
        }
        if (message.capId == 'pod' && message.name == 'module_lost') {
          _podModuleLost(message.data);
          return;
        }
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
        if (mapped == null) return;
        // A hit reaches the mode only while the game runs, as on a box.
        if (mapped.$1 == 'hit.hit' && !hits.take()) return;
        unawaited(_input(mapped.$1, mapped.$2));
      case PodLinkBroken(:final why):
        _log('pod link lost: $why');
        _podInputs = null;
        // The pod turns its outputs off when its link goes (pod_outputs.c),
        // and forgets its hit sensors' arming (pod_port.c).
        outputs.detach(_nowMs);
        hits.detach();
        // What it lent is not this prop's while its link is down: HELLO
        // (on Wi-Fi; a radio through it is down too) says so, and the
        // next IDENT lends it again.
        _capsPod = null;
        _tellCapabilities();
        notifyListeners();
      case PodRadioFrame():
        break; // the radio link (PodRadioLink) reads them
    }
  }

  /// A pod with a radio in a joined game: the field's radio joins the links.
  void _attachRadio(PodClient client, PodIdent ident, {bool replace = false}) {
    final l = _link;
    final make = radioLinkFor;
    if (!ident.hasRadio || l == null || make == null) return;
    // After a reconnect the lost link's radio is replaced: a new one,
    // configured again with a new epoch.
    if (l.radio != null && !replace) return;
    final r = make(client);
    if (r == null) return;
    _log('radio link through the pod');
    unawaited(l.attachRadio(r, hello: link?.hello ?? const {}));
  }

  /// An output switched on, or off before its time: output.switched for the
  /// controller (normal priority), as a box sends it.
  void _outputSwitched(int tMs, Map<String, Object?> data) {
    _log(
      'output.switched ${data['capability']} ${data['ms']} ${data['source']}',
    );
    _link?.sendEvent(
      seq: ++_shellSeq,
      tMs: gameTimeMs,
      type: 'output.switched',
      prio: 'normal',
      data: data,
    );
    notifyListeners();
  }

  /// The pod's EVT pod.modules (its simple outputs and the modules on its
  /// expansion port, in node.modules' text; each lent output's longest on):
  /// told to the controller as node.modules when the text changed, as a box
  /// tells it (EXP-21), and the longest ons taken for the outputs' model.
  void _podModules(Map<String, Object?> data) {
    final maxOn = data['max_on_s'];
    if (maxOn is Map) outputs.maxOn(maxOn.cast<String, Object?>());
    final text = data['modules'];
    if (text is! String || text == _modulesTold) return;
    _tellModules(text);
  }

  void _tellModules(String text) {
    _modulesTold = text;
    _log('node.modules ${text.isEmpty ? '(none)' : text}');
    _link?.sendEvent(
      seq: ++_shellSeq,
      tMs: gameTimeMs,
      type: 'node.modules',
      prio: 'normal',
      data: {'modules': text},
    );
    notifyListeners();
  }

  /// A module on the pod's port stopped answering: node.module_lost
  /// (critical) during a game, as a box tells it; between games the next
  /// node.modules says it.
  void _podModuleLost(Map<String, Object?> data) {
    final text = data['modules'];
    if (text is! String) return;
    _log('module lost: $text ${data['reason']}');
    if (!running) return;
    _link?.sendEvent(
      seq: ++_shellSeq,
      tMs: gameTimeMs,
      type: 'node.module_lost',
      prio: 'critical',
      data: {
        'modules': text,
        'reason': data['reason'] is String ? data['reason'] : 'no_answer',
      },
    );
  }

  /// The pod took the settings the field controller pushed over the radio
  /// (EVT pod.config {"rev"}, protocol/pod-config.md): said over the radio
  /// as node.setup_applied, the acknowledgement the boxes' setups use, so
  /// the controller stops sending them again. The radio's own ACKs and
  /// resends carry it (normal priority).
  void _podSettingsTaken(Map<String, Object?> data) {
    final rev = data['rev'];
    if (rev is! int) return;
    _log('pod settings rev $rev taken');
    _link?.sendEvent(
      seq: ++_shellSeq,
      tMs: gameTimeMs,
      type: 'node.setup_applied',
      prio: 'normal',
      data: {'kind': 'pod_config', 'rev': rev},
    );
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
    outputs.tick(_nowMs);
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
    final before = (gameTimeMs ~/ 1000, scores, phase, _lost);
    gameTimeMs = s.timeMs;
    scores = s.scores;
    _gained = s.gained;
    _lost = s.lost;
    _phaseFrom(s);
    if (phase == PropPhase.running && timer.update(gameTimeMs)) {
      // The game's length is up: the shell ends the game (decision PC6).
      _log('time is up: game.end');
      outputs.end(_nowMs);
      await node.input('game.end');
    }
    if (before != (gameTimeMs ~/ 1000, scores, phase, _lost)) {
      if (_link != null && (before.$2 != scores || before.$4 != _lost)) {
        _sendState();
      }
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
      // The gains, not the net: a penalty never takes a counter back (the
      // controller merges by maximum), it goes in `lost` (STATE key 9, sent
      // only when there is one, as a box does).
      'counters': {
        for (var i = 0; i < setup.teams.length; i++)
          if ((_gained[setup.teams[i]] ?? 0) > 0)
            '${i + 1}': _gained[setup.teams[i]],
      },
      'lost': {
        for (var i = 0; i < setup.teams.length; i++)
          if ((_lost[setup.teams[i]] ?? 0) > 0)
            '${i + 1}': _lost[setup.teams[i]],
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
          case 'peer':
            // A node's epoch for the receivers (RFC 0001 Amendment 24, decision EP-1): over Wi-Fi the prop has
            // no radio of its own, but a pod's receiver follows what the controller names, as a box does.
            if (radio?.applyPeerEpoch(params) ?? false) {
              _log(
                'peer epoch ${params['src']} at ${params['epoch']} told to the pod',
              );
            }
          case 'output':
            // CMD 12 (RFC 0001 Amendment 26): the shell's, whatever the
            // mode, as on a box (box_game.c).
            final r = outputs.command(_nowMs, params);
            _log('CMD output ${params['capability']} ${params['act']}: $r');
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
    if (phase == PropPhase.halted) {
      error = s.lastError;
      outputs.halt(_nowMs);
      hits.end();
    }
    // The mode ended the game: its game.end event has turned them off
    // already; this covers a snapshot that saw the end first.
    if (phase == PropPhase.ended) {
      outputs.end(_nowMs);
      hits.end();
    }
    if (phase == PropPhase.ended || phase == PropPhase.halted) {
      _stopGps();
      tracker.releaseAll();
      unawaited(foreground?.stop());
    }
  }

  Future<void> _input(String type, [Map<String, Object?>? data]) async {
    final node = _node;
    if (node == null || _closed) return;
    // The outputs before the mode's handlers (node_runner.c): a pause or an
    // end turns them off, and what a game.end handler switches is the grace's.
    switch (type) {
      case 'game.pause':
        outputs.pause(_nowMs);
        hits.pause();
      case 'game.resume':
        outputs.resume();
        hits.resume();
      case 'game.end':
        outputs.end(_nowMs);
        hits.end();
    }
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
        // The mode ended the game (game.finish, game.win): every output off
        // before its game.end handlers' commands, which come after it.
        if (event.type == 'game.end') {
          outputs.end(_nowMs);
          hits.end();
        }
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
        _gained = snapshot.gained;
        _lost = snapshot.lost;
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
      // The game's language as "lang" (join key 15), unless the mode gives
      // one, as a Field Box does: the built-in templates show their pt, de
      // or zh-tw texts for it, English otherwise (decision P5H-12).
      final lang = setup.join?.lang;
      screenData = lang != null && !data.containsKey('lang')
          ? {'lang': lang, ...data}
          : data;
      template = _template(name);
      unawaited(screenManager.activity());
      return;
    }
    if (c.target == 'audio') {
      if (c.method == 'play' && args.isNotEmpty) unawaited(_play('${args[0]}'));
      return;
    }
    // One of the pod's outputs: the box's rules, then the pod's CMD.
    if (outputs.scriptCall(_nowMs, c.target, c.method, args)) return;
    // A hit sensor's arm or disarm: kept, and told to the pod while the game
    // runs.
    if (hits.scriptCall(c.target, c.method)) return;
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
    _stopGps();
    tracker.releaseAll();
    // Not awaited: a cancelled subscription has nothing left to say.
    unawaited(_sub?.cancel());
    unawaited(_podSub?.cancel());
    _podLink?.dispose();
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
