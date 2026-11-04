// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The game history the fields of a hosted hub share, by each field's opt-in (staff_pages.py, decisions HUBH-*), on
// the API of api/hub_history.py:
//   - GET /api/v1/fields/<field>/hub-history/settings: this field's switch (off by default), since when, how many of
//     its games are shared; a single-field server answers 404 not_hosted and the page says there is no other field;
//   - PUT .../hub-history/settings {enabled}: the field's admin turns it on or off; off withdraws every game the field
//     shared, so it asks first;
//   - GET .../hub-history?before=&mode=&limit=: the games of every field that shares, newest first, and the fields
//     themselves; only while this field shares (403 history_sharing_off): a field sees the others' games only if it
//     shares its own.
// The page holds no rule: the API decides who may do what, and every refusal is shown in words.

import { $, ApiError, api, boot, clear, el, enable, errorText, fieldApi, fillRows, has, status, t, when } from './staff.js';

const PAGE_SIZE = 50;
let ctx = null;
let current = null;
let working = false;
let rows = [];
let next = null;

function refusal(err) {
    if (err instanceof ApiError && has(`hh_e_${err.code}`)) return t(`hh_e_${err.code}`);
    return errorText(err, ['admin', 'gm', 'marshal']);
}

async function guarded(work) {
    if (working) return;
    working = true;
    try {
        await work();
    } catch (err) {
        if (!(err instanceof ApiError && err.code === 'not_authenticated')) status(refusal(err), 'error');
    } finally {
        working = false;
    }
}

function scores(teams) {
    return (Array.isArray(teams) ? teams : []).map((team) => `${team.team} ${team.score}`).join(' · ');
}

function showState(state) {
    current = state;
    $('hh-state').textContent = state.enabled
        ? t('hh_state_on', { since: state.since ? when(state.since, ctx.zone) : '', n: state.shared_games })
        : t('hh_state_off');
    const admin = ctx.roles.has('admin');
    $('hh-form').hidden = !admin;
    $('hh-admin-only').hidden = admin;
    $('hh-enabled').checked = Boolean(state.enabled);
    $('hh-off').hidden = Boolean(state.enabled);
    $('hh-list').hidden = !state.enabled;
}

function showGames() {
    $('hh-empty').hidden = rows.length > 0;
    if (!rows.length) {
        $('hh-table').hidden = true;
    } else {
        fillRows($('hh-table'), rows.map((g) => [
            g.own ? el('span', {}, g.field_name, ' ', el('span', { class: 'hint', text: t('hh_own') })) : g.field_name,
            el('code', { text: g.mode_id }),
            g.started_at ? when(g.started_at, ctx.zone) : t('none'),
            when(g.ended_at, ctx.zone),
            scores(g.teams),
            g.winner || t('hh_no_winner')]));
    }
    $('hh-more').hidden = !next;
}

function showFields(fields) {
    const list = clear($('hh-fields'));
    for (const f of fields || []) {
        const label = f.own ? t('hh_field_own', { field: f.field_name }) : f.field_name;
        list.append(el('li', {}, el('span', { class: 'title', text: label }),
            el('span', { class: 'when', text: t('hh_field_line', { since: when(f.since, ctx.zone), n: f.games }) })));
    }
}

async function loadGames(more = false) {
    if (!current || !current.enabled) return;
    const q = new URLSearchParams({ limit: String(PAGE_SIZE) });
    const mode = $('hh-mode').value.trim();
    if (mode) q.set('mode', mode);
    if (more && next) q.set('before', next);
    const body = await api('GET', fieldApi(`/hub-history?${q}`));
    rows = more ? rows.concat(body.games || []) : (body.games || []);
    next = body.next_before || null;
    showFields(body.fields);
    showGames();
}

async function save() {
    const enabled = $('hh-enabled').checked;
    if (enabled === Boolean(current.enabled)) {
        status(t('hh_unchanged'));
        return;
    }
    if (!enabled && !window.confirm(t('hh_off_confirm'))) {
        $('hh-enabled').checked = true;
        return;
    }
    status('');
    showState(await api('PUT', fieldApi('/hub-history/settings'), { enabled }));
    rows = [];
    next = null;
    await loadGames();
    status(t(enabled ? 'hh_saved_on' : 'hh_saved_off'), 'ok');
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    try {
        showState(await api('GET', fieldApi('/hub-history/settings')));
    } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'not_hosted') {
            $('hh-none').hidden = false;  // a single-field server: there is no other field to share with
            return;
        }
        status(refusal(err), 'error');
        return;
    }
    $('hh-main').hidden = false;
    enable($('hh-form'));
    enable($('hh-filter'));
    $('hh-form').addEventListener('submit', (event) => {
        event.preventDefault();
        guarded(save);
    });
    $('hh-filter').addEventListener('submit', (event) => {
        event.preventDefault();
        guarded(() => loadGames());
    });
    $('hh-more').addEventListener('click', () => guarded(() => loadGames(true)));
    await guarded(() => loadGames());
}

main();
