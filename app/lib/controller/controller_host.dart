// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A phone's field controller, whole (slice S6 of PE24): what the Pi's
/// controller/atalaia_controller/main.py puts together, on the controller's
/// own isolate (controller_isolate.dart; never the UI isolate, constraint 1).
///
///   - the store (FileControllerStore) in the app's private storage, under
///     the controller's folder, with the field CA (field_tls.dart) and the
///     shell's own file (`shell.json`: the GM and read tokens, made on the
///     first start);
///   - the engine on the core, with an I/O pod as its radio when the shell
///     links one (pod_modem.dart, through a relay to the UI isolate's USB
///     or Bluetooth link), the check-in and positions services;
///   - the API (controller_api.dart) with the GM console's files
///     (console_files.dart) and the field CA's endpoint, on HTTP at the
///     loopback address (the app's own web view) and, once the GM opens the
///     controller to the field's Wi-Fi, on HTTPS with the field CA at every
///     address (decision PE24-62);
///   - the MQTT broker with the Pi's users and ACL, on the loopback address,
///     or every address once opened (PE24-13);
///   - slice S7b: the mode packages, presets, scenarios and branding
///     (controller_modes.dart, controller_scenarios.dart,
///     controller_branding.dart), signed packages with the app's `[modes]`
///     settings ([ControllerBoot.modes]) and the modes sent to boxes;
///   - the tick every 100 ms, and every [ControllerBoot.addressCheck] a look
///     at the phone's addresses: a new one (another network, the hotspot's
///     address) makes a new server certificate for it, the HTTPS listener
///     takes it, and the poster and join payloads name the new addresses.
///
/// Changing the radio or the Wi-Fi opening restarts the controller (the
/// shell stops this host and starts a new one on the same folder): the live
/// game is taken up again as after a restart (slice S3).
///
/// Slice S7c: the radio link is an I/O pod or a USB radio modem, whichever
/// answers (serial_modem.dart `probeRadioLink`, decision PE24-92); the free
/// boxes and invites, GAME_OVER and pairing by code (with the field join
/// key), field cards and firmware updates (releases in the controller's
/// folder, [ControllerBoot.firmwareKeys]) are set up as the Pi's main.py
/// sets them up.
///
/// Slice S7 (decisions PE24-118 onward): failover with the app's
/// `failover_mode` ([ControllerBoot.failoverMode]), the schedule always (the
/// console's area), and with the app's site server settings
/// ([ControllerBoot.sync]) the site sync (controller_sync.dart), the remote
/// GM's stream when it or the ATAK relay is on (controller_remote_gm.dart),
/// and with [ControllerBoot.atak] the CoT feed for ATAK
/// (controller_atak.dart), as the Pi's main.py builds them.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import '../ffi/bindings.dart';
import '../pod/pod_client.dart';
import 'console_files.dart';
import 'controller_adoption.dart';
import 'controller_api.dart';
import 'controller_atak.dart';
import 'controller_boxes.dart';
import 'controller_branding.dart';
import 'controller_channel.dart';
import 'controller_checkin.dart';
import 'controller_engine.dart';
import 'controller_failover.dart';
import 'controller_field.dart';
import 'controller_firmware.dart';
import 'controller_mode_fetch.dart';
import 'controller_pairing.dart';
import 'controller_radio.dart';
import 'controller_mqtt.dart';
import 'controller_positions.dart';
import 'controller_remote_gm.dart';
import 'controller_scenarios.dart';
import 'controller_schedule.dart';
import 'controller_signed_modes.dart';
import 'controller_store.dart';
import 'controller_sync.dart';
import 'field_addresses.dart';
import 'field_tls.dart';
import 'mqtt_broker.dart';
import 'pod_modem.dart';
import 'serial_modem.dart';

/// Everything a phone controller needs to start; sendable to its isolate.
final class ControllerBoot {
  const ControllerBoot({
    required this.dir,
    required this.joinKey,
    required this.limitsYaml,
    this.noticePt = '',
    this.noticeEn = '',
    this.console = const {},
    this.coreLibrary,
    this.open = true,
    this.pod = false,
    this.fieldId = 'field',
    this.fieldName = 'Atalaia',
    this.httpPort = 8080,
    this.httpsPort = 8443,
    this.mqttPort = 1883,
    this.openAddress = '0.0.0.0',
    this.addresses,
    this.addressCheck = const Duration(seconds: 10),
    this.firmwareKeys = const [],
    this.modes = const ModesConfig(),
    this.failoverMode = 'manual',
    this.sync,
    this.atak,
  });

