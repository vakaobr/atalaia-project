// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The ATAK / CoT emitter on the phone controller (lib/controller/
// controller_atak.dart, PE24 slice S7) against the Pi's: its known answers
// (protocol/vectors/atak_xml.json, written by tools/atak_xml_vectors.py
// from atak.py), the CoT facts of protocol/vectors/cot.json, and the Pi's
// test_atak.py and test_map_features.py cases ported to the engine: props
// on the georeferenced plan, captures sent at once, drops when the game
// ends or the map position goes, the extraction zone, map features by
// visibility, players to staff TCP only, the remote relay's narrow form
// (every event passes controller_sync_format.dart's cotEvent), the [atak]
// settings; over a real UDP socket and a real TCP listener on the loopback.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_atak.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_field.dart';
import 'package:atalaia_app/controller/controller_positions.dart'
    show ControllerPositions;
import 'package:atalaia_app/controller/controller_sync_format.dart'
    show XmlElement, cotEvent, parseXmlElement;
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';

final _vectors =
    jsonDecode(File('../protocol/vectors/atak_xml.json').readAsStringSync())
        as Map<String, Object?>;
final _cot =
    jsonDecode(File('../protocol/vectors/cot.json').readAsStringSync())
        as Map<String, Object?>;

List<Map<String, Object?>> _list(Object? v) => [
  for (final e in v! as List) (e as Map).cast<String, Object?>(),
];

Map<String, Object?> _map(Object? v) => (v! as Map).cast<String, Object?>();

final png = base64.decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC'
  'hwGA60e6kgAAAABJRU5ErkJggg==',
);
const tl = {'x': 0.0, 'y': 0.0, 'lat': 38.7240, 'lon': -9.1420};
const br = {'x': 1.0, 'y': 1.0, 'lat': 38.7200, 'lon': -9.1360};
const hostile = '</remarks><x a="1">&amp; \'"\x01\x1b\ud800￾\n\tCaixa';
const hostileClean = '</remarks><x a="1">&amp; \'" Caixa';
const square = [
  {'x': 0.1, 'y': 0.1},
  {'x': 0.4, 'y': 0.1},
  {'x': 0.4, 'y': 0.4},
  {'x': 0.1, 'y': 0.4},
];

Map<String, Object?> point([Map<String, Object?> kw = const {}]) => {
  'type': 'first_aid',
  'shape': 'point',
  'x': 0.5,
  'y': 0.5,
  ...kw,
};
Map<String, Object?> circle([Map<String, Object?> kw = const {}]) => {
  'type': 'safe_zone',
  'shape': 'circle',
  'x': 0.25,
  'y': 0.75,
  'radius_m': 30,
  ...kw,
};
Map<String, Object?> polygon([Map<String, Object?> kw = const {}]) => {
  'type': 'parking',
  'shape': 'polygon',
  'points': square,
  ...kw,
};

// --- cot.json's rules (test_atak.py CotChecks) -------------------------------------

RegExp _re(String p) => RegExp('^(?:$p)\$');
final _timeRe = _re(_map(_cot['time'])['pattern']! as String);

XmlElement? find(XmlElement root, String path) {
  XmlElement? el = root;
  for (final tag in path.split('/')) {
    final next = el!.children.where((c) => c.tag == tag);
    if (next.isEmpty) return null;
    el = next.first;
  }
  return el;
}

List<XmlElement> findAll(XmlElement root, String path) {
  final parts = path.split('/');
  final parent = parts.length == 1
      ? root
      : find(root, parts.sublist(0, parts.length - 1).join('/'));
  return [
    for (final c in parent?.children ?? const <XmlElement>[])
      if (c.tag == parts.last) c,
  ];
}

XmlElement checkEvent(String text) {
  expect(utf8.encode(text).length, lessThanOrEqualTo(cotDatagramMax));
  final nl = text.indexOf('\n');
  final decl = text.substring(0, nl), body = text.substring(nl + 1);
  expect(decl.startsWith('<?xml ') && decl.endsWith('?>'), isTrue);
  expect(body.startsWith('<event ') && body.endsWith('</event>'), isTrue);
  final root = parseXmlElement(body);
  expect(root.tag, 'event');
  final ev = _map(_cot['event']);
  for (final a in ev['required_attributes']! as List) {
    expect(root.attrib, contains(a));
  }
  expect(root.attrib['version'], ev['version']);
  expect(root.attrib['type'], matches(_re(ev['type_pattern']! as String)));
  expect(root.attrib['how'], matches(_re(ev['how_pattern']! as String)));
  for (final name in ['time', 'start', 'stale']) {
    expect(root.attrib[name], matches(_timeRe));
  }
  expect(
    [for (final c in root.children) c.tag]..sort(),
    [...(ev['children']! as List).cast<String>()]..sort(),
  );
  final pt = find(root, 'point')!;
  final spec = _map(_cot['point']);
  for (final a in spec['required_attributes']! as List) {
    expect(pt.attrib, contains(a));
  }
  final lat = double.parse(pt.attrib['lat']!);
  final lon = double.parse(pt.attrib['lon']!);
  expect(lat, inInclusiveRange(-90, 90));
  expect(lon, inInclusiveRange(-180, 180));
  for (final name in ['hae', 'ce', 'le']) {
    double.parse(pt.attrib[name]!);
  }
  final details = _map(_cot['details']);
  final teams = _map(_cot['teams']);
  for (final child in find(root, 'detail')!.children) {
    final s = details[child.tag] as Map?;
    expect(s, isNotNull, reason: 'a detail TAK does not have: ${child.tag}');
    for (final a in (s!['required'] as List?) ?? const []) {
      expect(child.attrib, contains(a), reason: child.tag);
    }
    for (final a in (s['integer'] as List?) ?? const []) {
      final v = child.attrib[a];
      if (v != null) {
        expect(int.parse(v), inInclusiveRange(-(1 << 31), (1 << 31) - 1));
      }
    }
    if (child.tag == '__group') {
      expect(teams['names'], contains(child.attrib['name']));
      expect(teams['roles'], contains(child.attrib['role']));
    }
  }
  return root;
}

Map<String, XmlElement> byUid(Iterable<String> events) => {
  for (final e in events) checkEvent(e).attrib['uid']!: checkEvent(e),
};

/// TAK Protocol version 0 on TCP: events broken apart right after each
/// `</event>`.
List<String> splitStream(List<int> data) {
  final parts = utf8.decode(data).split('</event>');
  expect(parts.last, '', reason: 'nothing may follow the last </event>');
  return [for (final p in parts.sublist(0, parts.length - 1)) '$p</event>'];
}

// --- the loopback devices ----------------------------------------------------------

/// A UDP socket on the loopback that keeps every datagram.
class Receiver {
  Receiver._(this.sock) {
    sock.listen((ev) {
      if (ev == RawSocketEvent.read) {
        final d = sock.receive();
        if (d != null) _got.add(utf8.decode(d.data));
      }
    });
  }

  static Future<Receiver> open() async =>
      Receiver._(await RawDatagramSocket.bind(InternetAddress.loopbackIPv4, 0));

  final RawDatagramSocket sock;
  final _got = <String>[];
  int get port => sock.port;

  Future<List<String>> drain([double wait = 1.0]) async {
    final end = DateTime.now().add(
      Duration(milliseconds: (wait * 1000).round()),
    );
    var seen = _got.length;
    var quiet = DateTime.now();
    while (DateTime.now().isBefore(end)) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
      if (_got.length != seen) {
        seen = _got.length;
        quiet = DateTime.now();
      } else if (_got.isNotEmpty &&
          DateTime.now().difference(quiet) >
              const Duration(milliseconds: 100)) {
        break;
      }
    }
    final out = List.of(_got);
    _got.clear();
    return out;
  }

  void close() => sock.close();
}

