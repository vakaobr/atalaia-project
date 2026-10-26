// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Small pieces the screens share: notices, the admin PIN prompt, a
/// confirmation, a team's colour dot.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app.dart';
import '../l10n/strings.dart';
import 'theme.dart';

enum NoticeKind { info, warning, error, ok }

class Notice extends StatelessWidget {
  const Notice(
    this.text, {
    this.kind = NoticeKind.info,
    this.action,
    super.key,
  });

  final String text;
  final NoticeKind kind;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (icon, color) = switch (kind) {
      NoticeKind.info => (Icons.info_outline, scheme.primary),
      NoticeKind.warning => (Icons.warning_amber, AtalaiaColors.warn),
      NoticeKind.error => (Icons.error_outline, scheme.error),
      NoticeKind.ok => (Icons.check_circle_outline, AtalaiaColors.ok),
    };
    return Card(
      color: Color.alphaBlend(
        color.withValues(alpha: 0.14),
        scheme.surfaceContainer,
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(text),
                  if (action != null) ...[const SizedBox(height: 8), action!],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(4, 20, 4, 8),
    child: Text(
      text,
      style: Theme.of(context).textTheme.titleMedium?.copyWith(
        color: Theme.of(context).colorScheme.primary,
        fontWeight: FontWeight.w600,
      ),
    ),
  );
}

class TeamDot extends StatelessWidget {
  const TeamDot(this.team, {this.size = 16, super.key});
  final String? team;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      color: AtalaiaColors.team(team),
      shape: BoxShape.circle,
      border: Border.all(color: Colors.white24),
    ),
  );
}

/// Asks for a yes or no.
Future<bool> confirm(
  BuildContext context, {
  required String title,
  String? body,
  required String yes,
}) async {
  final s = context.s;
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: body == null ? null : Text(body),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(c, false),
          child: Text(s.t('common.cancel')),
        ),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(yes)),
      ],
    ),
  );
  return ok ?? false;
}

/// The admin PIN, if one is set (settings): true when it is right or there
/// is none.
Future<bool> askPin(BuildContext context) async {
  final settings = AppScope.read(context).settings;
  if (!settings.hasPin) return true;
  final s = context.s;
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => _PinDialog(
      title: s.t('pin.title'),
      check: settings.checkPin,
      wrong: s.t('pin.wrong'),
      cancel: s.t('common.cancel'),
      ok: s.t('common.ok'),
    ),
  );
  return ok ?? false;
}

class _PinDialog extends StatefulWidget {
  const _PinDialog({
    required this.title,
    required this.check,
    required this.wrong,
    required this.cancel,
    required this.ok,
  });

  final String title;
  final bool Function(String pin) check;
  final String wrong;
  final String cancel;
  final String ok;

  @override
  State<_PinDialog> createState() => _PinDialogState();
}

class _PinDialogState extends State<_PinDialog> {
  final _pin = TextEditingController();
  String? _error;

  void _submit() {
    if (widget.check(_pin.text)) {
      Navigator.pop(context, true);
    } else {
      setState(() => _error = widget.wrong);
      _pin.clear();
    }
  }

  @override
  void dispose() {
    _pin.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: TextField(
      key: const Key('pin-field'),
      controller: _pin,
      autofocus: true,
      obscureText: true,
      keyboardType: TextInputType.number,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      maxLength: 8,
      decoration: InputDecoration(errorText: _error),
      onSubmitted: (_) => _submit(),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context, false),
        child: Text(widget.cancel),
      ),
      FilledButton(onPressed: _submit, child: Text(widget.ok)),
    ],
  );
}

/// A button of [promptText]: its label, what the dialog returns for the
/// text typed, and whether it is the main one.
typedef PromptAction = (String label, String? Function(String text), bool);

/// A dialog with one text field; returns what the chosen action makes of
/// the text (null when dismissed). The dialog owns its text controller, so
/// nothing is used after it is disposed while the dialog animates out.
Future<String?> promptText(
  BuildContext context, {
  required String title,
  String? body,
  Key? fieldKey,
  String? label,
  String? helper,
  bool obscure = false,
  bool monospace = false,
  int? maxLength,
  int maxLines = 1,
  TextInputType? keyboard,
  List<TextInputFormatter>? formatters,
  required List<PromptAction> actions,
}) => showDialog<String>(
  context: context,
  builder: (c) => _TextPrompt(
    title: title,
    body: body,
    fieldKey: fieldKey,
    label: label,
    helper: helper,
    obscure: obscure,
    monospace: monospace,
    maxLength: maxLength,
    maxLines: maxLines,
    keyboard: keyboard,
    formatters: formatters,
    actions: actions,
  ),
);

