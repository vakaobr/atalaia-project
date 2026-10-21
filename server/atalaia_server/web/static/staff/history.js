// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field's game history (GET /api/v1/fields/{field}/history, newest first, 50 at a time) with its
// filters, and the history settings (GET and PUT .../history/settings: the field's admin changes them).

import {
    $, api, boot, el, enable, errorText, fieldApi, fieldPage, fillRows, stateName, status, t, when,
} from './staff.js';

const PAGE = 50;
let ctx = null;
let rows = [];
let before = null;

function teamName(team) {
    return team.display_name || team.team;
}

function dayStart(value, add = 0) {
    const date = new Date(`${value}T00:00:00`);
    date.setDate(date.getDate() + add);
    return date.toISOString();
}

function query() {
    const q = new URLSearchParams({ limit: String(PAGE) });
    const state = $('f-state').value;
    const mode = $('f-mode').value.trim();
    if (state) q.set('state', state);
    if (mode) q.set('mode', mode);
    if ($('f-since').value) q.set('since', dayStart($('f-since').value));
    if ($('f-until').value) q.set('until', dayStart($('f-until').value, 1));
    if (before) q.set('before', before);
    return q;
}

function row(game) {
    const scores = game.teams.map((team) => `${teamName(team)} ${team.score}`).join(' · ');
    let winner = t('none');
    if (game.state === 'ended') {
        const best = game.teams.find((team) => team.team === game.winner);
        winner = best ? teamName(best) : t('draw');
    }
    const state = [stateName(game.state)];
    if (game.delayed) state.push(' ', el('span', { class: 'badge', text: t('delayed') }));
    return [
        el('a', { href: fieldPage(`/games/${encodeURIComponent(game.id)}`), text: game.name }),
        el('code', { text: game.mode_id }), el('span', {}, state), when(game.started_at || game.created_at, ctx.zone),
        scores || t('none'), winner,
    ];
}

async function load(more = false) {
    if (!more) {
        rows = [];
        before = null;
    }
    let body;
    try {
        body = await api('GET', `${fieldApi('/history')}?${query()}`);
    } catch (err) {
        status(errorText(err, ['admin', 'gm', 'marshal', 'player', 'spectator']), 'error');
        return;
    }
    status('');
    rows = rows.concat(body.games.map(row));
    before = body.next_before;
    fillRows($('games'), rows);
    $('games').hidden = rows.length === 0;
    $('games-none').hidden = rows.length > 0;
    $('games-more').hidden = !before;
}

async function settings() {
    let body;
    try {
        body = await api('GET', fieldApi('/history/settings'));
    } catch (err) {
        return; // the settings are for the field's admin and gm only: the section stays hidden
    }
    $('settings').hidden = false;
    $('s-public').checked = Boolean(body.public_scoreboard);
    $('s-delay').value = body.spectator_delay_s;
    $('s-retention').value = body.retention_days;
    const form = $('settings-form');
    if (!ctx.roles.has('admin')) {
        $('settings-readonly').hidden = false;
        return;
    }
    enable(form);
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
            public_scoreboard: $('s-public').checked,
            spectator_delay_s: Number.parseInt($('s-delay').value, 10),
            retention_days: Number.parseInt($('s-retention').value, 10),
        };
        try {
            const saved = await api('PUT', fieldApi('/history/settings'), payload);
            $('s-public').checked = Boolean(saved.public_scoreboard);
            $('s-delay').value = saved.spectator_delay_s;
            $('s-retention').value = saved.retention_days;
            status(t('saved'), 'ok');
        } catch (err) {
            status(errorText(err, ['admin']), 'error');
        }
    });
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const filters = $('filters');
    enable(filters);
    filters.addEventListener('submit', (event) => {
        event.preventDefault();
        load();
    });
    $('games-more').addEventListener('click', () => load(true));
    await load();
    await settings();
}

main();
