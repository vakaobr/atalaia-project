// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The out-of-bounds warning (decisions MF-31 to MF-40) on a field whose
// controller is a phone: MF-40 said it could not work there, since the
// phone controller had no field plan; slice S7a of PE24 brought it. A
// player's app (lib/position/field_bounds.dart) reads the boundary and the
// map position with its own token from the phone controller's API, and the
// stream's map_features message for that player, and judges its fixes.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_field.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/position/field_bounds.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

/// The player app's requests, answered by the phone controller's API.
class PhoneHttp implements FieldHttp {
  PhoneHttp(this.api);
  final ControllerApi api;
  final calls = <String>[];

  @override
  Future<FieldResponse> send(
    String method,
    String path, {
    Object? body,
    String? token,
  }) async {
    calls.add('$method $path');
    final r = await api.handleAsync(
      method,
      Uri.parse('/api/v1$path'),
      authorization: token == null ? null : 'Bearer $token',
      body: body == null ? '' : jsonEncode(body),
    );
    return FieldResponse(r.status, r.body);
  }
}

void main() {
  test(
    'a player on a phone-controlled field is warned out of bounds',
    () async {
      final engine = ControllerEngine(
        transport: RecordingRadio(),
        wallSeconds: () => 1800000000.0,
      );
      ControllerCheckin(
        engine,
        CheckinConfig(
          limitsYaml: File(
            'lib/chrono/limit_templates/portugal.yaml',
          ).readAsStringSync(),
          utcDay: true,
        ),
      );
      ControllerPositions(engine);
      final api = ControllerApi(engine, gmToken: 'g', readToken: 'r');
      // The console (decision PE24-70) now shows the Field tab on a phone.
      final who = api.handle(
        'GET',
        Uri.parse('/api/v1/whoami'),
        authorization: 'Bearer g',
      );
      expect((who.body! as Map)['features'], containsAll(['field', 'radio']));

      ApiResponse gm(String method, String path, [Object? body]) => api.handle(
        method,
        Uri.parse(path),
        authorization: 'Bearer g',
        body: body == null ? '' : jsonEncode(body),
      );

      final gid =
          (gm('POST', '/api/v1/games', {
                    'name': 'Bounds',
                    'mode_id': 'org.atalaia.domination',
                  }).body!
                  as Map)['id']!
              as int;
      final checkedIn = api.handle(
        'POST',
        Uri.parse('/api/v1/checkin'),
        body: jsonEncode({
          'game_id': gid,
          'player_id': 'p-aaaaaaaaaaaa',
          'player_secret': base64Url
              .encode(List.filled(32, 1))
              .replaceAll('=', ''),
          'display_name': 'r1',
          'notice_version': 1,
        }),
      );
      expect(checkedIn.status, 201);
      expect(
        gm('PATCH', '/api/v1/games/$gid/checkins/p-aaaaaaaaaaaa', {
          'team': 'red',
          'squad': 0,
          'role': 'player',
        }).status,
        200,
      );
      final token =
          (api
                      .handle(
                        'POST',
                        Uri.parse('/api/v1/checkin/token'),
                        authorization:
                            'Bearer ${(checkedIn.body! as Map)['token']}',
                      )
                      .body!
                  as Map)['token']!
              as String;

      // The GM's plan, its map position and the field boundary (the console's
      // Field tab, or the field loaded from a map).
      final png = Uint8List.fromList([0x89, 0x50, 0x4e, 0x47, 1, 2, 3]);
      expect(engine.field!.putImage(0, 'image/png', png)['bytes'], png.length);
      expect(
        gm('PUT', '/api/v1/field/georef', {
          'points': [
            {'x': 0, 'y': 0, 'lat': 38.72, 'lon': -9.16},
            {'x': 1, 'y': 1, 'lat': 38.71, 'lon': -9.14},
          ],
        }).status,
        200,
      );
      expect(
        gm('POST', '/api/v1/field/features', {
          'type': 'boundary',
          'shape': 'polygon',
          'points': [
            {'x': 0.1, 'y': 0.1},
            {'x': 0.9, 'y': 0.1},
            {'x': 0.9, 'y': 0.9},
            {'x': 0.1, 'y': 0.9},
          ],
        }).status,
        201,
      );

      // The player's app: the boundary and the map position, with its token.
      final http = PhoneHttp(api);
      final bounds = await loadFieldBounds(http, token);
      expect(http.calls, ['GET /field/features', 'GET /field/levels/0/georef']);
      expect(bounds, isNotNull);
      expect(bounds!.byLevel.keys, [0]);
      // Inside: the middle of the field; outside: 5 % of the plan above it,
      // about 55 m north of the boundary's top edge.
      expect(bounds.distanceOutsideM(38.715, -9.15, null), lessThan(0));
      final out = bounds.distanceOutsideM(38.7195, -9.15, null)!;
      expect(out, closeTo(55.6, 1.0));
      final watch = BoundsWatch();
      expect(watch.onFix(out, 5, 0), BoundsAlert.none);
      expect(watch.onFix(out, 5, 6000), BoundsAlert.left);
      expect(
        watch.onFix(bounds.distanceOutsideM(38.715, -9.15, null), 5, 7000),
        BoundsAlert.back,
      );

      // The stream's map_features message for this player (MF-35) feeds the
      // same check: the boundary made for the organisers only ends it.
      final viewer = api.viewerOf(token)!;
      final feed = FieldFeed(
        FieldLink(Uri.parse('http://127.0.0.1:8080'), token),
      );
      addTearDown(feed.dispose);
      final boundaryId = engine.field!
          .visibleFeatures(ApiViewer.gm)
          .single['id'];
      gm('PUT', '/api/v1/field/features/$boundaryId', {
        'type': 'boundary',
        'shape': 'polygon',
        'points': [
          {'x': 0.1, 'y': 0.1},
          {'x': 0.9, 'y': 0.1},
          {'x': 0.9, 'y': 0.9},
        ],
        'visibility': 'organisers',
      });
      feed.onMessage(api.hub.route(viewer, featuresChanged)!);
      expect(feed.mapFeatures, isEmpty);
      final none = await loadFieldBounds(
        http,
        token,
        features: feed.mapFeatures,
      );
      expect(none!.byLevel, isEmpty);
    },
  );
}
