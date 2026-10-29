// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The site server's privacy notice, and the account's consent to it, in the
/// app (decisions CONS-1 to CONS-6 of the site server; the staff pages'
/// "consent again" panel's twin).
///
/// The operator publishes the notice (`GET /api/v1/privacy-notice?lang=`, no
/// login); the app shows it in its own language (the server falls back to
/// another language when the version has no text in this one, and says which).
/// `GET /api/v1/me` says where the signed-in account's consent stands
/// (`consent.status`: `current`, `outdated` or `missing`); `POST
/// /api/v1/me/consents/account` names the version the person was shown, so a
/// notice that changed in between is refused (409 `notice_version_changed`)
/// and read again. Nothing is blocked (CONS-4: a lock would also block the
/// account's own export and erasure): the app asks, and keeps asking while
/// the field is open, until the consent is for the current version.
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

  /// The version a consent names.
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

/// Where an account's consent to the notice stands (`GET /me`'s `consent`).
final class ConsentState {
  ConsentState(Map<String, Object?> j)
    : status = _str(j['status']) ?? 'missing',
      version = _str(j['version']),
      currentVersion = _str(j['current_version']) ?? '',
      givenAt = j['given_at'] is String
          ? DateTime.tryParse('${j['given_at']}')
          : null,
      noticePublished = j['notice_published'] == true;

  /// `current`, `outdated` or `missing`.
  final String status;

  /// The version the account consented to (null: none).
  final String? version;
  final String currentVersion;
  final DateTime? givenAt;

  /// Whether the server has a text to show.
  final bool noticePublished;

  bool get isCurrent => status == 'current';

  /// The account is asked to consent again.
  bool get needed => !isCurrent;
}

/// The notice and the consent calls for one site.
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

  /// Where the signed-in account's consent stands; null from an older server
  /// that does not say.
  Future<ConsentState?> consent() async {
    final me = await session.call('GET', '/me');
    final c = me['consent'];
    return c is Map ? ConsentState(c.cast<String, Object?>()) : null;
  }

  /// Consent again to [version] (the one the person was shown). A notice that
  /// changed meanwhile throws [SiteException] with `notice_version_changed`.
  Future<ConsentState> renew(String version) async => ConsentState(
    await session.call(
      'POST',
      '/me/consents/account',
      body: {'notice_version': version},
    ),
  );
}
