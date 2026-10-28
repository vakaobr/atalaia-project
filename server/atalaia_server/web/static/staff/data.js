// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's data, for its admin: the download of everything the field holds (GET /api/v1/fields/{field}/export,
// a ZIP the server builds before it answers; the API's rules on who, how often and how large decide) and what the
// field uses of each hosted-mode limit (GET /api/v1/fields/{field}/quotas). The ZIP is read with the bearer token
// and offered from a blob: address made here; its SHA-256, which the API's audit log also holds, is shown so that it
// can be compared. Nothing here knows a limit: the numbers come from the API.

import { $, api, boot, errorText, fieldApi, fillRows, page, status, t } from './staff.js';

let download = null;

function hex(buffer) {
    return Array.from(new Uint8Array(buffer), (b) => b.toString(16).padStart(2, '0')).join('');
}

async function exportRun() {
    const button = $('export-run');
    button.disabled = true;
    $('export-done').hidden = true;
    $('export-working').hidden = false;
    status('');
    try {
        const file = await api('GET', fieldApi('/export'), undefined, { blob: true });
        if (download) URL.revokeObjectURL(download);
        download = URL.createObjectURL(file);  // a blob: address, made here, never one from the server
        const slug = String(page.field).slice(0, 8);
        const a = $('export-download');
        a.setAttribute('href', download);
        a.setAttribute('download', `atalaia-${slug}-${new Date().toISOString().slice(0, 10)}.zip`);
        let sha = '';
        try {
            sha = hex(await window.crypto.subtle.digest('SHA-256', await file.arrayBuffer()));
        } catch (e) {
            sha = '';  // no Web Crypto here: the file is still offered
        }
        $('export-sha').textContent = sha;
        $('export-sha').parentElement.hidden = sha === '';
        $('export-done').hidden = false;
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
    } finally {
        $('export-working').hidden = true;
        button.disabled = false;
    }
}

async function quotas() {
    let body;
    try {
        body = await api('GET', fieldApi('/quotas'));
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
        return;
    }
    $('quotas-none').hidden = body.hosted;
    $('quotas-table').hidden = !body.hosted;
    if (!body.hosted) return;
    fillRows($('quotas-table'), body.quotas.map((q) => [
        t(`quota_name_${q.name}`),
        [q.used === null ? t('none') : String(q.used), { class: 'num' }],
        [q.limit === null ? t('quota_no_limit') : String(q.limit), { class: 'num' }]]));
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    $('export-run').addEventListener('click', exportRun);
    $('export-run').disabled = false;
    await quotas();
}

main();
