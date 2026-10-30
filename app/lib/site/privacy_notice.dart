// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The site server's privacy notice, and which version the account was last
/// shown, in the app (decisions CONS-1 to CONS-6 and LEG-* of the site server;
/// the staff pages' "notice shown again" panel's twin). The account rests on
/// the contract, not on consent: the notice is information, and what the
/// server records is the version shown.
///
/// The operator publishes the notice (`GET /api/v1/privacy-notice?lang=`, no
/// login); the app shows it in its own language (the server falls back to
/// another language when the version has no text in this one, and says which).
/// `GET /api/v1/me` says where the signed-in account stands (`notice.status`:
/// `current`, `outdated` or `missing`); `POST /api/v1/me/notice` names the
/// version the person was shown, so a notice that changed in between is
/// refused (409 `notice_version_changed`) and read again. Nothing is blocked
/// (CONS-4: a lock would also block the account's own export and erasure): the
/// app asks, and keeps asking while the field is open, until the version
/// shown is the current one.
library;

import 'site_client.dart';

String? _str(Object? v) => v is String ? v : null;

/// The notice's text for one language.
final class PrivacyNotice {
  PrivacyNotice(Map<String, Object?> j)
    : version = '${j['version']}',
      lang = _str(j['lang']) ?? '',
      requestedLang = _str(j['requested_lang']) ?? '',
      available = [for (final l in (j['available'] as List?) ?? const []) '$l'],
      markdown = _str(j['markdown']) ?? '',
      url = _str(j['url']);

  /// The version of the notice.
  final String version;

  /// The language of [markdown].
  final String lang;

  /// The language the app asked for.
  final String requestedLang;
  final List<String> available;
  final String markdown;

  /// The notice's public page.
  final String? url;

  /// The text is not in the language asked for.
  bool get fallback => lang.isNotEmpty && lang != requestedLang;
}

/// Which notice version an account was last shown (`GET /me`'s `notice`).
final class NoticeState {
  NoticeState(Map<String, Object?> j)
    : status = _str(j['status']) ?? 'missing',
      version = _str(j['version']),
      currentVersion = _str(j['current_version']) ?? '',
      shownAt = j['shown_at'] is String
          ? DateTime.tryParse('${j['shown_at']}')
          : null,
      noticePublished = j['notice_published'] == true;

  /// `current`, `outdated` or `missing`.
  final String status;

  /// The version the account was last shown (null: none).
  final String? version;
  final String currentVersion;
  final DateTime? shownAt;

  /// Whether the server has a text to show.
  final bool noticePublished;

  bool get isCurrent => status == 'current';

  /// The account is shown the notice again.
  bool get needed => !isCurrent;
}

/// The notice calls for one site.
class PrivacyApi {
  PrivacyApi(this.session);
  final SiteSession session;

  /// The notice in [lang] (`pt`, `en`, `de`, `zh-tw`); null when the server
  /// has not published one (404) or is an older one without the call.
  Future<PrivacyNotice?> notice(String lang) async {
    final r = await session.http.send(
      'GET',
      '/privacy-notice?lang=${Uri.encodeQueryComponent(lang)}',
    );
    if (r.status == 404) return null;
    if (!r.ok) throw SiteException(r.status, r.detail);
    return PrivacyNotice(r.json);
  }

  /// Which version the signed-in account was last shown; null from an older
  /// server that does not say.
  Future<NoticeState?> noticeState() async {
    final me = await session.call('GET', '/me');
    final c = me['notice'];
    return c is Map ? NoticeState(c.cast<String, Object?>()) : null;
  }

  /// The account was shown [version] (the one on the screen) and confirms it.
  /// A notice that changed meanwhile throws [SiteException] with
  /// `notice_version_changed`.
  Future<NoticeState> acknowledge(String version) async => NoticeState(
    await session.call('POST', '/me/notice', body: {'notice_version': version}),
  );
}
