// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// APD membership (protocol/apd.md, decisions APD-1 to APD-14): the list of
/// APDs, a field's rule, a membership and the verdict. The Pi's
/// controller/atalaia_controller/apd.py and the server's services/apd.py do
/// the same; all run protocol/vectors/apd.json (test/protocol/apd_test.dart).
///
/// Pure Dart: the phone controller's isolate uses it as well as the screens.
library;

import 'dart:convert';

/// One APD of the list, or a field's own entry.
final class ApdEntry {
  const ApdEntry({
    required this.id,
    required this.name,
    required this.shortName,
    this.website,
  });

  final String id;
  final String name;
  final String shortName;
  final String? website;

  Map<String, Object?> toJson() => {
    'id': id,
    'name': name,
    'short_name': shortName,
    'website': website,
  };

  @override
  bool operator ==(Object other) =>
      other is ApdEntry &&
      other.id == id &&
      other.name == name &&
      other.shortName == shortName &&
      other.website == website;

  @override
  int get hashCode => Object.hash(id, name, shortName, website);
}

/// The membership verdict; `null` where no rule asks.
const apdStatuses = ['missing', 'not_accepted', 'expired', 'valid'];

final _idRe = RegExp(r'^[a-z0-9][a-z0-9-]{0,31}$');
final _dateRe = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$');
final _urlRe = RegExp(r'^https://\S{1,120}$');

const apdMaxAccepted = 32;
const apdMaxCustom = 16;
const apdNumberMax = 32;

/// Thrown by the checks with the protocol's error code.
final class ApdError implements Exception {
  const ApdError(this.code);
  final String code;
  @override
  String toString() => code;
}

bool _printable(String s) => !s.runes.any((c) => c < 0x20 || c == 0x7f);

/// The list of `apds.json` (its entries; `source` is not carried).
List<ApdEntry> parseApdList(String json) {
  final doc = jsonDecode(json) as Map<String, dynamic>;
  return [
    for (final e in (doc['apds'] as List<dynamic>? ?? const []))
      ApdEntry(
        id: (e as Map)['id'] as String,
        name: e['name'] as String,
        shortName: e['short_name'] as String,
        website: e['website'] as String?,
      ),
  ];
}

ApdEntry _entry(Object? v) {
  if (v is! Map) throw const ApdError('apd_rule_invalid');
  const known = {'id', 'name', 'short_name', 'website'};
  if (v.keys.any((k) => !known.contains(k))) {
    throw const ApdError('apd_rule_invalid');
  }
  final id = v['id'], name = v['name'], short = v['short_name'];
  final web = v['website'];
  if (id is! String || !_idRe.hasMatch(id) || !id.startsWith('x-')) {
    throw const ApdError('apd_rule_invalid');
  }
  if (name is! String ||
      name.isEmpty ||
      name.length > 96 ||
      !_printable(name)) {
    throw const ApdError('apd_rule_invalid');
  }
  if (short is! String || short.isEmpty || short.length > 16) {
    throw const ApdError('apd_rule_invalid');
  }
  if (web != null && (web is! String || !_urlRe.hasMatch(web))) {
    throw const ApdError('apd_rule_invalid');
  }
  if (web is String && web.length > 128) {
    throw const ApdError('apd_rule_invalid');
  }
  return ApdEntry(
    id: id,
    name: name,
    shortName: short,
    website: web as String?,
  );
}

/// A field's or controller's rule, normalised (protocol/apd.md "The rule").
final class ApdRule {
  const ApdRule({
    this.accepted,
    this.register = false,
    this.checkin = false,
    this.expiry = false,
    this.custom = const [],
  });

  static const defaults = ApdRule();

  /// Null: any APD.
  final List<String>? accepted;
  final bool register;
  final bool checkin;
  final bool expiry;
  final List<ApdEntry> custom;

  /// Whether the rule asks for anything (the verdict is worked out).
  bool get asks => checkin || register;

  /// [value] is JSON as decoded; null is the default. Throws [ApdError]
  /// `apd_rule_invalid`.
  static ApdRule parse(Object? value) {
    if (value == null) return defaults;
    if (value is! Map) throw const ApdError('apd_rule_invalid');
    const known = {'accepted', 'register', 'checkin', 'expiry', 'custom'};
    if (value.keys.any((k) => !known.contains(k))) {
      throw const ApdError('apd_rule_invalid');
    }
    bool flag(String k) {
      final v = value[k];
      if (v == null) return false;
      if (v is! bool) throw const ApdError('apd_rule_invalid');
      return v;
    }

    List<String>? accepted;
    final a = value['accepted'];
    if (a != null) {
      if (a is! List || a.isEmpty || a.length > apdMaxAccepted) {
        throw const ApdError('apd_rule_invalid');
      }
      accepted = [];
      for (final id in a) {
        if (id is! String || !_idRe.hasMatch(id) || accepted.contains(id)) {
          throw const ApdError('apd_rule_invalid');
        }
        accepted.add(id);
      }
    }
    final custom = <ApdEntry>[];
    final c = value['custom'];
    if (c != null) {
      if (c is! List || c.length > apdMaxCustom) {
        throw const ApdError('apd_rule_invalid');
      }
      for (final e in c) {
        final entry = _entry(e);
        if (custom.any((x) => x.id == entry.id)) {
          throw const ApdError('apd_rule_invalid');
        }
        custom.add(entry);
      }
    }
    return ApdRule(
      accepted: accepted,
      register: flag('register'),
      checkin: flag('checkin'),
      expiry: flag('expiry'),
      custom: custom,
    );
  }

