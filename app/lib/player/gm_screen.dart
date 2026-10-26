// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The GM role (ADR-P3-10): the field controller's GM console
/// (controller/console/), the same web app as on a laptop, in a web view.
/// The console asks for the GM or read code itself.
library;

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../ui/widgets.dart';

/// The console's address from what someone typed: a host, host:port or a
/// full URL; the controller's default port 8080 and /console/.
Uri? consoleUrl(String text) {
  var t = text.trim();
  if (t.isEmpty) return null;
  if (!t.contains('://')) t = 'http://$t';
  final Uri u;
  try {
    u = Uri.parse(t);
  } on FormatException {
    return null;
  }
  if (u.host.isEmpty || (u.scheme != 'http' && u.scheme != 'https')) {
    return null;
  }
  return Uri(
    scheme: u.scheme,
    host: u.host,
    port: u.hasPort ? u.port : 8080,
    path: u.path.isEmpty || u.path == '/' ? '/console/' : u.path,
  );
}

class GmScreen extends StatefulWidget {
  const GmScreen({super.key});

  @override
  State<GmScreen> createState() => _GmScreenState();
}

class _GmScreenState extends State<GmScreen> {
  late final TextEditingController _url;
  Uri? _open;
  bool _bad = false;

  @override
  void initState() {
    super.initState();
    final st = AppScope.read(context).settings;
    _url = TextEditingController(
      text: st.consoleUrl ?? _fromController(st.controllerUrl) ?? '',
    );
  }

  static String? _fromController(String? base) =>
      base == null ? null : consoleUrl(base)?.toString();

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    final u = consoleUrl(_url.text);
    if (u == null) {
      setState(() => _bad = true);
      return;
    }
    await AppScope.read(context).update((x) => x.consoleUrl = u.toString());
    setState(() {
      _bad = false;
      _open = u;
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final open = _open;
    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('role.gm')),
        actions: [
          if (open != null)
            IconButton(
              tooltip: s.t('gm.change'),
              icon: const Icon(Icons.edit),
              onPressed: () => setState(() => _open = null),
            ),
        ],
      ),
      body: open != null
          ? (context.services.consoleView ?? _webView)(context, open)
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Text(s.t('gm.intro')),
                const SizedBox(height: 12),
                if (_bad) Notice(s.t('gm.bad_url'), kind: NoticeKind.error),
                AddressField(
                  fieldKey: const Key('gm-url'),
                  clearKey: const Key('gm-url-clear'),
                  controller: _url,
                  label: s.t('gm.address'),
                  hint: 'http://192.168.4.1:8080/console/',
                  onSubmitted: (_) => _go(),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  key: const Key('gm-open'),
                  onPressed: _go,
                  child: Text(s.t('gm.open')),
                ),
              ],
            ),
    );
  }

  static Widget _webView(BuildContext context, Uri url) =>
      _ConsoleWebView(url: url);
}

class _ConsoleWebView extends StatefulWidget {
  const _ConsoleWebView({required this.url});
  final Uri url;

  @override
  State<_ConsoleWebView> createState() => _ConsoleWebViewState();
}

class _ConsoleWebViewState extends State<_ConsoleWebView> {
  late final WebViewController _controller = WebViewController()
    ..setJavaScriptMode(JavaScriptMode.unrestricted)
    ..loadRequest(widget.url);

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _controller);
}
