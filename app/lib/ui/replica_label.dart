// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A replica's QR label: the code the marshal's chrono queue scans to find
/// the replica (`ATL-` and eight characters, `Replica.labelFor`; or the text
/// of the QR tag a marshal registered), drawn big on a screen kept bright, and
/// as PNG images for a small sticker (30 x 30 mm at 300 dpi) or a sheet of
/// them (A4). The QR holds the label text only, nothing about the player.
library;

import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:qr/qr.dart';

import '../app.dart';
import '../l10n/strings.dart';
import '../platform/services.dart';
import 'qr_painter.dart';

/// 30 mm at 300 dpi: one label's side in pixels.
const labelPx = 354;

/// An A4 sheet at 300 dpi.
const sheetWidthPx = 2480;
const sheetHeightPx = 3508;

/// The margin kept free round a sheet's labels: 10 mm.
const sheetMarginPx = 118;

/// Labels across and down a sheet, and so on one page.
const sheetColumns = (sheetWidthPx - 2 * sheetMarginPx) ~/ labelPx;
const sheetRows = (sheetHeightPx - 2 * sheetMarginPx) ~/ labelPx;
const labelsPerSheet = sheetColumns * sheetRows;

/// The QR module matrix of [text] as the label draws it (medium error
/// correction, like [QrCodeView]); null when it is too long for a QR code.
QrImage? labelMatrix(String text) {
  try {
    return QrImage(
      QrCode(
        payload: QrPayload.fromString(text),
        errorCorrectLevel: QrErrorCorrectLevel.medium,
      ),
    );
  } on Object {
    return null;
  }
}

/// The side in pixels of one module in a label of [moduleCount] modules (a
/// quiet zone of two modules on each side included): whole pixels, so every
/// module is sharp.
int labelModulePx(int moduleCount) => 290 ~/ (moduleCount + 4);

/// The top-left corner of the first module in a label, from the label's own.
Offset labelQrOrigin(int moduleCount) {
  final m = labelModulePx(moduleCount);
  final side = (moduleCount + 4) * m;
  return Offset(((labelPx - side) ~/ 2 + 2 * m).toDouble(), 10.0 + 2 * m);
}

void _drawLabel(Canvas canvas, Offset at, String code, {bool guide = false}) {
  canvas.save();
  canvas.translate(at.dx, at.dy);
  const box = Rect.fromLTWH(0, 0, 354, 354);
  canvas.drawRect(box, Paint()..color = const Color(0xFFFFFFFF));
  final img = labelMatrix(code);
  var textTop = 300.0;
  if (img != null) {
    final n = img.moduleCount;
    final m = labelModulePx(n);
    final o = labelQrOrigin(n);
    final dark = Paint()..color = const Color(0xFF000000);
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) {
        if (img.isDark(r, c)) {
          canvas.drawRect(
            Rect.fromLTWH(
              o.dx + c * m,
              o.dy + r * m,
              m.toDouble(),
              m.toDouble(),
            ),
            dark,
          );
        }
      }
    }
    textTop = 10.0 + (n + 4) * m + 4;
  }
  var size = 44.0;
  late ui.Paragraph p;
  while (true) {
    final b =
        ui.ParagraphBuilder(
            ui.ParagraphStyle(
              textAlign: TextAlign.center,
              maxLines: 1,
              ellipsis: '…',
              fontSize: size,
              fontWeight: FontWeight.w700,
            ),
          )
          ..pushStyle(
            ui.TextStyle(
              color: const Color(0xFF000000),
              fontSize: size,
              fontWeight: FontWeight.w700,
            ),
          )
          ..addText(code);
    p = b.build()..layout(const ui.ParagraphConstraints(width: 334));
    if (p.longestLine <= 334 || size <= 14) break;
    size -= 2;
  }
  canvas.drawParagraph(p, Offset(10, math.min(textTop, 354 - p.height - 2)));
  if (guide) {
    // A thin line to cut along, on a sheet.
    canvas.drawRect(
      box.deflate(0.5),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = const Color(0xFFB0B0B0),
    );
  }
  canvas.restore();
}

Future<Uint8List> _png(int w, int h, void Function(Canvas) draw) async {
  final rec = ui.PictureRecorder();
  final canvas = Canvas(rec);
  draw(canvas);
  final image = await rec.endRecording().toImage(w, h);
  try {
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    return data!.buffer.asUint8List();
  } finally {
    image.dispose();
  }
}

/// One label as a PNG of [labelPx] x [labelPx] (30 x 30 mm at 300 dpi).
Future<Uint8List> renderLabelPng(String code) =>
    _png(labelPx, labelPx, (c) => _drawLabel(c, Offset.zero, code));

