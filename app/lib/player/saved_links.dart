// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The scoreboard links with a CA pin (`&ca=`, decisions PD13, SQR-1) that a
/// player has used, kept per field so the player need not scan again
/// (decision SQR-4 as amended by APX-2).
///
/// An https address needs its CA to connect, so what is kept is the link
/// with the SHA-256 of the field CA it named: one entry per CA fingerprint.
/// The CA is fetched and checked again each time the entry is used
/// ([FieldLink.trusted]); an entry whose CA no longer matches is forgotten,
/// as is an older one for the same address when a link with another
/// fingerprint comes. The read code is a secret, sealed at rest like the
/// player's saved read code (the list's `token` field, `app_store.dart`).
library;

import '../security/bytes.dart';
import '../storage/app_store.dart';
import 'field_feed.dart';

/// How many fields are remembered (the oldest go first).
const savedLinksMax = 8;

const _listName = 'scoreboard_links';

final class SavedLinks {
  SavedLinks(this._store);

  final AppStore _store;

  /// The remembered links, the latest used first.
  Future<List<FieldLink>> load() async {
    final out = <FieldLink>[];
    for (final j in await _store.loadList(_listName)) {
      final ca = j['ca'];
      final url = j['url'];
      final token = j['token'];
      if (ca is! String ||
          url is! String ||
          token is! String ||
          !RegExp(r'^[0-9a-f]{64}$').hasMatch(ca)) {
        continue;
      }
      final link = FieldLink.parse(
        '$url#token=${Uri.encodeComponent(token)}&ca=$ca',
      );
      if (link != null && link.caSha256 != null) out.add(link);
    }
    return out;
  }

  /// Remembers [link] (it must carry a CA fingerprint; others are ignored):
  /// it goes first, replacing the entry for the same fingerprint and any
  /// other for the same address (that address's CA has changed).
  Future<void> remember(FieldLink link) async {
    final ca = link.caSha256;
    if (ca == null) return;
    final hex = hexEncode(ca);
    final rest = [
      for (final l in await load())
        if (hexEncode(l.caSha256!) != hex && l.base != link.base) l,
    ];
    await _save([link, ...rest].take(savedLinksMax));
  }

  /// Forgets the entry for the CA fingerprint [ca].
  Future<void> forget(List<int> ca) async {
    final hex = hexEncode(ca);
    await _save([
      for (final l in await load())
        if (hexEncode(l.caSha256!) != hex) l,
    ]);
  }

  Future<void> _save(Iterable<FieldLink> links) => _store.saveList(_listName, [
    for (final l in links)
      {
        'ca': hexEncode(l.caSha256!),
        'url': l.base.toString(),
        'token': l.token,
      },
  ]);
}
