// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Cursor on Target (CoT) for ATAK on the Android field controller (PE24
/// slice S7): the Pi controller's controller/atalaia_controller/atak.py in
/// Dart (ADR-P4-7 as amended, P4R18), with the same events, uids, cycle
/// and status, checked byte for byte against the Pi's own output
/// (protocol/vectors/atak_xml.json, written by tools/atak_xml_vectors.py
/// from atak.py; test/controller/controller_atak_test.dart).
///
/// Off by default (`[atak] enabled = false`). When on, the controller in
/// charge of the live game sends one CoT `<event>` per box that has a place
/// on the georeferenced field plan of its level (controller_field.dart),
/// coloured by its owner, one for a VIP / Payload extraction zone, and the
/// field's map features:
///
/// - over UDP to [AtakConfig.multicast] (ATAK's mesh default
///   `239.2.3.1:6969`, TTL 1 so it stays on the field's network; a unicast
///   address works too), one event per datagram, every
///   [AtakConfig.intervalS] and at once when a box changes owner
///   (`zone.captured`, `zone.neutralized`, its STATE), moves on the plan, or
///   the map position, the levels, the features or the game change; when
///   the game ends every marker is dropped (stale before start);
/// - player positions never go to multicast. With [AtakConfig.players] they
///   go only to the staff ATAK devices of [AtakConfig.staffEndpoints] (TCP,
///   "host:port", default port 4242): GPS reports only, by pseudonymous
///   player id, never by name (decision M9-6);
/// - map features: only those for everyone to multicast; the staff devices
///   get them all; the remote relay gets the points and circles for
///   everyone, a circle as a spot marker with its radius as `ce`, never a
///   polygon (the relay's narrow form, controller_sync_format.dart
///   `cotEvent`);
/// - with [AtakConfig.remote] the same props, zones and (with
///   [AtakConfig.remotePlayers]) positions as CoT texts handed to
///   [AtakEmitter.remoteSink] while [AtakEmitter.remoteReady]: the remote GM
///   stream (the Pi's remote_gm.py) sets both, sends them as `cot`
///   messages of at most [maxCotEvents] events ([AtakEmitter.cotBatches])
///   and the site server relays them to the field's enrolled ATAK devices.
///
/// Decisions of the port:
///
/// - Dart has no ElementTree: [CotElement] is a small serializer that
///   writes what Python's `ET.tostring(..., short_empty_elements=True)`
///   writes for these elements: attributes in the order they were set, `&
///   < > "` and CR, LF, TAB escaped in attributes, `& < >` in text, an
///   element with no text and no children as `<x a="1" />`. Every text a
///   user wrote goes through [xmlText] first (characters XML 1.0 does not
///   allow dropped, whitespace folded as Python's `str.split()` does,
///   lengths capped), so nothing is ever pasted into the XML.
/// - Numbers are formatted as Python's `f"{v:.7f}"` (correctly rounded,
///   ties to even, `-0.0000000` kept), which `toStringAsFixed` is not
///   (ties away from zero): [pyFixed].
/// - The engine is synchronous and lives on the controller's own isolate;
///   the emitter is on the same isolate, as a listener of the engine
///   ([ControllerEngine.addListener], the Pi's `on_controller_message`) and
///   with timers instead of the Pi's thread: a full cycle every
///   `interval_s`, a short one every second while player positions are on,
///   and one at once (on the next turn of the event loop) for a change.
///   Cycles never overlap: each waits for the previous one's sends.
/// - "The controller in charge" is [ControllerEngine.inCharge] (the
///   election's leader with the game's key), as the Pi's `fc.is_controller`.
/// - Staff TCP endpoints are sent to concurrently (the Pi: one after the
///   other); what each gets is the same.
///
/// Android: sending multicast needs no `WifiManager.MulticastLock` (that
/// lock only lets the Wi-Fi chip pass multicast it receives up to apps),
/// nor any permission beyond INTERNET. On a phone with several networks
/// (Wi-Fi and mobile data, or a hotspot) the system may route the group's
/// datagrams out of the default network: give [UdpCotSender] the field
/// Wi-Fi's address (`bindAddress`, so Linux picks the interface that owns
/// it for multicast too) or its [NetworkInterface] (set as
/// `IP_MULTICAST_IF` through [RawSocketOption]; Dart's
/// `RawDatagramSocket.multicastInterface` is not implemented). Dart's
/// `RawDatagramSocket.send` never blocks: it returns 0 when the socket's
/// buffer is full, so [UdpCotSender] waits a little and tries again.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'controller_engine.dart';
import 'controller_field.dart' show Georef, levelsInUse;
import 'controller_positions.dart' show ControllerPositions;
import 'controller_sync_format.dart'
    show SyncFormatError, cotEvent, maxCotEvents;

const atakDefaultMulticast = '239.2.3.1:6969';
const atakDefaultStaffPort = 4242;
const atakStaffEndpointsMax = 8;
const cotXmlDecl = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n";
const cotDatagramMax = 1400;
const cotCallsignMax = 48;
const cotRemarksMax = 160;
const cotCallsignBytes = 160;
const cotRemarksBytes = 320;
const cotShapeCallsignBytes = 96;
const cotShapeRemarksBytes = 192;
const _escaped = {0x26: 5, 0x3c: 4, 0x3e: 4, 0x22: 6, 0x27: 6};
const atakTcpTimeout = Duration(seconds: 2);
const cotUnknown = '9999999.0';

const cotTypeProp = 'b-m-p-s-m';
const cotTypeZonePoint = 'b-m-p-s-m';
const cotTypePlayer = 'a-f-G-U-C';
const cotHowImage = 'h-e', cotHowPasted = 'h-p', cotHowGps = 'm-g';
const cotGroupRole = 'Team Member';
const cotTypeCircle = 'u-d-c-c';
const cotTypePolygon = 'u-d-f';
const cotStyleLinkType = 'b-x-KmlStyle';
const cotStrokeWeight = '3.0';
const cotFillAlpha = 0x60;
const cotBoundaryFillAlpha = 0x00;
const featureNames = {
  'safe_zone': 'Safe zone',
  'respawn': 'Respawn',
  'hq': 'HQ',
  'parking': 'Parking',
  'first_aid': 'First aid',
  'objective': 'Objective',
  'other': 'Feature',
  'boundary': 'Field boundary',
};
const featureColours = {
  'safe_zone': 0x14B8A6,
  'respawn': 0x6C757D,
  'hq': 0x6C757D,
  'parking': 0x546E7A,
  'first_aid': 0xE91E63,
  'objective': 0xF59E0B,
  'other': 0x94A3B8,
  'boundary': 0x84CC16,
};
const _colours = {
  'red': 0xD7263D,
  'blue': 0x1B6EE0,
  'green': 0x2A9D4B,
  'yellow': 0xE8B400,
  'orange': 0xEF7D1A,
  'purple': 0x8E44AD,
  'black': 0x333333,
  'white': 0xBBBBBB,
};
const _aliases = {
  'vermelho': 'red',
  'vermelha': 'red',
  'azul': 'blue',
  'verde': 'green',
  'amarelo': 'yellow',
  'amarela': 'yellow',
  'laranja': 'orange',
  'roxo': 'purple',
  'roxa': 'purple',
  'preto': 'black',
  'preta': 'black',
  'branco': 'white',
  'branca': 'white',
};
const _palette = [
  0xD7263D,
  0x1B6EE0,
  0x2A9D4B,
  0xE8B400,
  0x8E44AD,
  0xEF7D1A,
  0x16A2B8,
  0x6C757D,
];
const atakTeams = [
  'White',
  'Yellow',
  'Orange',
  'Magenta',
  'Red',
  'Maroon',
  'Purple',
  'Dark Blue',
  'Blue',
  'Cyan',
  'Teal',
  'Green',
  'Dark Green',
  'Brown',
];
final _atakTeam = {
  for (final t in atakTeams) t.toLowerCase().replaceAll(' ', ''): t,
};
const neutralArgb = -1;

