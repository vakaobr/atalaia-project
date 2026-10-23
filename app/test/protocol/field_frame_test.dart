// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field frames, pair frames, field cards and firmware releases of the
// phone controller's boxes (slice S7c of PE24) against the shared vectors
// the C and Python codecs check: protocol/vectors/field_frame.json,
// pairing.json, field_card.json and firmware.json.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/protocol/field_card.dart';
import 'package:atalaia_app/protocol/field_frame.dart';
import 'package:atalaia_app/protocol/firmware_release.dart';
import 'package:atalaia_app/protocol/pair_frame.dart';
import 'package:atalaia_app/security/aes_ccm.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/cpace.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

Uint8List h(Object? s) => hexDecode(s! as String);

/// A vector's fields with their bytes as bytes.
Map<String, Object?> ffFields(Map<String, dynamic> v) => {
  for (final e in (v['fields'] as Map).entries)
    '${e.key}': const ['device_id', 'token', 'chunk', 'key_tag'].contains(e.key)
        ? h(e.value)
        : e.value,
};

/// A message with its bytes in hex, to compare with a vector's fields.
Map<String, Object?> plain(Map<String, Object?> m) => {
  for (final e in m.entries)
    e.key: e.value is List<int> ? hexEncode(e.value! as List<int>) : e.value,
};

