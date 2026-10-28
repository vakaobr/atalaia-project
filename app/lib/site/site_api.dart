// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the app asks a site server for a player (plan phase 16's account
/// API, decision S16-13): a field's published games, registering with
/// pre-declared replicas, the account's registrations, changing and
/// cancelling them, a new ticket, and claiming this phone's player id at a
/// field (the field's controller confirms it, decision S16-4).
///
/// Tickets (decision F15) are shown by the server once, when a registration
/// is made or a new ticket asked for: [TicketStore] keeps them on the phone
/// before anything else happens, so a lost answer screen never loses one.
library;

import '../protocol/apd.dart';
import '../storage/app_store.dart';
import 'site_client.dart';

String? _str(Object? v) => v is String ? v : null;
DateTime? _time(Object? v) => v is String ? DateTime.tryParse(v) : null;
List<String> _strings(Object? v) => [
  for (final x in (v as List?) ?? const []) '$x',
];

final class SiteField {
  SiteField(Map<String, Object?> j)
    : id = '${j['id']}',
      slug = '${j['slug']}',
      name = '${j['name']}',
      timezone = _str(j['timezone']) ?? 'UTC',
      federationLabel = _str(j['federation_label']) ?? '',
      apd = ApdRule.lenient(j['apd']),
      country = j.containsKey('country')
          ? lenientApdCountry(j['country'])
          : 'PT',
      classes = _strings(j['classes']),
      maxReplicas = j['max_replicas'] is int ? j['max_replicas']! as int : 5;

  final String id;
  final String slug;
  final String name;
  final String timezone;
  final String federationLabel;

  /// The field's APD rule (protocol/apd.md); the default when it sends none.
  final ApdRule apd;

  /// The field's country (ISO 3166-1 alpha-2, null: unset): the wording of
  /// the membership texts and the list it offers. `PT` from a site server
  /// that sends none (before fields had one it only knew Portugal's APDs).
  final String? country;
  final List<String> classes;
  final int maxReplicas;
}

final class SiteGame {
  SiteGame(Map<String, Object?> j)
    : id = '${j['id']}',
      title = '${j['title']}',
      description = _str(j['description']),
      startsAt = _time(j['starts_at']) ?? DateTime.utc(1970),
      endsAt = _time(j['ends_at']) ?? DateTime.utc(1970),
      location = _str(j['location']),
      teams = _strings(j['teams']),
      maxPlayers = j['max_players'] as int?,
      placesLeft = j['places_left'] as int?,
      registrationState = _str(j['registration_state']),
      registrationOpen = j['registration_open'] == true,
      closesAt = _time(j['registration_closes_at']),
      opensAt = _time(j['registration_opens_at']),
      federation = _str(j['federation']) ?? 'off',
      predeclareReplicas = j['predeclare_replicas'] == true,
      status = _str(j['status']) ?? 'published',
      cancelledReason = _str(j['cancelled_reason']);

  final String id;
  final String title;
  final String? description;
  final DateTime startsAt;
  final DateTime endsAt;
  final String? location;
  final List<String> teams;
  final int? maxPlayers;
  final int? placesLeft;
  final String? registrationState;
  final bool registrationOpen;
  final DateTime? opensAt;
  final DateTime? closesAt;
  final String federation;
  final bool predeclareReplicas;
  final String status;
  final String? cancelledReason;
}

final class FieldGames {
  FieldGames(this.field, this.games);
  final SiteField field;
  final List<SiteGame> games;
}

final class RegReplica {
  const RegReplica({
    required this.type,
    required this.replicaClass,
    this.makeModel,
    this.state,
  });
  final String type;
  final String replicaClass;
  final String? makeModel;
  final String? state;

  Map<String, Object?> toRequest() => {
    'type': type,
    'class': replicaClass,
    if (makeModel != null && makeModel!.isNotEmpty) 'make_model': makeModel,
  };
}

