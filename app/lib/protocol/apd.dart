// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Association membership, historically "APD" (protocol/apd.md, decisions
/// APD-1 to APD-14 and MEM-1 to MEM-6): the list of membership bodies with
/// their country, a field's rule and country, a membership and the verdict. The Pi's
/// controller/atalaia_controller/apd.py and the server's services/apd.py do
/// the same; all run protocol/vectors/apd.json (test/protocol/apd_test.dart).
///
/// Pure Dart: the phone controller's isolate uses it as well as the screens.
library;

import 'dart:convert';

/// One entry of the list (it has a [country]), or a field's own entry (it
/// has none and is offered whatever the field's country).
final class ApdEntry {
  const ApdEntry({
    required this.id,
    required this.name,
    required this.shortName,
    this.website,
    this.country,
  });

  final String id;
  final String name;
  final String shortName;
  final String? website;

  /// ISO 3166-1 alpha-2 of the country whose fields offer the entry.
  final String? country;

  Map<String, Object?> toJson() => {
    'id': id,
    if (country != null) 'country': country,
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
      other.website == website &&
      other.country == country;

  @override
  int get hashCode => Object.hash(id, name, shortName, website, country);
}

final _countryRe = RegExp(r'^[A-Z]{2}$');

/// The time zones whose field defaults to Portugal (decision MEM-2).
const apdPortugalZones = {
  'Europe/Lisbon',
  'Atlantic/Azores',
  'Atlantic/Madeira',
};

/// A field's country: two capitals or null (unset); else [ApdError]
/// `country_invalid`.
String? checkApdCountry(Object? value) {
  if (value == null) return null;
  if (value is! String || !_countryRe.hasMatch(value)) {
    throw const ApdError('country_invalid');
  }
  return value;
}

/// [checkApdCountry] for a value from a peer: one this build cannot read is
/// unset.
String? lenientApdCountry(Object? value) {
  try {
    return checkApdCountry(value);
  } on ApdError {
    return null;
  }
}

/// The country a field gets from its time zone: PT in Portugal's, else unset.
String? apdDefaultCountry(String? zone) =>
    apdPortugalZones.contains(zone) ? 'PT' : null;

/// A time zone's IANA name from the abbreviation Dart gives for the phone's
/// (`DateTime.timeZoneName`, the only name it has): WET and WEST are taken as
/// Lisbon's, AZOT and AZOST as the Azores'; any other abbreviation is kept
/// (it is no zone of Portugal). The Canary Islands and the Faroes share WET:
/// their GM sets the country in the console.
String apdZoneOfAbbreviation(String abbreviation) => switch (abbreviation) {
  'WET' || 'WEST' => 'Europe/Lisbon',
  'AZOT' || 'AZOST' => 'Atlantic/Azores',
  _ => abbreviation,
};

/// Which words the screens use: `apd` (Portugal's APD texts) for PT,
/// `membership` ("association membership") for any other country or none.
String apdWording(String? country) => country == 'PT' ? 'apd' : 'membership';

/// What a field of [country] offers from [project]: the entries of the
/// country (none for a field without one), then the [rule]'s own entries
/// (decision MEM-3).
List<ApdEntry> apdOffered(
  List<ApdEntry> project,
  ApdRule rule,
  String? country,
) => rule.choices(project, country);

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
        country: e['country'] as String?,
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

  /// The choices a form shows on a field of [country]: the project's entries
  /// of that country (none for a field without one), then the field's own.
  List<ApdEntry> choices(List<ApdEntry> project, String? country) {
    final listed = [
      for (final e in project)
        if (country != null && e.country == country) e,
    ];
    return [
      ...listed,
      for (final e in custom)
        if (!listed.any((x) => x.id == e.id)) e,
    ];
  }

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