/// A staff ATAK device on the loopback: keeps the bytes of each connection.
class TcpReceiver {
  TcpReceiver._(this.srv) {
    srv.listen((conn) {
      final data = <int>[];
      conn.listen(
        data.addAll,
        onDone: () {
          connections.add(data);
          conn.destroy();
        },
      );
    });
  }

  static Future<TcpReceiver> open() async =>
      TcpReceiver._(await ServerSocket.bind(InternetAddress.loopbackIPv4, 0));

  final ServerSocket srv;
  final connections = <List<int>>[];
  int get port => srv.port;

  Future<void> close() => srv.close();
}

Future<bool> waitFor(bool Function() cond, [double seconds = 10]) async {
  final end = DateTime.now().add(
    Duration(milliseconds: (seconds * 1000).round()),
  );
  while (DateTime.now().isBefore(end)) {
    if (cond()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  return cond();
}

/// The site server's stream as the emitter sees it: a sink and its state.
class FakeRelay {
  final events = <String>[];
}

void main() {
  group('known answers (atak_xml.json, from atak.py)', () {
    test('xml_text', () {
      for (final c in _list(_vectors['xml_text'])) {
        expect(
          xmlText(
            c['value']! as String,
            c['limit']! as int,
            c['max_bytes'] as int?,
          ),
          c['out'],
          reason: jsonEncode(c['value']),
        );
      }
    });

    test('cot_time, _deg, _metres and the remarks\' {:.0f}', () {
      final n = _map(_vectors['numbers']);
      for (final c in n['cot_time']! as List) {
        expect(cotTime((c as List)[0]! as num), c[1], reason: '${c[0]}');
      }
      for (final c in n['deg']! as List) {
        expect(pyFixed((c as List)[0]! as num, 7), c[1], reason: '${c[0]}');
      }
      for (final c in n['metres']! as List) {
        final v = (c as List)[0] as num?;
        final got = v == null ? cotUnknown : pyFixed(v > 0 ? v : 0.0, 1);
        expect(got, c[1], reason: '$v');
        // The same through an event's ce.
        final xml = eventXml(
          uid: 'atalaia.x',
          cotType: cotTypeProp,
          how: cotHowImage,
          lat: 0,
          lon: 0,
          now: 0,
          start: 0,
          stale: 1,
          ce: v,
        );
        expect(xml, contains(' ce="${c[1]}" '));
      }
      for (final c in n['fixed0']! as List) {
        expect(pyFixed((c as List)[0]! as num, 0), c[1]);
      }
      // jsonDecode reads -0.0 as -0.0; check it directly too.
      expect(pyFixed(-0.0, 7), '-0.0000000');
    });

    test('a box\'s remarks, with "active" (PD-MODE-16)', () {
      for (final c in _vectors['node_remarks']! as List) {
        final l = c as List;
        expect(
          nodeRemarks(
            l[0]! as String,
            levelLabel: l[1] as String?,
            active: l[2]! as bool,
          ),
          l[3],
          reason: '$l',
        );
      }
    });

    test('a box\'s remarks with the grid cell (PKE-2)', () {
      for (final c in _vectors['node_remarks_grid']! as List) {
        final l = c as List;
        expect(
          nodeRemarks(
            l[0]! as String,
            levelLabel: l[1] as String?,
            active: l[2]! as bool,
            gridCell: l[3] as String?,
          ),
          l[4],
          reason: '$l',
        );
      }
    });

    test('the grid cell of a place and the row letters (field_grid.py)', () {
      expect([0, 1, 2, 25, 26, 27, 51, 52].map(gridRowLabel).toList(), [
        'A',
        'B',
        'C',
        'Z',
        'AA',
        'AB',
        'AZ',
        'BA',
      ]);
      expect(gridRowLabel(26 + 26 * 26), 'AAA');
      const grid = {'enabled': true, 'rows': 8, 'cols': 10};
      expect(gridCell(grid, 0, 0), 'A1');
      expect(gridCell(grid, 0.35, 0.3), 'C4');
      expect(gridCell(grid, 1, 1), 'H10');
      expect(gridCell(grid, 0.0999, 0.125), 'B1');
      expect(
        gridCell(const {'enabled': true, 'rows': 30, 'cols': 52}, 0.999, 0.89),
        'AA52',
      );
      expect(gridCell({...grid, 'enabled': false}, 0.5, 0.5), isNull);
      expect(gridCell(grid, 1.2, 0.5), isNull);
    });

    test('colours and ATAK teams', () {
      final c = _map(_vectors['colours']);
      final teams = (c['teams']! as List).cast<String>();
      for (final e in c['team_colour']! as List) {
        expect(
          teamColour((e as List)[0] as String?, teams),
          e[1],
          reason: '${e[0]}',
        );
      }
      for (final e in c['atak_team']! as List) {
        expect(atakTeam((e as List)[0] as String?), e[1], reason: '${e[0]}');
      }
      for (final e in c['argb_of']! as List) {
        expect(argbOf((e as List)[0]! as int, e[1]! as int), e[2]);
      }
      for (final e in c['kml_colour']! as List) {
        expect(kmlColour((e as List)[0]! as int), e[1]);
      }
      for (final e in c['feature_colour']! as List) {
        expect(featureColour(_map((e as List)[0]), teams), e[1]);
      }
    });

    test('the extraction parameter', () {
      for (final e in _vectors['extraction']! as List) {
        final got = parseExtraction((e as List)[0]);
        final want = e[1] as List?;
        expect(
          got == null ? null : [got.$1, got.$2],
          want,
          reason: jsonEncode(e[0]),
        );
      }
    });

    test('endpoints and the [atak] settings', () {
      for (final e in _list(_vectors['endpoints'])) {
        final text = e['text']! as String;
        final port = e['default_port'] as int?;
        if (e['error'] == true) {
          expect(
            () => parseEndpoint(text, port),
            throwsA(isA<AtakConfigError>()),
            reason: text,
          );
        } else {
          expect(parseEndpoint(text, port), (e['host'], e['port']));
        }
      }
      for (final e in _list(_vectors['config'])) {
        final cfg = AtakConfig(
          multicast: e['multicast']! as String,
          staffEndpoints: (e['staff_endpoints']! as List).cast<String>(),
          intervalS: (e['interval_s']! as num).toDouble(),
        );
        if (e['ok'] == true) {
          cfg.checkConfig();
        } else {
          expect(
            cfg.checkConfig,
            throwsA(isA<AtakConfigError>()),
            reason: '$e',
          );
        }
      }
    });

    test('whole events, byte for byte', () {
      for (final s in _list(_vectors['events'])) {
        final List<CotElement> detail;
        if (s['marker'] != null) {
          final m = _map(s['marker']);
          detail = markerDetail(
            m['callsign']! as String,
            m['remarks']! as String,
            m['argb']! as int,
            battery: m['battery'] as int?,
            group: m['group'] as String?,
          );
        } else if (s['player'] != null) {
          final p = _map(s['player']);
          detail = playerDetail(
            p['callsign']! as String,
            p['group'] as String?,
            p['remarks']! as String,
          );
        } else {
          detail = const [];
        }
        final xml = eventXml(
          uid: s['uid']! as String,
          cotType: s['type']! as String,
          how: s['how']! as String,
          lat: s['lat']! as num,
          lon: s['lon']! as num,
          now: s['now']! as num,
          start: s['start']! as num,
          stale: s['stale']! as num,
          ce: s['ce'] as num?,
          detail: detail,
        );
        expect(xml, s['xml'], reason: s['uid'] as String?);
        if (!xml.contains('&#')) {
          // (the narrow parser takes no character references)
          expect(
            parseXmlElement(xml.substring(cotXmlDecl.length)).tag,
            'event',
          );
        }
      }
      for (final p in _vectors['refused_points']! as List) {
        expect(
          () => eventXml(
            uid: 'u',
            cotType: cotTypeProp,
            how: cotHowImage,
            lat: (p as List)[0]! as num,
            lon: p[1]! as num,
            now: 0,
            start: 0,
            stale: 1,
          ),
          throwsArgumentError,
        );
      }
      for (final (lat, lon) in [
        (double.nan, 0.0),
        (0.0, double.infinity),
        (91.0, 0.0),
        (0.0, 181.0),
      ]) {
        expect(
          () => eventXml(
            uid: 'u',
            cotType: cotTypeProp,
            how: cotHowImage,
            lat: lat,
            lon: lon,
            now: 0,
            start: 0,
            stale: 1,
          ),
          throwsArgumentError,
        );
      }
    });

    test('map features: points, circles, polygons, the boundary', () {
      for (final f in _list(_vectors['features'])) {
        final geo = Georef(checkControlPoints(f['georef']));
        final (xml, kind, lat, lon) = featureXml(
          uid: f['uid']! as String,
          feature: _map(f['feature']),
          geo: geo,
          now: f['now']! as num,
          stale: f['stale']! as num,
          callsign: f['callsign']! as String,
          remarks: f['remarks']! as String,
          argb: f['argb']! as int,
          group: f['group'] as String?,
        );
        expect(xml, f['xml'], reason: f['uid'] as String?);
        expect(kind, f['type']);
        expect(lat, closeTo(f['lat']! as num, 1e-9));
        expect(lon, closeTo(f['lon']! as num, 1e-9));
        checkEvent(xml);
      }
    });

    test('drops', () {
      for (final d in _list(_vectors['drops'])) {
        final xml = dropXml(
          d['uid']! as String,
          d['type']! as String,
          d['lat']! as num,
          d['lon']! as num,
          d['now']! as num,
        );
        expect(xml, d['xml']);
        final root = checkEvent(xml);
        expect(
          root.attrib['stale']!.compareTo(root.attrib['start']!),
          lessThan(0),
        );
      }
    });
  });

  group('cot.json (the published CoT facts)', () {
    test('the time pattern, the types and the constants', () {
      for (final t in _map(_cot['time'])['valid']! as List) {
        expect(t, matches(_timeRe));
      }
      expect(cotTime(1608148774.91), '2020-12-16T19:59:34.910Z');
      final types = _map(_cot['types']);
      for (final name in [cotTypeProp, cotTypeZonePoint, cotTypePlayer]) {
        expect(types, contains(name));
        expect(_map(types[name])['use'], isNot(contains('not used')));
        expect(
          _map(types[name])['source'],
          contains(name.replaceAll('a-f-', 'a-.-')),
        );
      }
      for (final name in [cotTypeCircle, cotTypePolygon]) {
        expect(_map(types[name])['source'], contains(name));
      }
      expect(_map(_cot['affiliations']), contains(cotTypePlayer.split('-')[1]));
      for (final how in [cotHowImage, cotHowPasted, cotHowGps]) {
        expect(_map(_cot['how']), contains(how));
      }
      final teams = _map(_cot['teams']);
      expect(teams['roles'], contains(cotGroupRole));
      expect(atakTeams, teams['names']);
      final transport = _map(_cot['transport']);
      expect(atakDefaultMulticast, transport['multicast']);
      expect(atakDefaultStaffPort, transport['staff_port']);
      expect(cotUnknown, _map(_cot['point'])['unknown_value']);
      for (final ex in _list(_cot['argb_examples'])) {
        expect(
          ((ex['argb']! as int) & 0xFFFFFF).toRadixString(16).padLeft(6, '0'),
          ex['rgb'],
        );
      }
      expect(kmlColour(-1), 'ffffffff');
      expect(kmlColour(-1761607681), '96ffffff');
      expect(argbOf(0xFFFFFF, 0x96), -1761607681);
      expect(featureNames.keys.toSet(), mapFeatureTypes.toSet());
      expect(featureColours.keys.toSet(), mapFeatureTypes.toSet());
    });

    test('the emitter rebuilds the TAK examples', () {
      double epoch(String t) => DateTime.parse(t).microsecondsSinceEpoch / 1e6;
      for (final s in _list(_cot['samples'])) {
        final ev = _map(s['event']), pt = _map(s['point']);
        final det = _map(s['detail']);
        final argb = int.parse(_map(det['color'])['argb']! as String);
        final xml = eventXml(
          uid: ev['uid']! as String,
          cotType: ev['type']! as String,
          how: ev['how']! as String,
          lat: double.parse(pt['lat']! as String),
          lon: double.parse(pt['lon']! as String),
          now: epoch(ev['time']! as String),
          start: epoch(ev['start']! as String),
          stale: epoch(ev['stale']! as String),
          detail: markerDetail(
            _map(det['contact'])['callsign']! as String,
            '',
            argb,
          ),
        );
        final root = checkEvent(xml);
        expect(root.attrib, ev);
        for (final name in ['hae', 'ce', 'le']) {
          expect(find(root, 'point')!.attrib[name], pt[name]);
        }
        expect(find(root, 'detail/contact')!.attrib, det['contact']);
        expect(find(root, 'detail/color')!.attrib, det['color']);
        if (ev['type'] == cotTypeProp) {
          expect(find(root, 'detail/usericon')!.attrib, det['usericon']);
        }
      }
    });

    test('hostile text is escaped and cleaned', () {
      final xml = eventXml(
        uid: 'atalaia.f.node.4',
        cotType: cotTypeProp,
        how: cotHowImage,
        lat: 38.7,
        lon: -9.1,
        now: 1e9,
        start: 1e9,
        stale: 1e9 + 60,
        detail: markerDetail(hostile, 'Atalaia: $hostile', -1),
      );
      final root = checkEvent(xml);
      expect(find(root, 'detail/contact')!.attrib['callsign'], hostileClean);
      expect(find(root, 'detail/remarks')!.text, 'Atalaia: $hostileClean');
      expect(find(root, 'detail/x'), isNull);
      expect(find(root, 'detail')!.children, hasLength(4));
      expect(xml, isNot(contains('\x01')));
      expect(xml, isNot(contains('<x ')));
      expect(cotEvent(xml)['uid'], 'atalaia.f.node.4');
    });

    test('the largest event fits one datagram', () {
      for (final ch in ['<', '&', '"', "'", '\u{1F600}', '€', 'a']) {
        final xml = eventXml(
          uid: 'atalaia.${'f' * 64}.node.65534',
          cotType: cotTypeProp,
          how: cotHowImage,
          lat: -89.1234567,
          lon: -179.1234567,
          now: 1e9,
          start: 1e9,
          stale: 1e9 + 7200,
          ce: 1e6,
          detail: markerDetail(
            ch * 100,
            ch * 400,
            -16777216,
            battery: 100,
            group: 'Dark Green',
          ),
        );
        expect(find(checkEvent(xml), 'detail/remarks')!.text, startsWith(ch));
      }
      expect(xmlText('"' * 10, 48, 30), '"' * 5);
    });

    test('cot batches: at most 100 events in one cot message', () {
      final events = [for (var i = 0; i < 250; i++) 'e$i'];
      final b = AtakEmitter.cotBatches(events);
      expect(b.map((x) => x.length), [100, 100, 50]);
      expect(b.expand((x) => x), events);
      expect(AtakEmitter.cotBatches([]), isEmpty);
    });
  });

  group('the [atak] settings (config.py)', () {
    test('defaults, the section and the refusals', () {
      const d = AtakConfig();
      expect(
        (d.enabled, d.multicast, d.players, d.intervalS, d.remote),
        (false, '239.2.3.1:6969', false, 30.0, false),
      );
      d.checkConfig();
      final cfg = AtakConfig.fromSection({
        'enabled': true,
        'staff_endpoints': '10.42.0.5:4242, 10.42.0.6,[fd00::7]:4243',
        'players': true,
        'interval_s': 10,
      });
      expect(cfg.staffEndpoints, [
        '10.42.0.5:4242',
        '10.42.0.6',
        '[fd00::7]:4243',
      ]);
      expect(
        [for (final e in cfg.staffEndpoints) parseEndpoint(e, 4242)],
        [('10.42.0.5', 4242), ('10.42.0.6', 4242), ('fd00::7', 4243)],
      );
      cfg.checkConfig();
      for (final s in <Map<String, Object?>>[
        {'multicast': '239.2.3.1'},
        {'multicast': '0.0.0.0:6969'},
        {'multicast': 'atak.local:6969'},
        {'multicast': '239.2.3.1:70000'},
        {'multicast': '[ff02::1]:6969'},
        {'interval_s': 0.5},
        {'staff_endpoints': 'a b:1'},
        {
          'staff_endpoints': [for (var i = 0; i < 9; i++) '10.0.0.$i'],
        },
      ]) {
        expect(
          () => AtakConfig.fromSection(s).checkConfig(),
          throwsA(isA<AtakConfigError>()),
          reason: '$s',
        );
      }
      const AtakConfig(multicast: '').checkConfig(); // no UDP at all
      // The relay rides the sync's stream (config.py _check_atak).
      const remote = AtakConfig(enabled: true, remote: true);
      expect(remote.checkConfig, throwsA(isA<AtakConfigError>()));
      remote.checkConfig(syncEnabled: true);
      expect(
        () => const AtakConfig(remote: true).checkConfig(syncEnabled: true),
        throwsA(isA<AtakConfigError>()),
      );
      expect(
        () => const AtakConfig(
          enabled: true,
          remotePlayers: true,
        ).checkConfig(syncEnabled: true),
        throwsA(isA<AtakConfigError>()),
      );
    });
  });

  group('the emitter on the engine', () {
    late AtalaiaCore core;
    setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

    late double now;
    late ControllerEngine engine;
    late ControllerField field;
    late Receiver udp;
    TcpReceiver? tcp;
    late AtakEmitter emitter;
    late ControllerCheckin checkin;
    late ControllerPositions positions;
    var seq = 0;

    Future<void> rig({
      bool players = false,
      bool staff = false,
      bool remote = false,
      bool remotePlayers = false,
    }) async {
      now = 1e9;
      seq = 0;
      engine = ControllerEngine(
        core: core,
        transport: RecordingRadio(),
        wallSeconds: () => now,
      );
      field = ControllerField(engine);
      checkin = ControllerCheckin(
        engine,
        CheckinConfig(
          limitsYaml: File(
            'lib/chrono/limit_templates/portugal.yaml',
          ).readAsStringSync(),
        ),
      );
      positions = ControllerPositions(engine);
      udp = await Receiver.open();
      tcp = staff ? await TcpReceiver.open() : null;
      emitter = AtakEmitter(
        engine,
        AtakConfig(
          enabled: true,
          multicast: '127.0.0.1:${udp.port}',
          players: players,
          staffEndpoints: [if (tcp != null) '127.0.0.1:${tcp!.port}'],
          remote: remote,
          remotePlayers: remotePlayers,
        ),
        wall: () => now,
        // A loaded test machine (other suites in parallel) can keep this
        // isolate's event loop from seeing the loopback connection within
        // the field's 2 s; the senders' own tests keep the 2 s.
        tcp: tcp == null
            ? null
            : TcpCotSender([
                '127.0.0.1:${tcp!.port}',
              ], timeout: const Duration(seconds: 20)),
      );
    }

    tearDown(() async {
      await emitter.stop();
      udp.close();
      await tcp?.close();
      tcp = null;
      engine.close();
    });

    void putImageAndCorners() {
      field.putImage(0, 'image/png', png);
      field.putGeoref(0, {
        'points': [tl, br],
      });
    }

    int runningGame([Map<String, Object?> spec = const {}]) {
      final game = engine.createGame({
        'name': 'g',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
        'assignments': {'4': 'zone', '5': 'zone'},
        ...spec,
      });
      final id = game['id']! as int;
      engine.startGame(id, force: true);
      return id;
    }

    void place(int gid, int node, double x, double y) =>
        field.putPlace(gid, node, {'x': x, 'y': y});

    RfHeader hdr(int gid, int source, int type) => RfHeader.v1(
      gameId: gid,
      source: source,
      seq: seq++,
      hopLimit: 2,
      type: type,
    );

    void owner(int gid, int node, int team) => engine.onPacket(
      hdr(gid, node, RfType.state),
      RfState(
        ownerTeam: team,
        phase: 1,
        gameTimeMs: 0,
        counters: const {},
        epoch: 1,
      ).encode(),
      epoch: 1,
    );

    void captured(int gid, int node, int team) => engine.onPacket(
      hdr(gid, node, RfType.event),
      core
          .encodeEvent(
            node: node,
            seq: seq,
            tMs: 1000,
            type: 'zone.captured',
            team: team,
            squad: 0,
            prio: 2,
            dataJson: null,
          )
          .bytes!,
      epoch: 1,
    );

    (String, String) player(
      int gid,
      String name,
      String team, {
      String role = 'player',
    }) {
      final row = checkin.manualCheckin(ApiViewer.gm, gid, {
        'display_name': name,
      });
      final pid = row['player_id']! as String;
      checkin.patchCheckin(ApiViewer.gm, gid, pid, {
        'team': team,
        'role': role,
      });
      final teamId = team == 'red' ? 1 : 2;
      positions.report(
        ApiViewer('player', {
          'player_id': pid,
          'game_id': gid,
          'team': teamId,
          'squad': 0,
          'role': role,
        }),
        {
          'lat': 38.7221,
          'lon': -9.1391,
          'accuracy_m': 6.0,
          'source': 'gps',
          't': 1,
        },
      );
      return (pid, name);
    }

    test('props on the georeferenced plan', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      place(gid, 5, 0.0, 1.0);
      expect(emitter.udp, isNull); // nothing is opened before the first send
      final sent = await emitter.cycle(full: true);
      expect(sent['udp'], 2);
      final got = byUid(await udp.drain());
      expect(got.keys.toSet(), {
        'atalaia.field.node.4',
        'atalaia.field.node.5',
      });
      final mid = got['atalaia.field.node.4']!;
      expect((mid.attrib['type'], mid.attrib['how']), ('b-m-p-s-m', 'h-e'));
      expect(
        double.parse(find(mid, 'point')!.attrib['lat']!),
        closeTo((38.7240 + 38.7200) / 2, 1e-6),
      );
      expect(
        double.parse(find(mid, 'point')!.attrib['lon']!),
        closeTo((-9.1420 + -9.1360) / 2, 1e-6),
      );
      final corner = find(got['atalaia.field.node.5']!, 'point')!;
      expect(double.parse(corner.attrib['lat']!), closeTo(38.7200, 1e-6));
      expect(double.parse(corner.attrib['lon']!), closeTo(-9.1420, 1e-6));
      expect(find(mid, 'detail/color')!.attrib['argb'], '-1');
      expect(find(mid, 'detail/__group'), isNull);
      expect(find(mid, 'detail/contact')!.attrib['callsign'], 'node-4');
      expect(mid.attrib['start'], mid.attrib['time']);
      expect(mid.attrib['stale'], cotTime(now + 60));
      expect(emitter.status()['udp_events'], 2);
      expect(emitter.status()['last_sent_at'], now);
      expect(emitter.status()['markers'], 2);
    });

    test('the owner\'s colour, and a capture sent at once', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      place(gid, 5, 0.2, 0.2);
      owner(gid, 4, 0); // its first packet: the box is online
      await emitter.cycle(full: true);
      await udp.drain();
      captured(gid, 4, 2);
      var sent = await emitter.cycle(full: false);
      expect(sent['udp'], 1); // only the captured box
      var ev = byUid(await udp.drain())['atalaia.field.node.4']!;
      expect(
        int.parse(find(ev, 'detail/color')!.attrib['argb']!),
        teamColour('blue', ['red', 'blue']),
      );
      expect(find(ev, 'detail/remarks')!.text, contains('blue'));
      expect(find(ev, 'detail/__group')!.attrib, {
        'name': 'Blue',
        'role': 'Team Member',
      });
      // The box's STATE with the same owner sends nothing more; a new one does.
      owner(gid, 4, 2);
      expect((await emitter.cycle(full: false))['udp'], 0);
      owner(gid, 4, 1);
      sent = await emitter.cycle(full: false);
      expect(sent['udp'], 1);
      ev = byUid(await udp.drain())['atalaia.field.node.4']!;
      expect(
        int.parse(find(ev, 'detail/color')!.attrib['argb']!),
        teamColour('red', ['red', 'blue']),
      );
      expect(find(ev, 'detail/__group')!.attrib['name'], 'Red');
    });

    test(
      'the worker sends a capture without waiting for the interval',
      () async {
        await rig();
        putImageAndCorners();
        final gid = runningGame();
        place(gid, 4, 0.5, 0.5);
        owner(gid, 4, 0);
        emitter.start();
        expect(
          await waitFor(() => (emitter.stats['udp_events']! as int) >= 1),
          isTrue,
        );
        await udp.drain();
        captured(gid, 4, 1);
        final got = await udp.drain(
          2.0,
        ); // interval_s is 30 s: this is the capture
        await emitter.stop();
        final ev = byUid(got)['atalaia.field.node.4']!;
        expect(
          int.parse(find(ev, 'detail/color')!.attrib['argb']!),
          teamColour('red', []),
        );
      },
    );

    test('the active box says so in its remarks (PD-MODE-16)', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      place(gid, 5, 0.2, 0.2);
      await emitter.cycle(full: true);
      await udp.drain();
      void say(String type, String zone) => emitter.onControllerMessage({
        'type': 'event',
        'event': {
          'type': type,
          'node': 0,
          'data': {'zone': zone},
        },
      });
      say('progressive.activated', 'node-4');
      expect((await emitter.cycle(full: false))['udp'], 2); // all of them
      var got = byUid(await udp.drain());
      expect(
        find(got['atalaia.field.node.4']!, 'detail/remarks')!.text,
        'Atalaia: -, active',
      );
      expect(
        find(got['atalaia.field.node.5']!, 'detail/remarks')!.text,
        'Atalaia: -',
      );
      say('progressive.completed', 'node-4');
      await emitter.cycle(full: false);
      got = byUid(await udp.drain());
      expect(
        find(got['atalaia.field.node.4']!, 'detail/remarks')!.text,
        'Atalaia: -',
      );
    });

    test('the grid cell is in a marker\'s remarks, and a changed grid sends '
        'everything again (PKE-2)', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      place(gid, 5, 0.0, 1.0);
      final pin = field.addFeature({
        'type': 'first_aid',
        'shape': 'point',
        'x': 0.9,
        'y': 0.1,
        'label': 'Posto',
        'note': 'Kit verde',
      })['id']!;
      await emitter.cycle(full: true);
      var got = byUid(await udp.drain());
      expect(
        find(got['atalaia.field.node.4']!, 'detail/remarks')!.text,
        'Atalaia: -',
      ); // no grid yet
      field.putGrid(0, {'enabled': true, 'rows': 4, 'cols': 4});
      emitter.onControllerMessage({'type': 'field_grid', 'level': 0});
      expect(
        (await emitter.cycle(full: false))['udp'],
        greaterThanOrEqualTo(3),
      );
      got = byUid(await udp.drain());
      expect(
        find(got['atalaia.field.node.4']!, 'detail/remarks')!.text,
        'Atalaia: -, grid C3',
      );
      expect(
        find(got['atalaia.field.node.5']!, 'detail/remarks')!.text,
        'Atalaia: -, grid D1',
      );
      expect(
        find(got['atalaia.field.feature.$pin']!, 'detail/remarks')!.text,
        'Atalaia: First aid, grid A4. Kit verde',
      );
    });

    test('stop closes the socket', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      await emitter.cycle(full: true);
      final sender = emitter.udp! as UdpCotSender;
      expect(sender.socket!.port, greaterThan(0));
      await emitter.stop();
      expect(sender.socket, isNull); // closed
      expect(emitter.udp, isNull);
      await emitter.stop(); // again: nothing to do
    });

    test('no map position, no markers; deleting it drops them', () async {
      await rig();
      field.putImage(0, 'image/png', png);
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      expect((await emitter.cycle(full: true))['udp'], 0);
      expect(emitter.status()['no_georef'], isTrue);
      field.putGeoref(0, {
        'points': [tl, br],
      });
      expect((await emitter.cycle(full: false))['udp'], 1);
      await udp.drain();
      expect(field.deleteGeoref(0)['deleted'], isTrue);
      await emitter.cycle(full: false);
      final drops = await udp.drain();
      expect(drops, hasLength(1));
      final root = checkEvent(drops.single);
      expect(
        root.attrib['stale']!.compareTo(root.attrib['start']!),
        lessThan(0),
      );
    });

    test('hostile node and team names', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      engine.liveGame!['team_info'] = {
        'red': {'display_name': hostile},
      };
      owner(gid, 4, 1);
      await emitter.cycle(full: true);
      final ev = byUid(await udp.drain())['atalaia.field.node.4']!;
      expect(find(ev, 'detail/remarks')!.text, contains('</remarks><x'));
      expect(find(ev, 'detail/remarks')!.text, contains('(red)'));
      expect(find(ev, 'detail/x'), isNull);
    });

    test('the game\'s end drops every marker, then nothing goes', () async {
      await rig();
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      await emitter.cycle(full: true);
      await udp.drain();
      engine.endGame(gid);
      await emitter.cycle(full: false);
      final got = byUid(await udp.drain());
      expect(got.keys, ['atalaia.field.node.4']);
      final d = got['atalaia.field.node.4']!;
      expect(d.attrib['stale']!.compareTo(d.attrib['start']!), lessThan(0));
      expect((await emitter.cycle(full: true))['udp'], 0);
    });

    test('the extraction zone', () async {
      await rig();
      putImageAndCorners();
      final game = engine.createGame({
        'name': 'v',
        'mode_id': 'org.atalaia.vip_payload',
        'teams': ['red', 'blue'],
        'assignments': {'4': 'checkpoint'},
        'params': {
          'extraction': '38.7215,-9.1390',
          'radius_m': 40,
          'vip_team': 'blue',
        },
      });
      engine.startGame(game['id']! as int, force: true);
      await emitter.cycle(full: true);
      final got = byUid(await udp.drain());
      final ev = got['atalaia.field.game.${game['id']}.extraction']!;
      expect((ev.attrib['type'], ev.attrib['how']), ('b-m-p-s-m', 'h-p'));
      expect(find(ev, 'point')!.attrib['ce'], '40.0');
      expect(double.parse(find(ev, 'point')!.attrib['lat']!), 38.7215);
      expect(find(ev, 'detail/__group')!.attrib['name'], 'Blue');
      expect(find(ev, 'detail/remarks')!.text, 'Atalaia: blue, 40 m');
    });

    test('status', () async {
      await rig();
      final s = emitter.status();
      expect(s['enabled'], isTrue);
      expect(s['multicast'], '127.0.0.1:${udp.port}');
      expect(s.keys.toSet(), {
        'enabled',
        'multicast',
        'staff_endpoints',
        'players',
        'interval_s',
        'markers',
        'remote',
        'remote_players',
        'remote_relay',
        'udp_events',
        'tcp_events',
        'remote_events',
        'errors',
        'last_error',
        'last_sent_at',
        'no_georef',
        'features',
      });
    });

    test('players only to staff endpoints, never multicast', () async {
      await rig(players: true, staff: true);
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      final (red, _) = player(gid, 'Falcão', 'red');
      final (vip, _) = player(gid, 'Mocho', 'blue', role: 'vip');
      await emitter.cycle(full: true);
      final fromUdp = byUid(await udp.drain());
      expect(fromUdp.keys, ['atalaia.field.node.4']);
      // A change (the check-ins) may start a cycle of its own next to this
      // one: what reached the staff device, over every connection.
      expect(
        await waitFor(() => tcp!.connections.isNotEmpty),
        isTrue,
        reason: '${emitter.status()}',
      );
      final events = [for (final c in tcp!.connections) ...splitStream(c)];
      final got = byUid(events);
      expect(got.keys.toSet(), {
        'atalaia.field.node.4',
        'atalaia.field.player.$red',
        'atalaia.field.player.$vip',
      });
      final p = got['atalaia.field.player.$red']!;
      expect((p.attrib['type'], p.attrib['how']), ('a-f-G-U-C', 'm-g'));
      expect(find(p, 'detail/__group')!.attrib, {
        'name': 'Red',
        'role': 'Team Member',
      });
      expect(find(p, 'point')!.attrib['ce'], '6.0');
      expect(find(p, 'detail/contact')!.attrib['callsign'], red);
      expect(find(p, 'detail/remarks')!.text, 'Atalaia: red, player');
      final raw = utf8.decode(tcp!.connections.expand((c) => c).toList());
      expect(raw, isNot(contains('Falcão')));
      expect(raw, isNot(contains('Mocho')));
      expect(
        find(
          got['atalaia.field.player.$vip']!,
          'detail/contact',
        )!.attrib['callsign'],
        '$vip VIP',
      );
      for (final c in tcp!.connections) {
        final text = utf8.decode(c);
        expect(text, startsWith('<?xml '));
      }
      expect(
        '?>\n<event '.allMatches(raw),
        hasLength(emitter.status()['tcp_events']! as int),
      );
      expect(emitter.status()['tcp_events'], greaterThanOrEqualTo(3));
    });

    test('an indoor position is the beacon on the plan, the room in the '
        'remarks (BLE-8)', () async {
      await rig(players: true, staff: true);
      putImageAndCorners();
      final gid = runningGame();
      final (red, _) = player(gid, 'Falcão', 'red');
      final (blue, _) = player(gid, 'Mocho', 'blue');
      const uuid = 'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F';
      field.addBeacon({
        'uuid': uuid,
        'major': 1,
        'minor': 1,
        'room': 'Lobby',
        'zone': 'Ground',
        'x': 0.5,
        'y': 0.5,
      });
      field.addBeacon({'uuid': uuid, 'major': 1, 'minor': 2, 'room': 'Cellar'});
      ApiViewer viewer(String pid, int team) => ApiViewer('player', {
        'player_id': pid,
        'game_id': gid,
        'team': team,
        'squad': 0,
        'role': 'player',
      });
      positions.report(viewer(red, 1), {
        'source': 'ble',
        'beacon_id': '1:1',
        't': 5,
      });
      positions.report(viewer(blue, 2), {
        'source': 'ble',
        'beacon_id': '1:2', // not placed on the plan
        't': 5,
      });
      await emitter.cycle(full: true);
      expect(
        await waitFor(() => tcp!.connections.isNotEmpty),
        isTrue,
        reason: '${emitter.status()}',
      );
      final got = byUid([for (final c in tcp!.connections) ...splitStream(c)]);
      expect(got.containsKey('atalaia.field.player.$blue'), isFalse);
      final p = got['atalaia.field.player.$red']!;
      expect(p.attrib['how'], 'h-e'); // from the image, not a GPS fix
      final point = find(p, 'point')!;
      expect(
        double.parse(point.attrib['lat']!),
        closeTo((38.7240 + 38.7200) / 2, 1e-4),
      );
      expect(
        double.parse(point.attrib['lon']!),
        closeTo((-9.1420 + -9.1360) / 2, 1e-4),
      );
      expect(
        find(p, 'detail/remarks')!.text,
        'Atalaia: red, player, Lobby (Ground)',
      );
      // Never on the multicast.
      final types = {
        for (final e in await udp.drain()) checkEvent(e).attrib['type'],
      };
      expect(types, isNot(contains(cotTypePlayer)));
    });

    test('staff get props but no players without players = true', () async {
      await rig(players: false, staff: true);
      putImageAndCorners();
      final gid = runningGame();
      place(gid, 4, 0.5, 0.5);
      player(gid, 'Falcão', 'red');
      await emitter.cycle(full: true);
      expect(
        await waitFor(() => tcp!.connections.isNotEmpty),
        isTrue,
        reason: '${emitter.status()}',
      );
      final types = {
        for (final c in tcp!.connections)
          for (final e in splitStream(c)) checkEvent(e).attrib['type'],
      };
      expect(types, {cotTypeProp});
    });

    test(
      'a staff endpoint that is down is an error, the others still get it',
      () async {
        await rig(staff: true);
        // Nothing listens on port 1 (nobody may without root); a closed
        // ephemeral port could be taken again meanwhile.
        const deadPort = 1;
        await emitter.stop();
        emitter = AtakEmitter(
          engine,
          AtakConfig(
            enabled: true,
            multicast: '',
            staffEndpoints: ['127.0.0.1:${tcp!.port}', '127.0.0.1:$deadPort'],
          ),
          wall: () => now,
        );
        putImageAndCorners();
        final gid = runningGame();
        place(gid, 4, 0.5, 0.5);
        final sent = await emitter.cycle(full: true);
        expect(sent, {'udp': 0, 'tcp': 1, 'remote': 0});
        expect(emitter.status()['errors'], 1);
        expect(
          emitter.status()['last_error'],
          startsWith('TCP 127.0.0.1:$deadPort: '),
        );
        expect(emitter.status()['multicast'], isNull);
      },
    );

    group('map features', () {
      int add(Map<String, Object?> body) =>
          field.addFeature(body)['id']! as int;

      test('shapes on the map and who gets them', () async {
        await rig(staff: true);
        putImageAndCorners();
        final gid = runningGame();
        place(gid, 4, 0.5, 0.5);
        final hospital = add(
          point({'label': 'Hospital', 'note': 'Bring the green kit'}),
        );
        final safe = add(circle({'label': 'Safe zone A'}));
        final car = add(polygon());
        final red = add(
          circle({'type': 'respawn', 'team': 'red', 'label': 'Red respawn'}),
        );
        final staff = add(
          point({'type': 'hq', 'label': 'Control', 'visibility': 'organisers'}),
        );
        String uid(int id) => 'atalaia.field.feature.$id';
        await emitter.cycle(full: true);
        final fromUdp = byUid(await udp.drain());
        expect(fromUdp.keys.toSet(), {
          'atalaia.field.node.4',
          uid(hospital),
          uid(safe),
          uid(car),
        });
        expect(await waitFor(() => tcp!.connections.length == 1), isTrue);
        final fromTcp = byUid(splitStream(tcp!.connections[0]));
        expect(fromTcp.keys.toSet(), {
          'atalaia.field.node.4',
          for (final id in [hospital, safe, car, red, staff]) uid(id),
        });
        expect(emitter.status()['features'], 5);
        final h = fromUdp[uid(hospital)]!;
        expect((h.attrib['type'], h.attrib['how']), ('b-m-p-s-m', 'h-e'));
        expect(find(h, 'detail/contact')!.attrib['callsign'], 'Hospital');
        expect(
          find(h, 'detail/remarks')!.text,
          'Atalaia: First aid. Bring the green kit',
        );
        expect(
          int.parse(find(h, 'detail/color')!.attrib['argb']!),
          argbOf(featureColours['first_aid']!),
        );
        final s = fromUdp[uid(safe)]!;
        expect(s.attrib['type'], 'u-d-c-c');
        expect(find(s, 'detail/shape/ellipse')!.attrib, {
          'major': '30.0',
          'minor': '30.0',
          'angle': '360',
        });
        final link = find(s, 'detail/shape/link')!;
        expect(link.attrib, {
          'uid': '${uid(safe)}.Style',
          'type': 'b-x-KmlStyle',
          'relation': 'p-c',
        });
        expect(find(link, 'Style/LineStyle/color')!.text, 'ffa6b814');
        expect(find(s, 'detail/remarks')!.text, 'Atalaia: Safe zone, 30 m');
        expect(find(s, 'detail/labels_on')!.attrib['value'], 'true');
        expect(
          int.parse(find(s, 'detail/fillColor')!.attrib['value']!) & 0xFFFFFFFF,
          (cotFillAlpha << 24) | featureColours['safe_zone']!,
        );
        final p = fromUdp[uid(car)]!;
        expect(p.attrib['type'], 'u-d-f');
        final links = [
          for (final l in findAll(p, 'detail/link')) l.attrib['point'],
        ];
        expect(links, hasLength(square.length + 1));
        expect(links.first, links.last);
        expect(find(p, 'detail/contact')!.attrib['callsign'], 'Parking');
        final r = fromTcp[uid(red)]!;
        expect(
          int.parse(find(r, 'detail/strokeColor')!.attrib['value']!),
          teamColour('red', ['red', 'blue']),
        );
        expect(
          find(r, 'detail/remarks')!.text,
          'Atalaia: Respawn, red, team only, 30 m',
        );
        expect(
          find(fromTcp[uid(staff)]!, 'detail/remarks')!.text,
          'Atalaia: HQ, organisers only',
        );
        expect(find(fromTcp[uid(staff)]!, 'detail/__group'), isNull);

        // The car park becomes the organisers' and the hospital goes:
        // dropped on the Wi-Fi at once.
        field.putFeature(car, polygon({'visibility': 'organisers'}));
        field.deleteFeature(hospital);
        await emitter.cycle(full: false);
        final again = byUid(await udp.drain());
        for (final gone in [uid(car), uid(hospital)]) {
          final g = again[gone]!;
          expect(g.attrib['stale']!.compareTo(g.attrib['start']!), lessThan(0));
        }
        final ss = again[uid(safe)]!;
        expect(
          ss.attrib['stale']!.compareTo(ss.attrib['start']!),
          greaterThan(0),
        );
        expect(await waitFor(() => tcp!.connections.length == 2), isTrue);
        final tcp2 = byUid(splitStream(tcp!.connections[1]));
        final hh = tcp2[uid(hospital)]!;
        expect(hh.attrib['stale']!.compareTo(hh.attrib['start']!), lessThan(0));
        final cc = tcp2[uid(car)]!;
        expect(
          cc.attrib['stale']!.compareTo(cc.attrib['start']!),
          greaterThan(0),
        );

        // The game ends: every feature is dropped with the boxes.
        engine.endGame(gid);
        await emitter.cycle(full: false);
        final end = byUid(await udp.drain());
        final se = end[uid(safe)]!;
        expect(se.attrib['stale']!.compareTo(se.attrib['start']!), lessThan(0));
      });

      test('the largest events fit one datagram', () async {
        await rig();
        putImageAndCorners();
        runningGame();
        engine.liveGame!['team_info'] = {
          'red': {'display_name': 'é' * 32},
        };
        final many = [
          for (var i = 0; i < polygonMax; i++)
            {
              'x': double.parse(
                (0.5 + 0.45 * math.cos(i * 0.39)).toStringAsFixed(3),
              ),
              'y': double.parse(
                (0.5 + 0.45 * math.sin(i * 0.39)).toStringAsFixed(3),
              ),
            },
        ];
        final long = '"&<' * 16;
        add(
          polygon({
            'points': many,
            'label': long,
            'note': '&' * 200,
            'team': 'red',
            'visibility': 'everyone',
          }),
        );
        add(
          circle({
            'label': long,
            'note': '"' * 200,
            'team': 'red',
            'visibility': 'everyone',
          }),
        );
        add(
          point({
            'label': long,
            'note': "'" * 200,
            'team': 'red',
            'visibility': 'everyone',
          }),
        );
        await emitter.cycle(full: true);
        final got = await udp.drain();
        expect(got, hasLength(3));
        got.forEach(checkEvent);
      });
    });

    group('the remote relay', () {
      Map<String, Map<String, Object?>> shared(List<String> events) => {
        for (final e in events) cotEvent(e)['uid']! as String: cotEvent(e),
      };

      FakeRelay relay() {
        final fake = FakeRelay();
        emitter
          ..remoteSink = fake.events.addAll
          ..remoteReady = true;
        return fake;
      }

      test(
        'props go to the relay, positions only with remote_players',
        () async {
          await rig(players: true, remote: true);
          putImageAndCorners();
          final gid = runningGame();
          place(gid, 4, 0.5, 0.5);
          final (red, _) = player(gid, 'Falcão', 'red');
          final fake = relay();
          final sent = await emitter.cycle(full: true);
          expect(sent['remote'], 1);
          final got = shared(fake.events);
          expect(got.keys, ['atalaia.field.node.4']);
          expect(got['atalaia.field.node.4']!['map'], isTrue);
          expect(byUid(await udp.drain()).keys, ['atalaia.field.node.4']);
          expect(emitter.status()['remote_players'], isFalse);

          // remote_players on: a new emitter, as a new config gives.
          await emitter.stop();
          emitter = AtakEmitter(
            engine,
            AtakConfig(
              enabled: true,
              multicast: '127.0.0.1:${udp.port}',
              players: true,
              remote: true,
              remotePlayers: true,
            ),
            wall: () => now,
          );
          final fake2 = relay();
          await emitter.cycle(full: true);
          final got2 = shared(fake2.events);
          expect(got2.keys.toSet(), {
            'atalaia.field.node.4',
            'atalaia.field.player.$red',
          });
          expect(got2['atalaia.field.player.$red']!['map'], isFalse);
          expect(fake2.events.join(), isNot(contains('Falcão')));
          expect(byUid(await udp.drain()).keys, ['atalaia.field.node.4']);
          fake2.events.clear();
          engine.endGame(gid);
          await emitter.cycle(full: false);
          final drops = shared(fake2.events);
          expect(drops.keys.toSet(), {
            'atalaia.field.node.4',
            'atalaia.field.player.$red',
          });
          for (final d in drops.values) {
            expect(d['stale']! as double, lessThan(d['start']! as double));
          }
          final s = emitter.status();
          expect(
            (s['remote'], s['remote_players'], s['remote_relay']),
            (true, true, true),
          );
        },
      );

      test(
        'the extraction zone, and a new socket gets everything again',
        () async {
          await rig(remote: true);
          putImageAndCorners();
          final game = engine.createGame({
            'name': 'v',
            'mode_id': 'org.atalaia.vip_payload',
            'teams': ['red', 'blue'],
            'assignments': {'4': 'checkpoint'},
            'params': {
              'extraction': '38.7215,-9.1390',
              'radius_m': 40,
              'vip_team': 'blue',
            },
          });
          engine.startGame(game['id']! as int, force: true);
          place(game['id']! as int, 4, 0.2, 0.3);
          final fake = relay();
          await emitter.cycle(full: true);
          expect(shared(fake.events).keys.toSet(), {
            'atalaia.field.node.4',
            'atalaia.field.game.${game['id']}.extraction',
          });
          fake.events.clear();
          expect((await emitter.cycle(full: false))['remote'], 0);
          emitter.resendAll(); // the stream took a new socket
          expect((await emitter.cycle(full: false))['remote'], 2);
          // Not ready: nothing is handed over (the Pi's push_cot gives 0).
          emitter.remoteReady = false;
          fake.events.clear();
          expect((await emitter.cycle(full: true))['remote'], 0);
          expect(fake.events, isEmpty);
          expect(emitter.status()['remote_relay'], isFalse);
          // Ready again: the whole picture at the next cycle.
          emitter.remoteReady = true;
          expect((await emitter.cycle(full: false))['remote'], 2);
        },
      );

      test('points and circles for everyone, in the relay\'s form', () async {
        await rig(remote: true);
        putImageAndCorners();
        runningGame();
        final fake = relay();
        final pin = field.addFeature(
          point({'type': 'objective', 'label': 'Bridge'}),
        )['id']!;
        final ring = field.addFeature(circle())['id']! as int;
        field.addFeature(polygon());
        field.addFeature(circle({'type': 'respawn', 'team': 'red'}));
        field.addFeature(point({'visibility': 'organisers'}));
        await emitter.cycle(full: true);
        final got = shared(fake.events);
        for (final ev in got.values) {
          expect(ev['map'], isTrue);
        }
        expect(got.keys.toSet(), {
          'atalaia.field.feature.$pin',
          'atalaia.field.feature.$ring',
        });
        final ringEv = got['atalaia.field.feature.$ring']!;
        expect(ringEv['type'], 'b-m-p-s-m');
        expect(
          fake.events.firstWhere((e) => e.contains('feature.$ring"')),
          contains('ce="30.0"'),
        );
        fake.events.clear();
        field.deleteFeature(ring);
        await emitter.cycle(full: false);
        final drops = [
          for (final e in fake.events)
            if (cotEvent(e)['uid'] == 'atalaia.field.feature.$ring')
              cotEvent(e),
        ];
        expect(drops, hasLength(1));
        expect(
          drops.single['stale']! as double,
          lessThan(drops.single['start']! as double),
        );
      });

      test('off by default', () async {
        await rig();
        putImageAndCorners();
        final gid = runningGame();
        place(gid, 4, 0.5, 0.5);
        final fake = relay();
        expect((await emitter.cycle(full: true))['remote'], 0);
        expect(fake.events, isEmpty);
        expect(emitter.status()['remote'], isFalse);
      });
    });
  });

  group('the senders', () {
    test('UDP to a multicast group on this host (TTL 1)', () async {
      final rx = await RawDatagramSocket.bind(
        InternetAddress.anyIPv4,
        0,
        reuseAddress: true,
      );
      final group = InternetAddress('239.2.3.1');
      try {
        NetworkInterface? lo;
        for (final i in await NetworkInterface.list(includeLoopback: true)) {
          if (i.addresses.any((a) => a.isLoopback)) lo = i;
        }
        try {
          rx.joinMulticast(group, lo);
        } on Exception catch (e) {
          markTestSkipped('no multicast on the loopback here: $e');
          return;
        }
        final got = Completer<Uint8List>();
        rx.listen((ev) {
          final d = ev == RawSocketEvent.read ? rx.receive() : null;
          if (d != null && !got.isCompleted) got.complete(d.data);
        });
        final sender = UdpCotSender('239.2.3.1:${rx.port}', interface: lo);
        try {
          final data = dropXml(
            'atalaia.f.node.1',
            cotTypeProp,
            38.7,
            -9.1,
            1e9,
          );
          expect(await sender.send([Uint8List.fromList(utf8.encode(data))]), 1);
          expect(sender.socket!.multicastHops, 1); // the field's own network
          final Uint8List bytes;
          try {
            bytes = await got.future.timeout(const Duration(seconds: 2));
          } on TimeoutException {
            markTestSkipped('the loopback does not deliver multicast here');
            return;
          }
          expect(utf8.decode(bytes), data);
        } finally {
          sender.close();
        }
      } finally {
        rx.close();
      }
    });

    test(
      'UDP from a given address (the field Wi-Fi\'s), one per datagram',
      () async {
        final rx = await Receiver.open();
        final sender = UdpCotSender(
          '127.0.0.1:${rx.port}',
          bindAddress: InternetAddress.loopbackIPv4,
        );
        try {
          final events = [
            for (final n in ['a', 'b', 'c']) drop(n),
          ];
          expect(await sender.send([for (final e in events) _utf8(e)]), 3);
          expect(sender.socket!.address, InternetAddress.loopbackIPv4);
          expect(await rx.drain(), events);
        } finally {
          sender.close();
          rx.close();
        }
        expect(
          () => UdpCotSender('atak.local:6969'),
          throwsA(isA<AtakConfigError>()),
        );
      },
    );

    test('TCP: each event with its declaration, one after another', () async {
      final rx = await TcpReceiver.open();
      try {
        final sender = TcpCotSender([
          '127.0.0.1:${rx.port}',
          '[::1]:1',
        ], timeout: const Duration(seconds: 20));
        final a = drop('a'), b = drop('b');
        final (sent, errors) = await sender.send([
          Uint8List.fromList(utf8.encode(a)),
          Uint8List.fromList(utf8.encode(b)),
        ]);
        expect(sent, 2);
        expect(errors.single, startsWith('::1:1: '));
        expect(await waitFor(() => rx.connections.length == 1), isTrue);
        expect(splitStream(rx.connections.single), [a, b]);
        final (none, noErrors) = await sender.send([]);
        expect((none, noErrors.isEmpty), (0, true));
      } finally {
        await rx.close();
      }
    });
  });
}

String drop(String n) => dropXml('atalaia.f.node.$n', cotTypeProp, 1, 2, 1e9);

Uint8List _utf8(String s) => Uint8List.fromList(utf8.encode(s));