class AtakConfigError implements Exception {
  AtakConfigError(this.message);
  final String message;
  @override
  String toString() => message;
}

// --- text and values ------------------------------------------------------------

bool _xmlChar(int c) =>
    c == 0x09 ||
    c == 0x0a ||
    c == 0x0d ||
    (c >= 0x20 && c <= 0xd7ff) ||
    (c >= 0xe000 && c <= 0xfffd) ||
    (c >= 0x10000 && c <= 0x10ffff);

/// Python's `str.isspace()` (what `str.split()` and `\s` split on).
bool _pySpace(int c) =>
    (c >= 0x09 && c <= 0x0d) ||
    (c >= 0x1c && c <= 0x20) ||
    c == 0x85 ||
    c == 0xa0 ||
    c == 0x1680 ||
    (c >= 0x2000 && c <= 0x200a) ||
    c == 0x2028 ||
    c == 0x2029 ||
    c == 0x202f ||
    c == 0x205f ||
    c == 0x3000;

const _pySpaceClass =
    r'[\t\n\x0b\x0c\r\x1c-\x20\x85\xa0  -    '
    r' 　]';

int _utf8Len(int c) => c < 0x80
    ? 1
    : c < 0x800
    ? 2
    : c < 0x10000
    ? 3
    : 4;

/// User text made safe for an XML 1.0 attribute or element (atak.py
/// `xml_text`): characters XML does not allow (controls, lone surrogates,
/// U+FFFE/U+FFFF) dropped, whitespace runs folded, at most [limit]
/// characters (code points) and, escaped as in an attribute and in UTF-8,
/// at most [maxBytes] bytes. Escaping is the serializer's job.
String xmlText(String value, int limit, [int? maxBytes]) {
  final words = <List<int>>[];
  var word = <int>[];
  for (final c in value.runes) {
    if (!_xmlChar(c)) continue;
    if (_pySpace(c)) {
      if (word.isNotEmpty) words.add(word);
      word = <int>[];
    } else {
      word.add(c);
    }
  }
  if (word.isNotEmpty) words.add(word);
  final joined = <int>[];
  for (var i = 0; i < words.length; i++) {
    if (i > 0) joined.add(0x20);
    joined.addAll(words[i]);
  }
  var text = joined.length > limit ? joined.sublist(0, limit) : joined;
  if (maxBytes != null) {
    var size = 0;
    for (var i = 0; i < text.length; i++) {
      size += _escaped[text[i]] ?? _utf8Len(text[i]);
      if (size > maxBytes) {
        text = text.sublist(0, i);
        while (text.isNotEmpty && _pySpace(text.last)) {
          text.removeLast();
        }
        break;
      }
    }
  }
  return String.fromCharCodes(text);
}

double _roundHalfEven(double x) {
  final r = x.roundToDouble();
  if ((r - x).abs() == 0.5) return 2 * (x / 2).roundToDouble();
  return r;
}

String _two(int v) => v.toString().padLeft(2, '0');

/// CCYY-MM-DDThh:mm:ss.sssZ in UTC (atak.py `cot_time`: Python's
/// `datetime.fromtimestamp`, microseconds rounded half to even, then the
/// milliseconds truncated).
String cotTime(num t) {
  final d = t.toDouble();
  var whole = d.truncateToDouble();
  var us = _roundHalfEven((d - whole) * 1e6);
  if (us >= 1e6) {
    us -= 1e6;
    whole += 1;
  } else if (us < 0) {
    us += 1e6;
    whole -= 1;
  }
  final dt = DateTime.fromMillisecondsSinceEpoch(
    whole.toInt() * 1000,
    isUtc: true,
  );
  final ms = (us ~/ 1000).toString().padLeft(3, '0');
  return '${dt.year.toString().padLeft(4, '0')}-${_two(dt.month)}-'
      '${_two(dt.day)}T${_two(dt.hour)}:${_two(dt.minute)}:'
      '${_two(dt.second)}.${ms}Z';
}

/// Python's `f"{v:.{digits}f}"`: the exact binary value rounded half to
/// even, the sign of a negative value (-0.0 too) kept.
String pyFixed(num value, int digits) {
  final v = value.toDouble();
  if (v.isNaN) return 'nan';
  if (v.isInfinite) return v > 0 ? 'inf' : '-inf';
  final neg = v.isNegative;
  final bd = ByteData(8)..setFloat64(0, v.abs());
  final hi = bd.getUint32(0), lo = bd.getUint32(4);
  final expBits = (hi >> 20) & 0x7ff;
  var mant = (BigInt.from(hi & 0xfffff) << 32) | BigInt.from(lo);
  int e;
  if (expBits == 0) {
    e = -1074;
  } else {
    mant |= BigInt.one << 52;
    e = expBits - 1075;
  }
  var numer = mant * BigInt.from(10).pow(digits);
  var denom = BigInt.one;
  if (e >= 0) {
    numer <<= e;
  } else {
    denom <<= -e;
  }
  var q = numer ~/ denom;
  final twice = (numer - q * denom) * BigInt.two;
  if (twice > denom || (twice == denom && q.isOdd)) q += BigInt.one;
  var s = q.toString();
  if (digits > 0) {
    s = s.padLeft(digits + 1, '0');
    s = '${s.substring(0, s.length - digits)}.${s.substring(s.length - digits)}';
  }
  return neg ? '-$s' : s;
}

String _deg(num v) => pyFixed(v, 7); // about a centimetre

String _metres(num? v) => v == null ? cotUnknown : pyFixed(v > 0 ? v : 0.0, 1);

/// A team's colour as signed 32-bit ARGB (ATAK's `<color argb>`), like the
/// console's.
int teamColour(String? team, List<String> teams) {
  if (team == null || team.isEmpty) return neutralArgb;
  final lower = team.toLowerCase();
  var rgb = _colours[_aliases[lower] ?? lower];
  if (rgb == null) {
    final i = teams.contains(team) ? teams.indexOf(team) : team.runes.length;
    rgb = _palette[i % _palette.length];
  }
  return (0xFF000000 | rgb) - (1 << 32);
}

/// An RGB colour and an alpha as signed 32-bit ARGB.
int argbOf(int rgb, [int alpha = 0xFF]) {
  final v = ((alpha & 0xFF) << 24) | (rgb & 0xFFFFFF);
  return v >= 1 << 31 ? v - (1 << 32) : v;
}

String _hex2(int v) => v.toRadixString(16).padLeft(2, '0');

/// Signed ARGB as KML's aabbggrr.
String kmlColour(int argb) {
  final v = argb & 0xFFFFFFFF;
  return _hex2((v >> 24) & 0xFF) +
      _hex2(v & 0xFF) +
      _hex2((v >> 8) & 0xFF) +
      _hex2((v >> 16) & 0xFF);
}

/// A map feature's ARGB: its team's colour, else its type's.
int featureColour(Map<String, Object?> feature, List<String> teams) {
  final team = feature['team'];
  if (team is String && team.isNotEmpty) return teamColour(team, teams);
  return argbOf(featureColours[feature['type']] ?? featureColours['other']!);
}