final class Registration {
  Registration(Map<String, Object?> j)
    : id = '${j['id']}',
      scheduledGameId = '${j['scheduled_game_id']}',
      fieldId = '${j['field_id']}',
      playerId = '${j['player_id']}',
      displayName = _str(j['display_name']),
      teamPreference = _str(j['team_preference']),
      federationNumber =
          _str(j['membership_number']) ?? _str(j['federation_number']),
      apdId = _str(j['apd_id']),
      membershipExpires = _str(j['membership_expires']),
      status = _str(j['status']) ?? 'registered',
      hasTicket = j['has_ticket'] == true,
      replicas = [
        for (final r in (j['replicas'] as List?) ?? const [])
          if (r is Map)
            RegReplica(
              type: '${r['type']}',
              replicaClass: '${r['class']}',
              makeModel: _str(r['make_model']),
              state: _str(r['state']),
            ),
      ],
      gameTitle = _str((j['game'] as Map?)?['title']) ?? '',
      startsAt = _time((j['game'] as Map?)?['starts_at']),
      gameStatus = _str((j['game'] as Map?)?['status']),
      fieldName = _str((j['field'] as Map?)?['name']) ?? '',
      fieldSlug = _str((j['field'] as Map?)?['slug']) ?? '',
      ticket = _str(j['ticket']),
      ticketText = _str(j['ticket_text']);

  final String id;
  final String scheduledGameId;
  final String fieldId;
  final String playerId;
  final String? displayName;
  final String? teamPreference;

  /// The membership number (the old federation number).
  final String? federationNumber;
  final String? apdId;
  final String? membershipExpires;
  final String status;
  final bool hasTicket;
  final List<RegReplica> replicas;
  final String gameTitle;
  final DateTime? startsAt;
  final String? gameStatus;
  final String fieldName;
  final String fieldSlug;

  /// Only in the answer that made it (the secret, and the printable text).
  final String? ticket;
  final String? ticketText;

  bool get live => status == 'registered';
}

/// What the player sends to register or change a registration.
final class RegistrationForm {
  const RegistrationForm({
    required this.displayName,
    this.teamPreference,
    this.federationNumber,
    this.apdId,
    this.membershipExpires,
    this.replicas,
  });
  final String displayName;
  final String? teamPreference;

  /// The membership number (sent as `membership_number` and, for an older
  /// server, `federation_number`).
  final String? federationNumber;
  final String? apdId;

  /// `YYYY-MM-DD`.
  final String? membershipExpires;

  /// Null: not sent (the game does not ask for replicas).
  final List<RegReplica>? replicas;

  Map<String, Object?> toRequest() => {
    'display_name': displayName,
    'team_preference': teamPreference,
    'federation_number': federationNumber,
    'membership_number': federationNumber,
    'apd_id': apdId,
    'membership_expires': membershipExpires,
    if (replicas != null)
      'replicas': [for (final r in replicas!) r.toRequest()],
  };
}

final class PlayerIds {
  PlayerIds(Map<String, Object?> j)
    : linked = {
        for (final x in (j['player_ids'] as List?) ?? const [])
          if (x is Map) '${x['field_id']}': '${x['player_id']}',
      },
      claims = [
        for (final x in (j['claims'] as List?) ?? const [])
          if (x is Map) x.cast<String, Object?>(),
      ];

  /// Field id -> the account's player id there.
  final Map<String, String> linked;
  final List<Map<String, Object?>> claims;

  /// The latest claim at [fieldId]: pending, confirmed or refused.
  String? claimStatus(String fieldId) {
    String? out;
    for (final c in claims) {
      if (c['field_id'] == fieldId) out = '${c['status']}';
    }
    return out;
  }
}

