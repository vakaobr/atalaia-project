// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A field's branding (decisions BR1-BR24): the name, logo, wallpaper and
/// accent colour a field or club sets on its own controller
/// (`GET /api/v1/field/branding`, no token), and each team's display name
/// and crest in a game (`team_info` on the game, `GET /api/v1/crests/{id}`).
///
/// The app downloads it after a check-in or a join and keeps it per field
/// id (ADR-P3-13's field identity), so the field's look shows at once the
/// next time, also out of reach; an ETag and `If-None-Match` make a
/// refresh cost one small request when nothing changed. Crests are stored
/// by their content's hash and never fetched twice. Without branding, or if
/// a download fails, the app keeps the default Atalaia look.
///
/// The controller has already checked the images (PNG, JPEG or WebP, size
/// and dimension caps, metadata stripped); the app checks the size and the
/// signature again before keeping one, and the widgets fall back to the
/// default look if an image does not decode.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';

import '../storage/app_store.dart';
import '../ui/theme.dart';

/// The controller's caps (controller/atalaia_controller/images.py, decision BR6).
const logoMaxBytes = 1024 * 1024;
const wallpaperMaxBytes = 4 * 1024 * 1024;
const crestMaxBytes = 512 * 1024;

/// PNG, JPEG or WebP, by the file's own signature.
bool isBrandingImage(Uint8List b) {
  if (b.length >= 8 &&
      b[0] == 0x89 &&
      b[1] == 0x50 &&
      b[2] == 0x4E &&
      b[3] == 0x47 &&
      b[4] == 0x0D &&
      b[5] == 0x0A &&
      b[6] == 0x1A &&
      b[7] == 0x0A) {
    return true;
  }
  if (b.length >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF) {
    return true;
  }
  return b.length >= 12 &&
      ascii.decode(b.sublist(0, 4), allowInvalid: true) == 'RIFF' &&
      ascii.decode(b.sublist(8, 12), allowInvalid: true) == 'WEBP';
}

/// `#rrggbb` as a colour, or null.
Color? parseAccent(Object? text) {
  if (text is! String || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(text)) {
    return null;
  }
  return Color(0xFF000000 | int.parse(text.substring(1), radix: 16));
}

/// WCAG's contrast ratio between two colours (1 to 21).
double contrastRatio(Color a, Color b) {
  final la = a.computeLuminance();
  final lb = b.computeLuminance();
  final hi = la > lb ? la : lb;
  final lo = la > lb ? lb : la;
  return (hi + 0.05) / (lo + 0.05);
}

/// The field's accent as the theme's primary colour: lightened on the dark
/// theme, darkened on the light one, until it reads at 4.5:1 on the screen's
/// background (it is also the colour of text buttons and links; decision BR17).
Color brandPrimary(Color accent, Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final surface = dark ? AtalaiaColors.background : Colors.white;
  final towards = dark ? Colors.white : Colors.black;
  var c = accent.withValues(alpha: 1);
  for (var i = 0; i < 20 && contrastRatio(c, surface) < 4.5; i++) {
    c = Color.lerp(c, towards, 0.12)!;
  }
  return c;
}

/// One of the field's two images.
final class BrandImage {
  const BrandImage({
    required this.id,
    required this.bytes,
    this.width,
    this.height,
  });

  /// The SHA-256 of the image as the controller stores it (its ETag).
  final String id;
  final Uint8List bytes;
  final int? width;
  final int? height;
}

/// What the app shows of a field.
final class FieldBranding {
  const FieldBranding({
    required this.fieldId,
    required this.fieldName,
    this.accent,
    this.logo,
    this.wallpaper,
    this.etag,
  });

  final String fieldId;
  final String fieldName;
  final Color? accent;
  final BrandImage? logo;
  final BrandImage? wallpaper;

  /// The ETag of the controller's answer, for the next refresh.
  final String? etag;

  /// Whether there is anything to show beyond the default look.
  bool get isEmpty => accent == null && logo == null && wallpaper == null;

  Map<String, Object?> _record() => {
    'field_id': fieldId,
    'field_name': fieldName,
    'accent': accent == null
        ? null
        : '#${(accent!.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}',
    'etag': etag,
    'logo': logo == null
        ? null
        : {'id': logo!.id, 'width': logo!.width, 'height': logo!.height},
    'wallpaper': wallpaper == null
        ? null
        : {
            'id': wallpaper!.id,
            'width': wallpaper!.width,
            'height': wallpaper!.height,
          },
  };
}

/// A team's display name and crest in one game (its colour is its name).
final class TeamBrand {
  const TeamBrand({required this.team, this.displayName, this.crest});
  final String team;
  final String? displayName;
  final Uint8List? crest;
}

/// The teams of one game: display names and crests, by team (colour) name.
final class TeamBranding {
  const TeamBranding([this.teams = const {}]);
  final Map<String, TeamBrand> teams;

