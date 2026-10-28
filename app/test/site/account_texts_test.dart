// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Every refusal of the account's login methods is told in words in every
// language (decision PKA-1; the site server's ACC-2 does the same on its
// staff page against the codes its source raises, and these are those
// codes), and the words are picked by code: the account's own, else the
// site's general ones.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/site/account_screen.dart';
import 'package:atalaia_app/site/site_auth.dart';
import 'package:atalaia_app/site/site_client.dart';
import 'package:flutter_test/flutter_test.dart';

/// What the server raises on /me/*, /auth/stepup/*, /auth/totp/* and
/// /auth/passkey/* (api/login_methods.py, api/auth.py, api/me.py).
const accountCodes = [
  'last_login_method',
  'second_factor_required_by_role',
  'totp_required_by_role',
  'password_login_disabled',
  'confirmation_required',
  'invalid_password',
  'invalid_code',
  'no_password',
  'identity_not_found',
  'passkey_not_found',
  'too_many_passkeys',
  'passkey_exists',
  'passkey_invalid',
  'invalid_passkey',
  'invalid_challenge',
  'name_invalid',
  'totp_already_enabled',
  'totp_not_pending',
  'totp_not_enabled',
  'no_passkey',
  'password_too_short',
  'password_too_long',
  'password_is_username',
  'password_breached',
  'provider_not_configured',
];

/// What the callback puts in `?oidc_error=`, and what the phone adds.
const oidcCodes = [
  'state_invalid',
  'denied',
  'consent_required',
  'too_many_attempts',
  'quota_exceeded',
  'id_token_invalid',
  'token_exchange_failed',
  'provider_unreachable',
  'try_again',
  'already_linked',
  'identity_taken',
  'provider_already_linked',
  'identity_mismatch',
  'cancelled',
  'browser_unavailable',
  'other',
];

void main() {
  for (final lang in AppLanguage.values) {
    group('in ${lang.name}', () {
      final s = Strings(lang);

      test('a text for every refusal of the account', () {
        for (final c in accountCodes) {
          final text = accountError(s, SiteException(409, c));
          expect(text, isNotEmpty, reason: c);
          expect(
            lang.table.containsKey('acct.e.$c'),
            isTrue,
            reason: '$c has no text of its own in ${lang.name}',
          );
        }
      });

      test('a text for every way a social login ends badly', () {
        for (final c in oidcCodes) {
          expect(
            lang.table.containsKey('acct.oidc.$c'),
            isTrue,
            reason: '$c in ${lang.name}',
          );
          expect(accountError(s, OidcFailure(c)), isNotEmpty);
        }
        // A code nobody wrote words for is the general one.
        expect(
          accountError(s, OidcFailure('never_heard_of_it')),
          s.t('acct.oidc.other'),
        );
      });

      test('the phone\'s own failures, and a code with no text', () {
        for (final r in ['cancelled', 'no_credential', 'unsupported', 'x']) {
          expect(accountError(s, PasskeyException(r)), isNotEmpty);
        }
        expect(
          accountError(s, SiteException(0, 'offline')),
          s.t('site.err.offline'),
        );
        // The site's general texts still serve (no account text of its own).
        expect(
          accountError(s, SiteException(401, 'invalid_credentials')),
          s.t('site.err.invalid_credentials'),
        );
        expect(accountError(s, SiteException(500, 'zzz')), contains('zzz'));
      });
    });
  }
}
