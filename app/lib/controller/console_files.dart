// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The GM console and the scoreboard served by a phone controller (slice S6
/// of PE24, decision PE24-8): the very files of controller/console/src,
/// which the app carries as assets (assets/console/, copied in at build time
/// by tool/sync_console.dart and checked against the console by
/// test/controller/console_bundle_test.dart: PE24-61), served as the Pi's
/// api.py serves them: `/` and `/console` to `/console/`, `/scoreboard` to
/// the scoreboard page, a folder to its index.html, with the Pi's security
/// headers on every /console answer. No token: the console asks for one.
///
/// The UI isolate reads the assets (console_assets.dart: rootBundle is
/// there) and hands the bytes to the controller's isolate, which serves
/// them from memory: nothing is read from a path a request names.
library;

import 'dart:typed_data';

/// The Pi's SECURITY_HEADERS (api.py): same origin only, no inline scripts.
const consoleSecurityHeaders = {
  'Content-Security-Policy':
      "default-src 'self'; script-src 'self'; style-src 'self'; "
      "img-src 'self' blob: data:; connect-src 'self'; "
      "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
      "base-uri 'none'; form-action 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'geolocation=()',
};

/// The one page that may reach the internet (api.py's FIELD_MAP_PAGE,
/// decision MF-27): *Load the field from a map*, run in the GM's browser.
const fieldMapPage = '/console/field-map.html';

/// The origins of the field-map page's policy, the Pi's FIELD_MAP_* in api.py:
/// OSM's tiles (images), Overpass and its second instance and Nominatim
/// (connections), each open orthophoto's WMS (images and connections) and the
/// WMTS origins of their own (images only).
const _fieldMapOrthophotos =
    'https://ortos.dgterritorio.gov.pt https://www.ign.es '
    'https://data.geopf.fr https://service.pdok.nl '
    'https://wms.ngi.be https://geo.api.vlaanderen.be '
    'https://geoservices.wallonie.be https://wms.geoportail.lu '
    'https://wms.geo.admin.ch https://gdi.berlin.de '
    'https://isk.geobasis-bb.de https://geoservices.bayern.de '
    'https://geodienste.bremen.de https://www.gds-srv.hessen.de '
    'https://www.geodaten-mv.de https://www.wms.nrw.de '
    'https://geo4.service24.rlp.de https://geoportal.saarland.de '
    'https://geodienste.sachsen.de https://www.geoproxy.geoportal-th.de '
    'https://mapy.geoportal.gov.pl https://ags.cuzk.gov.cz';
const _fieldMapOrthoTiles =
    'https://wmts1.geoportail.lu https://wmts.geo.admin.ch '
    'https://www.wmts.nrw.de';

/// The Pi's FIELD_MAP_HEADERS (api.py, MF-27, MF-43, MF-64): the strict
/// headers with the page's own policy and `geolocation=(self)`. Scripts stay
/// same-origin. Keep in step with api.py: controller/tests/test_console.py
/// pins the same origins.
const fieldMapSecurityHeaders = {
  'Content-Security-Policy':
      "default-src 'self'; script-src 'self'; style-src 'self'; "
      "img-src 'self' blob: data: https://tile.openstreetmap.org "
      '$_fieldMapOrthophotos $_fieldMapOrthoTiles; '
      "connect-src 'self' https://overpass-api.de "
      'https://overpass.private.coffee $_fieldMapOrthophotos '
      'https://nominatim.openstreetmap.org; '
      "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
      "base-uri 'none'; form-action 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'geolocation=(self)',
};

/// The headers of a /console answer for [path]: the field-map page's own, the
/// strict ones for every other page and file.
Map<String, String> consoleHeadersFor(String path) =>
    path == fieldMapPage ? fieldMapSecurityHeaders : consoleSecurityHeaders;

const _types = {
  'html': 'text/html; charset=utf-8',
  'js': 'text/javascript; charset=utf-8',
  'mjs': 'text/javascript; charset=utf-8',
  'css': 'text/css; charset=utf-8',
  'json': 'application/json',
  'webmanifest': 'application/manifest+json',
  'png': 'image/png',
  'svg': 'image/svg+xml',
  'ico': 'image/x-icon',
  'woff2': 'font/woff2',
  'md': 'text/markdown; charset=utf-8',
  'txt': 'text/plain; charset=utf-8',
};

/// One file to send: its bytes, type and headers; or a redirect.
final class ConsoleAnswer {
  const ConsoleAnswer.file(this.bytes, this.contentType)
    : status = 200,
      location = null;

  const ConsoleAnswer.redirect(String this.location)
    : status = 307,
      bytes = null,
      contentType = null;

  const ConsoleAnswer.notFound()
    : status = 404,
      bytes = null,
      contentType = null,
      location = null;

  final int status;
  final Uint8List? bytes;
  final String? contentType;
  final String? location;
}

/// The console's files by their path under controller/console/src
/// (`index.html`, `components/live-feed.js`...).
final class ConsoleFiles {
  ConsoleFiles(Map<String, Uint8List> files) : files = Map.unmodifiable(files);

  final Map<String, Uint8List> files;

  bool get isEmpty => files.isEmpty;

  /// The answer for a GET of [path], or null when the path is not the
  /// console's (the API answers it).
  ConsoleAnswer? answer(String path) {
    if (files.isEmpty) return null;
    if (path == '/' || path == '/console') {
      return const ConsoleAnswer.redirect('/console/');
    }
    if (path == '/scoreboard') {
      return const ConsoleAnswer.redirect('/console/scoreboard.html');
    }
    if (!path.startsWith('/console/')) return null;
    var rel = path.substring('/console/'.length);
    if (rel.isEmpty || rel.endsWith('/')) rel = '${rel}index.html';
    final bytes = files[rel];
    if (bytes == null) {
      // A folder without its slash, as StaticFiles(html=True) answers it.
      if (files.containsKey('$rel/index.html')) {
        return ConsoleAnswer.redirect('$path/');
      }
      return const ConsoleAnswer.notFound();
    }
    return ConsoleAnswer.file(bytes, contentTypeOf(rel));
  }

  static String contentTypeOf(String name) {
    final dot = name.lastIndexOf('.');
    final ext = dot < 0 ? '' : name.substring(dot + 1).toLowerCase();
    return _types[ext] ?? 'application/octet-stream';
  }
}