/// [codes] on A4 pages (300 dpi) of [labelsPerSheet] labels each, in rows,
/// with a thin cutting guide round each label; one PNG per page.
Future<List<Uint8List>> renderLabelSheets(List<String> codes) async {
  final out = <Uint8List>[];
  for (var from = 0; from < codes.length; from += labelsPerSheet) {
    final page = codes.sublist(
      from,
      math.min(codes.length, from + labelsPerSheet),
    );
    final left = (sheetWidthPx - sheetColumns * labelPx) ~/ 2;
    out.add(
      await _png(sheetWidthPx, sheetHeightPx, (c) {
        c.drawRect(
          const Rect.fromLTWH(0, 0, 2480, 3508),
          Paint()..color = const Color(0xFFFFFFFF),
        );
        for (var i = 0; i < page.length; i++) {
          _drawLabel(
            c,
            Offset(
              (left + (i % sheetColumns) * labelPx).toDouble(),
              (sheetMarginPx + (i ~/ sheetColumns) * labelPx).toDouble(),
            ),
            page[i],
            guide: true,
          );
        }
      }),
    );
  }
  return out;
}

String _fileSafe(String code) =>
    code.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');

/// Opens the share sheet with the label of [codes]: one label as a sticker
/// PNG, several as A4 sheets. Tells the user when the phone cannot.
Future<void> shareLabels(BuildContext context, List<String> codes) async {
  final s = context.s;
  final sharer = context.services.share;
  final messenger = ScaffoldMessenger.of(context);
  if (codes.isEmpty) return;
  if (sharer == null || !await sharer.available) {
    messenger.showSnackBar(
      SnackBar(content: Text(s.t('label.share_unavailable'))),
    );
    return;
  }
  final files = <SharedFile>[];
  if (codes.length == 1) {
    files.add(
      SharedFile(
        'atalaia-label-${_fileSafe(codes.single)}.png',
        await renderLabelPng(codes.single),
      ),
    );
  } else {
    final pages = await renderLabelSheets(codes);
    for (var i = 0; i < pages.length; i++) {
      files.add(SharedFile('atalaia-labels-${i + 1}.png', pages[i]));
    }
  }
  final ok = await sharer.sharePng(files, title: s.t('label.share_title'));
  if (!ok) {
    messenger.showSnackBar(SnackBar(content: Text(s.t('label.share_failed'))));
  }
}

/// A big QR code with the label text under it, the screen kept on and as
/// bright as it goes (for a scanner or a phone camera), and the sticker to
/// share or print.
class ReplicaLabelScreen extends StatefulWidget {
  const ReplicaLabelScreen({required this.code, this.subtitle, super.key});

  /// The text the QR holds.
  final String code;

  /// What the replica is, under the code (type and class; never a name).
  final String? subtitle;

  @override
  State<ReplicaLabelScreen> createState() => _ReplicaLabelScreenState();
}

class _ReplicaLabelScreenState extends State<ReplicaLabelScreen> {
  DeviceServices? _device;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_device != null) return;
    final d = _device = context.services.device;
    unawaited(d.keepScreenOn(true));
    unawaited(d.setBrightness(1.0));
  }

  @override
  void dispose() {
    final d = _device;
    if (d != null) {
      unawaited(d.setBrightness(null));
      unawaited(d.keepScreenOn(false));
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.s;
    final side = math.min(MediaQuery.sizeOf(context).shortestSide - 48, 360.0);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('label.title'))),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Center(
            child: Container(
              key: const Key('label-qr'),
              color: Colors.white,
              child: QrCodeView(data: widget.code, size: side),
            ),
          ),
          const SizedBox(height: 16),
          SelectableText(
            widget.code,
            key: const Key('label-code'),
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
              fontWeight: FontWeight.w700,
              letterSpacing: 2,
            ),
          ),
          if (widget.subtitle != null)
            Text(widget.subtitle!, textAlign: TextAlign.center),
          const SizedBox(height: 16),
          Text(s.t('label.hint')),
          const SizedBox(height: 16),
          FilledButton.icon(
            key: const Key('label-share'),
            icon: const Icon(Icons.ios_share),
            label: Text(s.t('label.share')),
            onPressed: () => shareLabels(context, [widget.code]),
          ),
        ],
      ),
    );
  }
}

/// Pushes the label screen for [code].
Future<void> showLabel(BuildContext context, String code, {String? subtitle}) =>
    Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => ReplicaLabelScreen(code: code, subtitle: subtitle),
      ),
    );