class _TextPrompt extends StatefulWidget {
  const _TextPrompt({
    required this.title,
    required this.body,
    required this.fieldKey,
    required this.label,
    required this.helper,
    required this.obscure,
    required this.monospace,
    required this.maxLength,
    required this.maxLines,
    required this.keyboard,
    required this.formatters,
    required this.actions,
  });

  final String title;
  final String? body;
  final Key? fieldKey;
  final String? label;
  final String? helper;
  final bool obscure;
  final bool monospace;
  final int? maxLength;
  final int maxLines;
  final TextInputType? keyboard;
  final List<TextInputFormatter>? formatters;
  final List<PromptAction> actions;

  @override
  State<_TextPrompt> createState() => _TextPromptState();
}

class _TextPromptState extends State<_TextPrompt> {
  final _ctl = TextEditingController();

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (widget.body != null) ...[
          Text(widget.body!),
          const SizedBox(height: 12),
        ],
        TextField(
          key: widget.fieldKey,
          controller: _ctl,
          autofocus: true,
          obscureText: widget.obscure,
          maxLength: widget.maxLength,
          maxLines: widget.obscure ? 1 : widget.maxLines,
          keyboardType: widget.keyboard,
          inputFormatters: widget.formatters,
          style: widget.monospace
              ? const TextStyle(fontFamily: 'monospace')
              : null,
          decoration: InputDecoration(
            labelText: widget.label,
            helperText: widget.helper,
            helperMaxLines: 3,
          ),
        ),
      ],
    ),
    actions: [
      for (final (label, result, primary) in widget.actions)
        primary
            ? FilledButton(
                onPressed: () => Navigator.pop(context, result(_ctl.text)),
                child: Text(label),
              )
            : TextButton(
                onPressed: () => Navigator.pop(context, result(_ctl.text)),
                child: Text(label),
              ),
    ],
  );
}

void showMessage(BuildContext context, String text) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

/// A text field for an address the person types or edits (a console's, a
/// controller's, a site's), often prefilled with the last one used.
///
/// - A clear button (an x) shows while there is text; it empties the field
///   and keeps the focus, so the new address can be typed at once.
/// - On iOS the first focus selects the whole text, so typing replaces it:
///   a tap in a URL there puts the cursor at the word's edge (a URL is one
///   word), which makes a prefilled address awkward to edit. Later taps
///   place the cursor as usual. Android puts the cursor where the finger is,
///   so it keeps that.
class AddressField extends StatefulWidget {
  const AddressField({
    required this.controller,
    required this.label,
    this.hint,
    this.fieldKey,
    this.clearKey,
    this.onSubmitted,
    super.key,
  });

  final TextEditingController controller;
  final String label;
  final String? hint;

  /// The key of the text field itself (the tests type into it).
  final Key? fieldKey;

  /// The key of the clear button.
  final Key? clearKey;
  final ValueChanged<String>? onSubmitted;

  @override
  State<AddressField> createState() => _AddressFieldState();
}

class _AddressFieldState extends State<AddressField> {
  final _focus = FocusNode();
  bool _focusedOnce = false;

  @override
  void initState() {
    super.initState();
    _focus.addListener(_onFocus);
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  void _onFocus() {
    if (!_focus.hasFocus || _focusedOnce) return;
    _focusedOnce = true;
    if (defaultTargetPlatform != TargetPlatform.iOS) return;
    // After the tap's own selection, which would otherwise win.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final c = widget.controller;
      if (!mounted || !_focus.hasFocus || c.text.isEmpty) return;
      c.selection = TextSelection(baseOffset: 0, extentOffset: c.text.length);
    });
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) => TextField(
      key: widget.fieldKey,
      controller: widget.controller,
      focusNode: _focus,
      keyboardType: TextInputType.url,
      autocorrect: false,
      enableSuggestions: false,
      decoration: InputDecoration(
        labelText: widget.label,
        hintText: widget.hint,
        suffixIcon: widget.controller.text.isEmpty
            ? null
            : IconButton(
                key: widget.clearKey,
                tooltip: context.s.t('common.clear'),
                icon: const Icon(Icons.clear),
                onPressed: () {
                  widget.controller.clear();
                  _focus.requestFocus();
                },
              ),
      ),
      onSubmitted: widget.onSubmitted,
    ),
  );
}
