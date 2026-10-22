// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The mode editor's package (phase 5, decisions P5I-1 to P5I-6): the canonical, unsigned archive
// of the generated files, made in the page, byte for byte what `tools/mode_package.py pack`
// makes of the same files (protocol/mode-packages.md, "The archive"; the reference is pack() in
// controller/atalaia_controller/mode_package.py, and the browser tests compare the two for the
// shared vectors, every built-in mode and the editor's examples). It also gives the manifest a
// mode key will sign. Signing is not here: it stays offline, with `tools/mode_package.py sign`
// and the author's own key file (P5I-3); no key ever reaches the page.
//
// No dependencies: SHA-256 is computed here too (FIPS 180-4), because crypto.subtle exists only
// in a secure context and the simulator may be served over plain http with --allow-host.

export const MANIFEST_HEADER = 'atalaia-mode-package-v1';
export const MAX_PACKAGE_BYTES = 1000000; // the controller's limit for a package (P5-6)
export const MAX_FILES = 64;
const MODE_ID = /^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$/;
const MODE_ID_MAX = 63;
const FILE_NAME = /^(mode\.yaml|node\.lua|field\.lua|assets\/[A-Za-z0-9_.-]+(\/[A-Za-z0-9_.-]+)*)$/;
// firmware_release.VERSION and version_key: MAJOR.MINOR.PATCH, an optional pre-release.
const VERSION = /^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?$/;
export const KINDS = ['mode', 'modifier', 'role', 'scenario'];
export const TIERS = ['reduced', 'full'];
const BLOCK = 512;
const NAME_MAX = 100;
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** Why a package cannot be made: `code` as PackageError's in mode_package.py, `what` what it is about. */
export class PackageError extends Error {
    constructor(code, what = '', detail = '') {
        super(`${code}: ${what}${detail ? ` (${detail})` : ''}`);
        this.code = code;
        this.what = what;
    }
}

const ascii = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));

/** A ustar number field: width - 1 octal digits, then NUL. */
function octal(value, width) {
    return ascii(value.toString(8).padStart(width - 1, '0') + '\0');
}

function header(path, size) {
    const h = new Uint8Array(BLOCK);
    h.set(path, 0);
    h.set(octal(0o644, 8), 100);
    h.set(octal(0, 8), 108);
    h.set(octal(0, 8), 116);
    h.set(octal(size, 12), 124);
    h.set(octal(0, 12), 136);
    h.set(ascii('        '), 148);
    h.set(ascii('0'), 156);
    h.set(ascii('ustar\0'), 257);
    h.set(ascii('00'), 263);
    h.set(octal(0, 8), 329);
    h.set(octal(0, 8), 337);
    const sum = h.reduce((a, b) => a + b, 0);
    h.set(ascii(sum.toString(8).padStart(6, '0') + '\0 '), 148);
    return h;
}

/** mode_package.check_file_name: a file a package may carry. */
export function checkFileName(name) {
    if (typeof name !== 'string' || !FILE_NAME.test(name) || name.split('/').some((p) => p === '' || p.startsWith('.'))) {
        throw new PackageError('bad_archive', name, 'not allowed in a mode package');
    }
}

/**
 * The canonical archive (a Uint8Array) of a package's files ({name: text}) under the root folder
 * `modeId`: mode_package.pack, refusing what it refuses with the same codes.
 */
export function pack(modeId, files) {
    if (typeof modeId !== 'string' || !MODE_ID.test(modeId) || modeId.length > MODE_ID_MAX) {
        throw new PackageError('bad_archive', modeId, 'the id must look like org.club.name, at most 63 bytes');
    }
    const names = Object.keys(files || {});
    if (!names.length || names.length > MAX_FILES) throw new PackageError('bad_archive', `${names.length} files`, `1 to ${MAX_FILES}`);
    // Byte order; the names are ASCII, where it is the strings' code unit order.
    names.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    const encoder = new TextEncoder();
    const parts = [];
    let total = 0;
    for (const name of names) {
        checkFileName(name);
        const text = files[name];
        if (typeof text !== 'string' || text.includes('\0') || LONE_SURROGATE.test(text)) {
            throw new PackageError('bad_archive', name, 'files are text');
        }
        const data = encoder.encode(text);
        const path = `${modeId}/${name}`;
        if (path.length > NAME_MAX) throw new PackageError('bad_archive', name, `the path is longer than ${NAME_MAX} bytes`);
        parts.push([header(ascii(path), data.length), data]);
        total += BLOCK + Math.ceil(data.length / BLOCK) * BLOCK;
    }
    total += 2 * BLOCK;
    if (total > MAX_PACKAGE_BYTES) throw new PackageError('too_big', String(total), `at most ${MAX_PACKAGE_BYTES} bytes`);
    const out = new Uint8Array(total); // zero-filled: the padding and the two end blocks
    let pos = 0;
    for (const [head, data] of parts) {
        out.set(head, pos);
        out.set(data, pos + BLOCK);
        pos += BLOCK + Math.ceil(data.length / BLOCK) * BLOCK;
    }
    return out;
}

