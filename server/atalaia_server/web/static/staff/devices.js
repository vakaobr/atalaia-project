// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field's boxes with their health (GET /api/v1/fields/{field}/devices?days=), for its admin and gm.

import { $, api, boot, el, enable, errorText, fieldApi, fieldPage, fillRows, status } from './staff.js';
import { deviceCells } from './devicerow.js';

let ctx = null;

async function load() {
    let body;
    try {
        body = await api('GET', fieldApi(`/devices?days=${encodeURIComponent($('d-days').value)}`));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    status('');
    fillRows($('devices'), body.devices.map((d) => deviceCells(d, ctx.zone, [
        el('a', { href: fieldPage(`/games/${encodeURIComponent(d.game.id)}`), text: d.game.name }),
        [String(d.games), { class: 'num' }]])));
    $('devices').hidden = body.devices.length === 0;
    $('devices-none').hidden = body.devices.length > 0;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const form = $('devices-form');
    enable(form);
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        load();
    });
    await load();
}

main();