  /// The controller's folder in the app's private storage.
  final String dir;

  /// The field join key (32 bytes; join payloads are sealed with it).
  final Uint8List joinKey;

  /// The chrono limit template (lib/chrono/limit_templates, as text).
  final String limitsYaml;

  /// The check-in privacy notices (controller/templates/checkin-notice-*.md).
  final String noticePt;
  final String noticeEn;

  /// The GM console's files by path (console_files.dart).
  final Map<String, Uint8List> console;

  /// The core's library (null: the APK's).
  final String? coreLibrary;

  /// Open to the field's Wi-Fi: HTTPS and MQTT at every address.
  final bool open;

  /// Whether an I/O pod is linked (its bytes come through the relay).
  final bool pod;

  /// The field's id and name for check-in (the Pi's `[checkin] field_id`
  /// and `field_name`; the GM changes the name from the console's poster).
  final String fieldId;
  final String fieldName;

  /// Ports: 0 lets the system choose (tests).
  final int httpPort;
  final int httpsPort;
  final int mqttPort;

  /// The address the open listeners take (tests: the loopback address).
  final String openAddress;

  /// Fixed addresses instead of the phone's interfaces (tests).
  final List<String>? addresses;
  final Duration addressCheck;

  /// The firmware release keys' public halves (standard base64, at most 8;
  /// the Pi's `[firmware] release_keys`): none, no release is accepted.
  final List<String> firmwareKeys;

  /// The Pi's `[modes]` settings: trusted mode keys, revoked key ids, the
  /// registry index, the boxes' mode keys (slice S7b, decision PE24-82).
  final ModesConfig modes;

  /// `manual` or `auto` (ADR-P2-8; slice S7's failover).
  final String failoverMode;

  /// The site server's settings ([SyncConfig.toJson]); null: no sync.
  final Map<String, Object?>? sync;

  /// The `[atak]` section ([AtakConfig.fromSection]'s keys); null: off.
  final Map<String, Object?>? atak;
}

/// The controller's own secrets, kept in `shell.json` beside its store.
final class ShellSecrets {
  const ShellSecrets({required this.gmToken, required this.readToken});

  final String gmToken;
  final String readToken;

  /// Read from [dir], or made and written there on the first start.
  static ShellSecrets load(String dir, [Random? random]) {
    final f = File('$dir/shell.json');
    if (f.existsSync()) {
      try {
        final j = jsonDecode(f.readAsStringSync()) as Map;
        final gm = j['gm_token'];
        final read = j['read_token'];
        if (gm is String &&
            read is String &&
            gm.isNotEmpty &&
            read.isNotEmpty) {
          return ShellSecrets(gmToken: gm, readToken: read);
        }
      } on Object {
        // A damaged file: new tokens below.
      }
    }
    final r = random ?? Random.secure();
    String token(String prefix) =>
        prefix +
        base64Url
            .encode(List<int>.generate(18, (_) => r.nextInt(256)))
            .replaceAll('=', '');
    final s = ShellSecrets(gmToken: token('gm-'), readToken: token('rd-'));
    final tmp = File('${f.path}.tmp');
    tmp.writeAsStringSync(
      jsonEncode({
        'format': 1,
        'gm_token': s.gmToken,
        'read_token': s.readToken,
      }),
      flush: true,
    );
    tmp.renameSync(f.path);
    return s;
  }
}

/// A pod link through the UI isolate: what the pod sends arrives with
/// [receive], what the controller sends goes to [onSend].
final class RelayPodTransport implements PodTransport {
  RelayPodTransport(this.kind, this.onSend, {this.onClose});

  @override
  final String kind;
  final void Function(Uint8List bytes) onSend;
  final void Function()? onClose;
  final _in = StreamController<Uint8List>.broadcast(sync: true);

  void receive(Uint8List bytes) {
    if (!_in.isClosed) _in.add(bytes);
  }

