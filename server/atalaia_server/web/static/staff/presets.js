// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field's game presets (GET, POST /api/v1/fields/{field}/presets; PUT, DELETE .../presets/{id}), for
// its admin and gm: a name, a mode id and the mode's parameters as a JSON object.

import { $, api, boot, brief, el, enable, errorText, fieldApi, fillRows, status, t, when } from './staff.js';

let ctx = null;
let editing = null;

function reset() {
    editing = null;
    $('preset-form-title').textContent = t('preset_new');
    $('p-name').value = '';
    $('p-mode').value = '';
    $('p-params').value = '{}';
    $('p-cancel').hidden = true;
}

function edit(preset) {
    editing = preset.id;
    $('preset-form-title').textContent = t('preset_edit', { name: preset.name });
    $('p-name').value = preset.name;
    $('p-mode').value = preset.mode_id;
    $('p-params').value = JSON.stringify(preset.params, null, 2);
    $('p-cancel').hidden = false;
    $('p-name').focus();
}

async function remove(preset) {
    if (!window.confirm(t('preset_delete_confirm', { name: preset.name }))) return;
    try {
        await api('DELETE', fieldApi(`/presets/${encodeURIComponent(preset.id)}`));
        if (editing === preset.id) reset();
        status(t('saved'), 'ok');
        await load();
    } catch (err) {
        status(errorText(err), 'error');
    }
}

async function load() {
    let list;
    try {
        list = await api('GET', fieldApi('/presets'));
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    fillRows($('presets'), list.map((p) => [p.name, el('code', { text: p.mode_id }),
        el('code', { class: 'data', text: brief(p.params) }), when(p.updated_at, ctx.zone),
        el('span', { class: 'actions' },
            el('button', { type: 'button', text: t('edit'), 'aria-label': `${t('edit')}: ${p.name}`, onclick: () => edit(p) }), ' ',
            el('button', { type: 'button', class: 'danger', text: t('delete'), 'aria-label': `${t('delete')}: ${p.name}`,
                onclick: () => remove(p) }))]));
    $('presets').hidden = list.length === 0;
    $('presets-none').hidden = list.length > 0;
    return true;
}

async function submit(event) {
    event.preventDefault();
    let params;
    try {
        params = JSON.parse($('p-params').value || '{}');
    } catch (e) {
        params = null;
    }
    if (params === null || typeof params !== 'object' || Array.isArray(params)) {
        status(t('params_bad_json'), 'error');
        $('p-params').focus();
        return;
    }
    const body = { name: $('p-name').value.trim(), mode_id: $('p-mode').value.trim(), params };
    try {
        if (editing) await api('PUT', fieldApi(`/presets/${encodeURIComponent(editing)}`), body);
        else await api('POST', fieldApi('/presets'), body);
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    reset();
    status(t('saved'), 'ok');
    await load();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (!(await load())) return;
    const form = $('preset-form');
    enable(form);
    form.addEventListener('submit', submit);
    $('p-cancel').addEventListener('click', reset);
}

main();
