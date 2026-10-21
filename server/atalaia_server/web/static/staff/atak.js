// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The remote ATAK relay's enrolment (GET /api/v1/fields/{field}/atak, POST .../atak/certificates,
// POST .../atak/certificates/{id}/revoke, GET .../atak/log; Phase 4 follow-up FU5), for the field's admin
// and gm: a certificate for a named device, given once as a TAK data package (a file made in this page from
// the API's answer, never stored by the server) with its password; the field's certificates, revoking one;
// the devices connected now; the log.

import { $, api, boot, el, enable, errorText, fieldApi, fillRows, status, t, when } from './staff.js';

let ctx = null;
let download = null;

function stateName(state) {
    return t(`cert_${state}`);
}

function yesNo(value) {
    return value ? t('yes') : t('no');
}

async function revoke(cert) {
    if (!window.confirm(t('atak_revoke_confirm', { device: cert.device_name }))) return;
    try {
        const out = await api('POST', fieldApi(`/atak/certificates/${encodeURIComponent(cert.id)}/revoke`), {});
        status(t('atak_revoked', { n: out.closed }), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
    }
    await load();
}

async function loadLog() {
    let rows;
    try {
        rows = await api('GET', fieldApi('/atak/log'));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    fillRows($('atak-log'), rows.map((r) => [when(r.at, ctx.zone), r.username || t('none'),
        `${t(`log_${r.action}`)}${r.details && r.details.reason ? ` (${r.details.reason})` : ''}`,
        (r.details && r.details.device_name) || t('none'), r.address || t('none')]));
    $('atak-log').hidden = rows.length === 0;
    $('atak-log-none').hidden = rows.length > 0;
}

async function load() {
    let state;
    try {
        state = await api('GET', fieldApi('/atak'));
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    $('atak-off').hidden = state.enabled;
    $('atak-issue').hidden = !state.enabled;
    const connect = $('atak-connect');
    connect.hidden = !state.connect;
    if (state.connect) connect.textContent = t('atak_connect', { host: state.connect.host, port: state.connect.port });
    const certs = state.certificates;
    fillRows($('atak-certs'), certs.map((c) => [c.device_name, c.holder || t('atak_operator'), yesNo(c.positions),
        when(c.not_after, ctx.zone), stateName(c.state), when(c.last_connected_at, ctx.zone),
        c.state === 'valid' ? el('button', {
            type: 'button', class: 'danger', text: t('atak_revoke'), 'aria-label': `${t('atak_revoke')}: ${c.device_name}`,
            onclick: () => revoke(c),
        }) : '']));
    $('atak-certs').hidden = certs.length === 0;
    $('atak-certs-none').hidden = certs.length > 0;
    const live = state.connected;
    fillRows($('atak-connected'), live.map((c) => [c.device_name, when(c.connected_at, ctx.zone), c.address,
        yesNo(c.positions)]));
    $('atak-connected').hidden = live.length === 0;
    $('atak-connected-none').hidden = live.length > 0;
    await loadLog();
    return true;
}

function offer(answer) {
    // The package is made into a file here, from the answer: the server keeps neither it nor its password.
    const bytes = Uint8Array.from(atob(answer.package.base64), (c) => c.charCodeAt(0));
    if (download) URL.revokeObjectURL(download);
    download = URL.createObjectURL(new Blob([bytes], { type: answer.package.content_type }));
    const a = $('atak-download');
    a.setAttribute('href', download);
    a.setAttribute('download', answer.package.name);
    a.textContent = t('atak_download', { name: answer.package.name });
    $('atak-password').textContent = answer.password;
    $('atak-issued-text').textContent = t('atak_issued', { device: answer.certificate.device_name,
        until: when(answer.certificate.not_after, ctx.zone) });
    $('atak-issued').hidden = false;
}

async function submit(event) {
    event.preventDefault();
    const body = { device_name: $('a-device').value.trim(), days: Number($('a-days').value),
        positions: $('a-positions').checked };
    const holder = $('a-holder').value.trim();
    if (holder) body.holder = holder;
    $('atak-issued').hidden = true;
    status(t('sending'));
    let answer;
    try {
        answer = await api('POST', fieldApi('/atak/certificates'), body);
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    status('');
    offer(answer);
    $('a-device').value = '';
    $('a-positions').checked = false;
    await load();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (!(await load())) return;
    const form = $('atak-form');
    enable(form);
    form.addEventListener('submit', submit);
    $('atak-refresh').addEventListener('click', () => load());
}

main();
