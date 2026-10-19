// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The screens a Field Box draws from C when a mode has no template of that
/// name (modes/README.md "Screens"), written here as templates for the
/// Flutter renderer, with the same data and the same English text: Codes'
/// and Bomb's team codes' `code_entry`, and the older `final_score` that
/// Hold-All and Last Stand still call. The tests check them with the core's
/// parser like any mode's template.
library;

const shellScreens = <String, String>{
  'code_entry': _codeEntry,
  'final_score': _finalScore,
};

// Data: title (ARM, DEFUSE, CODE), digits (dots shown), left (optional
// seconds), message (optional), error (the message in red, else amber).
const _codeEntry =
    '''
template: code_entry
layout:
  - type: row
    style: { width: fill, height: 44, background: panel }
    children:
      - type: label
        text: "{(title || 'code')|upper}"
        style: { font_size: 20, width: fill, align: center }
  - type: spacer
    height: fill
  - type: label
    text: "{left|clock}"
    style: { font_size: 28, color: danger, visible: "{left}" }
  - type: row
    children:
$_dots
  - type: label
    text: "{message}"
    style: { font_size: 20, width: 300, color: "{error && 'danger' || 'accent'}", visible: "{message}" }
  - type: spacer
    height: fill
  - type: label
    text: "#  enter        *  delete"
    style:
      font_size: 14
      color: muted
      padding: { bottom: 10 }
''';

const _dots = '''
      - type: progress_bar
        value: "{digits >= 1}"
        style: { width: 22, height: 22 }
      - type: progress_bar
        value: "{digits >= 2}"
        style: { width: 22, height: 22 }
      - type: progress_bar
        value: "{digits >= 3}"
        style: { width: 22, height: 22 }
      - type: progress_bar
        value: "{digits >= 4}"
        style: { width: 22, height: 22 }
      - type: progress_bar
        value: "{digits >= 5}"
        style: { width: 22, height: 22, visible: "{digits >= 5}" }
      - type: progress_bar
        value: "{digits >= 6}"
        style: { width: 22, height: 22, visible: "{digits >= 6}" }
      - type: progress_bar
        value: "{digits >= 7}"
        style: { width: 22, height: 22, visible: "{digits >= 7}" }
      - type: progress_bar
        value: "{digits >= 8}"
        style: { width: 22, height: 22, visible: "{digits >= 8}" }''';

// Data: owner (the team holding the zone at the end).
const _finalScore = '''
template: final_score
layout:
  - type: row
    style: { width: fill, height: 44, background: panel }
    children:
      - type: label
        text: GAME OVER
        style: { font_size: 20, width: fill, align: center }
  - type: spacer
    height: fill
  - type: label
    text: The zone was held by
    style: { font_size: 20, color: muted, visible: "{owner}" }
  - type: label
    text: "{owner|upper}"
    style: { font_size: 48, color: "{owner}", visible: "{owner}" }
  - type: label
    text: No team held the zone
    style: { font_size: 20, color: muted, visible: "{!owner}" }
  - type: spacer
    height: fill
  - type: label
    text: Scores are final
    style:
      font_size: 14
      color: muted
      padding: { bottom: 10 }
''';
