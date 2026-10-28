// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Server administration, for a server administrator in a TOTP session: every field (GET, POST /api/v1/fields:
// a new field; refused on a hosted hub, where the operator makes them) and the reports of clubs' public pages
// (GET /api/v1/admin/club-reports?status=, PATCH .../club-reports/{id} {status}, PUT, DELETE
// /api/v1/admin/clubs/{id}/hidden). The firmware catalogue has its own page. What each call needs is the API's.

import { $, api, boot, el, enable, errorText, fillRows, link, status, t, when } from './staff.js';

let ctx = null;

async function loadFields() {
    let fields;
    try {
        fields = await api('GET', '/api/v1/fields');
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    fillRows($('fields-table'), fields.map((f) => [f.name, f.slug, f.field_type, f.timezone,
        f.public_page ? t('yes') : t('no'), el('span', { class: 'actions' },
            el('a', { href: link(`/staff/fields/${encodeURIComponent(f.id)}/roles`), text: t('nav_roles') }),
            el('a', { href: link(`/staff/fields/${encodeURIComponent(f.id)}/sync-keys`), text: t('nav_synckeys') }),
            el('a', { href: link(`/staff/fields/${encodeURIComponent(f.id)}/history`), text: t('nav_history') }))]));
    $('fields-table').hidden = fields.length === 0;
    $('fields-none').hidden = fields.length > 0;
    return true;
}

async function decide(report, outcome) {
    try {
        await api('PATCH', `/api/v1/admin/club-reports/${encodeURIComponent(report.id)}`, { status: outcome });
        status(t('saved'), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
    }
    await loadReports();
}

async function hide(report, hidden) {
    const path = `/api/v1/admin/clubs/${encodeURIComponent(report.club_id)}/hidden`;
    const reason = $('r-reason').value.trim();
    try {
        await api(hidden ? 'PUT' : 'DELETE', path, hidden ? (reason ? { reason } : {}) : undefined);
        status(t(hidden ? 'club_hidden_done' : 'club_shown_done'), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
    }
    await loadReports();
}

async function loadReports() {
    let reports;
    try {
        reports = await api('GET', `/api/v1/admin/club-reports?status=${encodeURIComponent($('r-status').value)}`);
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    fillRows($('reports-table'), reports.map((r) => [
        el('a', { href: link(`/staff/clubs/${encodeURIComponent(r.club_id)}`), text: r.club }),
        t(`report_reason_${r.reason}`), el('span', { class: 'message', text: r.text || t('none') }),
        when(r.created_at, ctx.zone),
        `${t(`report_status_${r.status}`)}${r.club_hidden ? `, ${t('club_hidden_by_admin')}` : ''}`,
        el('span', { class: 'actions' },
            r.status === 'open' ? el('button', { type: 'button', text: t('report_dismiss'), onclick: () => decide(r, 'dismissed') }) : null,
            r.status === 'open' ? el('button', { type: 'button', text: t('report_actioned'), onclick: () => decide(r, 'actioned') }) : null,
            el('button', {
                type: 'button', class: r.club_hidden ? null : 'danger', text: t(r.club_hidden ? 'club_show' : 'club_hide'),
                onclick: () => hide(r, !r.club_hidden),
            }))]));
    $('reports-table').hidden = reports.length === 0;
    $('reports-none').hidden = reports.length > 0;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const form = $('field-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await api('POST', '/api/v1/fields', {
                name: $('n-name').value, slug: $('n-slug').value.trim(), field_type: $('n-type').value,
                timezone: $('n-zone').value.trim(),
            });
            status(t('admin_field_created', { name: $('n-name').value }), 'ok');
            $('n-name').value = '';
            $('n-slug').value = '';
        } catch (err) {
            status(errorText(err), 'error');
        }
        await loadFields();
    });
    $('r-status').addEventListener('change', loadReports);
    if (await loadFields()) enable(form);
    await loadReports();
}

main();
