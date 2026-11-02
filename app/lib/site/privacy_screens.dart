// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field's privacy notice in the app, and the "notice shown again" prompt
/// (lib/site/privacy_notice.dart; the staff pages' twin, the site server's
/// CONS-* and LEG-* decisions).
///
/// [PrivacyNoticeScreen] reads the notice the operator published, in the app's
/// language (or the one the server fell back to, and says so). With a
/// [NoticeState] that shows it again it also offers the tick and the button
/// that record that it was seen: the version sent is the one on the screen, so
/// a notice that changed in between is read again and never recorded unseen.
/// The account rests on the contract, so this is information, not consent.
/// [NoticeBanner] is the prompt at the top of a signed-in field.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../ui/widgets.dart';
import 'account_screen.dart' show accountError;
import 'privacy_notice.dart';
import 'site_client.dart';

/// The prompt that shows an account the notice again (outdated or missing),
/// with the way to read it and confirm.
class NoticeBanner extends StatelessWidget {
  const NoticeBanner({required this.state, required this.onOpen, super.key});

  final NoticeState state;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final text = state.status == 'outdated'
        ? s.t('privacy.intro_outdated', {
            'old': state.version ?? '',
            'version': state.currentVersion,
          })
        : s.t('privacy.intro_missing', {'version': state.currentVersion});
    return Notice(
      text,
      kind: NoticeKind.warning,
      key: const Key('notice-banner'),
      action: TextButton(
        key: const Key('notice-open'),
        onPressed: onOpen,
        child: Text(s.t('privacy.read_and_confirm')),
      ),
    );
  }
}

class PrivacyNoticeScreen extends StatefulWidget {
  const PrivacyNoticeScreen({
    required this.session,
    this.again,
    this.onShown,
    this.onAcknowledged,
    super.key,
  });

  final SiteSession session;

  /// Shows the notice again: the tick and the button (null: only reads).
  final NoticeState? again;

  /// Told the version of the notice the person has in front of them.
  final void Function(String version)? onShown;

  /// Told when it is recorded that the notice was seen.
  final void Function(NoticeState state)? onAcknowledged;

  @override
  State<PrivacyNoticeScreen> createState() => _PrivacyNoticeScreenState();
}

class _PrivacyNoticeScreenState extends State<PrivacyNoticeScreen> {
  late final PrivacyApi _api = PrivacyApi(widget.session);
  PrivacyNotice? _notice;
  bool _loaded = false;
  bool _ticked = false;
  bool _busy = false;
  bool _done = false;
  String? _error;
  String? _info;

  @override
  void initState() {
    super.initState();
    // The language is read from the context, which is not ready in initState.
    WidgetsBinding.instance.addPostFrameCallback((_) => unawaited(_load()));
  }

