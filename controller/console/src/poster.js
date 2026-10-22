// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The check-in poster page (ADR-P3-13): asks the controller for the
// poster's text (GET /api/v1/checkin/poster, GM token) and draws it as a
// large QR code with the field's name, the steps in European Portuguese
// and English and the short form of the field CA's fingerprint, which
// staff compare with the console's. A field whose Wi-Fi has a password can
// draw a standard Wi-Fi QR code beside it: the password is typed here, used
// only to draw that code, and never stored or sent anywhere. The field's
// logo (its branding, decisions BR1-BR24) goes above its name, apart from
// the QR code, so the code reads as before.

import qrcode from './lib/qrcode.module.js';
import { t, loadLanguage, api, savedToken, fetchBranding, brandingUrl, posterProblem } from './ui.js';

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
    svg.setAttribute('data-testid', testid);
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

/** The Wi-Fi QR text phone cameras read: WIFI:T:WPA;S:<ssid>;P:<password>;; with \ ; , : " escaped. */
export function wifiText(ssid, password) {
    const esc = (s) => s.replace(/([\\;,:"])/g, '\\$1');
    return password ? `WIFI:T:WPA;S:${esc(ssid)};P:${esc(password)};;` : `WIFI:T:nopass;S:${esc(ssid)};;`;
}

function el(tag, attrs, text) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
}

async function main() {
    await loadLanguage();
    document.title = `Atalaia · ${t('poster.title')}`;
    const tools = document.getElementById('tools');
    tools.textContent = '';
    const token = savedToken();
    if (!token) {
        tools.append(el('p', { class: 'error', 'data-testid': 'poster-login' }, t('poster.login')));
        return;
    }
    let poster;
    try {
        poster = await api(token, 'GET', '/checkin/poster');
    } catch (e) {
        tools.append(el('p', { class: 'error', 'data-testid': 'poster-error' },
            e.status === 401 || e.status === 403 ? t('poster.login') : e.message));
        return;
    }
    if (!poster.text) {
        tools.append(el('p', { class: 'error', 'data-testid': 'poster-error' }, posterProblem(poster) || t('poster.no_text')));
        return;
    }
    document.getElementById('field-name').textContent = poster.field_name;
    const branding = await fetchBranding();
    if (branding && branding.logo) {
        const logo = document.getElementById('field-logo');
        logo.alt = t('branding.logo_alt', { name: poster.field_name });
        logo.src = brandingUrl(branding.logo);
        logo.hidden = false;
    }
    document.getElementById('ca-short').textContent = poster.ca_short;
    const ssid = poster.wifi_ssid;
    document.getElementById('step1-pt').textContent = ssid
        ? `Liga-te à rede Wi-Fi «${ssid}».` : 'Liga-te à rede Wi-Fi do campo.';
    document.getElementById('step1-en').textContent = ssid
        ? `Join the Wi-Fi network “${ssid}”.` : 'Join the field’s Wi-Fi network.';
    document.getElementById('qr').append(qrSvg(poster.text, 'M', 'poster-qr', t('poster.qr_label')));
    document.getElementById('poster').hidden = false;

    // Screen-only tools (hidden when printed).
    tools.append(el('p', { class: 'muted' }, t('poster.intro')));
    const row = el('div', { class: 'tool-row' });
    const print = el('button', { type: 'button', class: 'primary', 'data-testid': 'poster-print' }, t('poster.print'));
    print.addEventListener('click', () => window.print());
    row.append(print);
    if (ssid) {
        const label = el('label', { for: 'wifi-pass' }, t('poster.wifi_password'));
        const input = el('input', { id: 'wifi-pass', type: 'password', autocomplete: 'off', 'data-testid': 'poster-wifi-pass' });
        const draw = el('button', { type: 'button', 'data-testid': 'poster-wifi-draw' }, t('poster.wifi_draw'));
        draw.addEventListener('click', () => {
            const box = document.getElementById('wifi-qr');
            box.textContent = '';
            box.append(qrSvg(wifiText(ssid, input.value), 'M', 'poster-wifi-svg', t('poster.wifi_label')));
            document.getElementById('wifi-caption').textContent = `Wi-Fi «${ssid}»`;
            document.getElementById('wifi-figure').hidden = false;
            input.value = ''; // drawn: the password is not kept, not even in the form
        });
        row.append(label, input, draw);
        tools.append(row, el('p', { class: 'muted small' }, t('poster.wifi_note')));
    } else {
        tools.append(row);
    }
    tools.append(el('p', { class: 'muted small', 'data-testid': 'poster-text' }, poster.text));
}

main();
