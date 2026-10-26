// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The "details" line under a "the field controller does not answer" message
/// (decision check-R5): why each address of the field failed last, its kind
/// (no answer, refused, no route, certificate not accepted, an HTTP status),
/// the address tried and the time, from [FieldRoutes]. Nothing when the
/// field has no failure kept, so a line that is not about reaching the
/// controller (a 409, a 401) shows none.
library;

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import 'field_route.dart';

String _two(int n) => n.toString().padLeft(2, '0');

/// One failure as a line of text, in [s]'s language.
String failureLine(Strings s, FieldFailure f) {
  final kind = s.t('diag.${f.kind.name}', {'status': f.status ?? 0});
  final t = f.at;
  return s.t('diag.line', {
    'kind': kind,
    'url': f.url,
    'time': '${_two(t.hour)}:${_two(t.minute)}:${_two(t.second)}',
  });
}

class FailureDetails extends StatelessWidget {
  const FailureDetails({required this.routeKey, this.routes, super.key});

  /// The field's id (or the key of a plain link: [FieldFeed.routeKey]).
  final String? routeKey;

  /// The routes to read (default: the app's).
  final FieldRoutes? routes;

  @override
  Widget build(BuildContext context) {
    final key = routeKey;
    if (key == null) return const SizedBox.shrink();
    final all = (routes ?? context.services.routes).failures(key);
    // A status under 500 is the controller answering, not out of reach.
    final shown = [
      for (final f in all)
        if (f.kind != FailKind.http || (f.status ?? 0) >= 500) f,
    ];
    if (shown.isEmpty) return const SizedBox.shrink();
    final s = context.s;
    final style = Theme.of(context).textTheme.bodySmall;
    return Padding(
      key: const Key('failure-details'),
      padding: const EdgeInsets.only(bottom: 8, left: 4, right: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(s.t('diag.title'), style: style),
          for (final f in shown)
            SelectableText(failureLine(s, f), style: style),
        ],
      ),
    );
  }
}