  Future<void> _load() async {
    final s = context.s;
    try {
      final n = await _api.notice(s.code);
      if (!mounted) return;
      setState(() {
        _notice = n;
        _loaded = true;
      });
      if (n != null) widget.onShown?.call(n.version);
    } on SiteException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = accountError(s, e);
        _loaded = true;
      });
    }
  }

  Future<void> _confirm() async {
    final s = context.s;
    final n = _notice;
    if (n == null || _busy) return;
    if (!_ticked) {
      setState(() => _error = s.t('privacy.tick_first'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    try {
      final state = await _api.acknowledge(n.version);
      if (!mounted) return;
      setState(() {
        _done = true;
        _info = s.t('privacy.done');
      });
      widget.onAcknowledged?.call(state);
    } on SiteException catch (e) {
      if (!mounted) return;
      if (e.code == 'notice_version_changed') {
        // Read the new one before confirming it.
        setState(() {
          _ticked = false;
          _loaded = false;
          _notice = null;
          _error = s.t('privacy.changed');
        });
        await _load();
      } else {
        setState(() => _error = accountError(s, e));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final n = _notice;
    final asks = widget.again != null && !_done;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('privacy.title'))),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // Outside the list: a refusal stays in view wherever the
                // person has scrolled to (the tick and the button are below
                // the text).
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Notice(
                      _error!,
                      kind: NoticeKind.error,
                      key: const Key('privacy-error'),
                    ),
                  ),
                if (_info != null)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Notice(
                      _info!,
                      kind: NoticeKind.ok,
                      key: const Key('privacy-ok'),
                    ),
                  ),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (n == null)
                        Notice(
                          s.t('privacy.none'),
                          key: const Key('privacy-none'),
                        )
                      else ...[
                        Text(
                          s.t('privacy.version', {'version': n.version}),
                          key: const Key('privacy-version'),
                          style: TextStyle(color: Theme.of(context).hintColor),
                        ),
                        if (n.fallback)
                          Padding(
                            padding: const EdgeInsets.only(top: 8),
                            child: Notice(
                              s.t('privacy.lang_fallback', {
                                'requested': s.tOr(
                                  'settings.lang_${n.requestedLang}',
                                  n.requestedLang,
                                ),
                                'shown': s.tOr(
                                  'settings.lang_${n.lang}',
                                  n.lang,
                                ),
                              }),
                              key: const Key('privacy-fallback'),
                            ),
                          ),
                        const SizedBox(height: 12),
                        MarkdownText(
                          n.markdown,
                          key: const Key('privacy-text'),
                        ),
                        if (asks) ...[
                          const Divider(height: 32),
                          CheckboxListTile(
                            key: const Key('privacy-tick'),
                            contentPadding: EdgeInsets.zero,
                            controlAffinity: ListTileControlAffinity.leading,
                            value: _ticked,
                            onChanged: (v) =>
                                setState(() => _ticked = v ?? false),
                            title: Text(s.t('privacy.accept')),
                          ),
                          const SizedBox(height: 8),
                          FilledButton(
                            key: const Key('privacy-agree'),
                            onPressed: _busy ? null : _confirm,
                            child: Text(s.t('privacy.confirm')),
                          ),
                        ],
                      ],
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

/// The small subset of Markdown the privacy notice templates use, as plain
/// text widgets: headings, paragraphs, lists, quotes, rules, code, tables
/// (one row per line), with the inline marks dropped and a link's address
/// written after its words. Nothing in the text is ever opened or run.
class MarkdownText extends StatelessWidget {
  const MarkdownText(this.source, {super.key});

  final String source;

  static final _heading = RegExp(r'^(#{1,6})\s+(.*?)\s*#*\s*$');
  static final _bullet = RegExp(r'^\s*(?:[-*+]|\d+[.)])\s+(.*)$');
  static final _rule = RegExp(r'^\s*(?:-{3,}|\*{3,}|_{3,})\s*$');
  static final _tableRule = RegExp(
    r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$',
  );
  static final _link = RegExp(r'\[([^\]]*)\]\(([^)\s]*)[^)]*\)');
  static final _marks = RegExp(
    r'(\*\*|__|`|(?<![A-Za-z0-9])[*_](?=\S)|(?<=\S)[*_](?![A-Za-z0-9]))',
  );

  /// [t] without its inline marks.
  static String plain(String t) => t
      .replaceAllMapped(_link, (m) {
        final text = m[1]!, url = m[2]!;
        return url.isEmpty || text == url ? text : '$text ($url)';
      })
      .replaceAll(_marks, '');

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context).textTheme;
    final out = <Widget>[];
    final paragraph = <String>[];
    var fenced = false;
    final code = <String>[];

    void flush() {
      if (paragraph.isEmpty) return;
      out.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Text(plain(paragraph.join(' ')), style: theme.bodyMedium),
        ),
      );
      paragraph.clear();
    }

    for (final raw in source.replaceAll('\r\n', '\n').split('\n')) {
      final line = raw.trimRight();
      if (line.trimLeft().startsWith('```')) {
        flush();
        if (fenced && code.isNotEmpty) {
          out.add(
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                code.join('\n'),
                style: theme.bodyMedium?.copyWith(fontFamily: 'monospace'),
              ),
            ),
          );
          code.clear();
        }
        fenced = !fenced;
        continue;
      }
      if (fenced) {
        code.add(line);
        continue;
      }
      if (line.trim().isEmpty) {
        flush();
        continue;
      }
      final h = _heading.firstMatch(line);
      if (h != null) {
        flush();
        final level = h[1]!.length;
        out.add(
          Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 6),
            child: Text(
              plain(h[2]!),
              style: (level <= 1
                  ? theme.titleLarge
                  : level == 2
                  ? theme.titleMedium
                  : theme.titleSmall),
            ),
          ),
        );
        continue;
      }
      if (_rule.hasMatch(line)) {
        flush();
        out.add(const Divider());
        continue;
      }
      final b = _bullet.firstMatch(line);
      if (b != null) {
        flush();
        out.add(
          Padding(
            padding: const EdgeInsets.only(left: 8, bottom: 4),
            child: Text('•  ${plain(b[1]!)}', style: theme.bodyMedium),
          ),
        );
        continue;
      }
      if (line.trimLeft().startsWith('|')) {
        flush();
        if (_tableRule.hasMatch(line)) continue;
        final cells = [
          for (final c in line.trim().split('|'))
            if (c.trim().isNotEmpty) plain(c.trim()),
        ];
        out.add(
          Padding(
            padding: const EdgeInsets.only(left: 8, bottom: 4),
            child: Text(cells.join('  ·  '), style: theme.bodyMedium),
          ),
        );
        continue;
      }
      if (line.trimLeft().startsWith('>')) {
        flush();
        out.add(
          Padding(
            padding: const EdgeInsets.only(left: 12, bottom: 8),
            child: Text(
              plain(line.trimLeft().substring(1).trim()),
              style: theme.bodyMedium?.copyWith(fontStyle: FontStyle.italic),
            ),
          ),
        );
        continue;
      }
      paragraph.add(line.trim());
    }
    flush();
    if (code.isNotEmpty) {
      out.add(Text(code.join('\n'), style: theme.bodyMedium));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: out);
  }
}
