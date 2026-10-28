// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The APD membership part of a registration or check-in form, and the
/// verdict's label and colour (protocol/apd.md; decisions APD-40 to APD-49).
///
/// A player declares the APD, the membership number and its expiry. Nothing
/// is verified: the field's rule only says whether the declaration is needed
/// and which APDs it accepts; the marshal compares it with the card.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;

import '../l10n/strings.dart';
import '../protocol/apd.dart';

List<ApdEntry>? _projectList;

/// The project's list of APDs, from the app's assets (empty when the build
/// has none or the file is unreadable: a field's own entries still work).
Future<List<ApdEntry>> loadProjectApds([AssetBundle? bundle]) async {
  final cached = _projectList;
  if (cached != null) return cached;
  try {
    return _projectList = parseApdList(
      await (bundle ?? rootBundle).loadString('assets/apds.json'),
    );
  } on Object {
    return const [];
  }
}

/// What a person typed or was given: the APD, the number and the expiry.
final class ApdInput {
  ApdInput();

  final number = TextEditingController();
  final expires = TextEditingController();
  String? apd;

  void load({String? apd, String? number, String? expires}) {
    this.apd = apd;
    this.number.text = number ?? '';
    this.expires.text = expires ?? '';
  }

  void dispose() {
    number.dispose();
    expires.dispose();
  }

  String? get numberOrNull {
    final t = number.text.trim();
    return t.isEmpty ? null : t;
  }

  String? get expiresOrNull {
    final t = expires.text.trim();
    return t.isEmpty ? null : t;
  }

  /// The string key of what is wrong with the form for [rule], or null.
  /// [needNumber]: the number is required (the game's federation rule or
  /// the field's `register`).
  String? problem(ApdRule rule, {required bool needNumber}) {
    final e = expiresOrNull;
    if (e != null && !validApdDate(e)) return 'apd.bad_date';
    if (needNumber && numberOrNull == null) return 'apd.need_number';
    if (rule.expiry && rule.register && e == null) return 'apd.need_expiry';
    return null;
  }
}

/// Whether a form shows the APD block: the field asks for a membership or
/// names the APDs it accepts.
bool apdAsked(ApdRule rule) =>
    rule.checkin || rule.register || rule.expiry || rule.accepted != null;

/// The strings key of a verdict's label.
String apdStatusKey(String status) => 'apd.status.$status';

/// The colour a verdict is shown in.
Color apdStatusColor(BuildContext context, String? status) {
  final scheme = Theme.of(context).colorScheme;
  return switch (status) {
    'valid' => Colors.green.shade700,
    'expired' => Colors.orange.shade800,
    'not_accepted' || 'missing' => scheme.error,
    _ => scheme.outline,
  };
}

/// "valid" / "expired" / "not accepted" / "missing" as a small badge; nothing
/// when no rule asks (the verdict is null).
class ApdBadge extends StatelessWidget {
  const ApdBadge({required this.status, this.overridden = false, super.key});
  final String? status;

  /// A marshal confirmed it with this verdict.
  final bool overridden;

  @override
  Widget build(BuildContext context) {
    final st = status;
    if (st == null) return const SizedBox.shrink();
    final s = context.s;
    final color = apdStatusColor(context, st);
    return Container(
      key: Key('apd-badge-$st'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        s.t(apdStatusKey(st)) +
            (overridden ? ' · ${s.t('apd.overridden')}' : ''),
        style: TextStyle(color: color, fontWeight: FontWeight.w600),
      ),
    );
  }
}

/// The line a marshal reads: `APD · number · until date`. Empty when
/// nothing was declared.
String apdLine(
  Strings s,
  List<ApdEntry> choices, {
  String? apd,
  String? number,
  String? expires,
}) {
  final parts = [
    if (apd != null) apdLabel(apd, choices),
    ?number,
    if (expires != null) s.t('apd.until', {'date': expires}),
  ];
  return parts.join(' · ');
}

/// The APD picker, the membership number and the expiry of a form.
class ApdFields extends StatefulWidget {
  const ApdFields({
    required this.input,
    required this.rule,
    required this.numberRequired,
    this.choices,
    this.keyPrefix = 'apd',
    super.key,
  });

  final ApdInput input;
  final ApdRule rule;
  final bool numberRequired;

  /// The APDs to offer (the controller's `apds`); null: the project's list
  /// and the rule's own entries.
  final List<ApdEntry>? choices;
  final String keyPrefix;

  @override
  State<ApdFields> createState() => _ApdFieldsState();
}

class _ApdFieldsState extends State<ApdFields> {
  List<ApdEntry> _project = const [];

  @override
  void initState() {
    super.initState();
    if (widget.choices == null) {
      unawaited(
        loadProjectApds().then((l) {
          if (mounted) setState(() => _project = l);
        }),
      );
    }
  }

  List<ApdEntry> get _choices =>
      widget.choices ?? widget.rule.choices(_project);

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final rule = widget.rule;
    final input = widget.input;
    final choices = _choices;
    final accepted = rule.accepted;
    final names = accepted == null
        ? null
        : [for (final id in accepted) apdLabel(id, choices)].join(', ');
    final ids = {for (final e in choices) e.id};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 16),
        Text(s.t('apd.section'), style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(
          names == null
              ? s.t('apd.accepts_any')
              : s.t('apd.accepts', {'list': names}),
          key: Key('${widget.keyPrefix}-accepts'),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String?>(
          key: Key('${widget.keyPrefix}-pick'),
          initialValue: ids.contains(input.apd) ? input.apd : null,
          isExpanded: true,
          decoration: InputDecoration(labelText: s.t('apd.pick')),
          items: [
            DropdownMenuItem(value: null, child: Text(s.t('apd.unlisted'))),
            for (final e in choices)
              DropdownMenuItem(
                value: e.id,
                child: Text(e.name, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: (v) => setState(() => input.apd = v),
        ),
        const SizedBox(height: 12),
        TextField(
          key: Key('${widget.keyPrefix}-number'),
          controller: input.number,
          maxLength: 32,
          decoration: InputDecoration(
            labelText: s.t(
              widget.numberRequired ? 'apd.number_required' : 'apd.number',
            ),
            helperText: s.t('apd.hint'),
            helperMaxLines: 3,
          ),
        ),
        TextField(
          key: Key('${widget.keyPrefix}-expires'),
          controller: input.expires,
          maxLength: 10,
          keyboardType: TextInputType.datetime,
          decoration: InputDecoration(
            labelText: s.t(
              rule.expiry && rule.register
                  ? 'apd.expires_required'
                  : 'apd.expires',
            ),
            hintText: s.t('apd.date_format'),
          ),
        ),
      ],
    );
  }
}
