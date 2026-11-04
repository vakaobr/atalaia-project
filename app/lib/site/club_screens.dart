// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The club pages in the app (decision S18-11's "club pages in the app",
/// APPS-9 to APPS-16): the account's clubs ([ClubsScreen]), one club with
/// its members and the fields where it plays ([ClubScreen]), the account's
/// own memberships and invitations ([MyClubsScreen]), and making or
/// changing a club ([ClubFormScreen]). Each action is shown by the role the
/// site server names (`my_role`), as a hint: the server decides. Like the
/// other site screens, nothing is kept on the phone.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'account_screen.dart' show accountError;
import 'clubs.dart';
import 'site_client.dart';
import 'site_screens.dart' show siteMoment;

/// The words for a refusal of the club calls: `club.e.<code>`, else the
/// account's and the site's general texts.
String clubError(Strings s, Object e) {
  if (e is SiteException && !e.offline) {
    final own = 'club.e.${e.code}';
    if (s.tOr(own, '') != '') return s.t(own);
  }
  return accountError(s, e);
}

/// A club's colour (`#rrggbb`) as a [Color], or null.
Color? clubColour(String? hex) {
  if (hex == null || !RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(hex)) return null;
  return Color(0xFF000000 | int.parse(hex.substring(1), radix: 16));
}

Widget _swatch(Club c) {
  final colour = clubColour(c.colour);
  return CircleAvatar(
    backgroundColor: colour ?? Colors.grey.shade400,
    child: Text(
      c.shortName.isEmpty ? '?' : c.shortName.characters.first.toUpperCase(),
      style: TextStyle(
        color: colour != null && colour.computeLuminance() > 0.5
            ? Colors.black
            : Colors.white,
      ),
    ),
  );
}

/// An error and a done message above a list, in view wherever the person
/// has scrolled to.
Widget _messages(String? error, String? ok, String prefix) => Column(
  children: [
    if (error != null)
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Notice(error, kind: NoticeKind.error, key: Key('$prefix-error')),
      ),
    if (ok != null)
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Notice(ok, kind: NoticeKind.ok, key: Key('$prefix-ok')),
      ),
  ],
);

/// The account's clubs, a pointer to its invitations, and a new club.
class ClubsScreen extends StatefulWidget {
  const ClubsScreen({required this.session, super.key});
  final SiteSession session;

  @override
  State<ClubsScreen> createState() => _ClubsScreenState();
}

class _ClubsScreenState extends State<ClubsScreen> {
  late final ClubApi _api = ClubApi(widget.session);
  List<Club>? _clubs;
  int _invites = 0;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _clubs = null;
      _error = null;
    });
    try {
      final results = await Future.wait<Object>([_api.list(), _api.mine()]);
      if (!mounted) return;
      setState(() {
        _clubs = results[0] as List<Club>;
        _invites = (results[1] as List<MyClubMembership>)
            .where((m) => !m.accepted)
            .length;
      });
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(context.s, e));
    }
  }

  Future<void> _open(String id) async {
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => ClubScreen(session: widget.session, clubId: id),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _new() async {
    final made = await Navigator.push<Club>(
      context,
      MaterialPageRoute<Club>(
        builder: (_) => ClubFormScreen(session: widget.session),
      ),
    );
    if (made != null && mounted) await _open(made.id);
  }

  Future<void> _mine() async {
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => MyClubsScreen(session: widget.session),
      ),
    );
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final clubs = _clubs;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('club.title')),
        actions: [
          IconButton(
            key: const Key('clubs-reload'),
            tooltip: s.t('history.reload'),
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('club.intro')),
          const SizedBox(height: 12),
          if (_error != null)
            Notice(
              _error!,
              kind: NoticeKind.error,
              key: const Key('clubs-error'),
            )
          else if (clubs == null)
            const Center(child: CircularProgressIndicator())
          else ...[
            if (_invites > 0)
              Notice(
                s.t('club.invites_waiting', {'n': _invites}),
                key: const Key('clubs-invites'),
                action: TextButton(
                  onPressed: _mine,
                  child: Text(s.t('club.invites_open')),
                ),
              ),
            SectionTitle(s.t('club.list_title')),
            if (clubs.isEmpty)
              Notice(s.t('club.none'), key: const Key('clubs-none'))
            else
              for (final c in clubs)
                Card(
                  child: ListTile(
                    key: Key('club-${c.id}'),
                    leading: _swatch(c),
                    title: Text(c.name),
                    subtitle: Text(
                      [
                        c.shortName,
                        if (c.myRole != null) s.t('club.role.${c.myRole}'),
                        _pageState(s, c),
                      ].join(' · '),
                    ),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => _open(c.id),
                  ),
                ),
          ],
          const SizedBox(height: 16),
          FilledButton.icon(
            key: const Key('clubs-new'),
            icon: const Icon(Icons.add),
            label: Text(s.t('club.new')),
            onPressed: _new,
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('clubs-mine'),
            icon: const Icon(Icons.badge_outlined),
            label: Text(s.t('club.mine_title')),
            onPressed: _mine,
          ),
        ],
      ),
    );
  }
}

