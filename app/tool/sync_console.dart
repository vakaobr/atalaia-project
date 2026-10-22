// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Copies the GM console (controller/console/src) and the check-in notices
// (controller/templates/checkin-notice-*.md) into the app's assets, so the
// phone controller serves the very files the Pi serves (slice S6 of PE24,
// decision PE24-61). Run from app/ before `flutter test` or `flutter build`
// (app/tool/check.sh and CI do):
//
//     dart tool/sync_console.dart           copy (assets/console/, assets/notices/)
//     dart tool/sync_console.dart --check   only compare; exit 1 on any difference
//
// The copies are never committed (.gitignore): the console is edited in one
// place. test/controller/console_bundle_test.dart checks the copy, and that
// pubspec.yaml lists every folder of it (Flutter's asset folders are not
// recursive). Plain dart:io, no packages: it runs before `pub get`.

import 'dart:io';

const consoleSource = '../controller/console/src';
const noticeSource = '../controller/templates';
const consoleTarget = 'assets/console';
const noticeTarget = 'assets/notices';
const notices = ['checkin-notice-pt.md', 'checkin-notice-en.md'];

/// Every file under [dir], by its path relative to [dir] ('/' separators).
Map<String, File> filesUnder(String dir) {
  final root = Directory(dir);
  if (!root.existsSync()) return {};
  final prefix = root.absolute.path.length + 1;
  return {
    for (final e in root.listSync(recursive: true, followLinks: false))
      if (e is File) e.absolute.path.substring(prefix).replaceAll(r'\', '/'): e,
  };
}

bool sameBytes(File a, File b) {
  final x = a.readAsBytesSync();
  final y = b.readAsBytesSync();
  if (x.length != y.length) return false;
  for (var i = 0; i < x.length; i++) {
    if (x[i] != y[i]) return false;
  }
  return true;
}

/// What differs between the sources and the copies: one line each.
List<String> differences() {
  final out = <String>[];
  final src = filesUnder(consoleSource);
  final dst = filesUnder(consoleTarget);
  if (src.isEmpty) out.add('$consoleSource: not found (run from app/)');
  for (final e in src.entries) {
    final d = dst[e.key];
    if (d == null) {
      out.add('missing: $consoleTarget/${e.key}');
    } else if (!sameBytes(e.value, d)) {
      out.add('differs: $consoleTarget/${e.key}');
    }
  }
  for (final k in dst.keys) {
    if (!src.containsKey(k)) out.add('extra: $consoleTarget/$k');
  }
  for (final n in notices) {
    final s = File('$noticeSource/$n');
    final d = File('$noticeTarget/$n');
    if (!s.existsSync()) {
      out.add('$noticeSource/$n: not found');
    } else if (!d.existsSync()) {
      out.add('missing: $noticeTarget/$n');
    } else if (!sameBytes(s, d)) {
      out.add('differs: $noticeTarget/$n');
    }
  }
  return out;
}

void copy() {
  final target = Directory(consoleTarget);
  if (target.existsSync()) target.deleteSync(recursive: true);
  for (final e in filesUnder(consoleSource).entries) {
    final to = File('$consoleTarget/${e.key}');
    to.parent.createSync(recursive: true);
    e.value.copySync(to.path);
  }
  Directory(noticeTarget).createSync(recursive: true);
  for (final n in notices) {
    File('$noticeSource/$n').copySync('$noticeTarget/$n');
  }
}

void main(List<String> args) {
  final check = args.contains('--check');
  if (!check) {
    if (!Directory(consoleSource).existsSync()) {
      stderr.writeln('sync_console: $consoleSource not found (run from app/)');
      exit(2);
    }
    copy();
  }
  final diff = differences();
  if (diff.isNotEmpty) {
    stderr.writeln('sync_console: the app\'s copy is not the console\'s:');
    diff.forEach(stderr.writeln);
    exit(1);
  }
  final n = filesUnder(consoleTarget).length;
  stdout.writeln(
    'sync_console: $n console files and ${notices.length} notices '
    '${check ? 'match' : 'copied'}',
  );
}