  /// The link went (the UI isolate's USB or Bluetooth link closed).
  Future<void> linkClosed() => _in.close();

  @override
  Stream<Uint8List> get incoming => _in.stream;

  @override
  Future<void> send(Uint8List bytes) async {
    if (!_in.isClosed) onSend(bytes);
  }

  @override
  Future<void> close() async {
    onClose?.call();
    if (!_in.isClosed) await _in.close();
  }
}

class ControllerHost {
  ControllerHost(
    this.boot, {
    this.core,
    this.podTransport,
    Future<List<String>> Function()? addresses,
    DateTime Function()? now,
  }) : _addressesOf = addresses ?? localAddresses,
       _now = now ?? DateTime.now;

  final ControllerBoot boot;
  final AtalaiaCore? core;
  final PodTransport? podTransport;
  final Future<List<String>> Function() _addressesOf;
  final DateTime Function() _now;

  late final ShellSecrets secrets;
  late FieldTls tls;
  late final ControllerEngine engine;
  late final ControllerCheckin checkin;
  late final ControllerApi api;

  /// Slice S7: the site sync, the remote GM's stream and the ATAK feed
  /// (null: off), and why a setting left one off.
  ControllerSync? sync;
  RemoteGm? remote;
  AtakEmitter? atak;
  String? syncProblem, atakProblem;
  late final MqttBroker broker;
  late final ControllerMqtt bridge;
  late final HttpServer http;
  HttpServer? https;
  PodClient? _podClient;
  PodModem? _podModem;
  SerialModem? _serialModem;

  /// The radio: an I/O pod, or a USB radio modem ([radioKind]).
  ControllerModem? modem;

  /// "pod", "modem", or null without a radio link.
  String? radioKind;
  Timer? _ticker;
  Timer? _watcher;
  var _addresses = <String>[];
  var _running = false;
  var _checking = false;

  /// Called when what [status] says changes (a game, the addresses).
  void Function()? onChange;

  List<String> get addresses => List.unmodifiable(_addresses);

  /// The https addresses phones use (the poster, join key 14): up to 3.
  List<String> get urls =>
      boot.open ? _fieldAddresses().plan().defaultUrls : const [];

  /// The phone's addresses now, with the rules of the poster's addresses
  /// (field_addresses.dart, decision check-R8).
  FieldAddresses _fieldAddresses([List<String>? addresses]) => FieldAddresses(
    found: addresses ?? _addresses,
    interfaces: addresses ?? _addresses,
    tlsPort: https?.port ?? boot.httpsPort,
    filterFound: false, // localAddresses has filtered them
  );

  /// The names the server certificate covers: a superset of the poster's
  /// addresses (check-R9), so a poster address never fails with a name
  /// mismatch; an address that is stale is in neither.
  List<String> _certificateNames(
    String? savedPoster, {
    List<String>? addresses,
    List<String> checkinUrls = const [],
  }) => _fieldAddresses(
    addresses,
  ).plan(saved: savedPosterUrls(savedPoster), checkinUrls: checkinUrls).san;

  Future<List<String>> _currentAddresses() async =>
      boot.addresses ?? await _addressesOf();

