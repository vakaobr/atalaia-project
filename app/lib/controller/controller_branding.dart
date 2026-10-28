// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Field and team branding on a phone controller (slice S7b of PE24): the
/// Dart counterpart of the Pi controller's
/// controller/atalaia_controller/branding.py (decisions BR1-BR24), with the
/// team display names and crests of a game (engine.py `_team_entry` and
/// `set_team_info`, BR12-BR15).
///
/// The field's branding is its name (the check-in poster's), a logo, an
/// optional wallpaper and an accent colour, set by the GM in the console and
/// kept in the store. Teams get a display name and a crest per game next to
/// their colour (the colour stays the team's name: box LEDs and buttons need
/// it); team presets keep a club's name and crest for the next game.
///
/// Everything here is public to the field's network: no token is needed to
/// read it, and none of it is personal data. Uploads are PNG, JPEG or WebP
/// only, checked and stripped of metadata by controller_images.dart (the
/// Dart port of images.py).
///
/// Images are stored once, by the SHA-256 of their checked bytes, which is
/// also their ETag: each in its own store document (`img_` and the first 28
/// hex digits of its id), listed in the `images` document (decision
/// PE24-85). A logo or wallpaper that is replaced is deleted at once when
/// nothing else uses it; a crest nothing refers to is deleted a day after its
/// upload (purge, from the engine's tick).
///
/// Slice S7 (the site sync, controller_sync.dart): with the sync's branding
/// set to "site" ([siteManaged]) the field's branding and the site's saved
/// teams come from the site server ([applySite], branding.py
/// `apply_site`), and the console cannot change them (409), as on a Pi
/// with `[sync] branding = "site"`.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'controller_box_logo.dart';
import 'controller_checkin.dart';
import 'controller_engine.dart';
import 'controller_images.dart';

const fieldNameMax = 48;

/// Crests kept at once (decision BR8).
const crestMax = 500;

/// An unused crest's life after its upload.
const crestGraceS = 24 * 3600;
const _purgeEveryS = 600;

/// A team's display name's most characters (BR13).
const teamDisplayMax = 32;

/// The colour a team preset usually plays: a team name as the boxes know it.
const _teamNameMax = 23;

/// The field's images and their limits.
const brandingSlots = {
  'logo': ImageLimits.logo,
  'wallpaper': ImageLimits.wallpaper,
};

final _accent = RegExp(r'^#[0-9a-fA-F]{6}$');
final _crestId = RegExp(r'^[0-9a-f]{64}$');

String etagOf(String text) => '"$text"';

bool _control(int c) =>
    c < 0x20 || (c >= 0x7f && c <= 0x9f) || (c >= 0xd800 && c <= 0xdfff);

/// A team's display name: 1-32 characters without control characters, or
/// null to clear it (engine.py `display_name`).
String? displayName(Object? value, String name) {
  if (value == null) return null;
  if (value is! String) throw ControllerError('$name: text');
  final v = value.trim();
  if (v.isEmpty) return null;
  if (v.runes.length > teamDisplayMax || v.runes.any(_control)) {
    throw ControllerError(
      '$name: 1-$teamDisplayMax characters without control characters',
    );
  }
  return v;
}

/// Python's json.dumps(value, sort_keys=True), for the view's ETag.
String _pyJson(Object? v) => switch (v) {
  null => 'null',
  true => 'true',
  false => 'false',
  final String s => _pyString(s),
  final double d => d == d.truncateToDouble() ? d.toStringAsFixed(1) : '$d',
  final num n => '$n',
  final List<Object?> l => '[${l.map(_pyJson).join(', ')}]',
  final Map<Object?, Object?> m =>
    '{${(m.keys.map((k) => '$k').toList()..sort()).map((k) => '${_pyString(k)}: ${_pyJson(m[k])}').join(', ')}}',
  _ => _pyString('$v'),
};

