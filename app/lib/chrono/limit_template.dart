// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Energy limit templates (ADR-P3-7): a starting set of per-class limits a
/// field picks and then adjusts. The four built-in templates in
/// `limit_templates/` come from the project's research, not from an official
/// source, and are marked unverified (decision P3-5): the app must show
/// [LimitTemplate.warning] wherever one is chosen.
///
/// Format (version 1):
///
/// ```yaml
/// format: 1
/// id: portugal                 # a-z, 0-9, _
/// name: Portugal
/// status: unverified           # or verified (then verified_date and source say by whom)
/// warning: "Unverified: ..."   # required while unverified
/// source: "..."
/// verified_date: null          # YYYY-MM-DD when verified
/// notes: "..."                 # optional
/// classes:
///   rifle:                     # the replica class it applies to
///     max_energy_j: 1.14       # the limit; a reading above it fails
///     max_fps_020: 350         # the same limit in fps with 0.20 g BBs (within 1%)
///     med_m: 0                 # minimum engagement distance; null: the field decides
///     fire_mode: full_auto     # full_auto, semi_only or bolt_only
/// ```
library;

import 'package:yaml/yaml.dart';

import 'energy.dart';

/// The built-in templates, as Flutter asset paths (pubspec.yaml lists the folder).
const List<String> builtinLimitTemplates = [
  'lib/chrono/limit_templates/portugal.yaml',
  'lib/chrono/limit_templates/uk.yaml',
  'lib/chrono/limit_templates/germany.yaml',
  'lib/chrono/limit_templates/generic_cqb.yaml',
];

enum FireMode {
  fullAuto('full_auto'),
  semiOnly('semi_only'),
  boltOnly('bolt_only');

  const FireMode(this.wire);

  final String wire;

  static FireMode? fromWire(String wire) {
    for (final m in values) {
      if (m.wire == wire) return m;
    }
    return null;
  }
}

class LimitTemplateException implements Exception {
  LimitTemplateException(this.message);

  final String message;

  @override
  String toString() => 'LimitTemplateException: $message';
}

final _name = RegExp(r'^[a-z0-9_]{1,32}$');
final _date = RegExp(r'^\d{4}-\d{2}-\d{2}$');

/// One class's limits.
class ClassLimit {
  ClassLimit({
    required this.name,
    required this.maxEnergyJ,
    required this.maxFps020,
    required this.medM,
    required this.fireMode,
  }) {
    if (!_name.hasMatch(name)) {
      throw LimitTemplateException('class $name: a-z, 0-9 and _');
    }
    if (!maxEnergyJ.isFinite || maxEnergyJ <= 0 || maxEnergyJ > 100) {
      throw LimitTemplateException('$name: max_energy_j is more than 0');
    }
    final fps = fpsWith020(maxEnergyJ);
    if ((maxFps020 - fps).abs() > fps * 0.01) {
      throw LimitTemplateException(
        '$name: max_fps_020 $maxFps020 is not ${maxEnergyJ}J with 0.20 g '
        '(${fps.toStringAsFixed(1)} fps)',
      );
    }
    final med = medM;
    if (med != null && (med < 0 || med > 500)) {
      throw LimitTemplateException('$name: med_m is 0-500 or null');
    }
  }

  final String name;

  /// The limit. A reading with more energy fails.
  final double maxEnergyJ;

  /// The same limit in fps with 0.20 g BBs, for display.
  final int maxFps020;

  /// Minimum engagement distance in metres; null when the template leaves it
  /// to the field.
  final int? medM;
  final FireMode fireMode;

  /// This class with some values changed (a field's own limits).
  ClassLimit copyWith({
    double? maxEnergyJ,
    int? medM,
    bool clearMed = false,
    FireMode? fireMode,
  }) {
    final e = maxEnergyJ ?? this.maxEnergyJ;
    return ClassLimit(
      name: name,
      maxEnergyJ: e,
      maxFps020: maxEnergyJ == null ? maxFps020 : fpsWith020(e).round(),
      medM: clearMed ? null : (medM ?? this.medM),
      fireMode: fireMode ?? this.fireMode,
    );
  }

  Map<String, Object?> toJson() => {
    'max_energy_j': maxEnergyJ,
    'max_fps_020': maxFps020,
    'med_m': medM,
    'fire_mode': fireMode.wire,
  };
}