  Future<void> start() async {
    final dir = Directory(boot.dir)..createSync(recursive: true);
    secrets = ShellSecrets.load(dir.path);
    _addresses = await _currentAddresses();
    final store = FileControllerStore(Directory('${dir.path}/store'));
    tls = FieldTls.ensure(
      '${dir.path}/tls',
      _certificateNames(store.getSetting('checkin.poster')),
      fieldName: boot.fieldName,
      now: _now(),
    );
    final pod = podTransport;
    if (boot.pod && pod != null) {
      radioKind = await probeRadioLink(pod);
      if (radioKind == 'modem') {
        modem = _serialModem = SerialModem(pod);
      } else {
        _podClient = PodClient(pod);
        modem = _podModem = PodModem(_podClient!);
      }
    }
    engine = ControllerEngine(
      // A phone on its battery (ADR-P2-8: power source 1).
      config: ControllerConfig(
        powerSource: 1,
        failoverMode: failoverModes.contains(boot.failoverMode)
            ? boot.failoverMode
            : 'manual',
      ),
      store: store,
      core: core,
      modem: modem,
    )..joinKey = boot.joinKey;
    checkin = ControllerCheckin(
      engine,
      CheckinConfig(
        limitsYaml: boot.limitsYaml,
        fieldId: boot.fieldId,
        fieldName: boot.fieldName,
        noticePt: boot.noticePt,
        noticeEn: boot.noticeEn,
      ),
      caSha256: tls.caSha256,
    );
    ControllerPositions(engine);
    // Slice S7a: the field plan's images as files in the controller's
    // folder (decision PE24-75), and the radio channel.
    ControllerField(engine, dir: Directory('${dir.path}/field'));
    ControllerChannel(engine);
    // Slice S7c, as the Pi's main.py: adoption and firmware updates always;
    // the boxes over the radio and pairing with the field join key.
    ControllerAdoption(engine);
    ControllerFirmware(
      engine,
      firmwareDir(dir.path),
      keys: validReleaseKeys(boot.firmwareKeys),
    );
    if (boot.joinKey.length == 32) {
      ControllerBoxes(engine);
      ControllerPairing(engine);
    }
    // Slice S7b: scenarios, branding, signed packages, modes sent to boxes.
    ControllerScenarios(engine);
    ControllerBranding(engine, fieldId: boot.fieldId);
    engine.signedModes = ControllerSignedModes(engine.modes, boot.modes);
    ControllerModeFetch(
      engine,
      boot.modes.boxKeys,
      timeoutS: boot.modes.fetchTimeoutS,
    );
    api = ControllerApi(
      engine,
      gmToken: secrets.gmToken,
      readToken: secrets.readToken,
    );
    _startSiteAndAtak();
    api
      ..console = ConsoleFiles(boot.console)
      ..caPem = tls.caPem
      ..caSha256Hex = tls.caHex;
    final where = boot.open
        ? InternetAddress(boot.openAddress)
        : InternetAddress.loopbackIPv4;
    broker = MqttBroker(
      port: boot.mqttPort,
      address: where,
      users: {'gm': secrets.gmToken, 'reader': secrets.readToken},
      acl: MqttAcl.field,
    );
    await broker.start();
    bridge = ControllerMqtt.onBroker(engine, broker);
    http = await HttpServer.bind(InternetAddress.loopbackIPv4, boot.httpPort);
    http.listen((r) => unawaited(api.serveRequest(r)));
    if (boot.open) await _bindHttps(boot.httpsPort);
    _applyLinks();
    engine.addListener(_onMessage);
    await _podModem?.start();
    await _serialModem?.start();
    _ticker = Timer.periodic(
      const Duration(milliseconds: 100),
      (_) => engine.tick(),
    );
    _watcher = Timer.periodic(boot.addressCheck, (_) => unawaited(check()));
    _running = true;
  }

  /// Slice S7: the schedule, the site sync, the remote GM and ATAK, as the
  /// Pi's main.py `build` (a setting that does not pass its check leaves
  /// that part off and says why in [status]).
  void _startSiteAndAtak() {
    ControllerSchedule(engine);
    final cfg = SyncConfig.fromJson(boot.sync);
    if (boot.sync != null) {
      syncProblem = cfg == null ? 'the settings are damaged' : cfg.problem();
    }
    ControllerSync? s;
    if (cfg != null && syncProblem == null) {
      s = sync = ControllerSync(engine, cfg, schedule: engine.schedule)
        ..start();
    }
    AtakConfig? a;
    final section = boot.atak;
    if (section != null) {
      try {
        a = AtakConfig.fromSection(section)
          ..checkConfig(syncEnabled: s != null);
      } on AtakConfigError catch (e) {
        atakProblem = e.message;
      }
    }
    RemoteGm? r;
    if (s != null && cfg != null && (cfg.remoteGm || a?.remote == true)) {
      r = remote = RemoteGm(
        engine,
        s,
        remoteGm: cfg.remoteGm,
        atakRemote: a?.remote == true,
      )..start();
    }
    if (a != null && a.enabled) {
      final emitter = atak = AtakEmitter(engine, a, fieldId: boot.fieldId);
      engine.atakStatus = emitter.status;
      if (r != null) {
        emitter.remoteSink = (events) => r!.pushCot(events);
        r.onRelay = (on) => emitter.remoteReady = on;
      }
      emitter.start();
    }
  }