  static const none = TeamBranding();

  String? displayName(String team) => teams[team]?.displayName;
  Uint8List? crest(String team) => teams[team]?.crest;
  bool get isEmpty => teams.isEmpty;

  /// The display names alone, from a game's `team_info` (no crests yet).
  static TeamBranding namesOf(Object? teamInfo) {
    if (teamInfo is! Map) return none;
    return TeamBranding({
      for (final e in teamInfo.entries)
        if (e.value is Map)
          '${e.key}': TeamBrand(
            team: '${e.key}',
            displayName: (e.value as Map)['display_name'] as String?,
          ),
    });
  }
}

/// One answer of the branding endpoints.
final class BrandingResponse {
  const BrandingResponse(this.status, this.bytes, {this.etag});
  final int status;
  final Uint8List bytes;
  final String? etag;
}

/// Where branding comes from: the field controller's API (paths start with
/// /api/v1), over the field's pinned HTTPS or a player link's address.
abstract interface class BrandingSource {
  Future<BrandingResponse> get(String path, {String? ifNoneMatch});
}

/// [BrandingSource] over dart:io: the addresses in order, [client]'s trust
/// (the field CA alone for a pinned field), at most 4 MB per answer.
class IoBrandingSource implements BrandingSource {
  IoBrandingSource(this.urls, this.client);

  final List<String> urls;
  final HttpClient client;

  @override
  Future<BrandingResponse> get(String path, {String? ifNoneMatch}) async {
    Object? last;
    for (final base in urls) {
      try {
        final req = await client.getUrl(Uri.parse('$base$path'));
        if (ifNoneMatch != null) req.headers.set('If-None-Match', ifNoneMatch);
        final res = await req.close().timeout(const Duration(seconds: 15));
        final out = BytesBuilder(copy: false);
        await for (final chunk in res) {
          out.add(chunk);
          if (out.length > wallpaperMaxBytes) {
            throw const FormatException('too large');
          }
        }
        return BrandingResponse(
          res.statusCode,
          out.takeBytes(),
          etag: res.headers.value('etag'),
        );
      } on Object catch (e) {
        last = e; // the next address
      }
    }
    throw StateError('the field controller is out of reach ($last)');
  }

  void close() => client.close(force: true);
}

/// The branding of every field the app has seen, kept in the app's files.
class BrandingCache extends ChangeNotifier {
  BrandingCache(this.store);

  final AppStore store;
  final _fields = <String, FieldBranding>{};
  final _crests = <String, Uint8List>{};
  static const _list = 'field_branding';
  static const _crestList = 'crest_cache';
  static const crestCacheMax = 64;

  /// What was loaded or fetched this run (no I/O).
  FieldBranding? peek(String fieldId) => _fields[fieldId];

  static String _key(String fieldId) =>
      sha256.convert(utf8.encode(fieldId)).toString().substring(0, 24);

  static String _blob(String fieldId, String slot) =>
      'brand-${_key(fieldId)}-$slot';

  /// The field's branding as last kept, or null.
  Future<FieldBranding?> cached(String fieldId) async {
    final mem = _fields[fieldId];
    if (mem != null) return mem;
    for (final j in await store.loadList(_list)) {
      if (j['field_id'] != fieldId) continue;
      Future<BrandImage?> image(String slot) async {
        final ref = j[slot];
        if (ref is! Map) return null;
        final bytes = await store.loadBlob(_blob(fieldId, slot));
        if (bytes == null || !isBrandingImage(bytes)) return null;
        return BrandImage(
          id: '${ref['id']}',
          bytes: bytes,
          width: ref['width'] as int?,
          height: ref['height'] as int?,
        );
      }

      final b = FieldBranding(
        fieldId: fieldId,
        fieldName: (j['field_name'] as String?) ?? '',
        accent: parseAccent(j['accent']),
        logo: await image('logo'),
        wallpaper: await image('wallpaper'),
        etag: j['etag'] as String?,
      );
      _fields[fieldId] = b;
      return b;
    }
    return null;
  }

