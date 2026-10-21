// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One scenario of the library, or a new one. Viewing: the current revision (manifest, warnings, the
// package it compiles to), the revisions (each one's manifest on request) and archiving (DELETE).
// Editing: a manifest pasted or loaded from a file is checked by the server (POST .../scenarios/check,
// every problem listed, nothing stored) and saved as the next revision (POST .../scenarios).

import {
    $, api, boot, clear, el, enable, errorText, fieldApi, fieldPage, fillRows, page, status, t, when, ApiError,
} from './staff.js';
import { problemTable, showCheck } from './problems.js';

let ctx = null;
let shown = null;
const id = page.scenario;

function details(dl, rows) {
    clear(dl);
    for (const [k, v] of rows) dl.append(el('dt', { text: k }), el('dd', {}, v));
}

async function view() {
    let s;
    try {
        s = await api('GET', fieldApi(`/scenarios/${encodeURIComponent(id)}`));
    } catch (err) {
        status(errorText(err), 'error');
        return null;
    }
    $('scenario-heading').textContent = `${s.name} (${s.scenario_id})`;
    $('archived-notice').hidden = !s.archived;
    $('archive').hidden = s.archived;
    details($('current-details'), [[t('col_revision'), String(s.revision)], [t('col_version'), String(s.version)],
        [t('col_updated'), when(s.updated_at, ctx.zone)], ['SHA-256', el('code', { class: 'data', text: s.sha256 })]]);
    const warnings = clear($('current-warnings'));
    if (s.warnings && s.warnings.length) warnings.append(el('h3', { text: t('warnings') }), problemTable(s.warnings));
    $('current-manifest').textContent = s.manifest;
    const files = clear($('package-files'));
    if (s.files) {
        for (const [name, text] of Object.entries(s.files)) {
            files.append(el('h3', {}, el('code', { text: name })), el('pre', { class: 'code', text }));
        }
    } else {
        files.append(el('p', { text: t('package_none') }));
    }
    $('current').hidden = false;
    fillRows($('revisions'), s.revisions.map((r) => [[String(r.revision), { class: 'num' }], String(r.version), r.name,
        when(r.created_at, ctx.zone), el('button', { type: 'button', text: t('show'), onclick: () => revision(r.revision) })]));
    $('revisions-section').hidden = false;
    shown = s;
    return s;
}

async function revision(n) {
    try {
        const r = await api('GET', fieldApi(`/scenarios/${encodeURIComponent(id)}/revisions/${n}`));
        $('revision-title').textContent = t('revision_n', { n: r.revision });
        $('revision-manifest').textContent = r.manifest;
        $('revision-view').hidden = false;
        $('revision-title').scrollIntoView({ block: 'nearest' });
    } catch (err) {
        status(errorText(err), 'error');
    }
}

function editor(text) {
    $('editor').hidden = false;
    const area = $('manifest-text');
    if (text !== undefined) area.value = text;
    enable($('editor-form'));
}

async function check() {
    const manifest = $('manifest-text').value;
    try {
        const answer = await api('POST', fieldApi('/scenarios/check'), { manifest });
        showCheck($('check-result'), answer);
        return answer;
    } catch (err) {
        if (err instanceof ApiError && err.body.problems) showCheck($('check-result'), { ok: false, problems: err.body.problems });
        else status(errorText(err), 'error');
        return null;
    }
}

async function save(event) {
    event.preventDefault();
    const manifest = $('manifest-text').value;
    let saved;
    try {
        saved = await api('POST', fieldApi('/scenarios'), { manifest });
    } catch (err) {
        if (err instanceof ApiError && err.body.problems) {
            showCheck($('check-result'), { ok: false, problems: err.body.problems });
            status(t('e_scenario_refused'), 'error');
        } else {
            status(errorText(err), 'error');
        }
        return;
    }
    const message = t(`outcome_${saved.outcome}`, { n: saved.revision });
    if (saved.scenario_id !== id) {
        location.assign(fieldPage(`/scenarios/${encodeURIComponent(saved.scenario_id)}`));
        return;
    }
    clear($('check-result'));
    status(message, 'ok');
    await view();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    $('editor-form').addEventListener('submit', save);
    $('check').addEventListener('click', check);
    $('manifest-file').addEventListener('change', async (event) => {
        const file = event.target.files[0];
        if (file) $('manifest-text').value = await file.text();
    });
    if (!id) {
        editor('');
        return;
    }
    if (!(await view())) return;
    $('edit').addEventListener('click', () => {
        editor(shown.manifest);
        $('manifest-text').focus();
    });
    $('archive').addEventListener('click', async () => {
        if (!window.confirm(t('archive_confirm'))) return;
        try {
            await api('DELETE', fieldApi(`/scenarios/${encodeURIComponent(id)}`));
            status(t('saved'), 'ok');
            await view();
        } catch (err) {
            status(errorText(err), 'error');
        }
    });
}

main();
