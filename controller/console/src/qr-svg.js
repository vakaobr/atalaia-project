// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A QR code as an SVG element, drawn with the console's vendored generator: shared by the
// check-in poster and the replica labels page.

import qrcode from './lib/qrcode.module.js';

const SVG = 'http://www.w3.org/2000/svg';

/** The QR code of text as an SVG element (byte mode, 4-module quiet zone). */
export function qrSvg(text, level, testid, label) {
    const qr = qrcode(0, level);
    qr.addData(text, 'Byte');
    qr.make();
    const n = qr.getModuleCount();
    const q = 4;
    let d = '';
    for (let r = 0; r < n; r += 1) {
        for (let c = 0; c < n; c += 1) {
            if (qr.isDark(r, c)) d += `M${c + q} ${r + q}h1v1h-1z`;
        }
    }
    const size = n + 2 * q;
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', label);
    svg.setAttribute('shape-rendering', 'crispEdges');
    if (testid) svg.setAttribute('data-testid', testid);
    const bg = document.createElementNS(SVG, 'rect');
    bg.setAttribute('width', String(size));
    bg.setAttribute('height', String(size));
    bg.setAttribute('fill', '#fff');
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', '#000');
    svg.append(bg, path);
    return svg;
}