String _pageState(Strings s, Club c) => c.hidden
    ? s.t('club.page_hidden')
    : s.t(c.publicPage ? 'club.page_public' : 'club.page_private');

/// The account's memberships and invitations: accept or decline an
/// invitation, leave a club.
class MyClubsScreen extends StatefulWidget {
  const MyClubsScreen({required this.session, super.key});
  final SiteSession session;

  @override
  State<MyClubsScreen> createState() => _MyClubsScreenState();
}

class _MyClubsScreenState extends State<MyClubsScreen> {
  late final ClubApi _api = ClubApi(widget.session);
  List<MyClubMembership>? _mine;
  String? _error;
  String? _ok;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final mine = await _api.mine();
      if (mounted) setState(() => _mine = mine);
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(context.s, e));
    }
  }

  Future<void> _run(Future<void> Function() work, String done) async {
    if (_busy) return;
    final s = context.s;
    setState(() {
      _busy = true;
      _error = null;
      _ok = null;
    });
    try {
      await work();
      final mine = await _api.mine();
      if (!mounted) return;
      setState(() {
        _mine = mine;
        _ok = done;
      });
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _decline(MyClubMembership m) async {
    final s = context.s;
    if (!await confirm(
      context,
      title: s.t('club.decline_confirm', {'club': m.name}),
      yes: s.t('club.decline'),
    )) {
      return;
    }
    await _run(
      () => _api.removeMember(m.clubId, m.userId),
      s.t('club.declined_ok', {'club': m.name}),
    );
  }

  Future<void> _leave(MyClubMembership m) async {
    final s = context.s;
    if (!await confirm(
      context,
      title: s.t('club.leave_confirm', {'club': m.name}),
      body: s.t('club.leave_body'),
      yes: s.t('club.leave'),
    )) {
      return;
    }
    await _run(
      () => _api.removeMember(m.clubId, m.userId),
      s.t('club.left_ok', {'club': m.name}),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final mine = _mine;
    final invites = [
      for (final m in mine ?? const <MyClubMembership>[])
        if (!m.accepted) m,
    ];
    final joined = [
      for (final m in mine ?? const <MyClubMembership>[])
        if (m.accepted) m,
    ];
    return Scaffold(
      appBar: AppBar(title: Text(s.t('club.mine_title'))),
      body: Column(
        children: [
          _messages(_error, _ok, 'myclubs'),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(s.t('club.mine_intro')),
                if (mine == null && _error == null)
                  const Padding(
                    padding: EdgeInsets.only(top: 16),
                    child: Center(child: CircularProgressIndicator()),
                  )
                else if (mine != null) ...[
                  SectionTitle(s.t('club.invites_title')),
                  if (invites.isEmpty)
                    Text(
                      s.t('club.invites_none'),
                      key: const Key('myclubs-no-invites'),
                    ),
                  for (final m in invites)
                    Card(
                      key: Key('myclubs-invite-${m.clubId}'),
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            ListTile(
                              title: Text(m.name),
                              subtitle: Text(
                                [
                                  s.t('club.invited_as', {
                                    'role': s.t('club.role.${m.role}'),
                                  }),
                                  if (m.invitedAt != null)
                                    siteMoment(m.invitedAt!),
                                ].join(' · '),
                              ),
                            ),
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 16,
                              ),
                              child: Wrap(
                                spacing: 8,
                                children: [
                                  FilledButton(
                                    key: Key('myclubs-accept-${m.clubId}'),
                                    onPressed: _busy
                                        ? null
                                        : () => _run(
                                            () => _api.accept(m.clubId),
                                            s.t('club.joined_ok', {
                                              'club': m.name,
                                            }),
                                          ),
                                    child: Text(s.t('club.accept')),
                                  ),
                                  OutlinedButton(
                                    key: Key('myclubs-decline-${m.clubId}'),
                                    onPressed: _busy ? null : () => _decline(m),
                                    child: Text(s.t('club.decline')),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  SectionTitle(s.t('club.memberships_title')),
                  if (joined.isEmpty)
                    Text(
                      s.t('club.memberships_none'),
                      key: const Key('myclubs-none'),
                    ),
                  for (final m in joined)
                    Card(
                      child: ListTile(
                        key: Key('myclubs-member-${m.clubId}'),
                        title: Text(m.name),
                        subtitle: Text(
                          [
                            s.t('club.role.${m.role}'),
                            if (m.acceptedAt != null)
                              s.t('club.member_since', {
                                'when': siteMoment(m.acceptedAt!),
                              }),
                          ].join(' · '),
                        ),
                        trailing: TextButton(
                          key: Key('myclubs-leave-${m.clubId}'),
                          onPressed: _busy ? null : () => _leave(m),
                          child: Text(s.t('club.leave')),
                        ),
                        onTap: () => Navigator.push(
                          context,
                          MaterialPageRoute<void>(
                            builder: (_) => ClubScreen(
                              session: widget.session,
                              clubId: m.clubId,
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// One club: what it shows, where it plays, its members; an admin's
/// changes, invitations and roles; leaving.
class ClubScreen extends StatefulWidget {
  const ClubScreen({required this.session, required this.clubId, super.key});
  final SiteSession session;
  final String clubId;

  @override
  State<ClubScreen> createState() => _ClubScreenState();
}

class _ClubScreenState extends State<ClubScreen> {
  late final ClubApi _api = ClubApi(widget.session);
  final _invitee = TextEditingController();
  String _inviteRole = 'member';
  Club? _club;
  List<ClubMember> _members = const [];
  String? _error;
  String? _ok;
  bool _busy = false;
  bool _gone = false; // left, or deleted: nothing more to show

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _invitee.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final club = await _api.get(widget.clubId);
      final members = club.myRole == null
          ? const <ClubMember>[]
          : await _api.members(widget.clubId);
      if (!mounted) return;
      setState(() {
        _club = club;
        _members = members;
      });
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(context.s, e));
    }
  }

  Future<void> _run(
    Future<void> Function() work,
    String done, {
    bool leaves = false,
  }) async {
    if (_busy) return;
    final s = context.s;
    setState(() {
      _busy = true;
      _error = null;
      _ok = null;
    });
    try {
      await work();
      if (leaves) {
        if (mounted) {
          setState(() {
            _gone = true;
            _ok = done;
          });
        }
        return;
      }
      await _load();
      if (mounted) setState(() => _ok = done);
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  bool _self(ClubMember m) =>
      m.username.isNotEmpty && m.username == widget.session.username;

  Future<void> _invite() async {
    final s = context.s;
    final name = _invitee.text.trim();
    if (name.isEmpty) {
      setState(() => _error = s.t('club.invite_needed'));
      return;
    }
    await _run(() async {
      await _api.putMember(widget.clubId, name, _inviteRole);
      _invitee.clear();
    }, s.t('club.invited_ok', {'user': name}));
  }

  Future<void> _remove(ClubMember m) async {
    final s = context.s;
    final self = _self(m);
    if (!await confirm(
      context,
      title: self
          ? s.t('club.leave_confirm', {'club': _club!.name})
          : s.t('club.remove_confirm', {'user': m.username}),
      body: self ? s.t('club.leave_body') : null,
      yes: s.t(self ? 'club.leave' : 'club.remove'),
    )) {
      return;
    }
    await _run(
      () => _api.removeMember(widget.clubId, m.userId),
      self
          ? s.t('club.left_ok', {'club': _club!.name})
          : s.t('club.removed_ok', {'user': m.username}),
      leaves: self,
    );
  }

  Future<void> _edit() async {
    final s = context.s;
    final changed = await Navigator.push<Club>(
      context,
      MaterialPageRoute<Club>(
        builder: (_) => ClubFormScreen(session: widget.session, club: _club),
      ),
    );
    if (changed == null || !mounted) return;
    await _load();
    if (mounted) setState(() => _ok = s.t('club.saved_ok'));
  }

  Future<void> _delete() async {
    final s = context.s;
    if (!await confirm(
      context,
      title: s.t('club.delete_confirm', {'club': _club!.name}),
      body: s.t('club.delete_body'),
      yes: s.t('club.delete'),
    )) {
      return;
    }
    await _run(
      () => _api.delete(widget.clubId),
      s.t('club.deleted_ok', {'club': _club!.name}),
      leaves: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final c = _club;
    return Scaffold(
      appBar: AppBar(title: Text(c?.name ?? s.t('club.title'))),
      body: Column(
        children: [
          _messages(_error, _ok, 'club'),
          Expanded(
            child: _gone
                ? const SizedBox.shrink()
                : c == null
                ? (_error == null
                      ? const Center(child: CircularProgressIndicator())
                      : const SizedBox.shrink())
                : ListView(
                    padding: const EdgeInsets.all(16),
                    children: _body(s, c),
                  ),
          ),
        ],
      ),
    );
  }

  List<Widget> _body(Strings s, Club c) => [
    ListTile(
      contentPadding: EdgeInsets.zero,
      leading: _swatch(c),
      title: Text(c.name, style: Theme.of(context).textTheme.titleLarge),
      subtitle: Text(
        [
          c.shortName,
          c.slug,
          if (c.myRole != null) s.t('club.role.${c.myRole}'),
        ].join(' · '),
        key: const Key('club-head'),
      ),
    ),
    Text(_pageState(s, c), key: const Key('club-page-state')),
    if (c.hidden)
      Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Notice(
          c.hiddenReason == null || c.hiddenReason!.isEmpty
              ? s.t('club.hidden_note')
              : s.t('club.hidden_reason', {'reason': c.hiddenReason!}),
          kind: NoticeKind.warning,
          key: const Key('club-hidden'),
        ),
      ),
    if (c.description != null && c.description!.isNotEmpty) ...[
      const SizedBox(height: 12),
      Text(c.description!, key: const Key('club-description')),
    ],
    SectionTitle(s.t('club.fields_title')),
    if (c.fields.isEmpty)
      Text(s.t('club.fields_none'), key: const Key('club-no-fields'))
    else
      for (final f in c.fields)
        ListTile(
          key: Key('club-field-${f.id}'),
          dense: true,
          leading: const Icon(Icons.place_outlined),
          title: Text(f.name),
          subtitle: Text(
            s.t(f.publicPage ? 'club.field_public' : 'club.field_private'),
          ),
        ),
    if (c.myRole != null) ...[
      SectionTitle(s.t('club.members_title')),
      if (!c.admin) Text(s.t('club.members_hint')),
      for (final m in _members) _memberTile(s, c, m),
    ],
    if (c.admin) ..._adminTools(s),
    if (c.myRole != null && !c.admin) ...[
      const SizedBox(height: 16),
      Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton(
          key: const Key('club-leave'),
          onPressed: _busy
              ? null
              : () {
                  final me = _members.where(_self).firstOrNull;
                  if (me != null) unawaited(_remove(me));
                },
          child: Text(s.t('club.leave')),
        ),
      ),
    ],
  ];

  Widget _memberTile(Strings s, Club c, ClubMember m) {
    final self = _self(m);
    final next = m.role == 'admin' ? 'member' : 'admin';
    return Card(
      key: Key('club-member-${m.userId}'),
      child: ListTile(
        title: Text(self ? s.t('club.you', {'user': m.username}) : m.username),
        subtitle: Text(
          [
            s.t('club.role.${m.role}'),
            if (!m.accepted)
              s.t('club.invited')
            else if (m.acceptedAt != null)
              s.t('club.member_since', {'when': siteMoment(m.acceptedAt!)}),
          ].join(' · '),
        ),
        trailing: !c.admin
            ? null
            : PopupMenuButton<String>(
                key: Key('club-member-menu-${m.userId}'),
                enabled: !_busy,
                onSelected: (v) {
                  if (v == 'role') {
                    unawaited(
                      _run(
                        () => _api.putMember(widget.clubId, m.username, next),
                        s.t('club.role_ok', {
                          'user': m.username,
                          'role': s.t('club.role.$next'),
                        }),
                      ),
                    );
                  } else {
                    unawaited(_remove(m));
                  }
                },
                itemBuilder: (_) => [
                  if (!self)
                    PopupMenuItem(
                      key: Key('club-member-role-${m.userId}'),
                      value: 'role',
                      child: Text(s.t('club.make_$next')),
                    ),
                  PopupMenuItem(
                    key: Key('club-member-remove-${m.userId}'),
                    value: 'remove',
                    child: Text(
                      self
                          ? s.t('club.leave')
                          : m.accepted
                          ? s.t('club.remove')
                          : s.t('club.cancel_invite'),
                    ),
                  ),
                ],
              ),
      ),
    );
  }

  List<Widget> _adminTools(Strings s) => [
    SectionTitle(s.t('club.invite_title')),
    Text(s.t('club.invite_text')),
    TextField(
      key: const Key('club-invite-user'),
      controller: _invitee,
      maxLength: 64,
      autocorrect: false,
      decoration: InputDecoration(labelText: s.t('club.invite_user')),
      onSubmitted: (_) => _invite(),
    ),
    DropdownButtonFormField<String>(
      key: const Key('club-invite-role'),
      initialValue: _inviteRole,
      decoration: InputDecoration(labelText: s.t('club.invite_role')),
      items: [
        for (final r in clubRoles)
          DropdownMenuItem(value: r, child: Text(s.t('club.role.$r'))),
      ],
      onChanged: (v) => setState(() => _inviteRole = v ?? 'member'),
    ),
    const SizedBox(height: 8),
    Align(
      alignment: Alignment.centerLeft,
      child: FilledButton(
        key: const Key('club-invite'),
        onPressed: _busy ? null : _invite,
        child: Text(s.t('club.invite')),
      ),
    ),
    SectionTitle(s.t('club.admin_title')),
    Text(s.t('club.images_on_site')),
    const SizedBox(height: 8),
    Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        OutlinedButton.icon(
          key: const Key('club-edit'),
          icon: const Icon(Icons.edit_outlined),
          label: Text(s.t('club.edit')),
          onPressed: _busy ? null : _edit,
        ),
        OutlinedButton.icon(
          key: const Key('club-delete'),
          icon: const Icon(Icons.delete_outline),
          label: Text(s.t('club.delete')),
          onPressed: _busy ? null : _delete,
        ),
      ],
    ),
  ];
}

/// Making a club (its slug is fixed then), or changing one (and its public
/// page). Pops with the club the site server answered.
class ClubFormScreen extends StatefulWidget {
  const ClubFormScreen({required this.session, this.club, super.key});
  final SiteSession session;

  /// Null: a new club.
  final Club? club;

  @override
  State<ClubFormScreen> createState() => _ClubFormScreenState();
}

class _ClubFormScreenState extends State<ClubFormScreen> {
  late final ClubApi _api = ClubApi(widget.session);
  late final _name = TextEditingController(text: widget.club?.name);
  late final _short = TextEditingController(text: widget.club?.shortName);
  final _slug = TextEditingController();
  late final _description = TextEditingController(
    text: widget.club?.description,
  );
  late final _colour = TextEditingController(text: widget.club?.colour);
  late bool _public = widget.club?.publicPage ?? false;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    for (final c in [_name, _short, _slug, _description, _colour]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy) return;
    final s = context.s;
    final club = widget.club;
    if (_name.text.trim().isEmpty ||
        _short.text.trim().isEmpty ||
        (club == null && _slug.text.trim().isEmpty)) {
      setState(() => _error = s.t('club.form_needed'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final colour = _colour.text.trim();
      final description = _description.text;
      final Club saved;
      if (club == null) {
        saved = await _api.create(
          ClubForm(
            name: _name.text,
            shortName: _short.text,
            slug: _slug.text.trim(),
            description: description.trim().isEmpty ? null : description,
            colour: colour.isEmpty ? null : colour,
          ),
        );
      } else {
        saved = await _api.update(
          club.id,
          ClubForm(
            name: _name.text,
            shortName: _short.text,
            description: description,
            colour: colour,
            publicPage: _public,
          ),
        );
      }
      if (mounted) Navigator.pop(context, saved);
    } on SiteException catch (e) {
      if (mounted) setState(() => _error = clubError(s, e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final editing = widget.club != null;
    return Scaffold(
      appBar: AppBar(title: Text(s.t(editing ? 'club.edit' : 'club.new'))),
      body: Column(
        children: [
          _messages(_error, null, 'clubform'),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (!editing) Text(s.t('club.new_intro')),
                TextField(
                  key: const Key('clubform-name'),
                  controller: _name,
                  maxLength: 128,
                  decoration: InputDecoration(labelText: s.t('club.name')),
                ),
                TextField(
                  key: const Key('clubform-short'),
                  controller: _short,
                  maxLength: 32,
                  decoration: InputDecoration(
                    labelText: s.t('club.short_name'),
                    helperText: s.t('club.short_name_hint'),
                    helperMaxLines: 3,
                  ),
                ),
                if (!editing)
                  TextField(
                    key: const Key('clubform-slug'),
                    controller: _slug,
                    maxLength: 128,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: s.t('club.slug'),
                      helperText: s.t('club.slug_hint'),
                      helperMaxLines: 3,
                    ),
                  ),
                TextField(
                  key: const Key('clubform-description'),
                  controller: _description,
                  maxLength: 4000,
                  minLines: 2,
                  maxLines: 6,
                  decoration: InputDecoration(
                    labelText: s.t('club.description'),
                  ),
                ),
                TextField(
                  key: const Key('clubform-colour'),
                  controller: _colour,
                  maxLength: 7,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: s.t('club.colour'),
                    helperText: s.t('club.colour_hint'),
                  ),
                ),
                if (editing)
                  SwitchListTile(
                    key: const Key('clubform-public'),
                    contentPadding: EdgeInsets.zero,
                    value: _public,
                    onChanged: (v) => setState(() => _public = v),
                    title: Text(s.t('club.public_page')),
                    subtitle: Text(s.t('club.public_page_hint')),
                  ),
                const SizedBox(height: 12),
                FilledButton(
                  key: const Key('clubform-save'),
                  onPressed: _busy ? null : _save,
                  child: Text(s.t(editing ? 'common.save' : 'club.create')),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
