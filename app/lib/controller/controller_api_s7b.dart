// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

part of 'controller_api.dart';

// Slice S7b of PE24: presets, mode uploads and signed mode packages, the
// modes sent to boxes, scenarios and team branding, with the Pi's paths,
// tokens, bodies and status codes (controller/atalaia_controller/api.py):
//
//     GET  /api/v1/modes                     installed mode packages and their parameters
//     POST /api/v1/modes                     GM: upload a mode package {"files": {name: text}}
//     GET  /api/v1/mode-packages             GM: trusted mode keys and the index's packages (?refresh=1)
//     POST /api/v1/mode-packages             GM: upload a signed package (the archive;
//                                            ?id&version&kind&min_tier&signature&key_id)
//     POST /api/v1/mode-packages/install     GM: install a signed package from the index {"id", "version"}
//     POST /api/v1/mode-packages/report      a box: its report on a part it fetched (X-Atalaia-Mac)
//     GET  /api/v1/mode-packages/{id}/release   a box: the part's signed release text, no token
//     GET  /api/v1/mode-packages/{id}/package   a box: the part's archive, no token
//     GET|DELETE /api/v1/mode-fetch          GM: the fetches / stop waiting for them
//     PUT  /api/v1/mode-fetch/forget/{device}   GM: mark a box to forget its fetched modes
//     POST /api/v1/scenarios/check           a scenario manifest's problems {"manifest": text}
//     GET|POST /api/v1/scenarios             installed scenarios / GM: compile and install
//     GET  /api/v1/scenarios/{id}            GM: its manifest and generated package
//     GET|POST /api/v1/presets               saved presets / GM: save one {"name", "mode_id", "params"}
//     GET|PUT /api/v1/field/branding         the field's name, logo, wallpaper, accent (GET: no token, ETag)
//     GET|PUT|DELETE /api/v1/field/branding/{logo|wallpaper}  the images (GET: no token)
//     GET  /api/v1/field/box-logo[/release]  the PNG logo as a Field Box draws it, 96x96 RGB565 (no token)
//     POST /api/v1/crests                    GM: upload a team crest (raw PNG, JPEG or WebP)
//     GET  /api/v1/crests/{id}               a crest (no token, immutable)
//     GET|POST /api/v1/team-presets          saved teams: display name, colour, crest
//     PUT|DELETE /api/v1/team-presets/{id}   GM
//     GET  /api/v1/games/{id}/teams          a game's team colours, names and crests (no token)
//     PUT  /api/v1/games/{id}/teams/{team}   GM: {"display_name"?, "crest_id"?, "team_preset_id"?}

const _noBoxLogo =
    'no logo a box can draw (a PNG logo is converted for the box)';

/// Served images: never sniffed as anything else, inert if opened as a page
/// (api.py IMAGE_HEADERS, decision BR9).
const _imageHeaders = {
  'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "default-src 'none'; sandbox",
  'Content-Disposition': 'inline',
};

extension _S7bRoutes on ControllerApi {
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

  ControllerSignedModes _signed() =>
      engine.signedModes ??
      (throw ControllerError.unavailable(
        'signed mode packages are not set up on this controller',
      ));

  ControllerModeFetch _fetch() =>
      engine.modeFetch ??
      (throw ControllerError.unavailable(
        'sending modes to boxes is not set up on this controller',
      ));

  ControllerScenarios _scenarios() =>
      engine.scenarios ??
      (throw ControllerError.unavailable(
        'scenarios are not set up on this controller',
      ));

  ControllerBranding _branding() =>
      engine.branding ??
      (throw ControllerError.unavailable(
        'branding is not set up on this controller',
      ));

  Map<String, Object?> _modeApi(ModePackage m) {
    final out = m.toApi();
    return engine.signedModes?.annotate(out) ?? out;
  }

  /// An upload's bytes and declared type (api.py `read_upload`).
  (Uint8List, String) _upload(_Request r, int limit, String what) {
    if (r.bytes.length > limit) {
      throw _HttpError(413, 'the $what is over $limit bytes');
    }
    final type = (r.contentType ?? r.headers['content-type'] ?? '')
        .split(';')
        .first
        .trim()
        .toLowerCase();
    return (r.bytes, type);
  }

  void _publicRead(_Request r) {
    if (!_branding().rate.allow(r.client)) {
      throw _HttpError(
        429,
        'too many requests from this address; wait a minute',
      );
    }
  }

  bool _notModified(_Request r, String tag) {
    final wanted = r.headers['if-none-match'];
    if (wanted == null || wanted.isEmpty) return false;
    if (wanted.trim() == '*') return true;
    return wanted.split(',').any((t) {
      var x = t.trim();
      if (x.startsWith('W/')) x = x.substring(2);
      return x == tag;
    });
  }

