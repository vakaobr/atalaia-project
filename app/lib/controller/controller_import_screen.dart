// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A registration list imported from the phone controller's own screen
/// (decision PIM-1, PKE-1's caveat): the same `POST
/// /api/v1/games/{id}/checkins/import` the GM console's import panel uses
/// (the running controller on the loopback address with the GM token), with
/// the same rules (registration_import.dart): pick a CSV or JSON file with
/// Android's chooser, name the source, confirm that the field has its own
/// basis for the list, check it first (a dry run: nothing changes, every row
/// is listed as new, changed, unchanged, skipped or refused with the reason)
/// and only then import. A file or row the controller refuses is told in
/// words, in the app's language.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'registration_import.dart';

/// The controller refused the request, or could not be reached: [code] is
/// the controller's own (`basis_not_confirmed`, `csv_invalid`, ...) or
/// `offline`; [line] is the file's line it names, if any.
class ImportRequestError implements Exception {
  ImportRequestError(this.code, {this.line, this.detail});
  final String code;
  final int? line;
  final String? detail;

  @override
  String toString() => code;
}

/// Sends [body] (the import's JSON) to this phone's running controller and
/// returns its answer; [ImportRequestError] when it refuses.
Future<Map<String, Object?>> requestRegistrationImport(
  int port,
  String gmToken,
  int gameId,
  Map<String, Object?> body,
) async {
  final client = HttpClient();
  try {
    final req = await client.post(
      '127.0.0.1',
      port,
      '/api/v1/games/$gameId/checkins/import',
    );
    req.headers
      ..set(HttpHeaders.authorizationHeader, 'Bearer $gmToken')
      ..contentType = ContentType.json;
    req.add(utf8.encode(jsonEncode(body)));
    final res = await req.close();
    final text = await utf8.decodeStream(res);
    Object? json;
    try {
      json = jsonDecode(text);
    } on FormatException {
      // Not JSON: refused below with what it said.
    }
    if (res.statusCode == 200 && json is Map) {
      return json.cast<String, Object?>();
    }
    if (json is Map && json['detail'] is String) {
      final line = json['line'];
      throw ImportRequestError(
        json['detail']! as String,
        line: line is int ? line : null,
      );
    }
    throw ImportRequestError('refused', detail: '${res.statusCode}');
  } on SocketException {
    throw ImportRequestError('offline');
  } finally {
    client.close(force: true);
  }
}

/// The words for a file's, a row's or a request's [code] (the code itself
/// when the app has no text for it), with the file's [line] if there is one.
String importCodeText(Strings s, String code, [int? line]) {
  final base = s.tOr('ctl_import.codes.$code', code);
  return line == null ? base : '$base (${s.t('ctl_import.line', {'n': line})})';
}

class ControllerImportScreen extends StatefulWidget {
  const ControllerImportScreen({
    required this.gameId,
    required this.gameName,
    required this.request,
    super.key,
  });

  final int gameId;
  final String gameName;

  /// Sends the import's body to the controller (tests give their own).
  final Future<Map<String, Object?>> Function(Map<String, Object?> body)
  request;

  @override
  State<ControllerImportScreen> createState() => _ControllerImportScreenState();
}

class _ControllerImportScreenState extends State<ControllerImportScreen> {
  /// How many rows of the result are listed (the rest is only counted).
  static const _shownRows = 200;

  final _source = TextEditingController(text: 'csv');
  String? _fileName;
  String? _text;
  String _format = 'csv';
  bool _basis = false;
  bool _busy = false;
  bool _pickerMissing = false;
  Map<String, Object?>? _result;
  String? _error;
  int? _errorLine;
  String? _errorDetail;

  @override
  void dispose() {
    _source.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final picker = context.services.picker;
    if (picker == null || !await picker.available) {
      if (mounted) setState(() => _pickerMissing = true);
      return;
    }
    final file = await picker.pick(
      mimes: const [
        'text/csv',
        'text/comma-separated-values',
        'application/csv',
        'application/json',
        'text/plain',
      ],
      maxBytes: importMaxBytes,
    );
    if (!mounted || file == null) return;
    setState(() {
      _fileName = file.name;
      _text = null;
      _result = null;
      _error = null;
    });
    if (file.bytes.length > importMaxBytes) {
      setState(() => _error = 'too_large');
      return;
    }
    try {
      // Strictly UTF-8, as the controller reads it: a file in another
      // encoding is refused, not mangled.
      final text = utf8.decode(file.bytes);
      setState(() {
        _text = text;
        _format = file.name.toLowerCase().endsWith('.json') ? 'json' : 'csv';
      });
    } on FormatException {
      setState(() => _error = 'encoding_invalid');
    }
  }

