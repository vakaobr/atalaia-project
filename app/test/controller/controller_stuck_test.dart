// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A box still in an ended game, on the phone controller
// (controller_stuck.dart; decisions STUCK-1 to STUCK-19, STUCK-40 to
// STUCK-59 and STUCK-60 on; RFC 0001 Amendments 27 and 28), as the Pi's
// controller/tests/test_reinvite.py StuckGameTests and ReleaseFieldTests:
// WATCH_GAMES asked of a radio that can, OTHER_GAME reports of an ended game
// answered by its GAME_OVER at most once a minute, the GM's Release and the
// field-wide RELEASE with their rate limits and refusals, over the API too.

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_boxes.dart';
import 'package:atalaia_app/controller/controller_clock.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/controller_stuck.dart';
import 'package:atalaia_app/protocol/field_frame.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_modem.dart';

const gameHz = 869525000, otherHz = 868100000;

/// 2026-11-05 12:00 UTC: a plausible wall clock.
const wallStart = 1793966400.0;

void main() {
  late int now;
  late double wall;
  late RecordingModem radio;
  late ControllerEngine engine;
  late ControllerBoxes boxes;
  late ControllerStuck stuck;
  late Uint8List key;
  late List<Map<String, Object?>> messages;

  ControllerEngine make({RecordingModem? modem}) {
    final e = ControllerEngine(
      modem: modem ?? radio,
      clockMs: () => now,
      wallSeconds: () => wall + now / 1000,
    )..joinKey = Uint8List.fromList(List.generate(32, (i) => 7 + i));
    ControllerBoxes(e);
    return e;
  }

  setUp(() {
    now = 0;
    wall = wallStart;
    radio = RecordingModem();
    engine = make();
    boxes = engine.boxes!;
    stuck = engine.stuck!;
    key = fieldKey(engine.joinKey);
    messages = [];
    engine.addListener(messages.add);
  });

  tearDown(() => engine.close());

  void run(int ms) {
    final end = now + ms;
    while (now < end) {
      now += 50;
      engine.tick();
    }
  }

  /// Time passes; the field frames sent are counted and dropped.
  int drain(int ms) {
    var sent = radio.fields.length;
    radio.fields.clear();
    final end = now + ms;
    while (now < end) {
      now += 50;
      engine.tick();
      sent += radio.fields.length;
      radio.fields.clear();
    }
    return sent;
  }

  List<Map<String, Object?>> frames() => [
    for (final f in radio.fields) decodeFieldFrame(key, f),
  ];

  int game({int? channelHz}) {
    if (channelHz != null) {
      engine.store.setSetting('radio.channel_hz', '$channelHz');
    }
    return engine.createGame({
          'name': 'Sábado',
          'mode_id': 'org.atalaia.domination',
          'teams': ['red', 'blue'],
        })['id']!
        as int;
  }

  /// A game played and ended; its three GAME_OVERs went unheard.
  int endedGame() {
    final gid = game();
    engine.startGame(gid, force: true);
    expect(engine.endGame(gid)['game_over_frame'], 'sent');
    expect(drain(15000), gameOverRepeats);
    return gid;
  }

  String tagOf(int gid) => engine.store.getSetting('key_tag:$gid')!;

  test('WATCH_GAMES is asked of the radio, and stuck_watch says whether it '
      'can report', () {
    expect(radio.watching, [true]);
    expect(boxes.boxes()['stuck_watch'], isTrue);
    expect(boxes.boxes()['stuck'], isEmpty);
    expect(boxes.boxes()['stuck_reports'], 0);
    expect(boxes.boxes()['radio_kind'], 'modem');
    radio.games = false; // an older modem, or an I/O pod
    expect(boxes.boxes()['stuck_watch'], isFalse);
    // The console's hint tells the two apart (STUCK-64 as changed by the
    // maintainer): the stream's boxes message says what the radio is too.
    radio.kind = 'pod';
    expect(boxes.boxes()['radio_kind'], 'pod');
    expect(boxes.stuckView()['radio_kind'], 'pod');
  });

  test('a box still in an ended game is told again and listed', () {
    final gid = endedGame();
    messages.clear();
    radio.otherGame(gid, 4);
    expect(frames(), [
      {'kind': 'game_over', 'game_id': gid, 'key_tag': hexDecode(tagOf(gid))},
    ]);
    run(21000);
    final listed = boxes.boxes();
    final entry = (listed['stuck']! as List).single as Map;
    expect(
      [
        entry['game'],
        entry['name'],
        entry['nodes'],
        entry['rssi'],
        entry['game_over_resent'],
        entry['last_heard_s'],
      ],
      [
        gid,
        'Sábado',
        [4],
        -70,
        1,
        21,
      ],
    );
    expect([listed['stuck_reports'], listed['stuck_watch']], [1, true]);
    // The consoles heard of it on the stream, with the stuck list.
    final msg = messages.firstWhere((m) => m['type'] == 'boxes');
    expect((msg['stuck']! as List).single, containsPair('game', gid));
    expect(msg['stuck_watch'], isTrue);
  });

  test('at most once a minute per game', () {
    final gid = endedGame();
    radio.otherGame(gid, 4);
    expect(drain(10000), gameOverRepeats);
    for (var i = 0; i < 5; i++) {
      radio.otherGame(gid, 4); // the modem's next reports, 10 s apart
      expect(drain(10000), 0);
    }
    radio.otherGame(gid, 5); // a minute after the first burst: another
    expect(drain(10000), gameOverRepeats);
    final entry = (boxes.boxes()['stuck']! as List).single as Map;
    expect(
      [entry['nodes'], entry['game_over_resent']],
      [
        [4, 5],
        2,
      ],
    );
  });

  test('a game unheard for two minutes leaves the list and comes back when '
      'heard (STUCK-71)', () {
    // The bench finding of 2026-11-06: a freed box looked stuck for two
    // hours. What was heard stays stuckForgetMs, so a box heard again keeps
    // its game's resend count and once-a-minute limit.
    final gid = endedGame();
    radio.otherGame(gid, 4);
    expect(drain(10000), gameOverRepeats);
    now += stuckShownMs - 10000; // two minutes after it was heard: listed
    var entry = (boxes.boxes()['stuck']! as List).single as Map;
    expect([entry['game'], entry['last_heard_s']], [gid, stuckShownMs ~/ 1000]);
    now += 1000; // then silent (freed, or switched off): gone
    expect(boxes.boxes()['stuck'], isEmpty);
    expect(boxes.stuckView()['stuck'], isEmpty);
    expect(stuck.games, contains(gid)); // remembered
    radio.otherGame(gid, 5); // heard again: listed again, the count goes on
    drain(10000);
    entry = (boxes.boxes()['stuck']! as List).single as Map;
    expect(
      [entry['nodes'], entry['last_heard_s'], entry['game_over_resent']],
      [
        [4, 5],
        10,
        2,
      ],
    );
    now += stuckForgetMs + 1000;
    expect(boxes.boxes()['stuck'], isEmpty);
    expect(stuck.games, isNot(contains(gid))); // forgotten after two hours
  });

  test('the key tag outlives a restart without the key', () {
    final gid = endedGame();
    final tag = tagOf(gid);
    final again = make(modem: RecordingModem());
    addTearDown(again.close);
    // The same store would carry it; here the tag is all that is needed.
    again.store.createGame({...engine.store.game(gid)!});
    again.store.setSetting('key_tag:$gid', tag);
    final r = again.modem! as RecordingModem;
    r.otherGame(gid, 4);
    expect(decodeFieldFrame(key, r.fields.single), {
      'kind': 'game_over',
      'game_id': gid,
      'key_tag': hexDecode(tag),
    });
  });

  test("another field's game, the live game and a game with no tag change "
      'nothing', () {
    final gid = endedGame();
    radio.otherGame(999, 4); // not a game of this controller
    final live = game();
    radio.otherGame(live, 4); // the live game's own (not over)
    engine.store.deleteSetting('key_tag:$gid'); // ended before tags were kept
    radio.otherGame(gid, 4);
    expect(drain(10000), 0);
    final listed = boxes.boxes();
    expect(
      [listed['stuck'], listed['stuck_reports'], stuck.unknown],
      [<Object?>[], 3, 2],
    );
  });

  test('with a game live on another channel it is dropped', () {
    final gid = endedGame();
    game(channelHz: otherHz); // live on 868.1 MHz; the stuck box on 869.525
    radio.log.clear();
    radio.otherGame(gid, 4);
    expect(drain(10000), 0);
    expect(radio.log.where((e) => e['kind'] == 'channel'), isEmpty);
  });

  test('the key tags kept are bounded, a live game always keeps its own', () {
    final ids = <int>[];
    for (var i = 0; i < 3; i++) {
      final g = game();
      engine.endGame(g);
      ids.add(g);
    }
    expect(
      ids.every((g) => engine.store.getSetting('key_tag:$g') != null),
      true,
    );
    final live = game();
    pruneKeyTags(engine.store, keep: 2);
    expect(
      [for (final g in ids) engine.store.getSetting('key_tag:$g') != null],
      [false, true, true],
    );
    expect(engine.store.getSetting('key_tag:$live'), isNotNull);
  });

  group('a standby', () {
    late ControllerEngine leader;
    late int gid;

    setUp(() {
      gid = endedGame();
      leader = ControllerEngine()..joinKey = engine.joinKey;
      addTearDown(leader.close);
      leader.store.setSetting('radio.channel_hz', '$gameHz');
      leader.createGame({
        'name': 'Primary',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
      });
      engine.joinAsStandby(leader.issueJoin({'kind': 'controller'})['text']);
      radio.fields.clear();
    });

    test('never resends a GAME_OVER', () {
      radio.otherGame(gid, 4); // following a game: its primary tells the boxes
      expect(drain(10000), 0);
    });

    test('refuses Release and RELEASE', () {
      expect(
        () => stuck.release(gid),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 409)),
      );
      expect(
        () => stuck.releaseField(),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 409)),
      );
      final followed = engine.liveGame!['id']! as int;
      engine.endGame(followed); // left: its game is the primary's
      expect(engine.store.getSetting('key_tag:$followed'), isNotNull);
      radio.otherGame(followed, 4);
      expect(drain(10000), 0);
      expect(
        () => stuck.release(followed),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 409)),
      );
    });
  });

  group("the GM's Release", () {
    test("says the game's GAME_OVER now", () {
      final gid = endedGame();
      radio.otherGame(gid, 4);
      drain(65000); // the automatic burst is over, the next a minute away
      messages.clear();
      expect(stuck.release(gid), {'game': gid, 'game_over_frame': 'sent'});
      expect(frames(), [
        {'kind': 'game_over', 'game_id': gid, 'key_tag': hexDecode(tagOf(gid))},
      ]);
      final msg = messages.singleWhere((m) => m['type'] == 'boxes');
      expect(((msg['stuck']! as List).single as Map)['game_over_resent'], 2);
    });

    test('has a short rate limit', () {
      final gid = endedGame();
      // Not heard: allowed too.
      expect(stuck.release(gid)['game_over_frame'], 'sent');
      Matcher tooSoon() =>
          throwsA(isA<ControllerError>().having((e) => e.status, 's', 429));
      expect(() => stuck.release(gid), tooSoon()); // still being said
      expect(drain(9000), gameOverRepeats);
      expect(() => stuck.release(gid), tooSoon()); // under 10 s since
      drain(1100);
      expect(stuck.release(gid)['game_over_frame'], 'sent');
    });

    test('refuses what it cannot end', () {
      final gid = endedGame();
      expect(
        () => stuck.release(9999),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 404)),
      );
      final live = game();
      expect(
        () => stuck.release(live),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 409)),
      );
      engine.store.deleteSetting('key_tag:$gid');
      expect(stuck.release(gid), {'game': gid, 'game_over_frame': 'no_tag'});
      expect(drain(10000), 0);
    });

    test('without a radio', () {
      final gid = endedGame();
      radio.setState(ModemState.down);
      expect(stuck.release(gid)['game_over_frame'], 'no_radio');
    });

    test('with a game live on another channel is refused', () {
      final gid = endedGame();
      game(channelHz: otherHz);
      expect(
        () => stuck.release(gid),
        throwsA(
          isA<ControllerError>()
              .having((e) => e.status, 's', 409)
              .having((e) => e.message, 'm', contains('another channel')),
        ),
      );
      expect(drain(10000), 0);
    });
  });

  group('the field-wide RELEASE', () {
    test('names the live game and the wall clock, three times', () {
      final live = game();
      final out = stuck.releaseField();
      expect(out, {
        'live_game': live,
        'time': (wallStart).floor(),
        'release_frame': 'sent',
      });
      expect(frames(), [
        {'kind': 'release', 'live_game': live, 'time': wallStart.floor()},
      ]);
      expect(drain(10000), releaseRepeats); // the first one included
    });

    test('with no game live names none', () {
      expect(stuck.releaseField()['live_game'], 0);
      expect(frames().single['live_game'], 0);
    });

    test('has a rate limit', () {
      Matcher tooSoon() =>
          throwsA(isA<ControllerError>().having((e) => e.status, 's', 429));
      expect(stuck.releaseField()['release_frame'], 'sent');
      expect(() => stuck.releaseField(), tooSoon()); // still being said
      drain(10000);
      expect(() => stuck.releaseField(), tooSoon()); // under 30 s since
      drain(21000);
      expect(stuck.releaseField()['release_frame'], 'sent');
    });

    test('without a radio', () {
      radio.setState(ModemState.down);
      expect(stuck.releaseField()['release_frame'], 'no_radio');
      expect(radio.fields, isEmpty);
    });

    test('needs a plausible clock', () {
      wall = clockReleaseDateS - 3600.0; // a phone whose clock is far behind
      expect(
        () => stuck.releaseField(),
        throwsA(
          isA<ControllerError>()
              .having((e) => e.status, 's', 409)
              .having((e) => e.message, 'm', contains('clock')),
        ),
      );
      expect(radio.fields, isEmpty);
      // Behind a game it already recorded is not plausible either.
      wall = wallStart;
      endedGame();
      wall = wallStart - 7200;
      expect(
        () => stuck.releaseField(),
        throwsA(isA<ControllerError>().having((e) => e.status, 's', 409)),
      );
    });
  });

  test('TIME and RELEASE both carry the GM-corrected clock', () {
    // A GM moved the clock an hour forward (controller_clock.dart): the join
    // time a box takes from TIME and RELEASE's time must agree (Amendment
    // 28's replay rule compares them).
    engine.clock.set(wallStart + 3600);
    final gid = game();
    engine.startGame(gid, force: true);
    run(3000);
    final times = [
      for (final (h, p) in radio.sent)
        if (h.type == RfType.time) RfTime.decode(p).wallS,
    ];
    expect(times, isNotEmpty);
    expect(times.first, closeTo(wallStart + 3600, 5));
    engine.endGame(gid);
    drain(15000);
    final out = stuck.releaseField();
    expect(out['time']! as int, closeTo(wallStart + 3600 + now / 1000, 2));
    expect(out['time']! as int, greaterThan(times.last));
  });

  group('over the API', () {
    late ControllerApi api;

    setUp(() {
      api = ControllerApi(engine, gmToken: 'gm-secret', readToken: 'rd-secret');
    });

    (int, Object?) post(String path, {String token = 'gm-secret'}) {
      final r = api.handle(
        'POST',
        Uri.parse(path),
        authorization: 'Bearer $token',
      );
      return (r.status, r.body);
    }

    test('Release and RELEASE need the GM token and answer as the Pi', () {
      final gid = endedGame();
      final release = '/api/v1/boxes/stuck/$gid/release';
      expect(post(release, token: 'rd-secret').$1, 403);
      expect(post('/api/v1/boxes/release', token: 'rd-secret').$1, 403);
      final (status, body) = post(release);
      expect(status, 200);
      expect(body, {'game': gid, 'game_over_frame': 'sent'});
      expect(post(release).$1, 429);
      expect(post('/api/v1/boxes/stuck/9999/release').$1, 404);
      final all = post('/api/v1/boxes/release');
      expect(all.$1, 200);
      expect((all.$2! as Map)['release_frame'], 'sent');
      expect(post('/api/v1/boxes/release').$1, 429);
      final listed = api.handle(
        'GET',
        Uri.parse('/api/v1/boxes'),
        authorization: 'Bearer gm-secret',
      );
      expect(
        (listed.body! as Map).keys,
        containsAll(['stuck', 'stuck_reports', 'stuck_watch']),
      );
    });
  });
}