void main() {
  group('field frames (field_frame.json)', () {
    final v = loadVectors('field_frame.json');
    final key = h(v['field_key']);

    test('HKDF-SHA256: RFC 5869 appendix A', () {
      for (final c in cases(v, 'hkdf_sha256')) {
        expect(
          hexEncode(
            hkdfSha256(
              h(c['ikm']),
              c['length'] as int,
              salt: h(c['salt']),
              info: h(c['info']),
            ),
          ),
          c['okm'],
          reason: c['name'] as String,
        );
      }
      expect(hexEncode(fieldKey(h(v['join_key']))), v['field_key']);
    });

    test('valid bodies and frames, both ways', () {
      for (final c in cases(v, 'valid')) {
        final name = c['name'] as String;
        final fields = ffFields(c);
        expect(hexEncode(encodeFieldBody(fields)), c['body'], reason: name);
        expect(plain(decodeFieldBody(h(c['body']))), c['fields'], reason: name);
        expect(
          hexEncode(sealFieldBody(key, h(c['body']), h(c['nonce']))),
          c['frame'],
          reason: name,
        );
        expect(hexEncode(openFieldFrame(key, h(c['frame']))), c['body']);
      }
      final second = cases(v, 'valid')[1];
      expect(
        hexEncode(openFieldFrame(key, h(v['hop_limit_ignored']))),
        second['body'],
      );
    });

    test('frames and bodies that must be refused', () {
      for (final c in cases(v, 'invalid_frames')) {
        final frame = h(c['frame']);
        final reason = c['reason'] as String;
        if (reason == 'mac') {
          expect(isFieldFrame(frame), isTrue, reason: c['name'] as String);
        } else {
          expect(isFieldFrame(frame), isFalse, reason: c['name'] as String);
        }
        expect(
          () => openFieldFrame(key, frame),
          throwsA(isA<FieldFrameException>()),
          reason: c['name'] as String,
        );
      }
      final bodies = cases(v, 'invalid_bodies');
      expect(bodies, hasLength(37));
      for (final c in bodies) {
        expect(
          () => decodeFieldBody(h(c['body'])),
          throwsA(isA<FieldFrameException>()),
          reason: c['name'] as String,
        );
      }
      final skipped = decodeFieldBody(h(v['optional_key_skipped']));
      expect(skipped['kind'], 'announce');
      expect(skipped.containsKey('20'), isFalse);
    });

    test('invite chunks and their reassembly', () {
      for (final c in cases(v, 'split')) {
        final parts = splitJoin(h(c['payload']));
        expect([for (final p in parts) hexEncode(p)], c['parts']);
        final r = FieldReassembly();
        Uint8List? out;
        for (var i = parts.length - 1; i >= 0; i--) {
          out = r.add({
            'invite_id': 7,
            'token': Uint8List(8),
            'part': i,
            'parts': parts.length,
            'chunk': parts[i],
          });
        }
        expect(hexEncode(out!), c['payload']);
      }
    });

    test("nonces: the sender's pseudonym, boot and count", () {
      final n = (v['nonces'] as Map).cast<String, dynamic>();
      final nkey = fieldNonceKey(h(v['join_key']));
      expect(hexEncode(nkey), n['nonce_key']);
      for (final c in cases(n, 'cases')) {
        expect(
          hexEncode(
            fieldNonce(nkey, h(c['sender']), c['boot'] as int, c['ctr'] as int),
          ),
          c['nonce'],
        );
      }
      final s = (n['source'] as Map).cast<String, dynamic>();
      var stored = s['stored_boot'] as int;
      final src = FieldNonceSource(
        h(v['join_key']),
        h(s['sender']),
        loadBoot: () => stored,
        saveBoot: (b) {
          stored = b;
          return true;
        },
      );
      final got = [hexEncode(src.next()), hexEncode(src.next())];
      src.ctr = 0xffff;
      got
        ..add(hexEncode(src.next()))
        ..add(hexEncode(src.next()));
      expect(got, s['nonces']);
      expect(stored, s['stored_after']);
    });

    test('AES-CCM refuses an altered MIC', () {
      final c = cases(v, 'valid').first;
      final frame = h(c['frame']);
      frame[frame.length - 1] ^= 1;
      expect(
        () => openFieldFrame(key, frame),
        throwsA(isA<FieldFrameException>()),
      );
      expect(
        () => ccmOpen(key, Uint8List(13), Uint8List(4), const []),
        throwsA(isA<CcmException>()),
      );
    });
  });

  group('pairing (pairing.json)', () {
    final v = loadVectors('pairing.json');

    test("CPace: the draft's B.1", () {
      final b = (v['cpace_b1'] as Map).cast<String, dynamic>();
      expect(
        hexEncode(cpaceGeneratorString(h(b['prs']), h(b['ci']), h(b['sid']))),
        b['generator_string'],
      );
      final g = cpaceGenerator(h(b['prs']), h(b['ci']), h(b['sid']));
      expect(hexEncode(g), b['g']);
      final ya = x25519(h(b['ya']), g);
      final yb = x25519(h(b['yb']), g);
      expect(hexEncode(ya), b['Ya']);
      expect(hexEncode(yb), b['Yb']);
      final k = x25519Verified(h(b['ya']), yb);
      expect(hexEncode(k), b['K']);
      expect(hexEncode(x25519Verified(h(b['yb']), ya)), b['K']);
      expect(
        hexEncode(cpaceIskIr(h(b['sid']), k, ya, h(b['ada']), yb, h(b['adb']))),
        b['isk_ir'],
      );
    });

    test('CPace: low-order points abort', () {
      final lo = (v['cpace_low_order'] as Map).cast<String, dynamic>();
      for (final p in cases(lo, 'points')) {
        expect(hexEncode(x25519(h(lo['s']), h(p['u']))), p['q']);
        if ((p['q'] as String).replaceAll('0', '').isEmpty) {
          expect(
            () => x25519Verified(h(lo['s']), h(p['u'])),
            throwsA(isA<CpaceException>()),
          );
        }
      }
    });

    test('the whole run: keys, tags, the sealed key and the frames', () {
      final r = (v['run'] as Map).cast<String, dynamic>();
      final pid = h(r['pair_id']), sid = h(r['sid']);
      expect(hexEncode(pairChannelId(pid)), r['ci']);
      final g = pairGenerator(r['code'] as String, pid, sid);
      expect(hexEncode(g), r['g']);
      final ya = x25519(h(r['ya']), g), yb = x25519(h(r['yb']), g);
      expect(hexEncode(ya), r['Ya']);
      expect(hexEncode(yb), r['Yb']);
      final k = x25519Verified(h(r['ya']), yb);
      expect(hexEncode(k), r['K']);
      final isk = pairIsk(sid, k, ya, yb);
      expect(hexEncode(isk), r['isk']);
      final ks = PairKeys(isk, sid);
      expect(hexEncode(ks.confirmA), r['confirm_a']);
      expect(hexEncode(ks.confirmB), r['confirm_b']);
      expect(hexEncode(ks.seal), r['seal']);
      expect(hexEncode(ks.nonce), r['nonce_key']);
      final nonce = ks.keyNonce(h(r['sender']));
      expect(hexEncode(nonce), r['nonce']);
      expect(hexEncode(ks.tagReply), r['tag_reply']);
      expect(hexEncode(ks.tagKey), r['tag_key']);
      final sealed = sealPairKey(
        ks,
        nonce,
        pid,
        sid,
        h(r['join_key']),
        r['field_name'] as String,
      );
      expect(hexEncode(sealed), r['sealed']);
      final (joinKey, name) = openPairKey(ks, nonce, pid, sid, sealed);
      expect(hexEncode(joinKey), r['join_key']);
      expect(name, r['field_name']);
      expect(
        hexEncode(fieldFingerprintBytes(h(r['join_key']))),
        r['fingerprint'],
      );
      expect(
        hexEncode(ks.tagDone('adopted', h(r['fingerprint']))),
        r['tag_done'],
      );
      final frames = (r['frames'] as Map).cast<String, String>();
      for (final e in frames.entries) {
        final msg = decodePairFrame(h(e.value));
        expect(msg['kind'], e.key);
        expect(hexEncode(encodePairFrame(msg)), e.value, reason: e.key);
      }
      // A box showing another code: its REPLY's confirmation does not match.
      final w = (r['wrong_code'] as Map).cast<String, dynamic>();
      final ybw = x25519(
        h(r['yb']),
        pairGenerator(w['code'] as String, pid, sid),
      );
      expect(hexEncode(ybw), w['Yb']);
      final kw = x25519Verified(h(r['ya']), ybw);
      final kws = PairKeys(pairIsk(sid, kw, ya, ybw), sid);
      expect(hexEncode(kws.tagReply), isNot(r['tag_reply']));
      final mine = PairKeys(pairIsk(sid, k, ya, yb), sid);
      expect(hexEncode(mine.tagReply), r['tag_reply']);
    });

    test('generators with a high r', () {
      for (final c in cases(v, 'generators')) {
        expect(
          hexEncode(
            pairGenerator(c['code'] as String, h(c['pair_id']), h(c['sid'])),
          ),
          c['g'],
        );
      }
    });

    test('bodies and frames that must be refused', () {
      final inv = (v['invalid'] as Map).cast<String, dynamic>();
      for (final c in cases(inv, 'bodies')) {
        expect(
          () => decodePairBody(h(c['body'])),
          throwsA(isA<PairFrameException>()),
          reason: c['name'] as String,
        );
      }
      for (final c in cases(inv, 'frames')) {
        expect(
          () => decodePairFrame(h(c['frame'])),
          throwsA(isA<PairFrameException>()),
          reason: c['name'] as String,
        );
      }
      expect(pairCodeOk('042137'), isTrue);
      expect(pairCodeOk('42137'), isFalse);
      expect(pairCodeOk('04213a'), isFalse);
    });
  });

  group('field cards (field_card.json)', () {
    final v = loadVectors('field_card.json');

    test('valid cards: key, name, fingerprint and the tag memory', () {
      expect(v['ndef_type'], fieldCardNdefType);
      for (final c in cases(v, 'valid')) {
        final card = decodeFieldCard(h(c['payload']));
        expect(hexEncode(card.joinKey), c['join_key']);
        expect(card.name, c['field_name']);
        expect(card.fingerprint, c['fingerprint']);
        expect(
          hexEncode(
            encodeFieldCard(h(c['join_key']), c['field_name'] as String),
          ),
          c['payload'],
        );
        expect(hexEncode(fieldCardTag(h(c['payload']))), c['ndef_tag']);
      }
    });

    test('invalid cards fail with their reason', () {
      for (final c in cases(v, 'invalid')) {
        expect(
          () => decodeFieldCard(h(c['payload'])),
          throwsA(
            isA<FieldCardException>().having(
              (e) => e.reason,
              'reason',
              c['reason'],
            ),
          ),
          reason: c['name'] as String,
        );
      }
    });

    test('a field name made fit for a card', () {
      expect(cleanFieldName(' Campo "da" Atalaia\\ '), 'Campo da Atalaia');
      expect(cleanFieldName('a\u0007b\nc'), 'abc');
      final long = cleanFieldName('ç' * 40);
      expect(utf8.encode(long).length, 48);
    });
  });

  group('firmware releases (firmware.json)', () {
    final v = loadVectors('firmware.json');
    final trusted = [((v['signing_key'] as Map)['public_key_b64']) as String];

    test('releases: the manifest, the text and the signer', () async {
      for (final c in cases(v, 'releases')) {
        final name = c['name'] as String;
        expect(
          utf8.decode(
            releaseManifest(
              c['platform'] as String,
              c['version'] as String,
              c['size'] as int,
              c['sha256'] as String,
            ),
          ),
          c['manifest'],
          reason: name,
        );
        if (c['valid'] == true) {
          expect(
            utf8.decode(
              releaseText(
                c['platform'] as String,
                c['version'] as String,
                c['size'] as int,
                c['sha256'] as String,
                c['signature'] as String,
              ),
            ),
            c['release_text'],
            reason: name,
          );
        }
        final signer = await releaseSigner(
          trusted,
          c['platform'] as String,
          c['version'] as String,
          c['size'] as int,
          c['sha256'] as String,
          c['signature'] as String,
        );
        expect(signer != null, c['valid'], reason: name);
        if (signer != null) expect(signer, releaseKeyId(trusted.single));
      }
    });

    test('versions: their order, equal ones, valid and invalid forms', () {
      final vs = (v['versions'] as Map).cast<String, dynamic>();
      for (final list in ['semver_order', 'semver_core_order', 'order']) {
        final order = (vs[list] as List).cast<String>();
        for (var i = 0; i + 1 < order.length; i++) {
          expect(compareVersions(order[i], order[i + 1]), -1, reason: order[i]);
          expect(compareVersions(order[i + 1], order[i]), 1);
        }
      }
      for (final pair in (vs['equal'] as List).cast<List<dynamic>>()) {
        expect(compareVersions(pair[0] as String, pair[1] as String), 0);
      }
      for (final ok in (vs['valid'] as List).cast<String>()) {
        expect(versionKey(ok), isNotNull, reason: ok);
        expect(firmwareVersionKey(ok), versionKey(ok), reason: ok);
      }
      // Build metadata (decision FV-2): a firmware's, ignored; a package's
      // version refuses it.
      for (final meta in (vs['build_metadata'] as List).cast<String>()) {
        expect(firmwareVersionKey(meta), isNotNull, reason: meta);
        expect(versionKey(meta), isNull, reason: meta);
        expect(
          firmwareVersionKey(meta),
          versionKey(meta.split('+').first),
          reason: meta,
        );
      }
      for (final bad in (vs['invalid'] as List).cast<String>()) {
        expect(versionKey(bad), isNull, reason: bad);
        expect(firmwareVersionKey(bad), isNull, reason: bad);
      }
    });

    test("images: an image's descriptors", () {
      final im = (v['images'] as Map).cast<String, dynamic>();
      for (final c in cases(im, 'valid')) {
        final info = imageInfo(h(c['head']));
        expect(info.version, c['version'], reason: c['name'] as String);
        expect(info.project, c['project']);
        expect(info.variant, c['variant']);
        expect(info.board, c['board']);
      }
      for (final c in cases(im, 'invalid')) {
        expect(
          () => imageInfo(h(c['head'])),
          throwsA(isA<ReleaseException>()),
          reason: c['name'] as String,
        );
      }
    });

    test("reports: a box's report and its MAC", () {
      final r = (v['reports'] as Map).cast<String, dynamic>();
      final key = h(r['game_key']);
      for (final c in cases(r, 'valid')) {
        final body = utf8.encode(c['body'] as String);
        expect(
          utf8.decode(
            reportBody(
              c['game'] as int,
              c['node'] as int,
              c['release'] as String,
              c['result'] as String,
              c['version'] as String,
            ),
          ),
          c['body'],
        );
        expect(reportMac(key, body), c['mac']);
        final p = parseReport(body);
        expect(p.node, c['node']);
        expect(p.result, c['result']);
      }
      expect(
        () => parseReport(utf8.encode('atalaia-firmware-report-v1\n')),
        throwsA(isA<ReleaseException>()),
      );
    });
  });
}
