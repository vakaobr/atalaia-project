// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The replica labels page: asks the controller for the game's "replicas to chrono" list
// (GET /api/v1/games/{id}/chrono-list, GM token) and draws one 30 x 30 mm label for each declared
// replica of one player (?game=<id>&player=<player id>) or of everyone checked in (?game=<id>):
// a QR code with the label text under it, to cut out and stick on the replica. The text is what the
// marshal's app registers a replica under and scans in its chrono queue: "ATL-" and the first eight
// characters, upper case, of the replica's id at the field, or of its declaration's id while no
// marshal has registered it (protocol/checkin.md, "Replica labels"). It holds nothing about the
// player; the player's name and the replica's kind are on the screen only, above the sheet.

import { qrSvg } from './qr-svg.js';
import { t, loadLanguage, api, savedToken } from './ui.js';

/** The label text of a replica: ATL- and the first eight characters of its registry id, upper case. */
export function labelText(id) {
    return `ATL-${id.slice(0, 8).toUpperCase()}`;
}

/** The id a marshal's app registers a declared replica under: the field's own, else the declaration's. */
export function registryId(d) {
    return d.replica_id || d.declaration_id;
}

function el(tag, attrs, text) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
}

/** The labels to draw: [{code, who, what}] for the players of the list that the address asks for. */
export function labelsOf(list, playerId) {
    const out = [];
    for (const p of list.players) {
        if (playerId ? p.player_id !== playerId : p.status !== 'checked_in') continue;
        for (const d of p.declarations) {
            if (d.state === 'withdrawn' || !registryId(d)) continue;
            out.push({
                code: labelText(registryId(d)),
                who: p.display_name || p.player_id,
                what: [t(`checkin.types.${d.type}`), d.class, d.make_model].filter(Boolean).join(' · '),
            });
        }
    }
    return out;
}

async function main() {
    await loadLanguage();
    document.title = `Atalaia · ${t('labels.title')}`;
    const tools = document.getElementById('tools');
    tools.textContent = '';
    const token = savedToken();
    if (!token) {
        tools.append(el('p', { class: 'error', 'data-testid': 'labels-login' }, t('labels.login')));
        return;
    }
    const q = new URLSearchParams(window.location.search);
    const game = parseInt(q.get('game'), 10);
    const player = q.get('player') || '';
    let list;
    try {
        list = await api(token, 'GET', `/games/${game}/chrono-list`);
    } catch (e) {
        tools.append(el('p', { class: 'error', 'data-testid': 'labels-error' },
            e.status === 401 || e.status === 403 ? t('labels.login') : t('labels.error', { error: e.message })));
        return;
    }
    const labels = labelsOf(list, player);
    tools.append(el('h1', {}, t('labels.title')));
    if (labels.length === 0) {
        tools.append(el('p', { class: 'muted', 'data-testid': 'labels-none' }, t('labels.none')));
        return;
    }
    tools.append(el('p', { class: 'muted' }, t('labels.intro')));
    const row = el('div', { class: 'tool-row' });
    const print = el('button', { type: 'button', class: 'primary', 'data-testid': 'labels-print' }, t('labels.print'));
    print.addEventListener('click', () => window.print());
    row.append(print, el('span', { class: 'muted', 'data-testid': 'labels-count' }, t('labels.count', { n: labels.length })));
    tools.append(row);
    const sheet = document.getElementById('sheet');
    for (const l of labels) {
        const cell = el('figure', { class: 'label', 'data-testid': 'label' });
        const box = el('div', { class: 'qr' });
        box.append(qrSvg(l.code, 'M', 'label-qr', t('labels.qr_label', { code: l.code })));
        cell.append(box, el('figcaption', { 'data-testid': 'label-code' }, l.code),
            el('span', { class: 'who' }, `${l.who} · ${l.what}`));
        sheet.append(cell);
    }
    sheet.hidden = false;
}

main();