/// One event of a game the player took part in: what the site server keeps
/// of the player's own events (`game_history` in `GET /me/data`, plan
/// phase 20, decision S20-6).
final class HistoryEvent {
  HistoryEvent(Map<String, Object?> j)
    : tMs = j['t'] is int ? j['t']! as int : 0,
      type = '${j['type']}',
      team = _str(j['team']),
      data = j['data'] is Map
          ? (j['data']! as Map).cast<String, Object?>()
          : const {},
      receivedAt = _time(j['received_at']);

  final int tMs;
  final String type;
  final String? team;
  final Map<String, Object?> data;
  final DateTime? receivedAt;
}

/// A game in the player's history: the game, its final (or latest) scores
/// and the player's own events in it.
final class HistoryGame {
  HistoryGame(Map<String, Object?> j)
    : id = '${j['game']}',
      field = _str(j['field']) ?? '',
      name = _str(j['name']) ?? '',
      modeId = _str(j['mode_id']),
      teams = _strings(j['teams']),
      state = _str(j['state']) ?? 'ended',
      startedAt = _time(j['started_at']),
      endedAt = _time(j['ended_at']),
      playerIds = _strings(j['player_ids']),
      registered = j['registered'] == true,
      totals = {
        for (final e in ((j['totals'] as Map?) ?? const {}).entries)
          '${e.key}': e.value is int ? e.value as int : 0,
      },
      events = [
        for (final e in (j['events'] as List?) ?? const [])
          if (e is Map) HistoryEvent(e.cast<String, Object?>()),
      ];

  final String id;
  final String field;
  final String name;
  final String? modeId;
  final List<String> teams;
  final String state;
  final DateTime? startedAt;
  final DateTime? endedAt;

  /// The player's pseudonymous ids at the field in this game.
  final List<String> playerIds;

  /// Checked in to the game through a registration.
  final bool registered;

  /// Team -> points.
  final Map<String, int> totals;
  final List<HistoryEvent> events;

  bool get ended => state == 'ended';

  /// The team with the most points, null on a tie or with no points (the
  /// site server's rule, `services/history.winner`).
  String? get winner {
    if (totals.isEmpty) return null;
    final best = totals.values.reduce((a, b) => a > b ? a : b);
    final leaders = [
      for (final e in totals.entries)
        if (e.value == best) e.key,
    ];
    return leaders.length == 1 && best > 0 ? leaders.single : null;
  }
}

class SiteApi {
  SiteApi(this.session);
  final SiteSession session;

  Future<FieldGames> fieldGames(String slug) async {
    final j = await session.call(
      'GET',
      '/fields-by-slug/${Uri.encodeComponent(slug)}',
    );
    return FieldGames(
      SiteField(((j['field'] as Map?) ?? const {}).cast<String, Object?>()),
      [
        for (final g in (j['games'] as List?) ?? const [])
          if (g is Map) SiteGame(g.cast<String, Object?>()),
      ],
    );
  }

  Future<Registration> register(
    String fieldId,
    String gameId,
    RegistrationForm form,
  ) async => Registration(
    await session.call(
      'POST',
      '/fields/$fieldId/scheduled-games/$gameId/registrations',
      body: form.toRequest(),
    ),
  );

  Future<List<Registration>> mine() async {
    final r = await session.callRaw('GET', '/me/registrations');
    if (!r.ok) throw SiteException(r.status, r.detail);
    return [
      for (final x in (r.body as List?) ?? const [])
        if (x is Map) Registration(x.cast<String, Object?>()),
    ];
  }

  Future<Registration> change(String regId, RegistrationForm form) async =>
      Registration(
        await session.call(
          'PATCH',
          '/me/registrations/$regId',
          body: form.toRequest(),
        ),
      );

  Future<void> cancel(String regId) async {
    final r = await session.callRaw('DELETE', '/me/registrations/$regId');
    if (!r.ok) throw SiteException(r.status, r.detail);
  }

  Future<Registration> newTicket(String regId) async => Registration(
    await session.call('POST', '/me/registrations/$regId/ticket'),
  );

