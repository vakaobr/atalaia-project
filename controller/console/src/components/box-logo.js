// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The field's logo in the form a Field Box draws (decision LOGO-1; protocol/mode-packages.md, section 8).
// The controllers convert a PNG logo themselves (box_logo.py, controller_box_logo.dart) but have no JPEG or
// WebP decoder (decision BR7), so the browser, which has, decodes the logo and does the same sums on whole
// integers: fitted into 96x96 keeping its shape and centred, each output pixel the average of the source
// pixels it covers, alpha composited on the box's screen colour #101418, written as 'ALG1', u16le 96,
// u16le 96 and 9,216 little-endian RGB565 words (18,440 bytes). The controller checks what it is sent.

export const SIDE = 96;
export const HEADER = 8;
export const SIZE = HEADER + SIDE * SIDE * 2;
const BG = [0x10, 0x14, 0x18];

/** The box-ready bytes (a Uint8Array of SIZE) of a width x height picture given as 8-bit RGBA (4 bytes a pixel). */
export function convertRgba(width, height, rgba) {
    let tw;
    let th;
    if (width >= height) {
        tw = SIDE;
        th = Math.max(1, Math.floor((height * SIDE + (width >> 1)) / width));
    } else {
        tw = Math.max(1, Math.floor((width * SIDE + (height >> 1)) / height));
        th = SIDE;
    }
    const ox = (SIDE - tw) >> 1;
    const oy = (SIDE - th) >> 1;
    const out = new Uint8Array(SIZE);
    const view = new DataView(out.buffer);
    out.set([0x41, 0x4c, 0x47, 0x31]);
    view.setUint16(4, SIDE, true);
    view.setUint16(6, SIDE, true);
    const bg565 = ((BG[0] >> 3) << 11) | ((BG[1] >> 2) << 5) | (BG[2] >> 3);
    for (let i = 0; i < SIDE * SIDE; i++) view.setUint16(HEADER + 2 * i, bg565, true);
    for (let dy = 0; dy < th; dy++) {
        const y0 = Math.floor((dy * height) / th);
        const y1 = Math.max(y0 + 1, Math.floor(((dy + 1) * height) / th));
        for (let dx = 0; dx < tw; dx++) {
            const x0 = Math.floor((dx * width) / tw);
            const x1 = Math.max(x0 + 1, Math.floor(((dx + 1) * width) / tw));
            const n = (x1 - x0) * (y1 - y0);
            let sa = 0;
            let sr = 0;
            let sg = 0;
            let sb = 0;
            for (let y = y0; y < y1; y++) {
                let o = (y * width + x0) * 4;
                for (let x = x0; x < x1; x++, o += 4) {
                    const a = rgba[o + 3];
                    sa += a;
                    sr += rgba[o] * a;
                    sg += rgba[o + 1] * a;
                    sb += rgba[o + 2] * a;
                }
            }
            const full = 255 * n;
            const back = full - sa;
            const half = Math.floor(full / 2);
            // Whole-integer sums (at most 2048 * 2048 * 255 * 255 < 2^53): the controllers' bytes.
            const r = Math.floor((sr + BG[0] * back + half) / full);
            const g = Math.floor((sg + BG[1] * back + half) / full);
            const b = Math.floor((sb + BG[2] * back + half) / full);
            view.setUint16(HEADER + 2 * ((oy + dy) * SIDE + ox + dx), ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3), true);
        }
    }
    return out;
}

/** The box-ready bytes of an image file (PNG, JPEG or WebP) decoded by the browser, through a canvas. */
export async function convertImage(blob) {
    const bitmap = await createImageBitmap(blob);
    try {
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(bitmap, 0, 0);
        return convertRgba(bitmap.width, bitmap.height, ctx.getImageData(0, 0, bitmap.width, bitmap.height).data);
    } finally {
        bitmap.close();
    }
}
