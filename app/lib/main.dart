// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's entry point. Plan phase C has no user interface yet (that is
/// plan phase D): this screen only shows that the APK carries a core the app
/// can load. It reads the core's version and nothing else; nodes run in game
/// loop isolates (lib/core/), never on this isolate.
library;

import 'package:flutter/material.dart';

import 'core/node_runner.dart';

void main() => runApp(AtalaiaApp(runner: createNodeRunner()));

class AtalaiaApp extends StatelessWidget {
  const AtalaiaApp({required this.runner, super.key});

  final NodeRunner runner;

  @override
  Widget build(BuildContext context) {
    final version = runner.coreVersion;
    return MaterialApp(
      title: 'Atalaia',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFE8B341),
          brightness: Brightness.dark,
        ),
      ),
      home: Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Atalaia', style: Theme.of(context).textTheme.headlineLarge),
              const SizedBox(height: 16),
              Text(
                version == null
                    ? 'No game core on this device'
                    : 'Core $version',
              ),
            ],
          ),
        ),
      ),
    );
  }
}