  /// The games the account played, oldest first, from the player's own
  /// data (`GET /me/data`, its `game_history`): the site server has no
  /// smaller answer for a player, and its other history views
  /// (`/fields/{id}/history`, `/games/{id}/log`) need a role at the field.
  Future<List<HistoryGame>> history() async {
    final j = await session.call('GET', '/me/data');
    return [
      for (final g in (j['game_history'] as List?) ?? const [])
        if (g is Map) HistoryGame(g.cast<String, Object?>()),
    ];
  }

  Future<PlayerIds> playerIds() async =>
      PlayerIds(await session.call('GET', '/me/player-ids'));

  Future<String> claim(String fieldId, String playerId, String secret) async {
    final j = await session.call(
      'POST',
      '/me/player-ids',
      body: {
        'field_id': fieldId,
        'player_id': playerId,
        'player_secret': secret,
      },
    );
    return '${j['status']}';
  }
}

/// A check-in ticket the app keeps (decision F15): the registration it is
/// for, the secret the app sends at check-in, and the `atalaia:ticket:`
/// text a marshal scans.
final class KeptTicket {
  const KeptTicket({
    required this.site,
    required this.registrationId,
    required this.playerId,
    required this.ticket,
    required this.ticketText,
    required this.gameTitle,
    required this.fieldName,
    this.startsAt,
  });

  final String site;
  final String registrationId;
  final String playerId;
  final String ticket;
  final String ticketText;
  final String gameTitle;
  final String fieldName;
  final DateTime? startsAt;

  Map<String, Object?> toJson() => {
    'site': site,
    'registration_id': registrationId,
    'player_id': playerId,
    'ticket': ticket,
    'ticket_text': ticketText,
    'game_title': gameTitle,
    'field_name': fieldName,
    'starts_at': startsAt?.toUtc().toIso8601String(),
  };

  static KeptTicket? fromJson(Map<String, Object?> j) {
    final site = _str(j['site']);
    final rid = _str(j['registration_id']);
    final pid = _str(j['player_id']);
    final t = _str(j['ticket']);
    final text = _str(j['ticket_text']);
    if (site == null || rid == null || pid == null || t == null) return null;
    if (text == null) return null;
    return KeptTicket(
      site: site,
      registrationId: rid,
      playerId: pid,
      ticket: t,
      ticketText: text,
      gameTitle: _str(j['game_title']) ?? '',
      fieldName: _str(j['field_name']) ?? '',
      startsAt: _time(j['starts_at']),
    );
  }

  /// From an answer that carries a ticket, or null.
  static KeptTicket? of(String site, Registration r, {String? fieldName}) {
    if (r.ticket == null || r.ticketText == null) return null;
    return KeptTicket(
      site: site,
      registrationId: r.id,
      playerId: r.playerId,
      ticket: r.ticket!,
      ticketText: r.ticketText!,
      gameTitle: r.gameTitle,
      fieldName: fieldName ?? r.fieldName,
      startsAt: r.startsAt,
    );
  }
}

class TicketStore {
  TicketStore(this.store);
  final AppStore store;
  static const _list = 'site_tickets';

  Future<List<KeptTicket>> all() async => [
    for (final j in await store.loadList(_list)) ?KeptTicket.fromJson(j),
  ];

  Future<KeptTicket?> forRegistration(String regId) async =>
      (await all()).where((t) => t.registrationId == regId).firstOrNull;

  /// Keeps [t], replacing an older ticket of the same registration; at most
  /// 50 (the oldest games' go first).
  Future<void> keep(KeptTicket t) async {
    final rest = [
      for (final x in await all())
        if (x.registrationId != t.registrationId) x,
    ];
    final out = [...rest, t];
    while (out.length > 50) {
      out.removeAt(0);
    }
    await store.saveList(_list, [for (final x in out) x.toJson()]);
  }

  Future<void> remove(String regId) async => store.saveList(_list, [
    for (final x in await all())
      if (x.registrationId != regId) x.toJson(),
  ]);
}