/// The ATAK team (`__group name`) for an Atalaia team named after a
/// colour, else null.
String? atakTeam(String? team) {
  if (team == null || team.isEmpty) return null;
  final lower = team.toLowerCase();
  final key = (_aliases[lower] ?? lower)
      .replaceAll(' ', '')
      .replaceAll('_', '')
      .replaceAll('-', '');
  return _atakTeam[key];
}

final _nd = RegExp(r'^\p{Nd}$', unicode: true);
bool _isNd(int c) => c >= 0 && _nd.hasMatch(String.fromCharCode(c));
final _extractionRe = RegExp(
  '^$_pySpaceClass*\\+?(-?\\p{Nd}{1,2}(?:\\.\\p{Nd}+)?)$_pySpaceClass*,'
  '$_pySpaceClass*\\+?(-?\\p{Nd}{1,3}(?:\\.\\p{Nd}+)?)$_pySpaceClass*\$',
  unicode: true,
);

/// Python's `float()` of a matched number: any Unicode decimal digit
/// counts (each block of ten starts at its zero).
double _pyFloat(String s) {
  final out = StringBuffer();
  for (final c in s.runes) {
    if (c == 0x2d || c == 0x2e || (c >= 0x30 && c <= 0x39)) {
      out.writeCharCode(c);
      continue;
    }
    var start = c;
    while (_isNd(start - 1)) {
      start--;
    }
    out.write((c - start) % 10);
  }
  return double.parse(out.toString());
}

/// VIP / Payload's `extraction` parameter, "latitude,longitude" (decision
/// M5-3), or null.
(double, double)? parseExtraction(Object? value) {
  if (value is! String || value.runes.length > 28) return null;
  final m = _extractionRe.firstMatch(value);
  if (m == null) return null;
  final lat = _pyFloat(m.group(1)!), lon = _pyFloat(m.group(2)!);
  if (!(lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0)) {
    return null;
  }
  return (lat, lon);
}

// --- the XML ----------------------------------------------------------------------

String _escAttr(String s) => s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll('\r', '&#13;')
    .replaceAll('\n', '&#10;')
    .replaceAll('\t', '&#09;');

String _escText(String s) =>
    s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

/// One XML element, serialised as Python's ElementTree does
/// (`ET.tostring(el, encoding="unicode", short_empty_elements=True)`).
class CotElement {
  CotElement(this.tag, [Map<String, String>? attrs, this.text])
    : attrs = attrs ?? <String, String>{};

  final String tag;

  /// In the order they were set (ElementTree keeps it).
  final Map<String, String> attrs;
  String? text;
  final children = <CotElement>[];

  /// Adds [child] and returns it (ET.SubElement).
  CotElement sub(String tag, [Map<String, String>? attrs, String? text]) {
    final child = CotElement(tag, attrs, text);
    children.add(child);
    return child;
  }

  void write(StringBuffer out) {
    out
      ..write('<')
      ..write(tag);
    attrs.forEach((k, v) {
      out
        ..write(' ')
        ..write(k)
        ..write('="')
        ..write(_escAttr(v))
        ..write('"');
    });
    final t = text;
    if ((t != null && t.isNotEmpty) || children.isNotEmpty) {
      out.write('>');
      if (t != null) out.write(_escText(t));
      for (final c in children) {
        c.write(out);
      }
      out
        ..write('</')
        ..write(tag)
        ..write('>');
    } else {
      out.write(' />');
    }
  }

  @override
  String toString() {
    final out = StringBuffer();
    write(out);
    return out.toString();
  }
}

// --- events -----------------------------------------------------------------------

/// One CoT event: the XML declaration, a newline and the `<event>` (TAK
/// Protocol version 0). Throws [ArgumentError] for a point off the globe.
String eventXml({
  required String uid,
  required String cotType,
  required String how,
  required num lat,
  required num lon,
  required num now,
  required num start,
  required num stale,
  num? ce,
  Iterable<CotElement> detail = const [],
}) {
  if (!(lat.isFinite &&
      lon.isFinite &&
      lat >= -90.0 &&
      lat <= 90.0 &&
      lon >= -180.0 &&
      lon <= 180.0)) {
    throw ArgumentError(
      'a CoT point needs a latitude of -90 to 90 and a longitude of -180 to 180',
    );
  }
  final ev = CotElement('event', {
    'version': '2.0',
    'uid': uid,
    'type': cotType,
    'time': cotTime(now),
    'start': cotTime(start),
    'stale': cotTime(stale),
    'how': how,
  });
  ev.sub('point', {
    'lat': _deg(lat),
    'lon': _deg(lon),
    'hae': cotUnknown,
    'ce': _metres(ce),
    'le': cotUnknown,
  });
  ev.sub('detail').children.addAll(detail);
  return cotXmlDecl + ev.toString();
}

/// A box's remarks (atak.py `node_remarks`): its owner (`-` for none),
/// `active` while the mode has made it the box to take (Progressive
/// Domination, decision PD-MODE-16), then its level's name.
String nodeRemarks(
  String ownerDisplay, {
  String? levelLabel,
  bool active = false,
}) {
  var out = ownerDisplay.isNotEmpty ? 'Atalaia: $ownerDisplay' : 'Atalaia: -';
  if (active) out += ', active';
  if (levelLabel != null) out += ', $levelLabel';
  return out;
}

/// A spot marker's details (takcot/examples "Marker - Spot.cot"): the
/// owner's colour, and its ATAK team when it is named after one (M9-5).
List<CotElement> markerDetail(
  String callsign,
  String remarks,
  int argb, {
  int? battery,
  String? group,
}) {
  final cs = xmlText(callsign, cotCallsignMax, cotCallsignBytes);
  final out = [
    CotElement('contact', {'callsign': cs.isEmpty ? '?' : cs}),
    CotElement(
      'remarks',
      null,
      xmlText(remarks, cotRemarksMax, cotRemarksBytes),
    ),
    CotElement('color', {'argb': '$argb'}),
    CotElement('usericon', {
      'iconsetpath': 'COT_MAPPING_SPOTMAP/$cotTypeProp/$argb',
    }),
  ];
  if (group != null) {
    out.add(CotElement('__group', {'name': group, 'role': cotGroupRole}));
  }
  if (battery != null && battery >= 0 && battery <= 100) {
    out.insert(0, CotElement('status', {'battery': '$battery'}));
  }
  return out;
}

/// A drawn shape's style and names, in the order of takcot/examples
/// "Drawing Shapes - *.cot", with tighter byte caps than a marker's.
List<CotElement> shapeDetail(
  String callsign,
  String remarks,
  int argb, [
  int fillAlpha = cotFillAlpha,
]) {
  final cs = xmlText(callsign, cotCallsignMax, cotShapeCallsignBytes);
  return [
    CotElement('strokeColor', {'value': '$argb'}),
    CotElement('strokeWeight', {'value': cotStrokeWeight}),
    CotElement('fillColor', {'value': '${argbOf(argb, fillAlpha)}'}),
    CotElement('contact', {'callsign': cs.isEmpty ? '?' : cs}),
    CotElement(
      'remarks',
      null,
      xmlText(remarks, cotRemarksMax, cotShapeRemarksBytes),
    ),
    CotElement('labels_on', {'value': 'true'}),
  ];
}

/// A player's details, as the Pi's `AtakEmitter._players` builds them.
List<CotElement> playerDetail(
  String callsign,
  String? group,
  String remarks,
) => [
  CotElement('contact', {
    'callsign': xmlText(callsign, cotCallsignMax, cotCallsignBytes),
  }),
  if (group != null)
    CotElement('__group', {'name': group, 'role': cotGroupRole}),
  CotElement('remarks', null, xmlText(remarks, cotRemarksMax, cotRemarksBytes)),
];

double _d(Object? v) => (v! as num).toDouble();