String _pyString(String s) {
  final out = StringBuffer('"');
  for (final c in s.codeUnits) {
    switch (c) {
      case 0x22:
        out.write(r'\"');
      case 0x5c:
        out.write(r'\\');
      case 0x0a:
        out.write(r'\n');
      case 0x0d:
        out.write(r'\r');
      case 0x09:
        out.write(r'\t');
      case 0x08:
        out.write(r'\b');
      case 0x0c:
        out.write(r'\f');
      default:
        if (c < 0x20 || c > 0x7e) {
          out.write('\\u${c.toRadixString(16).padLeft(4, '0')}');
        } else {
          out.writeCharCode(c);
        }
    }
  }
  out.write('"');
  return out.toString();
}

class ControllerBranding {
  ControllerBranding(this.engine, {this.fieldId = 'field'}) {
    engine.branding = this;
  }

  final ControllerEngine engine;

  /// The field's id (the check-in's `field_id`).
  final String fieldId;

  /// Public reads per address and minute.
  final rate = RateLimit(240);
  double _lastPurge = 0;

  /// The field's branding and saved teams are the site server's (the
  /// sync's branding is "site"; branding.py `from_site`).
  bool siteManaged = false;
  var _applying = false;

  static const _sitePresets = 'branding.site_presets';
  static const _setting = 'branding.field';
  static const _boxLogoSetting = 'branding.box_logo';
  static const _nameSetting = 'branding.field_name';
  static const _imagesDoc = 'images';
  static const _teamPresetsDoc = 'team_presets';

  // --- the store's images -----------------------------------------------------

  Map<String, Object?> _images() =>
      (engine.store.document(_imagesDoc) as Map?)?.cast<String, Object?>() ??
      {};

  static String _docOf(String id) => 'img_${id.substring(0, 28)}';

  /// An image's record (with its bytes when [withData]), or null.
  Map<String, Object?>? image(String id, {bool withData = true}) {
    final row = _images()[id];
    if (row is! Map) return null;
    final out = row.cast<String, Object?>();
    if (!withData) return out;
    final data = engine.store.document(_docOf(id));
    if (data is! String) return null;
    return {...out, 'data': base64.decode(data)};
  }

  /// Stores a checked image once; false if it was there already.
  bool _putImage(String id, String kind, CheckedImage img) {
    final rows = _images();
    if (rows.containsKey(id)) return false;
    engine.store.putDocument(_docOf(id), base64.encode(img.data));
    rows[id] = {
      'id': id,
      'kind': kind,
      'content_type': img.contentType,
      'width': img.width,
      'height': img.height,
      'created_at': engine.wallSeconds(),
      'bytes': img.data.length,
    };
    engine.store.putDocument(_imagesDoc, rows);
    return true;
  }

  bool _deleteImage(String id) {
    final rows = _images();
    if (rows.remove(id) == null) return false;
    engine.store.putDocument(_imagesDoc, rows);
    engine.store.putDocument(_docOf(id), null);
    return true;
  }

  List<Map<String, Object?>> _imageIds([String? kind]) {
    final out =
        [
          for (final r in _images().values)
            if (r is Map && (kind == null || r['kind'] == kind))
              r.cast<String, Object?>(),
        ]..sort(
          (a, b) =>
              (a['created_at']! as num).compareTo(b['created_at']! as num),
        );
    return out;
  }

  // --- the field ------------------------------------------------------------

  Map<String, Object?> _saved() {
    final raw = engine.store.getSetting(_setting);
    if (raw == null || raw.isEmpty) return {};
    try {
      final v = jsonDecode(raw);
      return v is Map ? v.cast<String, Object?>() : {};
    } on FormatException {
      return {};
    }
  }

  void _save(Map<String, Object?> saved) {
    final keys = saved.keys.toList()..sort();
    engine.store.setSetting(
      _setting,
      jsonEncode({for (final k in keys) k: saved[k]}),
    );
  }

  /// One name for the field: the poster's (decision BR4).
  String fieldName() {
    final svc = engine.checkin;
    if (svc != null) return '${svc.posterFields()['field_name']}';
    return engine.store.getSetting(_nameSetting) ?? 'Atalaia';
  }

  Map<String, Object?>? _imageRef(String slot, Object? id) {
    final img = id is String ? image(id, withData: false) : null;
    if (img == null) return null;
    return {
      'url': '/api/v1/field/branding/$slot',
      'id': img['id'],
      'etag': etagOf('${img['id']}'),
      'content_type': img['content_type'],
      'width': img['width'],
      'height': img['height'],
      'bytes': img['bytes'],
    };
  }

