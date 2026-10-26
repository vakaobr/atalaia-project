// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Per-squad objective chains on the phone controller (decisions SQ-1 to
// SQ-8): who gets which objective, and who of a squad (the Pi's
// controller/tests/test_squad_objectives.py, which this mirrors; the shared
// contract case "SQ per-squad objective chains" is in api_contract_test.dart).
// With `disclosure: leader` only the squad's leader gets the objective, the
// members are told their leader has orders; a game's choice overrides the
// scenario's; a hidden objective is nothing to a squad before it is revealed.

import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_scenarios.dart';
import 'package:flutter_test/flutter_test.dart';

const _modeYaml = '''
id: org.club.chains
kind: scenario
name: Chains
scenario:
  lang: en
  teams: [red, blue]
  squads: 2
  reveal: active
  disclosure: leader
  nodes: {}
  objectives:
    - { id: a1, type: capture_and_hold, name: Alpha one, team: red, squad: 1, visibility: squad }
    - { id: a2, type: capture_and_hold, name: Alpha two SECRET, team: red, squad: 1, visibility: hidden, depends_on: [a1] }
    - { id: b1, type: capture_and_hold, name: Bravo one, team: red, squad: 2, visibility: squad }
    - { id: c1, type: capture_and_hold, name: Charlie one, team: blue, visibility: team }
    - { id: all, type: capture_and_hold, name: For everyone, visibility: public }
''';

ApiViewer _player(int team, int squad, [String role = 'player']) => ApiViewer(
  'player',
  {'player_id': 'p', 'game_id': 7, 'team': team, 'squad': squad, 'role': role},
);

final _game = <String, Object?>{
  'id': 7,
  'teams': ['red', 'blue'],
};

Map<String, Object?> _event(String type, String objective, {String? squad}) => {
  'type': type,
  'team': 'red',
  'squad': squad,
  'data': {'objective': objective, 'team': 'red', 'squad': ?squad},
};

void main() {
  final meta = ScenarioMeta.parse(_modeYaml)!;
  final leader1 = _player(1, 1, 'squad_leader');
  final member1 = _player(1, 1);
  final leader2 = _player(1, 2, 'squad_leader');
  final loner = _player(1, 0);
  final blueLeader = _player(2, 1, 'squad_leader');
  final blueMember = _player(2, 1);
  const read = ApiViewer.read;

  List<String> ids(ApiViewer? v, Set<String> revealed, [String d = 'leader']) =>
      [
        for (final o
            in (meta.playerView(v, _game, revealed, d)['objectives']!
                    as List<Object?>)
                .cast<Map<String, Object?>>())
          o['id']! as String,
      ];

  test('the manifest settings come with the package', () {
    expect((meta.reveal, meta.disclosure), ('active', 'leader'));
    final staff = meta.staffView('members');
    expect(
      (staff['disclosure'], staff['disclosure_default']),
      ('members', 'leader'),
    );
    expect(staff['reveal'], 'active');
    final plain = ScenarioMeta.parse(
      _modeYaml
          .replaceAll('  reveal: active\n', '')
          .replaceAll('  disclosure: leader\n', ''),
    )!;
    expect((plain.reveal, plain.disclosure), ('all', 'members'));
  });

  test('a squad knows its active objective, and a hidden one only once '
      'revealed', () {
    expect(ids(leader1, {}), ['a1', 'all']);
    expect(ids(leader2, {}), ['b1', 'all']);
    expect(ids(leader1, {'a2'}), ['a1', 'a2', 'all']);
    expect(ids(leader2, {'a2'}), ['b1', 'all']);
    // Staff and the GM see them all, revealed or not.
    expect(ids(ApiViewer.gm, {}), ['a1', 'a2', 'b1', 'c1', 'all']);
    expect(ids(_player(2, 0, 'marshal'), {}), ['a1', 'a2', 'b1', 'c1', 'all']);
    expect(ids(read, {'a2'}), ['all']);
  });

  test('with leader disclosure the members get none, the leaders all', () {
    expect(ids(member1, {'a2'}), ['all']);
    expect(ids(blueMember, {}), ['all']);
    expect(ids(blueLeader, {}), ['c1', 'all']);
    // A player in no squad has no leader to be told through: the team's
    // objectives are theirs, a squad's are not.
    expect(ids(loner, {}), ['all']);
    expect(ids(_player(2, 0), {}), ['c1', 'all']);
    // The GM's choice for the game: the whole squad.
    expect(ids(member1, {'a2'}, 'members'), ['a1', 'a2', 'all']);
  });

  test('access: full, a notice for the squad that its leader has orders, '
      'none', () {
    final a1 = meta.objectives['a1']!;
    ObjectiveAccess access(ApiViewer v, [String d = 'leader']) =>
        objectiveAccess(v, a1, _game, d);
    expect(access(leader1), ObjectiveAccess.full);
    expect(access(member1), ObjectiveAccess.notice);
    expect(access(member1, 'members'), ObjectiveAccess.full);
    expect(access(leader2), ObjectiveAccess.none);
    expect(access(blueLeader), ObjectiveAccess.none);
    expect(access(read), ObjectiveAccess.none);
    expect(access(ApiViewer.gm), ObjectiveAccess.full);
  });

  test('the events: whole for the leader, the flag for the squad, nothing of '
      'which for the rest', () {
    final revealed = _event('scenario.objective.revealed', 'a2', squad: '1');
    Map<String, Object?> data(ApiViewer v, [String d = 'leader']) =>
        (scenarioEvent(v, revealed, _game, meta.objectives, d)['data']!
            as Map<String, Object?>);
    expect(data(leader1)['objective'], 'a2');
    expect(data(member1), {'team': 'red', 'squad': '1', 'leader_only': true});
    expect(data(leader2).containsKey('objective'), false);
    expect(data(leader2).containsKey('leader_only'), false);
    expect(data(blueMember).containsKey('leader_only'), false);
    expect(data(member1, 'members')['objective'], 'a2');
    expect(data(ApiViewer.gm)['objective'], 'a2');
    // Only a reveal carries the flag: a completion is public to the squad.
    final done = scenarioEvent(
      member1,
      _event('scenario.objective.completed', 'a1', squad: '1'),
      _game,
      meta.objectives,
      'leader',
    );
    expect((done['data']! as Map).containsKey('objective'), false);
    expect((done['data']! as Map).containsKey('leader_only'), false);
  });

  test('the GM chooses per game, with a request that is checked', () {
    expect(ControllerScenarios.checkDisclosure('leader'), 'leader');
    expect(ControllerScenarios.checkDisclosure(null), isNull);
    expect(
      () => ControllerScenarios.checkDisclosure('everyone'),
      throwsA(isA<Object>()),
    );
  });
}