/// Where a feature's pin goes (map_features.py `centre`): its x, y, or a
/// polygon's vertex average.
(double, double) featureCentre(Map<String, Object?> feature) {
  if (feature['shape'] == 'polygon') {
    final pts = (feature['points']! as List).cast<Map<Object?, Object?>>();
    var sx = 0.0, sy = 0.0;
    for (final p in pts) {
      sx += _d(p['x']);
    }
    for (final p in pts) {
      sy += _d(p['y']);
    }
    return (sx / pts.length, sy / pts.length);
  }
  return (_d(feature['x']), _d(feature['y']));
}

/// A map feature's CoT event (MF-11): `(event, type, lat, lon)`, the point
/// being its pin. A point is a spot marker; a circle ATAK's drawn circle; a
/// polygon ATAK's drawn shape, closed by its first corner again at the end.
(String, String, double, double) featureXml({
  required String uid,
  required Map<String, Object?> feature,
  required Georef geo,
  required num now,
  required num stale,
  required String callsign,
  required String remarks,
  required int argb,
  String? group,
}) {
  final (cx, cy) = featureCentre(feature);
  final (lat, lon) = geo.toLatLon(cx, cy);
  final shape = feature['shape'];
  if (shape == 'point') {
    final data = eventXml(
      uid: uid,
      cotType: cotTypeProp,
      how: cotHowImage,
      lat: lat,
      lon: lon,
      now: now,
      start: now,
      stale: stale,
      detail: markerDetail(callsign, remarks, argb, group: group),
    );
    return (data, cotTypeProp, lat, lon);
  }
  final detail = <CotElement>[];
  String cotType;
  if (shape == 'circle') {
    final radius = pyFixed(_d(feature['radius_m']), 1);
    final el = CotElement('shape');
    el.sub('ellipse', {'major': radius, 'minor': radius, 'angle': '360'});
    final link = el.sub('link', {
      'uid': '$uid.Style',
      'type': cotStyleLinkType,
      'relation': 'p-c',
    });
    final style = link.sub('Style');
    final line = style.sub('LineStyle');
    line.sub('color', null, kmlColour(argb));
    line.sub('width', null, cotStrokeWeight);
    style
        .sub('PolyStyle')
        .sub('color', null, kmlColour(argbOf(argb, cotFillAlpha)));
    detail.add(el);
    cotType = cotTypeCircle;
  } else {
    final corners = [
      for (final p
          in (feature['points']! as List).cast<Map<Object?, Object?>>())
        geo.toLatLon(_d(p['x']), _d(p['y'])),
    ];
    for (final (la, lo) in [...corners, corners.first]) {
      detail.add(CotElement('link', {'point': '${_deg(la)},${_deg(lo)}'}));
    }
    cotType = cotTypePolygon;
  }
  final fill = feature['type'] == 'boundary'
      ? cotBoundaryFillAlpha
      : cotFillAlpha;
  detail.addAll(shapeDetail(callsign, remarks, argb, fill));
  final data = eventXml(
    uid: uid,
    cotType: cotType,
    how: cotHowImage,
    lat: lat,
    lon: lon,
    now: now,
    start: now,
    stale: stale,
    detail: detail,
  );
  return (data, cotType, lat, lon);
}

/// Removes a marker: its stale time before its start (MITRE's "drop
/// track").
String dropXml(String uid, String cotType, num lat, num lon, num now) =>
    eventXml(
      uid: uid,
      cotType: cotType,
      how: cotHowImage,
      lat: lat,
      lon: lon,
      now: now,
      start: now,
      stale: now - 1.0,
    );

// --- addresses and the [atak] settings ----------------------------------------------

final _endpointRe = RegExp(
  r'^(?:\[([0-9A-Fa-f:.]{2,45})\](?::([0-9]{1,5}))?|'
  r'([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?)$',
);

/// "host:port" (an IPv6 address in brackets, "[::1]:4242") as (host,
/// port); without a port, [defaultPort] if there is one.
(String, int) parseEndpoint(Object? text, [int? defaultPort]) {
  final m = text is String ? _endpointRe.firstMatch(text) : null;
  final shown = jsonEncode(text is String ? text : '$text');
  if (m == null) {
    throw AtakConfigError('$shown: host:port (an IPv6 address in brackets)');
  }
  final host = m.group(1) ?? m.group(3)!;
  final portText = m.group(2) ?? m.group(4);
  if (portText == null) {
    if (defaultPort == null) {
      throw AtakConfigError('$shown: host:port, with the port');
    }
    return (host, defaultPort);
  }
  final port = int.parse(portText);
  if (port < 1 || port > 65535) {
    throw AtakConfigError('$shown: a port of 1-65535');
  }
  return (host, port);
}

/// An IPv4 address as Python's `ipaddress.IPv4Address` takes it (four
/// decimal octets, no leading zeros), or null.
List<int>? _ipv4(String s) {
  final parts = s.split('.');
  if (parts.length != 4) return null;
  final out = <int>[];
  for (final p in parts) {
    if (p.isEmpty ||
        p.length > 3 ||
        !p.codeUnits.every((c) => c >= 0x30 && c <= 0x39) ||
        (p.length > 1 && p[0] == '0')) {
      return null;
    }
    final v = int.parse(p);
    if (v > 255) return null;
    out.add(v);
  }
  return out;
}

/// The `[atak]` section (config.py's `atak_*` settings).
class AtakConfig {
  const AtakConfig({
    this.enabled = false,
    this.multicast = atakDefaultMulticast,
    this.intervalS = 30.0,
    this.staffEndpoints = const [],
    this.players = false,
    this.remote = false,
    this.remotePlayers = false,
  });

  /// From the section's keys as the Pi names them: enabled, multicast,
  /// interval_s, staff_endpoints (a list or a comma list), players, remote,
  /// remote_players; a key left out keeps its default.
  factory AtakConfig.fromSection(Map<String, Object?> s) {
    const d = AtakConfig();
    bool flag(String k, bool def) {
      final v = s[k];
      if (v == null) return def;
      if (v is bool) return v;
      throw AtakConfigError('atak.$k: true or false');
    }

    final staff = s['staff_endpoints'];
    final List<String> endpoints;
    if (staff == null) {
      endpoints = const [];
    } else if (staff is String) {
      endpoints = [
        for (final e in staff.split(','))
          if (e.trim().isNotEmpty) e.trim(),
      ];
    } else if (staff is List && staff.every((e) => e is String)) {
      endpoints = staff.cast<String>();
    } else {
      throw AtakConfigError('atak.staff_endpoints: "host:port" texts');
    }
    final multicast = s['multicast'] ?? d.multicast;
    final interval = s['interval_s'] ?? d.intervalS;
    if (multicast is! String) {
      throw AtakConfigError('atak.multicast: an IP address and port');
    }
    if (interval is! num) {
      throw AtakConfigError('atak.interval_s must be 1-3600 seconds');
    }
    return AtakConfig(
      enabled: flag('enabled', d.enabled),
      multicast: multicast,
      intervalS: interval.toDouble(),
      staffEndpoints: endpoints,
      players: flag('players', d.players),
      remote: flag('remote', d.remote),
      remotePlayers: flag('remote_players', d.remotePlayers),
    );
  }

  final bool enabled;

  /// "host:port" of the UDP target ("" for none).
  final String multicast;
  final double intervalS;
  final List<String> staffEndpoints;
  final bool players;
  final bool remote;
  final bool remotePlayers;