  ApiResponse _image(_Request r, Map<String, Object?> img, String cache) {
    final tag = etagOf('${img['id']}');
    final headers = {'ETag': tag, 'Cache-Control': cache, ..._imageHeaders};
    if (_notModified(r, tag)) return ApiResponse(304, null, headers);
    return ApiResponse.bytes(
      200,
      img['data']! as Uint8List,
      '${img['content_type']}',
      headers,
    );
  }

  ImageLimits _slot(String slot) =>
      brandingSlots[slot] ??
      (throw _HttpError(
        404,
        "the field's branding images are 'logo' and 'wallpaper'",
      ));

  List<(String, RegExp, _Handler)> s7bRoutes() => [
    // --- modes and signed mode packages ------------------------------------
    ControllerApi._route(
      'GET',
      r'/api/v1/modes',
      _read(
        (r, who) =>
            ApiResponse(200, [for (final m in engine.modes.all()) _modeApi(m)]),
      ),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/modes',
      _gm((r) {
        final out = _modeApi(engine.modes.install(r.body['files']));
        engine.emit({'type': 'modes'});
        return ApiResponse(201, out);
      }),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/mode-packages',
      _gmAsync(
        (r) async => ApiResponse(
          200,
          await _signed().status(refresh: r.queryBool('refresh')),
        ),
      ),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/mode-packages',
      _gmAsync((r) async {
        final (data, _) = _upload(r, modePackageMaxBytes, 'mode package');
        final q = r.uri.queryParameters;
        final keyIdValue = q['key_id'] ?? '';
        final out = await _signed().upload(data, {
          'id': q['id'] ?? '',
          'version': q['version'] ?? '',
          'kind': q['kind'] ?? '',
          'min_tier': q['min_tier'] ?? '',
          'signature': q['signature'] ?? '',
          'key_id': keyIdValue.isEmpty ? null : keyIdValue,
        });
        engine.emit({'type': 'modes'});
        return ApiResponse(201, out);
      }),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/mode-packages/install',
      _gmAsync((r) async {
        final b = r.body;
        final out = await _signed().installFromIndex(b['id'], b['version']);
        engine.emit({'type': 'modes'});
        return ApiResponse(201, out);
      }),
    ),
    ControllerApi._route('POST', r'/api/v1/mode-packages/report', (r) {
      final (data, _) = _upload(r, modeReportMax, 'report');
      return ApiResponse(
        200,
        _fetch().report(data, r.headers['x-atalaia-mac']),
      );
    }),
    ControllerApi._route(
      'GET',
      r'/api/v1/mode-packages/([^/]+)/release',
      (r) => ApiResponse.text(
        200,
        latin1.decode(_fetch().releaseText(r.pathText(1))),
        'text/plain; charset=utf-8',
        const {'Cache-Control': 'no-store'},
      ),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/mode-packages/([^/]+)/package',
      (r) => ApiResponse.bytes(
        200,
        _fetch().archive(r.pathText(1)),
        'application/x-tar',
        const {'Cache-Control': 'no-store'},
      ),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/mode-fetch',
      _gm((r) => ApiResponse(200, _fetch().status())),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/mode-fetch',
      _gm((r) => ApiResponse(200, {'cancelled': _fetch().cancel()})),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/mode-fetch/forget/([^/]+)',
      _gm(
        (r) => ApiResponse(
          200,
          _fetch().setForget(r.pathText(1), r.body['forget']),
        ),
      ),
    ),
    // --- scenarios -----------------------------------------------------------
    ControllerApi._route(
      'POST',
      r'/api/v1/scenarios/check',
      _read(
        (r, who) => ApiResponse(200, _scenarios().check(manifestText(r.json))),
      ),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/scenarios',
      _read((r, who) => ApiResponse(200, _scenarios().listing())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/scenarios',
      _gm((r) {
        final out = _scenarios().install(manifestText(r.json));
        engine.emit({'type': 'modes'});
        return ApiResponse(201, out);
      }),
    ),
    ControllerApi._route(
      'GET',
      r'/api/v1/scenarios/([^/]+)',
      _gm(
        (r) => ApiResponse(200, _scenarios().read(r.pathText(1)), const {
          'Cache-Control': 'no-store',
        }),
      ),
    ),
    // --- presets -------------------------------------------------------------
    ControllerApi._route(
      'GET',
      r'/api/v1/presets',
      _read((r, who) {
        final out = engine.modes.presets();
        if (who == 'gm') return ApiResponse(200, out);
        // The read token's console: without the gm_only parameters (M5-1).
        return ApiResponse(200, [
          for (final p in out)
            {
              ...p,
              'params': () {
                final mode = engine.modes.get(p['mode_id'])?.mode;
                final params = p['params'];
                if (mode == null || params is! Map) return <String, Object?>{};
                return mode.publicParams(params.cast<String, Object?>());
              }(),
            },
        ]);
      }),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/presets',
      _gm((r) {
        final spec = r.body;
        final name = spec['name'];
        if (name is! String || name.runes.isEmpty || name.runes.length > 64) {
          throw ControllerError('name: 1 to 64 characters');
        }
        final pkg = spec['mode_id'] is String
            ? engine.modes.get(spec['mode_id'])
            : null;
        if (pkg == null) {
          throw ControllerError('unknown mode ${spec['mode_id']}');
        }
        final params = spec.containsKey('params')
            ? spec['params']
            : <String, Object?>{};
        resolvePresetParams(pkg.mode, params, null);
        return ApiResponse(
          201,
          engine.modes.savePreset(
            name,
            pkg.id,
            (params! as Map).cast<String, Object?>(),
          ),
        );
      }),
    ),
    // --- field and team branding ---------------------------------------------
    ControllerApi._route('GET', r'/api/v1/field/branding', (r) {
      _publicRead(r);
      final view = _branding().view();
      final tag = view['etag']! as String;
      final headers = {'ETag': tag, 'Cache-Control': 'no-cache'};
      if (_notModified(r, tag)) return ApiResponse(304, null, headers);
      return ApiResponse(200, view, headers);
    }),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/branding',
      _gm((r) => ApiResponse(200, _branding().setField(r.body))),
    ),
    // The logo as a Field Box draws it (controller_box_logo.dart, decision
    // PKG-1): the box asks for the text, and for the bytes only when the id in
    // it is not the one it keeps. 404: no logo, or one the controller cannot
    // convert (not a PNG); the box then shows the Atalaia logo.
    ControllerApi._route('GET', r'/api/v1/field/box-logo/release', (r) {
      _publicRead(r);
      final made = _branding().boxLogo();
      if (made == null) throw _HttpError(404, _noBoxLogo);
      return ApiResponse.bytes(
        200,
        Uint8List.fromList(utf8.encode(boxLogoReleaseText(made.$1, made.$2))),
        'text/plain',
        const {'Cache-Control': 'no-cache'},
      );
    }),
    ControllerApi._route('GET', r'/api/v1/field/box-logo', (r) {
      _publicRead(r);
      final made = _branding().boxLogo();
      if (made == null) throw _HttpError(404, _noBoxLogo);
      return ApiResponse.bytes(200, made.$2, 'application/octet-stream', {
        'Cache-Control': 'no-cache',
        'ETag': etagOf(made.$1),
      });
    }),
    ControllerApi._route('GET', r'/api/v1/field/branding/([^/]+)', (r) {
      final slot = r.pathText(1);
      _slot(slot);
      _publicRead(r);
      final img = _branding().slotImage(slot);
      if (img == null) throw _HttpError(404, 'no $slot uploaded');
      return _image(r, img, 'no-cache');
    }),
    ControllerApi._route(
      'PUT',
      r'/api/v1/field/branding/([^/]+)',
      _gm((r) {
        final slot = r.pathText(1);
        final limits = _slot(slot);
        final (data, type) = _upload(r, limits.maxBytes, slot);
        return ApiResponse(200, _branding().putImage(slot, data, type));
      }),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/field/branding/([^/]+)',
      _gm((r) {
        final slot = r.pathText(1);
        _slot(slot);
        return ApiResponse(200, _branding().deleteImage(slot));
      }),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/crests',
      _gm((r) {
        final (data, type) = _upload(r, ImageLimits.crest.maxBytes, 'crest');
        final (out, created) = _branding().addCrest(data, type);
        return ApiResponse(created ? 201 : 200, out);
      }),
    ),
    ControllerApi._route('GET', r'/api/v1/crests/([^/]+)', (r) {
      _publicRead(r);
      final img = _branding().crest(r.pathText(1));
      if (img == null) throw _HttpError(404, 'no such crest');
      // A crest's id is its content's hash: the same URL never changes.
      return _image(r, img, 'public, max-age=31536000, immutable');
    }),
    ControllerApi._route(
      'GET',
      r'/api/v1/team-presets',
      _read((r, who) => ApiResponse(200, _branding().teamPresets())),
    ),
    ControllerApi._route(
      'POST',
      r'/api/v1/team-presets',
      _gm((r) => ApiResponse(201, _branding().saveTeamPreset(r.body))),
    ),
    ControllerApi._route(
      'PUT',
      r'/api/v1/team-presets/([^/]+)',
      _gm(
        (r) =>
            ApiResponse(200, _branding().saveTeamPreset(r.body, r.pathInt(1))),
      ),
    ),
    ControllerApi._route(
      'DELETE',
      r'/api/v1/team-presets/([^/]+)',
      _gm((r) => ApiResponse(200, _branding().deleteTeamPreset(r.pathInt(1)))),
    ),
    ControllerApi._route('GET', r'/api/v1/games/([^/]+)/teams', (r) {
      final id = r.pathInt(1);
      _publicRead(r);
      return ApiResponse(200, _branding().gameTeams(id));
    }),
    ControllerApi._route(
      'PUT',
      r'/api/v1/games/([^/]+)/teams/([^/]+)',
      _gm(
        (r) => ApiResponse(
          200,
          _branding().setTeamInfo(r.pathInt(1), r.pathText(2), r.body),
        ),
      ),
    ),
  ];
}