  Future<void> _bindHttps(int port) async {
    final s = await HttpServer.bindSecure(
      InternetAddress(boot.openAddress),
      port,
      tls.context(),
    );
    s.listen((r) => unawaited(api.serveRequest(r)));
    https = s;
  }

  /// The poster's default addresses and join payloads' keys 13 and 14; the
  /// saved poster's and `config.urls`' addresses are checked against the
  /// phone's addresses now (check-R8).
  void _applyLinks() {
    final u = urls;
    checkin.defaultUrls = List.of(u);
    checkin.useAddresses(_fieldAddresses());
    engine
      ..caSha256 = boot.open ? tls.caSha256 : null
      ..linkUrls = u;
  }

  void _onMessage(Map<String, Object?> m) {
    final t = m['type'];
    if (t == 'game' || t == 'system') onChange?.call();
  }

  /// A look at the phone's addresses (every [ControllerBoot.addressCheck]):
  /// on a change, or a server certificate near its end, a new certificate
  /// and the HTTPS listener again on the same port.
  Future<void> check() async {
    if (!_running || _checking) return;
    _checking = true;
    try {
      final now = await _currentAddresses();
      final changed = now.join(',') != _addresses.join(',');
      // The poster's addresses are in the certificate (check-R9): a name the
      // GM saved on the poster since the last look makes a new one too.
      final names = _certificateNames(
        checkin.engine.store.getSetting('checkin.poster'),
        addresses: now,
        checkinUrls: checkin.config.urls,
      );
      final due =
          tls.notAfter.difference(_now().toUtc()) <
          const Duration(days: renewDays);
      final namesChanged = names.join(',') != tls.names.join(',');
      if (!changed && !due && !namesChanged) return;
      _addresses = now;
      tls = FieldTls.ensure(
        tls.dir,
        names,
        fieldName: boot.fieldName,
        now: _now(),
      );
      final old = https;
      if (old != null) {
        final port = old.port;
        await old.close();
        await _bindHttps(port);
      }
      _applyLinks();
      onChange?.call();
    } finally {
      _checking = false;
    }
  }

  /// What the controller's screen shows (controller_isolate.dart sends it).
  Map<String, Object?> status() {
    final g = engine.liveGame;
    Map<String, Object?>? game;
    if (g != null) {
      final view = engine.publicGame(g);
      game = {
        'id': view['id'],
        'name': view['name'],
        'mode_id': view['mode_id'],
        'teams': view['teams'],
        'state': view['state'],
        'game_time_ms': view['game_time_ms'],
        'duration_ms': view['duration_ms'],
        'key_lost': view['key_lost'] == true,
      };
    }
    return {
      'running': _running,
      'open': boot.open,
      'http_port': http.port,
      'https_port': https?.port,
      'mqtt_port': broker.boundPort,
      'addresses': addresses,
      'urls': urls,
      'ca_sha256': tls.caHex,
      'ca_short': tls.caShort,
      'cert_names': tls.names,
      'gm_token': secrets.gmToken,
      'read_token': secrets.readToken,
      'radio': engine.radioState,
      'pod': boot.pod,
      'radio_kind': radioKind,
      'field_frames': modem?.hasFieldFrames ?? false,
      'game': game,
      'stream_clients': api.hub.clientCount,
      'mqtt_clients': broker.clientCount,
      'props': api.props.count,
      'console': !api.console.isEmpty,
      'sync': sync != null,
      'sync_problem': syncProblem,
      'remote_gm': remote?.remoteGm ?? false,
      'atak': atak != null,
      'atak_problem': atakProblem,
    };
  }

  /// Stops everything; the store keeps the live game for the next start.
  Future<void> stop() async {
    if (!_running) return;
    _running = false;
    _ticker?.cancel();
    _watcher?.cancel();
    engine.removeListener(_onMessage);
    await atak?.stop();
    await remote?.stop();
    await sync?.stop();
    await api.props.close();
    await api.hub.close();
    await http.close(force: true);
    await https?.close(force: true);
    await broker.stop();
    await _podModem?.close();
    await _serialModem?.close();
    await _podClient?.close();
    engine.close();
  }
}