  /// atak.py `check_config` and config.py `_check_atak`; [syncEnabled]:
  /// whether the controller's sync (whose stream the relay rides) is on.
  /// Throws [AtakConfigError].
  void checkConfig({bool syncEnabled = false}) {
    if (multicast.isNotEmpty) {
      final (host, _) = parseEndpoint(multicast);
      final v4 = _ipv4(host);
      if (v4 == null) {
        final v6 = host.contains(':') ? InternetAddress.tryParse(host) : null;
        if (v6 == null || v6.type != InternetAddressType.IPv6) {
          throw AtakConfigError(
            'atak.multicast: an IP address and port, such as 239.2.3.1:6969',
          );
        }
      }
      if (v4 == null || v4.every((b) => b == 0) || v4.every((b) => b == 255)) {
        throw AtakConfigError(
          'atak.multicast: an IPv4 multicast (or unicast) address and port, '
          'such as 239.2.3.1:6969',
        );
      }
    }
    if (staffEndpoints.length > atakStaffEndpointsMax) {
      throw AtakConfigError(
        'atak.staff_endpoints: at most $atakStaffEndpointsMax',
      );
    }
    for (final ep in staffEndpoints) {
      parseEndpoint(ep, atakDefaultStaffPort);
    }
    if (!(intervalS >= 1.0 && intervalS <= 3600.0)) {
      throw AtakConfigError('atak.interval_s must be 1-3600 seconds');
    }
    if (remote && !(enabled && syncEnabled)) {
      throw AtakConfigError(
        "atak.remote needs atak.enabled and sync.enabled (the relay rides the sync's stream)",
      );
    }
    if (remotePlayers && !remote) {
      throw AtakConfigError('atak.remote_players needs atak.remote');
    }
  }
}

// --- the senders --------------------------------------------------------------------

/// Where the multicast events go: one datagram each. Returns how many were
/// sent; throws on a socket error.
abstract interface class AtakUdpSender {
  Future<int> send(List<Uint8List> events);
  void close();
}

/// The staff devices: `(events sent, one error text per failed endpoint)`.
abstract interface class AtakTcpSender {
  Future<(int, List<String>)> send(List<Uint8List> events);
  void close();
}

/// One CoT event per datagram, to a multicast group (TTL 1: the field's
/// own network) or one host (atak.py `UdpSender`). The socket is bound on
/// the first send: to [bindAddress] when given (the field Wi-Fi's address
/// on a phone with several networks), and multicast goes out of
/// [interface] (or the bound address) when given.
class UdpCotSender implements AtakUdpSender {
  UdpCotSender(String target, {this.bindAddress, this.interface}) {
    final (host, port) = parseEndpoint(target);
    final addr = InternetAddress.tryParse(host);
    if (addr == null) throw AtakConfigError('$target: an IP address');
    address = addr;
    this.port = port;
  }

  late final InternetAddress address;
  late final int port;
  final InternetAddress? bindAddress;
  final NetworkInterface? interface;
  RawDatagramSocket? socket;
  Future<RawDatagramSocket>? _opening;

  bool get isMulticast => address.isMulticast;

  Future<RawDatagramSocket> _open() async {
    final s = await RawDatagramSocket.bind(
      bindAddress ?? InternetAddress.anyIPv4,
      0,
    );
    if (isMulticast) {
      s.multicastHops = 1;
      InternetAddress? out = bindAddress;
      final iface = interface;
      if (iface != null) {
        for (final a in iface.addresses) {
          if (a.type == InternetAddressType.IPv4) {
            out = a;
            break;
          }
        }
      }
      if (out != null && out.type == InternetAddressType.IPv4) {
        s.setRawOption(
          RawSocketOption(
            RawSocketOption.levelIPv4,
            RawSocketOption.IPv4MulticastInterface,
            Uint8List.fromList(out.rawAddress),
          ),
        );
      }
    }
    socket = s;
    return s;
  }

  @override
  Future<int> send(List<Uint8List> events) async {
    final s = socket ?? await (_opening ??= _open());
    _opening = null;
    for (final data in events) {
      var tries = 0;
      while (s.send(data, address, port) == 0) {
        // The socket's buffer is full: send never blocks in Dart.
        if (++tries > 40) {
          throw const SocketException('the UDP send buffer stays full');
        }
        await Future<void>.delayed(const Duration(milliseconds: 5));
      }
    }
    return events.length;
  }

  @override
  void close() {
    socket?.close();
    socket = null;
  }
}

/// Staff ATAK devices: one connection per endpoint and cycle, the events
/// one after another (atak.py `TcpSender`).
class TcpCotSender implements AtakTcpSender {
  TcpCotSender(List<String> endpoints, {this.timeout = atakTcpTimeout})
    : endpoints = [
        for (final e in endpoints) parseEndpoint(e, atakDefaultStaffPort),
      ];

  final List<(String, int)> endpoints;
  final Duration timeout;

  Future<String?> _one(String host, int port, Uint8List payload) async {
    Socket? s;
    try {
      s = await Socket.connect(host, port, timeout: timeout);
      s.add(payload);
      await s.flush().timeout(timeout);
      await s.close().timeout(timeout);
      return null;
    } on Exception catch (e) {
      s?.destroy();
      return '$host:$port: $e';
    }
  }

  @override
  Future<(int, List<String>)> send(List<Uint8List> events) async {
    if (events.isEmpty) return (0, <String>[]);
    final payload = Uint8List.fromList([for (final e in events) ...e]);
    final results = await Future.wait([
      for (final (host, port) in endpoints) _one(host, port, payload),
    ]);
    final errors = [for (final r in results) ?r];
    return ((endpoints.length - errors.length) * events.length, errors);
  }

  @override
  void close() {}
}

// --- the emitter ----------------------------------------------------------------------

typedef _Marker = (String, double, double);

/// Follows the engine's messages and sends the picture over UDP, to staff
/// over TCP and to the remote relay (atak.py `AtakEmitter`).
class AtakEmitter {
  AtakEmitter(
    this.engine,
    this.config, {
    this.fieldId = 'field',
    double Function()? wall,
    AtakUdpSender? udp,
    AtakTcpSender? tcp,
    this.bindAddress,
    this.multicastInterface,
    this.log,
  }) : _wall = wall ?? engine.wallSeconds,
       _udpGiven = udp,
       udp = udp,
       tcp =
           tcp ??
           (config.staffEndpoints.isNotEmpty
               ? TcpCotSender(config.staffEndpoints)
               : null) {
    engine.addListener(onControllerMessage);
    _listening = true;
  }

  final ControllerEngine engine;
  final AtakConfig config;

  /// The field's id in every uid (`atalaia.<field>.node.4`): the Pi's
  /// `field_id`.
  final String fieldId;
  final double Function() _wall;
  final AtakUdpSender? _udpGiven;

  /// The UDP sender, opened on the first send and closed by [stop].
  AtakUdpSender? udp;
  final AtakTcpSender? tcp;
  final InternetAddress? bindAddress;
  final NetworkInterface? multicastInterface;

  /// Warnings (a failed send), each once until it changes.
  final void Function(String message)? log;

  /// The remote relay (with [AtakConfig.remote]): the remote GM stream sets
  /// it; it gets the events of each cycle while [remoteReady], to queue
  /// and send as `cot` messages ([cotBatches]).
  void Function(List<String> events)? remoteSink;
  bool _remoteReady = false;

  /// Whether the site server takes the events on the stream's current
  /// socket (its `hello.ack` said `atak_relay: true`). Setting it true
  /// sends the whole picture again at once (the Pi's `on_relay_open`).
  bool get remoteReady => _remoteReady;
  set remoteReady(bool v) {
    final opened = v && !_remoteReady;
    _remoteReady = v;
    if (opened) resendAll();
  }

