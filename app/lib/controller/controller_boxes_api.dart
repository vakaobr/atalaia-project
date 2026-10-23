// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

part of 'controller_api.dart';

// Slice S7c of PE24: the Pi's endpoints for boxes over the radio, adoption
// and firmware updates (controller/atalaia_controller/api.py), with the same
// paths, tokens, bodies and status codes:
//
//     GET  /api/v1/boxes                     GM: the free boxes heard, the previous game
//     POST /api/v1/boxes/discover            GM: "who is free?" (at most every 10 s)
//     GET|POST /api/v1/games/{id}/invites    GM: the live game's invites / invite boxes
//     GET  /api/v1/adopt                     GM: the fingerprint, the field's name, the records
//     POST /api/v1/adopt/card                GM: the NFC field card's bytes (never cached)
//     POST /api/v1/adopt/usb/scan|usb        GM: 503, no USB adoption on a phone (PE24-95)
//     GET  /api/v1/adopt/pair                GM: boxes offering a code, the run
//     POST /api/v1/adopt/pair/listen         GM: the radio on the pairing channel, 5 min
//     POST /api/v1/adopt/pair                GM: pair a box with the code it shows
//     GET|POST /api/v1/firmware              GM: releases and updates / upload a signed release
//     DELETE /api/v1/firmware/updates        GM: stop waiting for the updates on their way
//     DELETE /api/v1/firmware/{id}           GM: delete a release
//     POST /api/v1/firmware/{id}/install     GM: CMD update to boxes of the live game
//     GET  /api/v1/firmware/{id}/release|image   no token: what a box fetches
//     POST /api/v1/firmware/report           no token: a box's report (X-Atalaia-Mac)

extension _BoxesRoutes on ControllerApi {
  /// The GM token, for an endpoint that answers asynchronously.
  _Handler _gmAsync(Future<ApiResponse> Function(_Request r) h) => (r) {
    final who = role(r.token);
    if (who == null) {
      throw _HttpError(401, 'the GM token is needed', {
        'WWW-Authenticate': 'Bearer',
      });
    }
    if (who != 'gm') {
      throw _HttpError(
        403,
        'the read token cannot change the game; use the GM token',
      );
    }
    return h(r);
  };

  ControllerBoxes _needBoxes() =>
      engine.boxes ??
      (throw ControllerError(
        'no field join key: boxes cannot be invited over the radio',
      ));

  ControllerPairing _needPairing() =>
      engine.pairing ??
      (throw _HttpError(503, 'pairing needs the field join key'));

  ControllerAdoption _needAdoption() =>
      engine.adoption ??
      (throw _HttpError(503, 'adoption is not set up on this controller'));

  ControllerFirmware _needFirmware() =>
      engine.firmware ??
      (throw _HttpError(
        503,
        'firmware updates are not set up on this controller',
      ));

  List<(String, RegExp, _Handler)> _boxesRoutes() => [
    ControllerApi._route(
      'GET',
      r'/api/v1/boxes',
      _gm((r) => ApiResponse(200, _needBoxes().boxes())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/boxes/discover',
      _gm((r) => ApiResponse(200, _needBoxes().discover())),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/games/([^/]+)/invites',
      _gm(
        (r) =>
            ApiResponse(200, {'invites': _needBoxes().invites(r.pathInt(1))}),
      ),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/games/([^/]+)/invites',
      _gm((r) {
        final id = r.pathInt(1);
        return ApiResponse(200, _needBoxes().invite(id, r.body['boxes']));
      }),
    ),
    // --- adoption (protocol/adoption.md): GM only, never cached ----------
    ControllerApi._route(
      'GET',
      r'/api/v1/adopt',
      _gm((r) => ApiResponse(200, _needAdoption().info())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/adopt/card',
      _gm((r) => ApiResponse(200, _needAdoption().fieldCard())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/adopt/usb/scan',
      _gm((r) => _needAdoption().usbOff()),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/adopt/usb',
      _gm((r) => _needAdoption().usbOff()),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/adopt/pair',
      _gm((r) => ApiResponse(200, _needPairing().status())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/adopt/pair/listen',
      _gm((r) => ApiResponse(200, _needPairing().listen())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/adopt/pair',
      _gm((r) {
        final b = r.body;
        return ApiResponse(200, _needPairing().pair(b['pair_id'], b['code']));
      }),
    ),
    // --- firmware updates (protocol/firmware-update.md) -------------------
    ControllerApi._route(
      'GET',
      r'/api/v1/firmware',
      _gmAsync((r) async => ApiResponse(200, await _needFirmware().status())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/firmware',
      _gmAsync((r) async {
        final q = r.uri.queryParameters;
        return ApiResponse(
          201,
          await _needFirmware().add(
            r.bytes,
            q['platform'] ?? '',
            q['version'] ?? '',
            q['signature'] ?? '',
          ),
        );
      }),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/firmware/updates',
      _gm((r) => ApiResponse(200, {'cancelled': _needFirmware().cancel()})),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/firmware/([^/]+)',
      _gm((r) {
        final id = r.pathText(1);
        _needFirmware().remove(id);
        return ApiResponse(200, {'deleted': id});
      }),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/firmware/([^/]+)/install',
      _gmAsync((r) async {
        final id = r.pathText(1);
        final nodes = r.body['nodes'];
        return ApiResponse(200, await _needFirmware().install(id, nodes));
      }),
    ),
    ControllerApi._route('GET', r'/api/v1/firmware/([^/]+)/release', (r) async {
      // For the boxes, no token: a signed release is public.
      final text = await _needFirmware().releaseTextOf(r.pathText(1));
      return ApiResponse.bytes(200, text, 'text/plain; charset=utf-8');
    }),
    ControllerApi._route('GET', r'/api/v1/firmware/([^/]+)/image', (r) async {
      final image = await _needFirmware().image(r.pathText(1));
      return ApiResponse.bytes(200, image, 'application/octet-stream');
    }),
    ControllerApi._route('POST', r'/api/v1/firmware/report', (r) {
      // A box's report: no token, the live game's key signs it (an HMAC).
      if (r.bytes.length > reportMax) {
        throw _HttpError(413, 'the report is over $reportMax bytes');
      }
      return ApiResponse(
        200,
        _needFirmware().report(r.bytes, r.headers['x-atalaia-mac']),
      );
    }),
  ];
}
