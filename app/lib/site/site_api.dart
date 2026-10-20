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
      classes = _strings(j['classes']),
      maxReplicas = j['max_replicas'] is int ? j['max_replicas']! as int : 5;

  final String id;
  final String slug;
  final String name;
  final String timezone;
  final String federationLabel;
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
      federationNumber = _str(j['federation_number']),
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
  final String? federationNumber;
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
    this.replicas,
  });
  final String displayName;
  final String? teamPreference;
  final String? federationNumber;

  /// Null: not sent (the game does not ask for replicas).
  final List<RegReplica>? replicas;

  Map<String, Object?> toRequest() => {
    'display_name': displayName,
    'team_preference': teamPreference,
    'federation_number': federationNumber,
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