  bool _listening = false;
  final _dirty = <int>{};
  var _all = true;
  int? _end;
  final _ownerHint = <int, String?>{};
  String? _active; // the box a mode has made active, by name (PD-MODE-16)
  Object? _activeGame;
  final _sentOwner = <int, String?>{};
  final _markers = <String, _Marker>{};
  final _staffMarkers = <String, _Marker>{};
  final _remoteMarkers = <String, _Marker>{};
  var _nextPlayers = 0.0;
  Timer? _fullTimer, _playerTimer;
  var _wakePending = false;
  var _running = false;
  Future<Object?> _chain = Future<Object?>.value();

  final stats = <String, Object?>{
    'udp_events': 0,
    'tcp_events': 0,
    'remote_events': 0,
    'errors': 0,
    'last_error': null,
    'last_sent_at': null,
    'no_georef': false,
    'features': 0,
  };

  bool get _remoteOn => config.remote;

  /// The events of one `cot` message each, at most [maxCotEvents] (the
  /// Pi's remote_gm.py `_send_cot`).
  static List<List<String>> cotBatches(List<String> events) => [
    for (var i = 0; i < events.length; i += maxCotEvents)
      events.sublist(
        i,
        i + maxCotEvents < events.length ? i + maxCotEvents : events.length,
      ),
  ];

  // --- lifecycle ---------------------------------------------------------------

  /// A full cycle now, then every `interval_s`; a short one every second
  /// while player positions are on.
  void start() {
    if (_running) return;
    _running = true;
    if (!_listening) {
      engine.addListener(onControllerMessage);
      _listening = true;
    }
    _safeCycle(true);
    _fullTimer = Timer.periodic(
      Duration(milliseconds: (config.intervalS * 1000).round()),
      (_) => _safeCycle(true),
    );
    if (_playersOn || _remotePlayersOn) {
      _playerTimer = Timer.periodic(
        const Duration(seconds: 1),
        (_) => _safeCycle(false),
      );
    }
  }

  /// Stops the timers, waits for a cycle under way and closes the sockets
  /// (safe to call again).
  Future<void> stop() async {
    _running = false;
    _fullTimer?.cancel();
    _playerTimer?.cancel();
    _fullTimer = _playerTimer = null;
    if (_listening) {
      engine.removeListener(onControllerMessage);
      _listening = false;
    }
    await _chain;
    close();
  }

  /// Closes the sockets ([stop] does).
  void close() {
    udp?.close();
    udp = null;
    tcp?.close();
  }

  AtakUdpSender? _udpSender() {
    if (udp == null) {
      if (_udpGiven != null) {
        udp = _udpGiven;
      } else if (config.multicast.isNotEmpty) {
        udp = UdpCotSender(
          config.multicast,
          bindAddress: bindAddress,
          interface: multicastInterface,
        );
      }
    }
    return udp;
  }

  void _safeCycle(bool full) {
    unawaited(
      cycle(full: full).then<void>(
        (_) {},
        onError: (Object e) => log?.call('ATAK cycle failed: $e'),
      ),
    );
  }

  void _wake() {
    if (!_running || _wakePending) return;
    _wakePending = true;
    Timer.run(() {
      _wakePending = false;
      if (_running) _safeCycle(false);
    });
  }

  // --- what changed --------------------------------------------------------------

  /// The engine's live feed (atak.py `on_controller_message`).
  void onControllerMessage(Map<String, Object?> msg) {
    final kind = msg['type'];
    var wake = true;
    if (kind == 'node') {
      final node = msg['node'];
      final nid = node is Map ? node['node_id'] : null;
      if (node is Map && nid is int) {
        _ownerHint.remove(nid);
        final sent = _sentOwner.containsKey(nid) ? _sentOwner[nid] : '?';
        if (node['owner'] != sent) {
          _dirty.add(nid);
        } else {
          wake = false;
        }
      }
    } else if (kind == 'event') {
      final ev = msg['event'];
      final type = ev is Map ? ev['type'] : null;
      final node = ev is Map ? ev['node'] : null;
      if ((type == 'zone.captured' || type == 'zone.neutralized') &&
          node is int) {
        // Sent at once with the event's team: the box's next STATE
        // confirms it.
        final team = (ev! as Map)['team'];
        _ownerHint[node] = type == 'zone.captured' && team is String
            ? team
            : null;
        _dirty.add(node);
      } else if (type == 'progressive.activated' ||
          type == 'progressive.completed') {
        // The old and the new marker both change: all of them again.
        final data = (ev! as Map)['data'];
        final zone = data is Map ? data['zone'] : null;
        _active =
            type == 'progressive.activated' && zone is String && zone.isNotEmpty
            ? zone
            : null;
        _all = true;
      } else {
        wake = false;
      }
    } else if (kind == 'position' && msg['node_id'] is int) {
      _dirty.add(msg['node_id']! as int);
    } else if (kind == 'game') {
      final game = msg['game'];
      if (game is Map && game['state'] == 'ended' && game['id'] is int) {
        _end = game['id'] as int;
      }
      if (game is Map &&
          (game['state'] == 'ended' || game['id'] != _activeGame)) {
        _active = null;
      }
      _activeGame = game is Map ? game['id'] : null;
      _all = true;
    } else if (const [
      'field_georef',
      'field_image',
      'field_levels',
      'map_features',
    ].contains(kind)) {
      _all = true;
    } else {
      wake = false;
    }
    if (wake) _wake();
  }

  bool get _playersOn => config.players && tcp != null;

  bool get _remotePlayersOn => _remoteOn && config.remotePlayers;

  /// Everything again at the next cycle (the site server's relay has just
  /// taken a new socket).
  void resendAll() {
    _all = true;
    _wake();
  }

  // --- one cycle -------------------------------------------------------------------

  /// Sends what is due; the number of events sent per transport, `udp`,
  /// `tcp` and `remote`. Cycles run one after another.
  Future<Map<String, int>> cycle({bool full = true}) {
    final next = _chain.then((_) => _cycle(full));
    _chain = next.then<Object?>((_) => null, onError: (Object _) => null);
    return next;
  }

  Future<Map<String, int>> _cycle(bool full) {
    final dirty = Set.of(_dirty);
    _dirty.clear();
    final everything = full || _all;
    _all = false;
    final ended = _end;
    _end = null;
    final hints = Map.of(_ownerHint);
    final active = _active;
    final now = _wall();
    final udpOut = <String>[], tcpOut = <String>[], remoteOut = <String>[];
    if (ended != null) {
      udpOut.addAll(_drops(_markers, now));
      tcpOut.addAll(_drops(_staffMarkers, now));
      remoteOut.addAll(_drops(_remoteMarkers, now));
    }
    final game = _liveGame();
    final field = engine.field;
    final levels = field?.levelsMeta() ?? _defaultLevels;
    final geos = <int, Georef?>{
      if (game != null)
        for (var lv = 0; lv < levelsInUse(levels); lv++)
          lv: field?.georefFor(lv),
    };
    final anyGeo = geos.values.any((g) => g != null);
    stats['no_georef'] = game != null && !anyGeo;
    if (game != null && anyGeo) {
      final props = _props(
        game,
        geos,
        levels,
        now,
        hints,
        everything ? null : dirty,
        active,
      );
      udpOut.addAll(props);
      tcpOut.addAll(props);
      if (_remoteOn) remoteOut.addAll(props);
      if (everything) {
        final (u, t, r) = _features(game, geos, levels, now);
        udpOut.addAll(u);
        tcpOut.addAll(t);
        remoteOut.addAll(r);
      }
    } else {
      // No live game here or no map position any more: what ATAK shows is
      // no longer true.
      udpOut.addAll(_drops(_markers, now));
      tcpOut.addAll(_drops(_staffMarkers, now));
      remoteOut.addAll(_drops(_remoteMarkers, now));
    }
    final staff = _playersOn, remote = _remotePlayersOn;
    if (game != null &&
        (staff || remote) &&
        (everything || now >= _nextPlayers)) {
      for (final (uid, data, lat, lon) in _players(game, now)) {
        if (staff) {
          tcpOut.add(data);
          _staffMarkers[uid] = (cotTypePlayer, lat, lon);
        }
        if (remote) {
          // Never without remote_players (P4R18): the site server filters
          // again.
          remoteOut.add(data);
          _remoteMarkers[uid] = (cotTypePlayer, lat, lon);
        }
      }
      _nextPlayers = now + ControllerPositions.interval(game);
    }
    return _send(udpOut, tcpOut, remoteOut, now);
  }

