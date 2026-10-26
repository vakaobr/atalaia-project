// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A preview server's feedback (GET /api/v1/admin/feedback; PATCH, DELETE .../feedback/{id}), for the server's
// administrators: what visitors wrote on the feedback form, with its state (new, seen, done).

import { $, api, boot, el, enable, errorText, fillRows, has, status, t, when } from './staff.js';

const STATES = ['new', 'seen', 'done'];

async function setState(row, state) {
    try {
        await api('PATCH', `/api/v1/admin/feedback/${encodeURIComponent(row.id)}`, { status: state });
        status(t('saved'), 'ok');
        await load();
    } catch (err) {
        status(errorText(err), 'error');
    }
}

async function remove(row) {
    if (!window.confirm(t('feedback_delete_confirm'))) return;
    try {
        await api('DELETE', `/api/v1/admin/feedback/${encodeURIComponent(row.id)}`);
        status(t('saved'), 'ok');
        await load();
    } catch (err) {
        status(errorText(err), 'error');
    }
}

function word(prefix, key) {
    return key && has(`${prefix}${key}`) ? t(`${prefix}${key}`) : (key || t('none'));
}

async function load() {
    let body;
    try {
        body = await api('GET', `/api/v1/admin/feedback?status=${encodeURIComponent($('f-status').value)}`);
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
        return false;
    }
    $('feedback-counts').textContent = t('feedback_counts', body.counts);
    fillRows($('feedback'), body.feedback.map((f) => [
        when(f.created_at), word('fb_kind_', f.kind), word('fb_who_', f.who),
        el('span', { class: 'message', text: f.message }), f.contact || t('none'),
        f.page ? el('code', { text: f.page }) : t('none'),
        el('select', { 'aria-label': t('fb_col_status'), onchange: (e) => setState(f, e.target.value) },
            STATES.map((s) => el('option', { value: s, selected: s === f.status, text: t(`fb_status_${s}`) }))),
        el('button', { type: 'button', class: 'danger', text: t('delete'), onclick: () => remove(f) }),
    ]));
    $('feedback').hidden = body.feedback.length === 0;
    $('feedback-none').hidden = body.feedback.length > 0;
    return true;
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    const form = $('filters');
    enable(form);
    form.addEventListener('submit', (e) => e.preventDefault());
    $('f-status').addEventListener('change', load);
    await load();
}

main();
