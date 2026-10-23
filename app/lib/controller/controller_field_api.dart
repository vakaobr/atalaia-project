// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

part of 'controller_api.dart';

// Slice S7a of PE24: the field plan (controller_field.dart) and the radio
// channel (controller_channel.dart) on the phone's API, with the Pi's paths,
// tokens and status codes (api.py):
//
//     GET  /api/v1/field                     whether a field image is uploaded, and the levels
//     GET|PUT|DELETE /api/v1/field/image     the field image (PUT: the bytes, PNG, JPEG or WebP)
//     GET|PUT|DELETE /api/v1/field/georef    its map position: 2-8 points {x, y, lat, lon}
//     GET|PUT /api/v1/field/levels           a multi-story field: levels on or off, number, names
//     GET|PUT|DELETE /api/v1/field/levels/{n}/image   level n's plan
//     GET|PUT|DELETE /api/v1/field/levels/{n}/georef  level n's own map position
//     POST /api/v1/field/levels/{n}/from-map GM: plan, map position and boundary at once
//     GET  /api/v1/field/features            the map features this token may see
//     POST /api/v1/field/features            GM: add one
//     PUT|DELETE /api/v1/field/features/{id} GM: change or delete one
//     GET  /api/v1/games/{id}/positions      the boxes' places on the plan {x, y, level}
//     PUT  /api/v1/games/{id}/positions/{node}  GM: place a box
//     GET  /api/v1/radio                     the field's channel, candidates, last scan
//     PUT  /api/v1/radio/channel             GM: set it {"channel_hz", "source"}
//     POST|GET|DELETE /api/v1/radio/scan     GM: find a quiet channel / its state / cancel
//     POST /api/v1/radio/random              GM: a random legal channel, as a suggestion
//
// Reading the plan, its map position, the levels and the features needs any
// token (a player's too: the out-of-bounds warning reads them, MF-31); the
// radio's state the GM or read token; every change the GM token.

/// The largest request body the phone reads: a plan (4 MB) or the field
/// from a map (its image in base64, about 5.6 MB) on the field's paths,
/// 1 MB elsewhere (decision PE24-76).
int _bodyLimit(String path) =>
    path.startsWith('/api/v1/field/') ? 6 << 20 : 1 << 20;

extension on ControllerApi {
  ControllerField get _field => engine.field!;
  ControllerChannel get _channel => engine.channel!;

  static const _noStoreField = {'Cache-Control': 'no-store'};

  ApiResponse _plan(_Request r, int level) {
    final (ctype, data) = _field.image(level);
    return ApiResponse.bytes(200, data, ctype, _noStoreField);
  }

  List<(String, RegExp, _Handler)> _fieldRoutes() => [
    ControllerApi._route(
      'GET',
      r'/api/v1/field',
      _viewer((r, v) => ApiResponse(200, _field.info())),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/image',
      _viewer((r, v) => _plan(r, 0)),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/image',
      _gm((r) => ApiResponse(200, _field.putImage(0, r.contentType, r.bytes))),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/image',
      _gm((r) => ApiResponse(200, _field.deleteImage(0))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/georef',
      _viewer((r, v) => ApiResponse(200, _field.georef0())),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/georef',
      _gm((r) => ApiResponse(200, _field.putGeoref(0, r.json))),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/georef',
      _gm((r) => ApiResponse(200, _field.deleteGeoref(0))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/levels',
      _viewer((r, v) => ApiResponse(200, _field.levelsView())),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/levels',
      _gm((r) => ApiResponse(200, _field.putLevels(r.json))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/levels/([^/]+)/image',
      _viewer((r, v) => _plan(r, r.pathInt(1))),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/levels/([^/]+)/image',
      _gm(
        (r) => ApiResponse(
          200,
          _field.putImage(r.pathInt(1), r.contentType, r.bytes),
        ),
      ),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/levels/([^/]+)/image',
      _gm((r) => ApiResponse(200, _field.deleteImage(r.pathInt(1)))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/levels/([^/]+)/georef',
      _viewer((r, v) => ApiResponse(200, _field.levelGeoref(r.pathInt(1)))),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/levels/([^/]+)/georef',
      _gm((r) => ApiResponse(200, _field.putGeoref(r.pathInt(1), r.json))),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/levels/([^/]+)/georef',
      _gm((r) => ApiResponse(200, _field.deleteGeoref(r.pathInt(1)))),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/field/levels/([^/]+)/from-map',
      _gm((r) => ApiResponse(200, _field.fromMap(r.pathInt(1), r.json))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/field/features',
      _viewer(
        (r, v) => ApiResponse(200, {'features': _field.visibleFeatures(v)}),
      ),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/field/features',
      _gm((r) => ApiResponse(201, _field.addFeature(r.json))),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/features/([^/]+)',
      _gm((r) => ApiResponse(200, _field.putFeature(r.pathInt(1), r.json))),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/features/([^/]+)',
      _gm((r) => ApiResponse(200, _field.deleteFeature(r.pathInt(1)))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/games/([^/]+)/positions',
      _viewer((r, v) => ApiResponse(200, _field.places(r.pathInt(1)))),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/games/([^/]+)/positions/([^/]+)',
      _gm(
        (r) => ApiResponse(
          200,
          _field.putPlace(r.pathInt(1), r.pathInt(2), r.json),
        ),
      ),
    ),
    // The field's radio channel (channels.py, RFC 0001 Amendment 3).
    ControllerApi._route(
      'GET',
      r'/api/v1/radio',
      _read((r, who) => ApiResponse(200, _channel.settings())),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/radio/channel',
      _gm((r) {
        final b = r.body;
        return ApiResponse(
          200,
          _channel.setChannel(
            b['channel_hz'],
            b.containsKey('source') ? b['source'] : 'manual',
          ),
        );
      }),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/radio/scan',
      _gm((r) => ApiResponse(202, _channel.startScan(r.body['dwell_s']))),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/radio/scan',
      _read((r, who) => ApiResponse(200, {'scan': _channel.scanStatus()})),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/radio/scan',
      _gm((r) => ApiResponse(200, _channel.cancelScan())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/radio/random',
      _gm((r) => ApiResponse(200, {'suggestion': randomChannel()})),
    ),
  ];
}
