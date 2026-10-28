// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The firmware catalogue (GET /api/v1/firmware, any account; POST /api/v1/firmware and DELETE
// /api/v1/firmware/{id}?reason=, a server administrator): every release with whether today's release keys still
// verify its signature, the latest verified stable release per platform and the keys' ids. A list only: no
// image is stored or sent from here (decision S19-5). A release is added only if a trusted release key signed
// it, which the API checks; a withdrawn release stays in the list, marked.

import { $, api, boot, el, enable, errorText, fillRows, status, t, when } from './staff.js';

let ctx = null;
let admin = false;

function state(r) {
    const parts = [];
    parts.push(r.yanked_at ? t('fw_withdrawn', { when: when(r.yanked_at, ctx.zone), reason: r.yank_reason || t('none') })
        : (r.verified ? t('fw_verified') : t('fw_not_verified')));
    if (r.pre_release) parts.push(t('fw_pre_release'));
    return parts.join(', ');
}

async function withdraw(release) {
    if (!window.confirm(t('fw_withdraw_confirm', { platform: release.platform, version: release.version }))) return;
    const reason = $('fw-reason').value.trim();
    try {
        await api('DELETE', `/api/v1/firmware/${encodeURIComponent(release.id)}${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`);
        status(t('fw_withdrawn_done', { platform: release.platform, version: release.version }), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
    }
    await load();
}

async function load() {
    let body;
    try {
        body = await api('GET', '/api/v1/firmware');
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    const latest = Object.entries(body.latest || {});
    const list = $('fw-latest');
    list.replaceChildren(...latest.map(([platform, version]) => el('li', { text: `${platform}: ${version}` })));
    $('fw-latest-none').hidden = latest.length > 0;
    $('fw-keys').textContent = body.keys.length ? body.keys.join(', ') : t('fw_no_keys');
    fillRows($('fw-table'), body.releases.map((r) => [r.platform, r.version, state(r), [String(r.size), { class: 'num' }],
        [el('code', { class: 'data', text: r.sha256 }), {}], r.key_id || t('none'), when(r.released_at, ctx.zone),
        r.notes || t('none'),
        admin && !r.yanked_at ? el('button', {
            type: 'button', class: 'danger', text: t('fw_withdraw'),
            'aria-label': `${t('fw_withdraw')}: ${r.platform} ${r.version}`, onclick: () => withdraw(r),
        }) : '']));
    $('fw-table').hidden = body.releases.length === 0;
    $('fw-none').hidden = body.releases.length > 0;
    return true;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    admin = Boolean(ctx.session.mfa && ctx.session.user.server_admin);
    $('fw-withdraw').hidden = !admin;
    $('fw-add').hidden = !admin;
    const form = $('fw-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = {
            platform: $('f-platform').value, version: $('f-version').value.trim(), size: Number($('f-size').value),
            sha256: $('f-sha256').value.trim(), signature: $('f-signature').value.trim(),
        };
        if ($('f-notes').value.trim()) body.notes = $('f-notes').value.trim();
        if ($('f-released').value) body.released_at = new Date($('f-released').value).toISOString();
        try {
            await api('POST', '/api/v1/firmware', body);
            status(t('fw_added', { platform: body.platform, version: body.version }), 'ok');
            form.reset();
        } catch (err) {
            status(errorText(err), 'error');
        }
        await load();
    });
    if (await load() && admin) enable(form);
}

main();