class LimitTemplate {
  LimitTemplate({
    required this.id,
    required this.name,
    required this.verified,
    required this.warning,
    required this.source,
    required this.verifiedDate,
    required this.notes,
    required Map<String, ClassLimit> classes,
  }) : classes = Map.unmodifiable(classes) {
    if (!_name.hasMatch(id)) throw LimitTemplateException('id: a-z, 0-9, _');
    if (name.isEmpty) throw LimitTemplateException('$id: name is empty');
    if (source.isEmpty) throw LimitTemplateException('$id: source is empty');
    if (!verified && (warning == null || warning!.trim().isEmpty)) {
      throw LimitTemplateException('$id: an unverified template has a warning');
    }
    final date = verifiedDate;
    if (verified && (date == null || !_date.hasMatch(date))) {
      throw LimitTemplateException(
        '$id: a verified template has verified_date',
      );
    }
    if (classes.isEmpty) throw LimitTemplateException('$id: no classes');
  }

  /// Parses a template's YAML text; throws [LimitTemplateException].
  factory LimitTemplate.parse(String yamlText) {
    final Object? doc;
    try {
      doc = loadYaml(yamlText);
    } on YamlException catch (e) {
      throw LimitTemplateException('not YAML: ${e.message}');
    }
    if (doc is! YamlMap) throw LimitTemplateException('a template is a map');
    const keys = {
      'format',
      'id',
      'name',
      'status',
      'warning',
      'source',
      'verified_date',
      'notes',
      'classes',
    };
    _onlyKeys(doc, keys, 'template');
    if (doc['format'] != 1) throw LimitTemplateException('format is 1');
    final status = doc['status'];
    if (status != 'verified' && status != 'unverified') {
      throw LimitTemplateException('status is verified or unverified');
    }
    final classesNode = doc['classes'];
    if (classesNode is! YamlMap) {
      throw LimitTemplateException('classes is a map');
    }
    final classes = <String, ClassLimit>{};
    for (final entry in classesNode.entries) {
      final name = entry.key;
      final c = entry.value;
      if (name is! String || c is! YamlMap) {
        throw LimitTemplateException('classes: name: {limits}');
      }
      _onlyKeys(c, {'max_energy_j', 'max_fps_020', 'med_m', 'fire_mode'}, name);
      final energy = c['max_energy_j'];
      final fps = c['max_fps_020'];
      final med = c['med_m'];
      final mode = c['fire_mode'] is String
          ? FireMode.fromWire(c['fire_mode'] as String)
          : null;
      if (energy is! num || fps is! int || (med != null && med is! int)) {
        throw LimitTemplateException(
          '$name: max_energy_j is a number, max_fps_020 and med_m integers',
        );
      }
      if (mode == null) {
        throw LimitTemplateException(
          '$name: fire_mode is full_auto, semi_only or bolt_only',
        );
      }
      classes[name] = ClassLimit(
        name: name,
        maxEnergyJ: energy.toDouble(),
        maxFps020: fps,
        medM: med as int?,
        fireMode: mode,
      );
    }
    return LimitTemplate(
      id: _string(doc, 'id'),
      name: _string(doc, 'name'),
      verified: status == 'verified',
      warning: _optionalString(doc, 'warning'),
      source: _string(doc, 'source'),
      verifiedDate: _optionalString(doc, 'verified_date'),
      notes: _optionalString(doc, 'notes'),
      classes: classes,
    );
  }

  static void _onlyKeys(YamlMap m, Set<String> keys, String where) {
    for (final k in m.keys) {
      if (!keys.contains(k)) {
        throw LimitTemplateException('$where: unknown key $k');
      }
    }
  }

  static String _string(YamlMap m, String k) {
    final v = m[k];
    if (v is! String) throw LimitTemplateException('$k is text');
    return v;
  }

  static String? _optionalString(YamlMap m, String k) {
    final v = m[k];
    if (v != null && v is! String) throw LimitTemplateException('$k is text');
    return v as String?;
  }

  final String id;
  final String name;

  /// False for every built-in template (decision P3-5).
  final bool verified;

  /// What the app shows next to an unverified template.
  final String? warning;
  final String source;
  final String? verifiedDate;
  final String? notes;
  final Map<String, ClassLimit> classes;

  /// The limits for [replicaClass], or null if the template has no such class.
  ClassLimit? limitFor(String replicaClass) => classes[replicaClass];

  /// A field's own copy of this template with [changes] applied (classes
  /// replaced or added). It keeps the template's verification status: the
  /// field's changes are the field's responsibility.
  LimitTemplate withClasses(Map<String, ClassLimit> changes) => LimitTemplate(
    id: id,
    name: name,
    verified: verified,
    warning: warning,
    source: source,
    verifiedDate: verifiedDate,
    notes: notes,
    classes: {...classes, ...changes},
  );
}