  /// Asks the controller for its branding (null [fieldId]: whatever field
  /// answers, as for a prop), downloads the images that changed and keeps
  /// it. Out of reach or refused: what was kept before.
  Future<FieldBranding?> refresh(BrandingSource src, {String? fieldId}) async {
    final old = fieldId == null ? null : await cached(fieldId);
    final BrandingResponse r;
    try {
      r = await src.get('/api/v1/field/branding', ifNoneMatch: old?.etag);
    } on Object {
      return old;
    }
    if (r.status == 304 && old != null) return old;
    if (r.status != 200) return old;
    final Map<String, Object?> j;
    try {
      j = (jsonDecode(utf8.decode(r.bytes)) as Map).cast<String, Object?>();
    } on Object {
      return old;
    }
    final fid = j['field_id'];
    if (fid is! String || fid.isEmpty || (fieldId != null && fid != fieldId)) {
      return old; // another field answered at this address
    }
    final prev = old ?? await cached(fid);

    Future<BrandImage?> image(String slot, int max) async {
      final ref = j[slot];
      if (ref is! Map || ref['id'] is! String || ref['url'] is! String) {
        await store.deleteBlob(_blob(fid, slot));
        return null;
      }
      final id = ref['id']! as String;
      final had = slot == 'logo' ? prev?.logo : prev?.wallpaper;
      if (had != null && had.id == id) return had;
      try {
        final got = await src.get(ref['url']! as String);
        if (got.status != 200 ||
            got.bytes.length > max ||
            !isBrandingImage(got.bytes)) {
          return had;
        }
        await store.saveBlob(_blob(fid, slot), got.bytes);
        return BrandImage(
          id: id,
          bytes: got.bytes,
          width: ref['width'] as int?,
          height: ref['height'] as int?,
        );
      } on Object {
        return had;
      }
    }

    final b = FieldBranding(
      fieldId: fid,
      fieldName: (j['field_name'] as String?) ?? prev?.fieldName ?? '',
      accent: parseAccent(j['accent']),
      logo: await image('logo', logoMaxBytes),
      wallpaper: await image('wallpaper', wallpaperMaxBytes),
      etag: r.etag ?? j['etag'] as String?,
    );
    await _save(b);
    return b;
  }

  Future<void> _save(FieldBranding b) async {
    _fields[b.fieldId] = b;
    final rest = [
      for (final j in await store.loadList(_list))
        if (j['field_id'] != b.fieldId) j,
    ];
    await store.saveList(_list, [...rest, b._record()]);
    notifyListeners();
  }

  /// Forgets a field's branding (the player removed the field).
  Future<void> forget(String fieldId) async {
    _fields.remove(fieldId);
    await store.deleteBlob(_blob(fieldId, 'logo'));
    await store.deleteBlob(_blob(fieldId, 'wallpaper'));
    await store.saveList(_list, [
      for (final j in await store.loadList(_list))
        if (j['field_id'] != fieldId) j,
    ]);
    notifyListeners();
  }

  /// A crest by its id (its content's hash: never fetched twice), or null.
  Future<Uint8List?> crest(BrandingSource? src, String crestId) async {
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(crestId)) return null;
    final mem = _crests[crestId];
    if (mem != null) return mem;
    final kept = await store.loadBlob('crest-$crestId');
    if (kept != null && isBrandingImage(kept)) {
      return _crests[crestId] = kept;
    }
    if (src == null) return null;
    try {
      final r = await src.get('/api/v1/crests/$crestId');
      if (r.status != 200 ||
          r.bytes.length > crestMaxBytes ||
          !isBrandingImage(r.bytes) ||
          sha256.convert(r.bytes).toString() != crestId) {
        return null;
      }
      await store.saveBlob('crest-$crestId', r.bytes);
      final ids = [
        for (final j in await store.loadList(_crestList))
          if (j['id'] != crestId) '${j['id']}',
        crestId,
      ];
      while (ids.length > crestCacheMax) {
        await store.deleteBlob('crest-${ids.removeAt(0)}');
      }
      await store.saveList(_crestList, [
        for (final id in ids) {'id': id},
      ]);
      return _crests[crestId] = r.bytes;
    } on Object {
      return null;
    }
  }

  /// A game's teams with their crests, from its `team_info`.
  Future<TeamBranding> teams(BrandingSource? src, Object? teamInfo) async {
    if (teamInfo is! Map) return TeamBranding.none;
    final out = <String, TeamBrand>{};
    for (final e in teamInfo.entries) {
      final v = e.value;
      if (v is! Map) continue;
      final id = v['crest_id'];
      out['${e.key}'] = TeamBrand(
        team: '${e.key}',
        displayName: v['display_name'] as String?,
        crest: id is String ? await crest(src, id) : null,
      );
    }
    return TeamBranding(out);
  }

  /// The teams of [gameId] from `GET /api/v1/games/{id}/teams` (no token: a
  /// prop has none), with their crests.
  Future<TeamBranding> gameTeams(BrandingSource src, int gameId) async {
    try {
      final r = await src.get('/api/v1/games/$gameId/teams');
      if (r.status != 200) return TeamBranding.none;
      final j = jsonDecode(utf8.decode(r.bytes)) as Map;
      return teams(src, {
        for (final t in (j['teams'] as List?) ?? const [])
          if (t is Map && t['team'] is String)
            t['team']: {
              'display_name': t['display_name'],
              'crest_id': t['crest_id'],
            },
      });
    } on Object {
      return TeamBranding.none;
    }
  }
}
