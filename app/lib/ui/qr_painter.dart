// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A QR code drawn from the `qr` package's module matrix (the template
/// widget qr_code, and the app's own join and scoreboard codes).
library;

import 'package:flutter/widgets.dart';
import 'package:qr/qr.dart';

class QrCodeView extends StatelessWidget {
  const QrCodeView({
    required this.data,
    this.size = 120,
    this.dark = const Color(0xFF101418),
    this.light = const Color(0xFFFFFFFF),
    super.key,
  });

  final String data;
  final double size;
  final Color dark;
  final Color light;

  @override
  Widget build(BuildContext context) {
    QrImage? image;
    try {
      image = QrImage(
        QrCode(
          payload: QrPayload.fromString(data),
          errorCorrectLevel: QrErrorCorrectLevel.medium,
        ),
      );
    } on Object {
      image = null; // too long for a QR code: an empty square
    }
    return SizedBox.square(
      dimension: size,
      child: CustomPaint(painter: _QrPainter(image, dark, light)),
    );
  }
}

class _QrPainter extends CustomPainter {
  _QrPainter(this.image, this.dark, this.light);

  final QrImage? image;
  final Color dark;
  final Color light;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = light);
    final img = image;
    if (img == null) return;
    // A quiet zone of two modules on each side.
    final n = img.moduleCount + 4;
    final m = size.shortestSide / n;
    final paint = Paint()..color = dark;
    for (var r = 0; r < img.moduleCount; r++) {
      for (var c = 0; c < img.moduleCount; c++) {
        if (img.isDark(r, c)) {
          canvas.drawRect(
            Rect.fromLTWH((c + 2) * m, (r + 2) * m, m + 0.01, m + 0.01),
            paint,
          );
        }
      }
    }
  }

  @override
  bool shouldRepaint(_QrPainter old) =>
      old.image != image || old.dark != dark || old.light != light;
}