  Future<void> _run({required bool dryRun}) async {
    final s = context.s;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await widget.request({
        'format': _format,
        'data': _text,
        'source': _source.text.trim(),
        'dry_run': dryRun,
        'basis_confirmed': _basis,
      });
      if (!mounted) return;
      setState(() {
        _result = result;
        _busy = false;
      });
      if (!dryRun) {
        final c = (result['counts']! as Map).cast<String, Object?>();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              s.t('ctl_import.done', {
                'created': c['created'],
                'updated': c['updated'],
              }),
            ),
          ),
        );
      }
    } on ImportRequestError catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _result = null;
        _error = e.code;
        _errorLine = e.line;
        _errorDetail = e.detail;
      });
    }
  }

  String _errorText(Strings s, String code) {
    if (code == 'offline') return s.t('ctl_import.offline');
    if (code == 'refused') {
      return s.t('ctl_import.failed', {'detail': _errorDetail ?? ''});
    }
    return importCodeText(s, code, code == 'too_large' ? null : _errorLine);
  }

  Widget _resultView(Strings s, Map<String, Object?> r) {
    final c = (r['counts']! as Map).cast<String, Object?>();
    final dry = r['dry_run'] == true;
    final ignored = (r['not_imported_columns'] as List?)?.cast<String>() ?? [];
    final more = r['not_imported_more'];
    final missing = ((r['missing'] as Map?)?['count'] as int?) ?? 0;
    final rows = [
      for (final x in (r['results']! as List).cast<Map<String, Object?>>())
        if (x['result'] != 'unchanged') x,
    ];
    final cut = rows.length > _shownRows;
    return Column(
      key: const Key('import-result'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Notice(
          '${s.t(dry ? 'ctl_import.checked' : 'ctl_import.imported')} '
          '${s.t('ctl_import.counts', {'rows': r['rows'], 'created': c['created'], 'updated': c['updated'], 'unchanged': c['unchanged'], 'skipped': c['skipped'], 'refused': c['refused']})}',
          kind: NoticeKind.ok,
        ),
        if (ignored.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              '${s.t('ctl_import.ignored', {'names': ignored.join(', ')})}'
              '${more is int && more > 0 ? ' ${s.t('ctl_import.more', {'n': more})}' : ''}',
              key: const Key('import-ignored'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        if (missing > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              s.t('ctl_import.missing', {'n': missing}),
              key: const Key('import-missing'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        for (final x in rows.take(_shownRows)) _rowTile(s, x),
        if (cut)
          Text(
            s.t('ctl_import.rows_more', {'n': rows.length - _shownRows}),
            key: const Key('import-rows-more'),
          ),
      ],
    );
  }

  Widget _rowTile(Strings s, Map<String, Object?> x) {
    final result = '${x['result']}';
    final notes = <String>[
      if (x['code'] is String) importCodeText(s, x['code']! as String),
      if (x['changed'] is List) (x['changed']! as List).join(', '),
      for (final w in (x['warnings'] as List? ?? const []))
        importCodeText(s, '$w'),
    ];
    final refused = result == 'refused';
    return Semantics(
      container: true,
      child: Card(
        key: Key('import-row-${x['row']}'),
        child: ListTile(
          dense: true,
          leading: Text('${s.t('ctl_import.row')} ${x['row']}'),
          title: Text(
            '${x['display_name'] ?? '–'}  ·  '
            '${s.t('ctl_import.results.$result')}',
            style: refused
                ? TextStyle(color: Theme.of(context).colorScheme.error)
                : null,
          ),
          subtitle: notes.isEmpty ? null : Text(notes.join('; ')),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final ready = _text != null;
    final checked = _result != null && _result!['dry_run'] == true;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('ctl_import.title'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(s.t('ctl_import.intro')),
          const SizedBox(height: 12),
          Notice(
            s.t('tags.for_game', {'game': widget.gameName}),
            kind: NoticeKind.ok,
          ),
          if (_pickerMissing)
            Notice(
              s.t('ctl_import.no_picker'),
              kind: NoticeKind.warning,
              key: const Key('import-no-picker'),
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              key: const Key('import-pick'),
              icon: const Icon(Icons.upload_file),
              label: Text(
                s.t(
                  _fileName == null
                      ? 'ctl_import.pick'
                      : 'ctl_import.pick_again',
                ),
              ),
              onPressed: _busy ? null : _pick,
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              _fileName == null
                  ? s.t('ctl_import.no_file')
                  : s.t('ctl_import.picked', {'name': _fileName}),
              key: const Key('import-file-name'),
            ),
          ),
          TextField(
            key: const Key('import-source'),
            controller: _source,
            maxLength: 32,
            autocorrect: false,
            enableSuggestions: false,
            decoration: InputDecoration(
              labelText: s.t('ctl_import.source'),
              helperText: s.t('ctl_import.source_hint'),
              helperMaxLines: 4,
            ),
            // A new source is another list: check it again.
            onChanged: (_) => setState(() => _result = null),
          ),
          CheckboxListTile(
            key: const Key('import-basis'),
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _basis,
            title: Text(s.t('ctl_import.basis')),
            onChanged: (v) => setState(() => _basis = v ?? false),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton(
                key: const Key('import-check'),
                onPressed: !ready || _busy ? null : () => _run(dryRun: true),
                child: Text(s.t('ctl_import.check')),
              ),
              FilledButton(
                key: const Key('import-run'),
                onPressed: !ready || _busy || !_basis || !checked
                    ? null
                    : () => _run(dryRun: false),
                child: Text(s.t('ctl_import.run')),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              s.t('ctl_import.order'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          if (_error != null)
            Notice(
              _errorText(s, _error!),
              kind: NoticeKind.error,
              key: const Key('import-error'),
            ),
          if (_result != null) _resultView(s, _result!),
        ],
      ),
    );
  }
}
