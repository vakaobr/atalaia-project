// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Links into the app's online registration (plan phase 16's app part,
/// decision S16-13): a field's site server, the field (its slug) and,
/// optionally, one of its scheduled games.
///
/// Two forms are read:
///
/// - `atalaia://register?site=<origin>&field=<slug>&game=<uuid>`, the
///   button on the site server's register page
///   (`/f/<slug>/games/<id>/register`), which Android opens in the app;
/// - the address of a field or game page, pasted or scanned:
///   `https://host[:port]/f/<slug>[/games/<uuid>[/register]]`, with any
///   query (`?lang=en`).
///
/// Only `https://` sites, except `http://` for this phone and the Android
/// emulator's host (localhost, 127.0.0.1, 10.0.2.2), as the site server's
/// own `ATALAIA_PUBLIC_URL` rule. The site is reduced to its origin.
library;

final _slug = RegExp(r'^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$');
final _uuid = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
const _localHosts = {'localhost', '127.0.0.1', '10.0.2.2'};

/// Whether [site] may be a site server: https, or http on a local address;
/// no user name or password in it.
bool siteOriginOk(Uri site) {
  if (site.host.isEmpty || site.userInfo.isNotEmpty) return false;
  if (site.scheme == 'https') return true;
  return site.scheme == 'http' && _localHosts.contains(site.host);
}

/// [site]'s origin (`https://host[:port]`), or null when it may not be one.
Uri? siteOrigin(Uri site) {
  if (!siteOriginOk(site)) return null;
  return Uri(
    scheme: site.scheme,
    host: site.host,
    port: site.hasPort ? site.port : null,
  );
}

/// Parses a site address typed by hand (`campo.example.pt`,
/// `https://campo.example.pt/`): https is assumed when no scheme is given.
Uri? parseSiteAddress(String text) {
  var t = text.trim();
  if (t.isEmpty) return null;
  if (!t.contains('://')) t = 'https://$t';
  final u = Uri.tryParse(t);
  return u == null ? null : siteOrigin(u);
}

final class SiteGameLink {
  const SiteGameLink(this.site, this.fieldSlug, [this.gameId]);

  /// The site server's origin.
  final Uri site;
  final String fieldSlug;

  /// A scheduled game's id (lowercase UUID), or null for the whole field.
  final String? gameId;

  /// What the app shows the person to confirm: the site's host (and port).
  String get host => site.hasPort ? '${site.host}:${site.port}' : site.host;

  /// The `atalaia://register` form of this link.
  Uri toAppLink() => Uri(
    scheme: 'atalaia',
    host: 'register',
    queryParameters: {
      'site': site.toString(),
      'field': fieldSlug,
      'game': ?gameId,
    },
  );

  @override
  bool operator ==(Object other) =>
      other is SiteGameLink &&
      other.site == site &&
      other.fieldSlug == fieldSlug &&
      other.gameId == gameId;

  @override
  int get hashCode => Object.hash(site, fieldSlug, gameId);

  @override
  String toString() => 'SiteGameLink($site, $fieldSlug, $gameId)';

  /// Reads either form; null for anything else (a wrong scheme, a site on
  /// plain http elsewhere, a bad slug or game id).
  static SiteGameLink? parse(String text) {
    final u = Uri.tryParse(text.trim());
    if (u == null) return null;
    if (u.scheme == 'atalaia') {
      if (u.host != 'register') return null;
      final q = u.queryParameters;
      final site = Uri.tryParse(q['site'] ?? '');
      final origin = site == null ? null : siteOrigin(site);
      if (origin == null || site!.path.replaceAll('/', '').isNotEmpty) {
        return null;
      }
      return _make(origin, q['field'], q['game']);
    }
    if (u.scheme != 'https' && u.scheme != 'http') return null;
    final origin = siteOrigin(u);
    if (origin == null) return null;
    final seg = u.pathSegments.where((s) => s.isNotEmpty).toList();
    if (seg.length < 2 || seg[0] != 'f') return null;
    if (seg.length == 2) return _make(origin, seg[1], null);
    if (seg[2] != 'games' || seg.length < 4 || seg.length > 5) return null;
    if (seg.length == 5 && seg[4] != 'register') return null;
    return _make(origin, seg[1], seg[3]);
  }

  static SiteGameLink? _make(Uri origin, String? slug, String? game) {
    if (slug == null || !_slug.hasMatch(slug)) return null;
    if (game != null && game.isNotEmpty) {
      final g = game.toLowerCase();
      if (!_uuid.hasMatch(g)) return null;
      return SiteGameLink(origin, slug, g);
    }
    return SiteGameLink(origin, slug);
  }
}