/** firmware_release.version_key's form: a version a manifest may carry. */
export function validVersion(version) {
    const m = typeof version === 'string' ? VERSION.exec(version) : null;
    return Boolean(m) && !(m[4] !== undefined && m[4].split('.').includes(''));
}

/** The exact bytes' text a mode key signs (mode_package.manifest). */
export function manifest(fields, size, digest) {
    return `${MANIFEST_HEADER}\nid=${fields.id}\nversion=${fields.version}\nkind=${fields.kind}\n`
        + `min_tier=${fields.min_tier}\nsize=${size}\nsha256=${digest}\n`;
}

// ---- SHA-256 (FIPS 180-4) ----

const K = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

/** The SHA-256 of bytes (a Uint8Array) as 64 lower-case hex digits. */
export function sha256Hex(bytes) {
    const bitLength = bytes.length * 8;
    const padded = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
    padded.set(bytes);
    padded[bytes.length] = 0x80;
    const view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor(bitLength / 0x100000000));
    view.setUint32(padded.length - 4, bitLength >>> 0);
    const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const W = new Uint32Array(64);
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    for (let off = 0; off < padded.length; off += 64) {
        for (let i = 0; i < 16; i++) W[i] = view.getUint32(off + 4 * i);
        for (let i = 16; i < 64; i++) {
            const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
            const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
            W[i] = W[i - 16] + s0 + W[i - 7] + s1;
        }
        let [a, b, c, d, e, f, g, h] = H;
        for (let i = 0; i < 64; i++) {
            const t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) >>> 0;
            const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
            h = g; g = f; f = e; e = (d + t1) >>> 0;
            d = c; c = b; b = a; a = (t1 + t2) >>> 0;
        }
        H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
    }
    return [...H].map((x) => x.toString(16).padStart(8, '0')).join('');
}

// ---- the editor's package ----

/**
 * The files of the editor's mode a package carries, as a mode folder would hold them: mode.yaml,
 * node.lua, field.lua when there is one (as Test sends it), and the screens (assets/screens/).
 */
export function packageFiles(generated) {
    const files = {};
    for (const [key, name] of [['mode_yaml', 'mode.yaml'], ['node_lua', 'node.lua'], ['field_lua', 'field.lua']]) {
        if (generated[key]) files[name] = generated[key];
    }
    for (const [name, text] of Object.entries(generated)) if (name.startsWith('assets/')) files[name] = text;
    return files;
}

/**
 * The package of the editor's mode: { file, bytes, size, sha256, fields, manifest, release }, or a
 * PackageError. `fields` are the manifest's (id, version, kind, min_tier) and the licence, from the
 * Mode tab that wrote mode.yaml, checked as mode_package.manifest_fields checks mode.yaml's.
 */
export function makePackage(info, kind, licences, generated) {
    const fields = { id: info.id, version: info.version, kind, min_tier: info.min_tier, license: info.license };
    if (typeof fields.id !== 'string' || !MODE_ID.test(fields.id) || fields.id.length > MODE_ID_MAX) {
        throw new PackageError('bad_manifest', 'id');
    }
    if (!validVersion(fields.version)) throw new PackageError('bad_manifest', 'version');
    if (!KINDS.includes(fields.kind)) throw new PackageError('bad_manifest', 'kind');
    if (!TIERS.includes(fields.min_tier)) throw new PackageError('bad_manifest', 'min_tier');
    if (!licences.includes(fields.license)) throw new PackageError('licence', 'license');
    const bytes = pack(fields.id, packageFiles(generated));
    const sha256 = sha256Hex(bytes);
    const text = manifest(fields, bytes.length, sha256);
    return {
        file: `${fields.id}-${fields.version}.tar`, bytes, size: bytes.length, sha256, fields, manifest: text,
        release: `${fields.id}-${fields.version}.tar.release.json`,
    };
}
