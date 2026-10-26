// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's version: the one in pubspec.yaml and the Pi controller's
/// `__version__` (test/version_test.dart keeps all three equal). Settings >
/// About shows it, a phone controller's /healthz and /whoami give it, and a
/// prop reports `app-<version>` as its firmware version.
library;

const appVersion = '0.3.0';
