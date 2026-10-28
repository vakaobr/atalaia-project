// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's sync (API) keys (GET, POST /api/v1/fields/{field}/sync-keys; DELETE .../sync-keys/{id}), for its
// admin: each controller gets its own key, with a label; the key is shown once, when it is made, and after that
// only its fingerprint (the first 8 hex digits of its SHA-256, which the controller shows too). How many may be
// live at once is the API's rule (409 too_many_keys).

import { $, api, boot, el, enable, errorText, fieldApi, fillRows, status, t, when } from './staff.js';

let ctx = null;

async function revoke(key) {
    if (!window.confirm(t('keys_revoke_confirm', { fingerprint: key.fingerprint, label: key.label || t('none') }))) return;
    try {
        await api('DELETE', fieldApi(`/sync-keys/${encodeURIComponent(key.id)}`));
        status(t('keys_revoked', { fingerprint: key.fingerprint }), 'ok');
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
    }
    await load();
}

async function load() {
    let keys;
    try {
        keys = await api('GET', fieldApi('/sync-keys'));
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
        return false;
    }
    fillRows($('keys-table'), keys.map((k) => [
        [el('code', { class: 'data', text: k.fingerprint }), {}], k.label || t('none'), when(k.created_at, ctx.zone),
        k.last_used_at ? when(k.last_used_at, ctx.zone) : t('keys_never_used'),
        k.revoked_at ? t('keys_revoked_at', { when: when(k.revoked_at, ctx.zone) }) : t('keys_live'),
        k.revoked_at ? '' : el('button', {
            type: 'button', class: 'danger', text: t('revoke'), 'aria-label': `${t('revoke')}: ${k.fingerprint}`,
            onclick: () => revoke(k),
        })]));
    $('keys-table').hidden = keys.length === 0;
    $('keys-none').hidden = keys.length > 0;
    return true;
}

async function create(event) {
    event.preventDefault();
    $('key-issued').hidden = true;
    const label = $('k-label').value.trim();
    let made;
    try {
        made = await api('POST', fieldApi('/sync-keys'), label ? { label } : {});
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
        return;
    }
    status('');
    $('key-value').textContent = made.key;
    $('key-issued').hidden = false;
    $('k-label').value = '';
    await load();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const form = $('key-form');
    form.addEventListener('submit', create);
    if (await load()) enable(form);
}

main();