  Future<Map<String, int>> _send(
    List<String> udpOut,
    List<String> tcpOut,
    List<String> remoteOut,
    double now,
  ) async {
    final out = {'udp': 0, 'tcp': 0, 'remote': 0};
    if (_remoteOn && remoteOut.isNotEmpty) {
      final sink = remoteSink;
      if (sink != null && _remoteReady) {
        final checked = <String>[];
        for (final text in remoteOut) {
          try {
            cotEvent(text);
            checked.add(text);
          } on SyncFormatError catch (e) {
            _error('remote: an event the relay would refuse ($e)');
          }
        }
        if (checked.isNotEmpty) sink(checked);
        out['remote'] = checked.length;
        _add('remote_events', checked.length);
      }
    }
    final u = udpOut.isNotEmpty ? _udpSender() : null;
    final sends = <Future<void>>[];
    if (u != null) {
      sends.add(() async {
        try {
          out['udp'] = await u.send([for (final e in udpOut) _bytes(e)]);
          _add('udp_events', out['udp']!);
        } on Exception catch (e) {
          _error('UDP ${config.multicast}: $e');
        }
      }());
    }
    final t = tcp;
    if (t != null && tcpOut.isNotEmpty) {
      sends.add(() async {
        final (sent, errors) = await t.send([
          for (final e in tcpOut) _bytes(e),
        ]);
        out['tcp'] = sent;
        _add('tcp_events', sent);
        for (final e in errors) {
          _error('TCP $e');
        }
      }());
    }
    await Future.wait(sends);
    if (out['udp']! > 0 || out['tcp']! > 0 || out['remote']! > 0) {
      stats['last_sent_at'] = now;
    }
    return out;
  }

  static Uint8List _bytes(String s) => Uint8List.fromList(utf8.encode(s));

  void _add(String key, int n) => stats[key] = (stats[key]! as int) + n;

  void _error(String text) {
    _add('errors', 1);
    if (stats['last_error'] != text) log?.call('ATAK: $text');
    stats['last_error'] = text;
  }

  Map<String, Object?>? _liveGame() {
    final game = engine.liveGame;
    if (game == null || game['state'] == 'ended') return null;
    // A standby controller sends nothing: the one in charge does.
    if (!engine.inCharge) return null;
    return game;
  }

  static List<String> _drops(Map<String, _Marker> markers, double now) {
    final out = [
      for (final e in markers.entries)
        dropXml(e.key, e.value.$1, e.value.$2, e.value.$3, now),
    ];
    markers.clear();
    return out;
  }

  String _uid(List<Object?> parts) =>
      ['atalaia', fieldId, for (final p in parts) '$p'].join('.');

  static String _display(Map<String, Object?> game, String? team) {
    if (team == null || team.isEmpty) return '';
    final all = game['team_info'];
    final info = all is Map ? all[team] : null;
    final name = info is Map ? info['display_name'] : null;
    return name is String && name.isNotEmpty ? '$name ($team)' : team;
  }

  static List<String> _teams(Map<String, Object?> game) => [
    for (final t in (game['teams'] as List?) ?? const []) '$t',
  ];

  static const _defaultLevels = <String, Object?>{
    'enabled': false,
    'count': 1,
    'names': [''],
  };

  /// The level a position on [level] is shown on (field_levels.py `shown`).
  static int _shown(Map<String, Object?> levels, Object? level) =>
      level is int && level >= 0 && level < levelsInUse(levels) ? level : 0;

  /// A level's name for the remarks (field_levels.py `label`).
  static String _label(Map<String, Object?> levels, int level) {
    final names = (levels['names'] as List?) ?? const [];
    final name = level >= 0 && level < names.length ? '${names[level]}' : '';
    return name.isEmpty ? 'L$level' : name;
  }

  List<String> _props(
    Map<String, Object?> game,
    Map<int, Georef?> geos,
    Map<String, Object?> levels,
    double now,
    Map<int, String?> hints,
    Set<int>? only,
    String? active,
  ) {
    final stale = now + 2 * config.intervalS;
    final teams = _teams(game);
    final gid = game['id']! as int;
    final places = <int, Map<Object?, Object?>>{
      for (final e in (engine.field?.places(gid) ?? const {}).entries)
        if (int.tryParse(e.key) != null && e.value is Map)
          int.parse(e.key): e.value! as Map,
    };
    final out = <String>[];
    final nodes = <int, Map<String, Object?>>{
      for (final n in engine.nodes(gid))
        if (n['node_id'] is int) n['node_id']! as int: n,
    };
    final ids = {...nodes.keys, ...places.keys}.toList()..sort();
    final levelsOn = levels['enabled'] == true;
    for (final nid in ids) {
      if (only != null && !only.contains(nid)) continue;
      final place = places[nid];
      if (place == null) continue; // not placed on the plan
      final level = _shown(levels, place['level']);
      final geo = geos[level];
      if (geo == null) continue; // its level has no place on the map
      final node = nodes[nid] ?? const {};
      final rawOwner = hints.containsKey(nid) ? hints[nid] : node['owner'];
      final owner = rawOwner is String ? rawOwner : null;
      final (lat, lon) = geo.toLatLon(_d(place['x']), _d(place['y']));
      final uid = _uid(['node', nid]);
      final rawName = node['name'];
      final name = rawName is String && rawName.isNotEmpty ? rawName : '$nid';
      final remarks = nodeRemarks(
        owner != null && owner.isNotEmpty ? _display(game, owner) : '',
        levelLabel: levelsOn ? _label(levels, level) : null,
        active: active != null && name == active,
      );
      final battery = node['battery_pct'];
      out.add(
        eventXml(
          uid: uid,
          cotType: cotTypeProp,
          how: cotHowImage,
          lat: lat,
          lon: lon,
          now: now,
          start: now,
          stale: stale,
          detail: markerDetail(
            name,
            remarks,
            teamColour(owner, teams),
            battery: battery is int ? battery : null,
            group: atakTeam(owner),
          ),
        ),
      );
      _sentOwner[nid] = owner;
      _mark(uid, cotTypeProp, lat, lon);
    }
    if (only == null) out.addAll(_zones(game, now, stale, teams));
    return out;
  }

