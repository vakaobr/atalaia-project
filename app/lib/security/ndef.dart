// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// One NDEF MIME record in an NFC Forum Type 2 tag's user memory, as used by
/// join cards (protocol/join.md, `application/vnd.atalaia.join`) and player
/// tags (protocol/nfc-tag.md, `application/vnd.atalaia.tag`). Mirrors
/// `join.to_ndef_tag` / `join.from_ndef_tag` in the simulator and
/// `core/src/join.c`.
library;

import 'dart:convert';
import 'dart:typed_data';

/// One NDEF record: MB and ME set, TNF 2 (MIME), short when under 256 bytes.
Uint8List ndefMimeRecord(List<int> payload, String mimeType) {
  final type = ascii.encode(mimeType);
  final short = payload.length < 256;
  final out = BytesBuilder();
  out.addByte(0x80 | 0x40 | (short ? 0x10 : 0) | 0x02);
  out.addByte(type.length);
  if (short) {
    out.addByte(payload.length);
  } else {
    out.add([
      (payload.length >> 24) & 0xff,
      (payload.length >> 16) & 0xff,
      (payload.length >> 8) & 0xff,
      payload.length & 0xff,
    ]);
  }
  out.add(type);
  out.add(payload);
  return out.toBytes();
}

/// A Type 2 tag's user memory from page 4: the NDEF message TLV holding one
/// record of [mimeType], then the terminator TLV.
Uint8List type2Memory(List<int> payload, String mimeType) {
  final message = ndefMimeRecord(payload, mimeType);
  final out = BytesBuilder()..addByte(0x03);
  if (message.length < 0xff) {
    out.addByte(message.length);
  } else {
    out.add([0xff, (message.length >> 8) & 0xff, message.length & 0xff]);
  }
  out.add(message);
  out.addByte(0xfe);
  return out.toBytes();
}

/// The payload of the first [mimeType] record in a Type 2 tag's user memory,
/// or null. NULL TLVs and other TLVs before the NDEF message are skipped.
Uint8List? payloadFromType2Memory(List<int> mem, String mimeType) {
  var i = 0;
  while (i < mem.length) {
    final t = mem[i++];
    if (t == 0x00) continue;
    if (t == 0xfe || i >= mem.length) return null;
    var length = mem[i++];
    if (length == 0xff) {
      if (mem.length - i < 2) return null;
      length = (mem[i] << 8) | mem[i + 1];
      i += 2;
    }
    if (length > mem.length - i) return null;
    if (t == 0x03) {
      return _findRecord(mem.sublist(i, i + length), ascii.encode(mimeType));
    }
    i += length;
  }
  return null;
}

Uint8List? _findRecord(List<int> m, List<int> type) {
  var i = 0;
  while (i < m.length) {
    final hdr = m[i++];
    if (hdr & 0x20 != 0 || i >= m.length) return null;
    final tlen = m[i++];
    int plen;
    if (hdr & 0x10 != 0) {
      if (i >= m.length) return null;
      plen = m[i++];
    } else {
      if (m.length - i < 4) return null;
      plen = (m[i] << 24) | (m[i + 1] << 16) | (m[i + 2] << 8) | m[i + 3];
      i += 4;
    }
    var idlen = 0;
    if (hdr & 0x08 != 0) {
      if (i >= m.length) return null;
      idlen = m[i++];
    }
    if (tlen > m.length - i) return null;
    final rtype = m.sublist(i, i + tlen);
    i += tlen;
    if (idlen > m.length - i) return null;
    i += idlen;
    if (plen > m.length - i) return null;
    if (hdr & 0x07 == 0x02 && _same(rtype, type)) {
      return Uint8List.fromList(m.sublist(i, i + plen));
    }
    i += plen;
    if (hdr & 0x40 != 0) return null;
  }
  return null;
}

bool _same(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}
