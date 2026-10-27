// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field's scheduled games (GET, POST /api/v1/fields/{field}/scheduled-games; PATCH, DELETE
// .../{id}; POST .../{id}/publish and .../cancel): list them (upcoming, past, all), create a draft, edit a
// draft or a published game, delete a draft, and, for the field's admin, publish and cancel. The rules are
// the API's; this page only asks. Times are typed and shown in the field's time zone.

import {
    $, api, boot, el, enable, errorText, fieldApi, fieldPage, fillRows, status, t, when, zonedInput, zonedIso,
} from './staff.js';

const EDITABLE = ['draft', 'published'];
let ctx = null;
let editing = null;
let cancelling = null;

function resetForm() {
    editing = null;
    $('game-form-title').textContent = t('sched_new');
    $('game-form').reset();
    $('g-submit').textContent = t('sched_create');
    $('g-cancel').hidden = true;
}

function edit(game) {
    editing = game.id;
    $('game-form-title').textContent = t('sched_edit', { title: game.title });
    $('g-title').value = game.title;
    $('g-description').value = game.description || '';
    $('g-starts').value = zonedInput(game.starts_at, ctx.zone);
    $('g-ends').value = zonedInput(game.ends_at, ctx.zone);
    $('g-location').value = game.location_text || '';
    $('g-mode').value = game.mode_id || '';
    $('g-teams').value = (game.teams || []).join('\n');
    $('g-max').value = game.max_players === null ? '' : String(game.max_players);
    $('g-opens').value = zonedInput(game.registration_opens_at, ctx.zone);
    $('g-closes').value = zonedInput(game.registration_closes_at, ctx.zone);
    $('g-federation').value = game.federation;
    $('g-replicas').checked = Boolean(game.predeclare_replicas);
    $('g-submit').textContent = t('save');
    $('g-cancel').hidden = false;
    $('game-form-title').scrollIntoView({ block: 'start' });
    $('g-title').focus();
}

function closeCancel() {
    cancelling = null;
    $('cancel-section').hidden = true;
    $('c-reason').value = '';
}

function openCancel(game) {
    cancelling = game;
    $('cancel-title').textContent = t('sched_cancel_title', { title: game.title });
    $('cancel-section').hidden = false;
    $('c-reason').focus();
}

/** One call, then the list again; the message in words when the API refuses. */
async function act(method, path, body, done, roles) {
    try {
        await api(method, path, body);
    } catch (err) {
        status(errorText(err, roles), 'error');
        return false;
    }
    status(done, 'ok');
    await load();
    return true;
}

async function publish(game) {
    if (!window.confirm(t('sched_publish_confirm', { title: game.title }))) return;
    await act('POST', fieldApi(`/scheduled-games/${encodeURIComponent(game.id)}/publish`), undefined, t('sched_published'), ['admin']);
}

async function remove(game) {
    if (!window.confirm(t('sched_delete_confirm', { title: game.title }))) return;
    if (await act('DELETE', fieldApi(`/scheduled-games/${encodeURIComponent(game.id)}`), undefined, t('sched_deleted'))
        && editing === game.id) resetForm();
}

function places(game) {
    return game.max_players === null
        ? t('sched_places_nolimit', { n: game.registered })
        : t('sched_places', { n: game.registered, max: game.max_players });
}

function actions(game) {
    const id = encodeURIComponent(game.id);
    const label = (key) => ({ 'aria-label': `${t(key)}: ${game.title}` });
    const out = [];
    const add = (node) => {
        if (out.length) out.push(' ');
        out.push(node);
    };
    if (game.status !== 'draft') {
        add(el('a', { class: 'button', href: fieldPage(`/schedule/${id}/registrations`), text: t('sched_registrations'),
            ...label('sched_registrations') }));
        add(el('a', { class: 'button', href: fieldPage(`/schedule/${id}/roster`), text: t('sched_roster'),
            ...label('sched_roster') }));
    }
    if (EDITABLE.includes(game.status)) {
        add(el('button', { type: 'button', text: t('edit'), ...label('edit'), onclick: () => edit(game) }));
    }
    if (game.status === 'draft' && ctx.roles.has('admin')) {
        add(el('button', { type: 'button', text: t('sched_publish'), ...label('sched_publish'),
            onclick: () => publish(game) }));
    }
    if (game.status === 'published' && ctx.roles.has('admin')) {
        add(el('button', { type: 'button', class: 'danger', text: t('sched_cancel'), ...label('sched_cancel'),
            onclick: () => openCancel(game) }));
    }
    if (game.status === 'draft') {
        add(el('button', { type: 'button', class: 'danger', text: t('sched_delete'), ...label('sched_delete'),
            onclick: () => remove(game) }));
    }
    return el('span', { class: 'actions' }, out);
}

