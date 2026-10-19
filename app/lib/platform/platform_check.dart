// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Which platform the app runs on, and what that allows (ADR-P3-10): the
/// prop and controller roles are Android only; iOS gets the player, marshal
/// and GM roles. Based on [defaultTargetPlatform], so widget tests can
/// pretend to be either (debugDefaultTargetPlatformOverride).
library;

import 'package:flutter/foundation.dart';

bool get isAndroid => defaultTargetPlatform == TargetPlatform.android;

bool get isIOS => defaultTargetPlatform == TargetPlatform.iOS;

/// The prop role needs kiosk mode, background NFC, USB-OTG and the core:
/// Android only (ADR-P3-10).
bool get propRoleAvailable => !kIsWeb && isAndroid;