  /// [parse], but a rule this build cannot read asks for nothing (a field
  /// that sent it must not lock a player out).
  static ApdRule lenient(Object? value) {
    try {
      return parse(value);
    } on ApdError {
      return defaults;
    }
  }

  Map<String, Object?> toJson() => {
    'accepted': accepted == null ? null : List<String>.of(accepted!),
    'register': register,
    'checkin': checkin,
    'expiry': expiry,
    'custom': [for (final e in custom) e.toJson()],
  };

  /// The choices a form shows: the project's list, then the field's own.
  List<ApdEntry> choices(List<ApdEntry> project) => [...project, ...custom];

  @override
  bool operator ==(Object other) =>
      other is ApdRule && jsonEncode(other.toJson()) == jsonEncode(toJson());

  @override
  int get hashCode => jsonEncode(toJson()).hashCode;
}

/// A player's declared membership; every part may be null.
final class ApdMembership {
  const ApdMembership({this.apd, this.number, this.expires});

  final String? apd;
  final String? number;

  /// `YYYY-MM-DD`.
  final String? expires;

  static ApdMembership parse(Object? value) {
    if (value is! Map) throw const ApdError('apd_membership_invalid');
    if (value.keys.any(
      (k) => !const {'apd', 'number', 'expires'}.contains(k),
    )) {
      throw const ApdError('apd_membership_invalid');
    }
    final apd = value['apd'], number = value['number'];
    final expires = value['expires'];
    if (apd != null && (apd is! String || !_idRe.hasMatch(apd))) {
      throw const ApdError('apd_membership_invalid');
    }
    if (number != null &&
        (number is! String ||
            number.isEmpty ||
            number.length > apdNumberMax ||
            !_printable(number))) {
      throw const ApdError('apd_membership_invalid');
    }
    if (expires != null && (expires is! String || !validApdDate(expires))) {
      throw const ApdError('apd_membership_invalid');
    }
    return ApdMembership(
      apd: apd as String?,
      number: number as String?,
      expires: expires as String?,
    );
  }

  Map<String, Object?> toJson() => {
    'apd': apd,
    'number': number,
    'expires': expires,
  };
}

/// A real calendar date `YYYY-MM-DD`, 2000-2100.
bool validApdDate(String s) {
  final m = _dateRe.firstMatch(s);
  if (m == null) return false;
  final y = int.parse(m[1]!), mo = int.parse(m[2]!), d = int.parse(m[3]!);
  if (y < 2000 || y > 2100) return false;
  final dt = DateTime.utc(y, mo, d);
  return dt.year == y && dt.month == mo && dt.day == d;
}

/// The verdict for [rule], [m] and [on] (`YYYY-MM-DD`, the local date the
/// player plays); protocol/apd.md "The verdict". The caller decides whether
/// a rule asks (a null verdict where it does not: [apdVerdict]).
String apdStatus(ApdRule rule, ApdMembership m, String on) {
  if (m.number == null || (rule.expiry && m.expires == null)) return 'missing';
  final accepted = rule.accepted;
  if (accepted != null && (m.apd == null || !accepted.contains(m.apd))) {
    return 'not_accepted';
  }
  if (rule.expiry && m.expires!.compareTo(on) < 0) return 'expired';
  return 'valid';
}

/// [apdStatus] when [forCheckin] (or, for registration, `register`) asks;
/// null otherwise.
String? apdVerdict(
  ApdRule rule,
  ApdMembership m,
  String on, {
  bool forCheckin = true,
}) {
  final asks = forCheckin ? rule.checkin : rule.register;
  return asks ? apdStatus(rule, m, on) : null;
}

/// `YYYY-MM-DD` of [t] (local).
String apdDateOf(DateTime t) =>
    '${t.year.toString().padLeft(4, '0')}-'
    '${t.month.toString().padLeft(2, '0')}-'
    '${t.day.toString().padLeft(2, '0')}';

/// The name to show for [id] among [choices], else the id itself.
String apdLabel(String? id, List<ApdEntry> choices) {
  if (id == null) return '';
  for (final e in choices) {
    if (e.id == id) return e.shortName;
  }
  return id;
}