  /// GET /api/v1/field/branding: no token, no personal data.
  Map<String, Object?> view() {
    final saved = _saved();
    final out = <String, Object?>{
      'version': 1,
      'field_id': engine.checkin?.config.fieldId ?? fieldId,
      'field_name': fieldName(),
      'accent': saved['accent'],
      'logo': _imageRef('logo', saved['logo']),
      'wallpaper': _imageRef('wallpaper', saved['wallpaper']),
    };
    // PKE-4: the console says so and does not offer to edit it (absent when local).
    if (siteManaged) out['source'] = 'site';
    final digest = sha256.convert(utf8.encode(_pyJson(out))).toString();
    out['etag'] = etagOf(digest.substring(0, 32));
    return out;
  }

  Map<String, Object?> _changed() {
    final v = view();
    engine.emit({'type': 'branding', 'branding': v});
    return v;
  }

  void _localOnly() {
    if (siteManaged) {
      throw ControllerError.conflict(
        "the field's branding comes from the site server (the sync's "
        'branding is "site"): change it there',
      );
    }
  }

  /// PUT /api/v1/field/branding {"field_name"?, "accent"?}.
  Map<String, Object?> setField(Map<String, Object?> spec) {
    _localOnly();
    final unknown =
        spec.keys.where((k) => k != 'field_name' && k != 'accent').toList()
          ..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError(
        'unknown branding fields $unknown (images have their own endpoints)',
      );
    }
    final saved = _saved();
    if (spec.containsKey('accent')) {
      final accent = spec['accent'];
      if (accent == null || accent == '') {
        saved.remove('accent');
      } else if (accent is! String || !_accent.hasMatch(accent)) {
        throw ControllerError(
          'accent: a colour as #rrggbb, or null for the default',
        );
      } else {
        saved['accent'] = accent.toLowerCase();
      }
    }
    if (spec.containsKey('field_name')) {
      final name = spec['field_name'];
      if (name is! String ||
          name.trim().runes.isEmpty ||
          name.trim().runes.length > fieldNameMax ||
          name.runes.any((c) => c < 0x20 || (c >= 0x7f && c <= 0x9f))) {
        throw ControllerError(
          'field_name: 1-$fieldNameMax characters without control characters',
        );
      }
      final svc = engine.checkin;
      if (svc != null) {
        svc.setPoster({'field_name': name.trim()});
      } else {
        engine.store.setSetting(_nameSetting, name.trim());
      }
    }
    _save(saved);
    return _changed();
  }

  /// PUT /api/v1/field/branding/{logo|wallpaper}: raw PNG, JPEG or WebP.
  Map<String, Object?> putImage(
    String slot,
    Uint8List data,
    String contentType,
  ) {
    _localOnly();
    final checked = _check(data, contentType, brandingSlots[slot]!);
    final id = sha256.convert(checked.data).toString();
    _putImage(id, slot, checked);
    final saved = _saved();
    final old = saved[slot];
    saved[slot] = id;
    _save(saved);
    if (old is String && old != id) _dropIfUnused(old);
    return _changed();
  }

  Map<String, Object?> deleteImage(String slot) {
    _localOnly();
    final saved = _saved();
    final old = saved.remove(slot);
    _save(saved);
    if (old is String) _dropIfUnused(old);
    return _changed();
  }

  /// The logo or wallpaper with its bytes, or null.
  Map<String, Object?>? slotImage(String slot) {
    final id = _saved()[slot];
    return id is String ? image(id) : null;
  }

  /// The field's logo as a Field Box draws it (controller_box_logo.dart,
  /// decisions PKG-1 and LOGO-1): the source image's id and the box-ready
  /// bytes, or null when there is no logo or none a box can draw. A PNG is
  /// converted here (kept by the image's id, so each logo is converted once);
  /// a JPEG or WebP logo is the bytes the GM console made in the browser and
  /// uploaded for exactly this logo ([putBoxLogo]), when there are any.
  (String, Uint8List)? boxLogo() {
    final img = slotImage('logo');
    if (img == null) return null;
    final id = img['id']! as String;
    if (img['content_type'] != 'image/png') return _uploadedBoxLogo(id);
    if (_boxLogo == null || _boxLogo!.$1 != id) {
      try {
        _boxLogo = (id, convertBoxLogo(img['data']! as Uint8List));
      } on BoxLogoError {
        _boxLogo = (id, Uint8List(0));
      }
    }
    return _boxLogo!.$2.isEmpty ? null : _boxLogo;
  }

  (String, Uint8List)? _uploadedBoxLogo(String id) {
    final raw = engine.store.getSetting(_boxLogoSetting);
    if (raw == null || raw.isEmpty) return null;
    try {
      final v = jsonDecode(raw);
      if (v is! Map || v['id'] != id || v['data'] is! String) return null;
      final data = base64Decode(v['data'] as String);
      return checkBoxLogo(data) ? (id, data) : null;
    } on FormatException {
      return null;
    }
  }

  /// PUT /api/v1/field/branding/logo/box?id=<logo id>: the box-ready bytes of
  /// the field's JPEG or WebP logo, made by the GM console (the controller has
  /// no decoder for them). Checked (size, header) and kept for that logo
  /// only; a new logo, or none, makes them stale and they are never served.
  Map<String, Object?> putBoxLogo(String id, Uint8List data) {
    _localOnly();
    final img = slotImage('logo');
    if (img == null || img['id'] != id) {
      throw ControllerError.conflict(
        "the box logo is for another logo than the field's: upload the logo "
        'first',
      );
    }
    if (img['content_type'] == 'image/png') {
      throw ControllerError.conflict(
        'a PNG logo is converted by the controller itself',
      );
    }
    if (!checkBoxLogo(data)) {
      throw ControllerError(
        'the box logo is $boxLogoSize bytes: \'ALG1\', 96, 96 and 9,216 '
        'RGB565 pixels',
      );
    }
    engine.store.setSetting(
      _boxLogoSetting,
      jsonEncode({'id': id, 'data': base64Encode(data)}),
    );
    return view();
  }

  (String, Uint8List)? _boxLogo;

  static CheckedImage _check(
    Uint8List data,
    String contentType,
    ImageLimits limits,
  ) {
    try {
      return checkImage(data, contentType, limits);
    } on ImageError catch (e) {
      throw ControllerError(e.message, status: e.status);
    }
  }

  // --- crests and team presets ---------------------------------------------------

  /// POST /api/v1/crests: a team crest, stored once by its checked bytes'
  /// SHA-256; (its reference, whether it is new).
  (Map<String, Object?>, bool) addCrest(Uint8List data, String contentType) {
    final checked = _check(data, contentType, ImageLimits.crest);
    final id = sha256.convert(checked.data).toString();
    if (image(id, withData: false) == null &&
        _imageIds('crest').length >= crestMax) {
      purge(force: true);
      if (_imageIds('crest').length >= crestMax) {
        throw ControllerError.conflict(
          'the controller keeps at most $crestMax crests; delete team presets first',
        );
      }
    }
    final created = _putImage(id, 'crest', checked);
    return (crestRef(id), created);
  }

  Map<String, Object?> crestRef(String id) {
    final img = image(id, withData: false);
    if (img == null) throw ControllerError.notFound('no crest $id');
    return {
      'crest_id': id,
      'url': '/api/v1/crests/$id',
      'etag': etagOf(id),
      'content_type': img['content_type'],
      'width': img['width'],
      'height': img['height'],
      'bytes': img['bytes'],
    };
  }

  Map<String, Object?>? crest(String id) =>
      _crestId.hasMatch(id) ? image(id) : null;

  /// A crest id a game or preset may name: an uploaded one.
  bool crestExists(Object? id) =>
      id is String &&
      _crestId.hasMatch(id) &&
      image(id, withData: false) != null;

  Map<String, Object?> _presetDoc() =>
      (engine.store.document(_teamPresetsDoc) as Map?)
          ?.cast<String, Object?>() ??
      {'next_id': 1, 'items': <Object?>[]};

  List<Map<String, Object?>> _presetRows() => [
    for (final p in (_presetDoc()['items'] as List?) ?? const [])
      (p as Map).cast<String, Object?>(),
  ];

  /// Every team preset, by name.
  List<Map<String, Object?>> teamPresetRows() =>
      _presetRows()..sort((a, b) => '${a['name']}'.compareTo('${b['name']}'));

  Map<String, Object?>? teamPreset(int id) {
    for (final p in _presetRows()) {
      if (p['id'] == id) return p;
    }
    return null;
  }

  (String, String?, String?) _presetSpec(
    Map<String, Object?> spec,
    Map<String, Object?>? current,
  ) {
    final unknown =
        spec.keys
            .where((k) => !const ['name', 'colour', 'crest_id'].contains(k))
            .toList()
          ..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError('unknown team preset fields $unknown');
    }
    var name = current?['name'] as String?;
    var colour = current?['colour'] as String?;
    var crestId = current?['crest_id'] as String?;
    if (spec.containsKey('name') || current == null) {
      name = displayName(spec['name'], 'name');
      if (name == null) {
        throw ControllerError("name: the team's display name, 1-32 characters");
      }
    }
    if (spec.containsKey('colour')) {
      final c = spec['colour'];
      if (c == null || c == '') {
        colour = null;
      } else if (c is! String ||
          utf8.encode(c).isEmpty ||
          utf8.encode(c).length > _teamNameMax ||
          c.runes.any((r) => r < 0x21)) {
        throw ControllerError(
          'colour: a team name as the game uses it (red, blue...), '
          '1-$_teamNameMax bytes',
        );
      } else {
        colour = c;
      }
    }
    if (spec.containsKey('crest_id')) {
      final c = spec['crest_id'];
      if (c != null && (c is! String || crest(c) == null)) {
        throw ControllerError(
          "crest_id: an uploaded crest's id (POST /api/v1/crests)",
        );
      }
      crestId = c as String?;
    }
    return (name!, colour, crestId);
  }

  Map<String, Object?> saveTeamPreset(
    Map<String, Object?> spec, [
    int? presetId,
  ]) {
    Map<String, Object?>? current;
    if (presetId != null) {
      current = teamPreset(presetId);
      if (current == null) {
        throw ControllerError.notFound('no team preset $presetId');
      }
      _notSitePreset(presetId);
    }
    final (name, colour, crestId) = _presetSpec(spec, current);
    final doc = _presetDoc();
    final rows = _presetRows();
    if (rows.any((p) => p['name'] == name && p['id'] != presetId)) {
      throw ControllerError.conflict(
        'a team preset named ${jsonEncode(name)} already exists',
      );
    }
    final now = engine.wallSeconds();
    Map<String, Object?> row;
    if (presetId == null) {
      final id = (doc['next_id'] as int?) ?? 1;
      row = {
        'id': id,
        'name': name,
        'colour': colour,
        'crest_id': crestId,
        'created_at': now,
        'updated_at': now,
      };
      rows.add(row);
      doc['next_id'] = id + 1;
    } else {
      final i = rows.indexWhere((p) => p['id'] == presetId);
      row = {
        ...rows[i],
        'name': name,
        'colour': colour,
        'crest_id': crestId,
        'updated_at': now,
      };
      rows[i] = row;
    }
    doc['items'] = rows;
    engine.store.putDocument(_teamPresetsDoc, doc);
    final old = current?['crest_id'];
    if (old is String && old != crestId) _dropIfUnused(old, grace: true);
    return presetView(row);
  }

  Map<String, Object?> deleteTeamPreset(int presetId) {
    final current = teamPreset(presetId);
    if (current == null) {
      throw ControllerError.notFound('no team preset $presetId');
    }
    _notSitePreset(presetId);
    final doc = _presetDoc();
    doc['items'] = [
      for (final p in _presetRows())
        if (p['id'] != presetId) p,
    ];
    engine.store.putDocument(_teamPresetsDoc, doc);
    final old = current['crest_id'];
    if (old is String) _dropIfUnused(old, grace: true);
    return {'deleted': presetId};
  }

  static Map<String, Object?> presetView(Map<String, Object?> p) => {
    ...p,
    'crest_url': p['crest_id'] != null
        ? '/api/v1/crests/${p['crest_id']}'
        : null,
  };

  List<Map<String, Object?>> teamPresets() {
    final site = siteManaged ? sitePresets().values.toSet() : <int>{};
    return [
      for (final p in teamPresetRows())
        {...presetView(p), if (site.contains(p['id'])) 'source': 'site'},
    ];
  }

  void _notSitePreset(int presetId) {
    if (!_applying && siteManaged && sitePresets().values.contains(presetId)) {
      throw ControllerError.conflict(
        "this team preset comes from the site server's saved teams: change "
        'it there',
      );
    }
  }

  // --- from the site server (slice S7; branding.py, plan phase 18) ----------

  /// {site team id: team preset id}.
  Map<String, int> sitePresets() {
    try {
      final v = jsonDecode(engine.store.getSetting(_sitePresets) ?? '{}');
      if (v is! Map) return {};
      return {
        for (final e in v.entries)
          if (e.key is String && e.value is int)
            e.key as String: e.value as int,
      };
    } on FormatException {
      return {};
    }
  }

  /// Keeps an image fetched from the site server (checked by the sync with
  /// [checkImage], its bytes unchanged).
  void storeSiteImage(String sha, String kind, CheckedImage img) =>
      _putImage(sha, kind, img);

  /// Makes the field's branding and the site's team presets match the site
  /// server's answer (checked by `checkField`; its images already stored,
  /// except those in [unavailable], which keep what was there). A preset
  /// made here with a site team's name becomes that team's (branding.py
  /// `apply_site`). Returns the counts of what changed.
  Map<String, int> applySite(
    Map<String, Object?> answer, {
    Set<String> unavailable = const {},
  }) {
    final out = {
      'field': 0,
      'added': 0,
      'updated': 0,
      'removed': 0,
      'conflicts': 0,
    };
    final field = (answer['field']! as Map).cast<String, Object?>();
    final saved = _saved();
    final before = jsonEncode(saved);
    final replaced = <String>[], dropped = <String>[];
    for (final slot in brandingSlots.keys) {
      final ref = field[slot] as Map?;
      final want = ref?['sha256'] as String?;
      if (want != null &&
          (unavailable.contains(want) ||
              image(want, withData: false) == null)) {
        continue; // not fetched yet: the next cycle tries again
      }
      if (saved[slot] != want) {
        final old = saved[slot];
        if (old is String && old.isNotEmpty) replaced.add(old);
        if (want == null) {
          saved.remove(slot);
        } else {
          saved[slot] = want;
        }
      }
    }
    if (field['accent'] == null) {
      saved.remove('accent');
    } else {
      saved['accent'] = field['accent'];
    }
    if (jsonEncode(saved) != before) {
      _save(saved);
      out['field'] = out['field']! + 1;
    }
    final name = field['field_name'];
    if (name is String && name != fieldName()) {
      try {
        final svc = engine.checkin;
        if (svc != null) {
          svc.setPoster({'field_name': name});
        } else {
          engine.store.setSetting(_nameSetting, name);
        }
        out['field'] = out['field']! + 1;
      } on ControllerError {
        // As the Pi (logged there): the site's field name is not used.
      }
    }
    _applying = true;
    try {
      _applySiteTeams(
        (answer['teams']! as List).cast<Map<String, Object?>>(),
        unavailable,
        dropped,
        out,
      );
    } finally {
      _applying = false;
    }
    replaced.forEach(_dropIfUnused);
    for (final id in dropped) {
      _dropIfUnused(id, grace: true);
    }
    if (out['field']! + out['added']! + out['updated']! + out['removed']! > 0) {
      _changed();
    }
    return out;
  }

  void _applySiteTeams(
    List<Map<String, Object?>> teams,
    Set<String> unavailable,
    List<String> dropped,
    Map<String, int> out,
  ) {
    final mapping = sitePresets();
    final byName = {for (final p in _presetRows()) p['name']: p};
    final kept = <String, int>{};
    for (final team in teams) {
      final teamId = team['team_id']! as String;
      var crest = (team['crest'] as Map?)?['sha256'] as String?;
      var current = mapping.containsKey(teamId)
          ? teamPreset(mapping[teamId]!)
          : null;
      current ??= byName[team['name']];
      if (crest != null &&
          (unavailable.contains(crest) ||
              image(crest, withData: false) == null)) {
        crest = current?['crest_id'] as String?;
      }
      if (current != null &&
          current['name'] == team['name'] &&
          current['colour'] == team['colour'] &&
          current['crest_id'] == crest) {
        kept[teamId] = current['id']! as int;
        continue;
      }
      final Map<String, Object?> row;
      try {
        row = saveTeamPreset({
          'name': team['name'],
          'colour': team['colour'],
          'crest_id': crest,
        }, current?['id'] as int?);
      } on ControllerError {
        out['conflicts'] = out['conflicts']! + 1; // another preset has the name
        if (current != null) kept[teamId] = current['id']! as int;
        continue;
      }
      kept[teamId] = row['id']! as int;
      if (current == null) {
        out['added'] = out['added']! + 1;
      } else {
        out['updated'] = out['updated']! + 1;
      }
    }
    for (final e in mapping.entries) {
      if (kept.containsKey(e.key) || kept.values.contains(e.value)) continue;
      if (teamPreset(e.value) != null) {
        deleteTeamPreset(e.value);
        out['removed'] = out['removed']! + 1;
      }
    }
    if (jsonEncode(kept) != jsonEncode(mapping)) {
      final keys = kept.keys.toList()..sort();
      engine.store.setSetting(
        _sitePresets,
        jsonEncode({for (final k in keys) k: kept[k]}),
      );
    }
  }

  /// GET /api/v1/games/{id}/teams: each team's colour, display name and
  /// crest (no token).
  Map<String, Object?> gameTeams(int gameId) {
    final game = engine.store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    final info = (game['team_info'] as Map?) ?? const {};
    return {
      'game_id': gameId,
      'state': game['state'],
      'teams': [
        for (final team in game['teams']! as List)
          () {
            final entry = (info[team] as Map?) ?? const {};
            final crestId = entry['crest_id'];
            return {
              'team': team,
              'display_name': entry['display_name'],
              'crest_id': crestId,
              'crest_url': crestId != null ? '/api/v1/crests/$crestId' : null,
            };
          }(),
      ],
    };
  }

  // --- a game's teams (engine.py `_team_entry`, BR12-BR15) ---------------------

  /// A team's display name and crest from a request: a team preset's, then
  /// the request's own fields on top (null removes one).
  Map<String, Object?> teamEntry(
    String team,
    Object? spec,
    Map<String, Object?> current,
  ) {
    if (spec is! Map) {
      throw ControllerError(
        'team_info.$team: an object with display_name, crest_id or team_preset_id',
      );
    }
    final unknown =
        spec.keys
            .where(
              (k) => !const [
                'display_name',
                'crest_id',
                'team_preset_id',
              ].contains(k),
            )
            .map((k) => '$k')
            .toList()
          ..sort();
    if (unknown.isNotEmpty) {
      throw ControllerError('team_info.$team: unknown fields $unknown');
    }
    final out = Map<String, Object?>.of(current);
    final presetValue = spec['team_preset_id'];
    if (presetValue != null) {
      final id = _intOf(presetValue, 'team_preset_id');
      final preset = teamPreset(id);
      if (preset == null) {
        throw ControllerError.notFound('no team preset $presetValue');
      }
      out
        ..['display_name'] = preset['name']
        ..['crest_id'] = preset['crest_id']
        ..['team_preset_id'] = preset['id'];
    }
    if (spec.containsKey('display_name')) {
      out['display_name'] = displayName(
        spec['display_name'],
        'team_info.$team.display_name',
      );
    }
    if (spec.containsKey('crest_id')) {
      final c = spec['crest_id'];
      if (c != null && !crestExists(c)) {
        throw ControllerError(
          "team_info.$team.crest_id: an uploaded crest's id (POST /api/v1/crests)",
        );
      }
      out['crest_id'] = c;
    }
    if (spec.containsKey('display_name') || spec.containsKey('crest_id')) {
      out.remove('team_preset_id'); // changed by hand: no longer the preset's
    }
    return {
      for (final e in out.entries)
        if (e.value != null) e.key: e.value,
    };
  }

  /// A new game's `team_info` from its spec.
  Map<String, Object?> teamInfoFor(Object? raw, List<String> teams) {
    final info = _truthyMap(raw);
    if (info == null) {
      throw ControllerError(
        'team_info: an object {team: {display_name, crest_id, team_preset_id}}',
      );
    }
    final out = <String, Object?>{};
    for (final e in info.entries) {
      if (!teams.contains(e.key)) {
        throw ControllerError(
          "team_info: ${jsonEncode(e.key)} is not one of the game's teams $teams",
        );
      }
      final entry = teamEntry('${e.key}', e.value, const {});
      if (entry.isNotEmpty) out['${e.key}'] = entry;
    }
    return out;
  }

  static Map<Object?, Object?>? _truthyMap(Object? raw) {
    if (raw == null || raw == false || raw == 0 || raw == '') return const {};
    if (raw is List && raw.isEmpty) return const {};
    return raw is Map ? raw : null;
  }

  static int _intOf(Object? v, String name) {
    if (v is int) return v;
    if (v is double && v.isFinite) return v.truncate();
    if (v is String) {
      final n = int.tryParse(v.trim());
      if (n != null) return n;
    }
    throw ControllerError('$name must be an integer');
  }

  /// PUT /api/v1/games/{id}/teams/{team}: a team's display name or crest
  /// until the game ends.
  Map<String, Object?> setTeamInfo(int gameId, String team, Object? spec) {
    final game = engine.store.game(gameId);
    if (game == null) throw ControllerError.notFound('no game $gameId');
    if (game['state'] == 'ended') {
      throw ControllerError.conflict('game $gameId has ended');
    }
    if (!(game['teams']! as List).contains(team)) {
      throw ControllerError.notFound(
        'game $gameId has no team ${jsonEncode(team)}',
      );
    }
    final info = Map<String, Object?>.of(
      (game['team_info'] as Map?)?.cast<String, Object?>() ?? const {},
    );
    final entry = teamEntry(
      team,
      spec,
      (info[team] as Map?)?.cast<String, Object?>() ?? const {},
    );
    if (entry.isNotEmpty) {
      info[team] = entry;
    } else {
      info.remove(team);
    }
    engine.updateTeamInfo(gameId, info);
    final out = engine.getGame(gameId);
    engine.emit({'type': 'game', 'game': out});
    return out;
  }

  // --- clean-up --------------------------------------------------------------

  Set<String> referenced() {
    final saved = _saved();
    return {
      for (final s in brandingSlots.keys)
        if (saved[s] is String) saved[s]! as String,
      for (final p in _presetRows())
        if (p['crest_id'] is String) p['crest_id']! as String,
      for (final g in engine.store.games())
        for (final v in ((g['team_info'] as Map?) ?? const {}).values)
          if (v is Map && v['crest_id'] is String) v['crest_id']! as String,
    };
  }

  void _dropIfUnused(String id, {bool grace = false}) {
    if (referenced().contains(id)) return;
    if (grace) {
      final img = image(id, withData: false);
      if (img != null &&
          (img['created_at']! as num) > engine.wallSeconds() - crestGraceS) {
        return; // a fresh upload may be about to go into a game or a preset
      }
    }
    _deleteImage(id);
  }

  /// Deletes images nothing refers to (crests a day after their upload); at
  /// most every 10 minutes.
  int purge({bool force = false, double? now}) {
    final t = now ?? engine.wallSeconds();
    if (!force && t - _lastPurge < _purgeEveryS) return 0;
    _lastPurge = t;
    final used = referenced();
    var gone = 0;
    for (final img in _imageIds()) {
      final id = img['id']! as String;
      if (used.contains(id)) continue;
      if (img['kind'] == 'crest' &&
          (img['created_at']! as num) > t - crestGraceS) {
        continue;
      }
      if (_deleteImage(id)) gone++;
    }
    return gone;
  }
}
