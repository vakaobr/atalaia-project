// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What a scanned or typed text is, among the codes Atalaia itself makes, so
/// a screen that got the wrong kind can say what it is and where to use it
/// ("this is X: use Y") instead of "invalid".
library;

import '../player/field_feed.dart';
import '../protocol/checkin_poster.dart' show isPosterText;
import '../protocol/join_payload.dart' show joinTextPrefix;
import '../site/site_link.dart';

enum CodeKind {
  /// A field's check-in poster (`atalaia:checkin:…`): Player > Check in.
  poster('code.is_poster'),

  /// A join code for a prop (`atalaia:join:…`): Game prop > Join a game.
  joinCard('code.is_join_card'),

  /// A field's online registration (`atalaia://register?…`, `https://…/f/…`):
  /// Player > Online registration.
  siteLink('code.is_site_link'),

  /// The scoreboard's address with its access code: Player > Follow a game.
  scoreboard('code.is_scoreboard');

  const CodeKind(this.messageKey);

  /// The text saying what this is and where to use it.
  final String messageKey;
}

/// The kind of [text], or null when it is none of Atalaia's own codes.
CodeKind? classifyCode(String text) {
  if (isPosterText(text)) return CodeKind.poster;
  if (text.trim().startsWith(joinTextPrefix)) return CodeKind.joinCard;
  if (SiteGameLink.parse(text) != null) return CodeKind.siteLink;
  if (FieldLink.parse(text) != null) return CodeKind.scoreboard;
  return null;
}

/// The message key for [text] when it is a kind of code other than [here]
/// (what the screen takes); null when it is [here] or no code of ours.
String? wrongCodeMessage(String text, CodeKind here) {
  final k = classifyCode(text);
  return k == null || k == here ? null : k.messageKey;
}
