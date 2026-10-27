// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Shared by the registrations page and the roster page: the scheduled game and its registrations from the
// API (admin or gm only: the API refuses anyone else), the game's summary, and a registration's replicas.

import { api, clear, el, fieldApi, has, page, t, when } from './staff.js';

/** The game (GET .../scheduled-games/{id}) and its registrations (GET .../registrations), in that order. */
export async function loadBoth() {
    const id = encodeURIComponent(page.game);
    const game = await api('GET', fieldApi(`/scheduled-games/${id}`));
    const list = await api('GET', fieldApi(`/scheduled-games/${id}/registrations`));
    return { game, list };
}

/** Whether staff may still change or withdraw a registration: the API's rule (a published game not started). */
export function changeable(game) {
    return game.status === 'published' && new Date(game.starts_at) > new Date();
}

function row(dl, label, value) {
    dl.append(el('dt', { text: label }), el('dd', {}, value));
}

/** The game's facts, as a description list. */
export function summarise(dl, game, zone) {
    clear(dl);
    row(dl, t('col_title'), game.title);
    row(dl, t('col_starts'), when(game.starts_at, zone));
    row(dl, t('col_ends'), when(game.ends_at, zone));
    row(dl, t('col_state'), t(`sched_status_${game.status}`));
    row(dl, t('col_teams'), (game.teams || []).join(', ') || t('none'));
    row(dl, t('col_registered'), game.max_players === null
        ? t('sched_places_nolimit', { n: game.registered })
        : t('sched_places', { n: game.registered, max: game.max_players }));
    row(dl, t('f_federation'), t(`fed_${game.federation}`));
}

/** A registration's replicas: one line each (type, class, make and model, and the final state once known). */
export function replicaCell(replicas, withState) {
    if (!replicas || !replicas.length) return t('none');
    return el('ul', { class: 'compact' }, replicas.map((r) => {
        const parts = [r.type, r.class];
        if (r.make_model) parts.push(r.make_model);
        const state = withState && r.state && has(`replica_state_${r.state}`) ? ` (${t(`replica_state_${r.state}`)})` : '';
        return el('li', { text: `${parts.join(', ')}${state}` });
    }));
}

export function ticketText(reg) {
    return reg.has_ticket ? t('ticket_yes') : t('ticket_no');
}
