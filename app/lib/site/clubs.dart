// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the app asks a site server about clubs (the site server's
/// api/clubs.py, plan phase 18, decisions S18-5, S18-8, S18-9 and APPS-9 to
/// APPS-16): a club is an organisation's profile, not an account. Any
/// account may make one and becomes its admin; an admin edits it, invites
/// accounts by their username and changes or removes members; an invited
/// person accepts (or declines); any member may leave; a club keeps at least
/// one admin (409 `last_admin`). Images and moderation stay with the staff
/// pages.
library;

import 'site_client.dart';

String? _str(Object? v) => v is String ? v : null;
DateTime? _time(Object? v) => v is String ? DateTime.tryParse(v) : null;

/// The club roles (the site server's `CLUB_ROLES`).
const clubRoles = ['admin', 'member'];

/// A field where a club plays (`fields` in `GET /clubs/{id}`).
final class ClubField {
  ClubField(Map<String, Object?> j)
    : id = '${j['id']}',
      name = _str(j['name']) ?? '',
      slug = _str(j['slug']) ?? '',
      publicPage = j['public_page'] == true;

  final String id;
  final String name;
  final String slug;
  final bool publicPage;
}

/// A club (services/branding.club_json).
final class Club {
  Club(Map<String, Object?> j)
    : id = '${j['id']}',
      name = _str(j['name']) ?? '',
      shortName = _str(j['short_name']) ?? '',
      slug = _str(j['slug']) ?? '',
      description = _str(j['description']),
      colour = _str(j['colour']),
      publicPage = j['public_page'] == true,
      hidden = j['hidden'] == true,
      hiddenReason = _str(j['hidden_reason']),
      hasLogo = j['logo'] != null,
      hasCrest = j['crest'] != null,
      myRole = _str(j['my_role']),
      fields = [
        for (final f in (j['fields'] as List?) ?? const [])
          if (f is Map) ClubField(f.cast<String, Object?>()),
      ];

  final String id;
  final String name;
  final String shortName;
  final String slug;
  final String? description;

  /// `#rrggbb`, or null.
  final String? colour;
  final bool publicPage;

  /// A server administrator took the public page off the site.
  final bool hidden;
  final String? hiddenReason;
  final bool hasLogo;
  final bool hasCrest;

  /// The caller's role (`admin` or `member`), null for someone who is not a
  /// member (a public club's page).
  final String? myRole;

  /// Only in `GET /clubs/{id}`.
  final List<ClubField> fields;

  bool get admin => myRole == 'admin';
}

/// A member of a club, or an invitation (`GET /clubs/{id}/members`).
final class ClubMember {
  ClubMember(Map<String, Object?> j)
    : userId = '${j['user_id']}',
      username = _str(j['username']) ?? '',
      role = _str(j['role']) ?? 'member',
      accepted = j['accepted'] == true,
      acceptedAt = _time(j['accepted_at']),
      invitedAt = _time(j['invited_at']);

  final String userId;
  final String username;
  final String role;

  /// False: invited, not yet accepted (only a club admin sees these).
  final bool accepted;
  final DateTime? acceptedAt;
  final DateTime? invitedAt;
}

/// One of the account's own memberships or invitations (`GET /me/clubs`).
final class MyClubMembership extends ClubMember {
  MyClubMembership(super.j)
    : clubId = '${j['club_id']}',
      slug = _str(j['slug']) ?? '',
      name = _str(j['name']) ?? '';

  final String clubId;
  final String slug;
  final String name;
}

/// A new club, or the changes to one (null: not sent).
final class ClubForm {
  const ClubForm({
    this.name,
    this.shortName,
    this.slug,
    this.description,
    this.colour,
    this.publicPage,
  });

  final String? name;
  final String? shortName;

  /// Only when making a club: it cannot change.
  final String? slug;
  final String? description;

  /// `#rrggbb`; an empty text clears it.
  final String? colour;

  /// Only when changing a club: a new club's page is off.
  final bool? publicPage;

  Map<String, Object?> toRequest() => {
    'name': ?name,
    'short_name': ?shortName,
    'slug': ?slug,
    'description': ?description,
    'colour': ?colour,
    'public_page': ?publicPage,
  };
}

class ClubApi {
  ClubApi(this.session);
  final SiteSession session;

  Future<List<Object?>> _list(String path) async {
    final r = await session.callRaw('GET', path);
    if (!r.ok) throw SiteException(r.status, r.detail);
    return (r.body as List?) ?? const [];
  }

  Future<void> _done(String method, String path) async {
    final r = await session.callRaw(method, path);
    if (!r.ok) throw SiteException(r.status, r.detail);
  }

  String _club(String id) => '/clubs/${Uri.encodeComponent(id)}';

  /// The clubs the account belongs to (every club, for a server
  /// administrator), by slug.
  Future<List<Club>> list() async => [
    for (final c in await _list('/clubs'))
      if (c is Map) Club(c.cast<String, Object?>()),
  ];

  /// A club, with the fields where it plays.
  Future<Club> get(String id) async =>
      Club(await session.call('GET', _club(id)));

  Future<Club> create(ClubForm form) async =>
      Club(await session.call('POST', '/clubs', body: form.toRequest()));

  Future<Club> update(String id, ClubForm form) async =>
      Club(await session.call('PATCH', _club(id), body: form.toRequest()));

  Future<void> delete(String id) => _done('DELETE', _club(id));

  Future<List<ClubMember>> members(String id) async => [
    for (final m in await _list('${_club(id)}/members'))
      if (m is Map) ClubMember(m.cast<String, Object?>()),
  ];

  /// Invites [username] with [role], or changes the role of a member.
  Future<ClubMember> putMember(String id, String username, String role) async =>
      ClubMember(
        await session.call(
          'PUT',
          '${_club(id)}/members',
          body: {'username': username, 'role': role},
        ),
      );

  /// Removes a member (an admin), or leaves, or declines an invitation (the
  /// account's own user id).
  Future<void> removeMember(String id, String userId) =>
      _done('DELETE', '${_club(id)}/members/${Uri.encodeComponent(userId)}');

  /// The account's memberships and invitations, by club slug.
  Future<List<MyClubMembership>> mine() async => [
    for (final m in await _list('/me/clubs'))
      if (m is Map) MyClubMembership(m.cast<String, Object?>()),
  ];

  Future<void> accept(String id) =>
      _done('POST', '/me/clubs/${Uri.encodeComponent(id)}/accept');
}