async function load() {
    const view = $('v-view').value;
    const now = new Date();
    let path = fieldApi('/scheduled-games');
    if (view === 'upcoming') path += `?from=${encodeURIComponent(now.toISOString())}`;
    let list;
    try {
        list = await api('GET', path);
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    if (view === 'past') list = list.filter((g) => new Date(g.ends_at) <= now).reverse();
    fillRows($('schedule'), list.map((g) => [
        g.title, when(g.starts_at, ctx.zone), t(`sched_status_${g.status}`), places(g),
        g.status === 'draft' ? t('none') : t(`reg_window_${g.registration_state || 'none'}`), actions(g)]));
    $('schedule').hidden = list.length === 0;
    $('schedule-none').hidden = list.length > 0;
    return true;
}

function body() {
    const zone = ctx.zone;
    const starts = zonedIso($('g-starts').value, zone);
    const ends = zonedIso($('g-ends').value, zone);
    if (!starts || !ends) {
        status(t('form_times_needed'), 'error');
        $(starts ? 'g-ends' : 'g-starts').focus();
        return null;
    }
    const maxText = $('g-max').value.trim();
    const max = maxText === '' ? null : Number(maxText);
    if (max !== null && !(Number.isInteger(max) && max >= 1 && max <= 10000)) {
        status(t('form_max_bad'), 'error');
        $('g-max').focus();
        return null;
    }
    const orNull = (text) => (text.trim() === '' ? null : text.trim());
    return {
        title: $('g-title').value.trim(),
        description: orNull($('g-description').value),
        starts_at: starts,
        ends_at: ends,
        location_text: orNull($('g-location').value),
        mode_id: orNull($('g-mode').value),
        teams: $('g-teams').value.split('\n').map((s) => s.trim()).filter((s) => s !== ''),
        max_players: max,
        registration_opens_at: zonedIso($('g-opens').value, zone),
        registration_closes_at: zonedIso($('g-closes').value, zone),
        federation: $('g-federation').value,
        predeclare_replicas: $('g-replicas').checked,
    };
}

async function submit(event) {
    event.preventDefault();
    const data = body();
    if (data === null) return;
    const was = editing;
    try {
        if (was) await api('PATCH', fieldApi(`/scheduled-games/${encodeURIComponent(was)}`), data);
        else await api('POST', fieldApi('/scheduled-games'), data);
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    resetForm();
    status(was ? t('saved') : t('sched_created'), 'ok');
    await load();
}

async function submitCancel(event) {
    event.preventDefault();
    if (!cancelling) return;
    const game = cancelling;
    const ok = await act('POST', fieldApi(`/scheduled-games/${encodeURIComponent(game.id)}/cancel`),
        { reason: $('c-reason').value.trim() }, t('sched_cancelled'), ['admin']);
    if (ok) closeCancel();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    $('zone-note').textContent = t('schedule_zone', {
        zone: ctx.zone || Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    if (!(await load())) return;
    for (const id of ['view-form', 'game-form']) enable($(id));
    $('view-form').addEventListener('submit', (event) => {
        event.preventDefault();
        load();
    });
    $('game-form').addEventListener('submit', submit);
    $('g-cancel').addEventListener('click', resetForm);
    $('cancel-form').addEventListener('submit', submitCancel);
    $('c-back').addEventListener('click', closeCancel);
}

main();