  /// VIP / Payload's extraction zone (public, decision M5-1): a marker with
  /// the radius as ce.
  List<String> _zones(
    Map<String, Object?> game,
    double now,
    double stale,
    List<String> teams,
  ) {
    final params = game['params'] is Map
        ? game['params']! as Map
        : const <Object?, Object?>{};
    final where = parseExtraction(params['extraction']);
    if (where == null) return [];
    final rawRadius = params.containsKey('radius_m') ? params['radius_m'] : 25;
    final radius = rawRadius is num ? rawRadius.toDouble() : 25.0;
    final vip = params['vip_team'];
    final team = vip is String ? vip : null;
    final uid = _uid(['game', game['id'], 'extraction']);
    final shown = _display(game, team);
    final data = eventXml(
      uid: uid,
      cotType: cotTypeZonePoint,
      how: cotHowPasted,
      lat: where.$1,
      lon: where.$2,
      now: now,
      start: now,
      stale: stale,
      ce: radius,
      detail: markerDetail(
        'Extraction',
        'Atalaia: ${shown.isEmpty ? '-' : shown}, ${pyFixed(radius, 0)} m',
        teamColour(team, teams),
        group: atakTeam(team),
      ),
    );
    _mark(uid, cotTypeZonePoint, where.$1, where.$2);
    return [data];
  }

  /// The field's map features on levels in use whose level has a place on
  /// the map (MF-11 to MF-13), as (multicast, staff, remote) events; one
  /// that went is dropped where it was sent.
  (List<String>, List<String>, List<String>) _features(
    Map<String, Object?> game,
    Map<int, Georef?> geos,
    Map<String, Object?> levels,
    double now,
  ) {
    final stale = now + 2 * config.intervalS;
    final teams = _teams(game);
    final prefix = '${_uid(['feature'])}.';
    final udpOut = <String>[], tcpOut = <String>[], remoteOut = <String>[];
    final sentUdp = <String, _Marker>{},
        sentTcp = <String, _Marker>{},
        sentRemote = <String, _Marker>{};
    final levelsOn = levels['enabled'] == true;
    for (final f
        in engine.field?.featuresInUse() ?? const <Map<String, Object?>>[]) {
      final level = f['level']! as int;
      final geo = geos[level];
      if (geo == null) continue; // its level has no place on the map
      final uid = '$prefix${f['id']}';
      final rawTeam = f['team'];
      final team = rawTeam is String && rawTeam.isNotEmpty ? rawTeam : null;
      final name = featureNames[f['type']] ?? featureNames['other']!;
      var remarks = 'Atalaia: $name';
      if (team != null) remarks += ', ${_display(game, team)}';
      if (f['visibility'] == 'team') {
        remarks += ', team only';
      } else if (f['visibility'] == 'organisers') {
        remarks += ', organisers only';
      }
      if (f['shape'] == 'circle') {
        remarks += ', ${pyFixed(_d(f['radius_m']), 0)} m';
      }
      if (levelsOn) remarks += ', ${_label(levels, level)}';
      final note = f['note'];
      if (note is String && note.isNotEmpty) remarks += '. $note';
      final argb = featureColour(f, teams);
      final group = atakTeam(team);
      final label = f['label'];
      final callsign = label is String && label.isNotEmpty ? label : name;
      final (data, kind, lat, lon) = featureXml(
        uid: uid,
        feature: f,
        geo: geo,
        now: now,
        stale: stale,
        callsign: callsign,
        remarks: remarks,
        argb: argb,
        group: group,
      );
      // The staff's devices see every feature, as the organisers do (MF-12).
      tcpOut.add(data);
      sentTcp[uid] = (kind, lat, lon);
      if (f['visibility'] != 'everyone') continue; // never on the Wi-Fi
      udpOut.add(data);
      sentUdp[uid] = (kind, lat, lon);
      if (_remoteOn && f['shape'] != 'polygon') {
        // The relay's narrow form takes spot markers only (MF-13): a circle
        // goes as its centre with the radius as ce.
        remoteOut.add(
          eventXml(
            uid: uid,
            cotType: cotTypeProp,
            how: cotHowImage,
            lat: lat,
            lon: lon,
            now: now,
            start: now,
            stale: stale,
            ce: f['shape'] == 'circle' ? _d(f['radius_m']) : null,
            detail: markerDetail(callsign, remarks, argb, group: group),
          ),
        );
        sentRemote[uid] = (cotTypeProp, lat, lon);
      }
    }
    for (final (out, markers, sent) in [
      (udpOut, _markers, sentUdp),
      (tcpOut, _staffMarkers, sentTcp),
      (remoteOut, _remoteMarkers, sentRemote),
    ]) {
      final gone = [
        for (final u in markers.keys)
          if (u.startsWith(prefix) && !sent.containsKey(u)) u,
      ];
      for (final u in gone) {
        final (t, la, lo) = markers.remove(u)!;
        out.add(dropXml(u, t, la, lo, now));
      }
      markers.addAll(sent);
    }
    stats['features'] = sentTcp.length;
    return (udpOut, tcpOut, remoteOut);
  }

  /// A box or zone sent: every transport that got it drops it at the end.
  void _mark(String uid, String cotType, double lat, double lon) {
    _markers[uid] = (cotType, lat, lon);
    _staffMarkers[uid] = (cotType, lat, lon);
    if (_remoteOn) _remoteMarkers[uid] = (cotType, lat, lon);
  }

  /// Staff endpoints and the remote relay only, never UDP: every GPS
  /// position of the live game, as (uid, event, lat, lon).
  List<(String, String, double, double)> _players(
    Map<String, Object?> game,
    double now,
  ) {
    final teams = _teams(game);
    final interval = ControllerPositions.interval(game);
    final levels = engine.field?.levelsMeta() ?? _defaultLevels;
    final gid = game['id']! as int;
    final all = engine.positions?.playerPositions(gid) ?? const {};
    final out = <(String, String, double, double)>[];
    for (final pid in all.keys.toList()..sort()) {
      final pos = all[pid]!;
      final plat = pos['lat'], plon = pos['lon'];
      if (pos['source'] != 'gps' || plat is! num || plon is! num) continue;
      final received = pos['received_at'];
      final seen = received is num && received != 0 ? received.toDouble() : now;
      final stale = seen + 2 * interval;
      if (stale <= now) continue;
      final teamId = pos['team'];
      final team = teamId is int && teamId >= 1 && teamId <= teams.length
          ? teams[teamId - 1]
          : null;
      final rawRole = engine.checkin?.checkinRow(gid, pid)?['role'];
      final role = rawRole is String && rawRole.isNotEmpty ? rawRole : 'player';
      final callsign = role == 'vip' ? '$pid VIP' : pid;
      final shown = _display(game, team);
      var remarks = 'Atalaia: ${shown.isEmpty ? '-' : shown}, $role';
      final level = pos['level'];
      if (levels['enabled'] == true &&
          level is int &&
          level < levelsInUse(levels)) {
        // ML-7: only a level the phone gave.
        remarks += ', ${_label(levels, level)}';
      }
      final uid = _uid(['player', pid]);
      final lat = plat.toDouble(), lon = plon.toDouble();
      final acc = pos['accuracy_m'];
      out.add((
        uid,
        eventXml(
          uid: uid,
          cotType: cotTypePlayer,
          how: cotHowGps,
          lat: lat,
          lon: lon,
          now: now,
          start: seen < now ? seen : now,
          stale: stale,
          ce: acc is num ? acc : null,
          detail: playerDetail(callsign, atakTeam(team), remarks),
        ),
        lat,
        lon,
      ));
    }
    return out;
  }

  // --- status ------------------------------------------------------------------------

  /// GET /api/v1/atak's answer (atak.py `status`).
  Map<String, Object?> status() => {
    'enabled': true,
    'multicast': config.multicast.isEmpty ? null : config.multicast,
    'staff_endpoints': config.staffEndpoints.length,
    'players': config.players,
    'interval_s': config.intervalS,
    'markers': _markers.length,
    'remote': _remoteOn,
    'remote_players': _remotePlayersOn,
    'remote_relay': _remoteOn && _remoteReady,
    ...stats,
  };
}
