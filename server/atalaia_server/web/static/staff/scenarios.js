// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field's scenario library (GET /api/v1/fields/{field}/scenarios[?archived=true]), for its admin and gm.

import { $, api, boot, el, errorText, fieldApi, fieldPage, fillRows, status, t, when } from './staff.js';

let ctx = null;

async function load() {
    const archived = $('show-archived').checked;
    let list;
    try {
        list = await api('GET', fieldApi(`/scenarios${archived ? '?archived=true' : ''}`));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    status('');
    fillRows($('scenarios'), list.map((s) => [
        el('a', { href: fieldPage(`/scenarios/${encodeURIComponent(s.scenario_id)}`) }, el('code', { text: s.scenario_id })),
        s.archived ? el('span', {}, s.name, ' ', el('span', { class: 'badge', text: t('archived') })) : s.name,
        String(s.version), [String(s.revision), { class: 'num' }], when(s.updated_at, ctx.zone),
    ]));
    $('scenarios').hidden = list.length === 0;
    $('scenarios-none').hidden = list.length > 0;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const box = $('show-archived');
    box.disabled = false;
    box.addEventListener('change', load);
    await load();
}

main();
