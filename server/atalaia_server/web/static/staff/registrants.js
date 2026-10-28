// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Shared by the registrations page and the roster page: the scheduled game and its registrations from the
// API (admin or gm only: the API refuses anyone else), the game's summary, and a registration's replicas.

import { api, clear, el, fieldApi, has, membershipWording, page, t, when } from './staff.js';

/** The game (GET .../scheduled-games/{id}) and its registrations (GET .../registrations), in that order. */
export async function loadBoth() {
    const id = encodeURIComponent(page.game);
    const game = await api('GET', fieldApi(`/scheduled-games/${id}`));
    const list = await api('GET', fieldApi(`/scheduled-games/${id}/registrations`));
    membershipWording(list.country, [['#th-fed', 'col_fed_number'], ['label[for="r-apd"]', 'reg_edit_apd']]);
    return { game, list };
}

/** Whether staff may still change or withdraw a registration: the API's rule (a published game not started). */
export function changeable(game) {
    return game.status === 'published' && new Date(game.starts_at) > new Date();
}

/** Whether the game is over, when staff may mark who did not come: the API's rule (not cancelled, and
 * completed or past its end). */
export function over(game) {
    return game.status !== 'cancelled' && (game.status === 'completed' || new Date(game.ends_at) <= new Date());
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

/** Whether the membership column shows: the game asks for the federation number or the field's rule asks for an
 * APD membership at registration or check-in (protocol/apd.md). */
export function asksMembership(game, list) {
    const rule = list.apd || {};
    return game.federation !== 'off' || Boolean(rule.register || rule.checkin);
}

/** The APDs a registration may name: the project's, then the field's own. */
export function apdChoices(list) {
    return [...(list.apds || []), ...((list.apd || {}).custom || [])];
}

/** A registration's membership as text: the APD, the number, the expiry and the verdict when a rule asks. */
export function membershipText(reg, list) {
    if (!reg.federation_number && !reg.apd_id && !reg.membership_expires) {
        return reg.apd_status ? t(`apd_status_${reg.apd_status}`) : t('none');
    }
    const apd = apdChoices(list).find((e) => e.id === reg.apd_id);
    const parts = [reg.apd_id ? (apd ? apd.short_name : reg.apd_id) : t('apd_unknown'), reg.federation_number || t('none')];
    if (reg.membership_expires) parts.push(`${t('apd_expires')} ${reg.membership_expires}`);
    const text = parts.join(' · ');
    return reg.apd_status ? `${text} — ${t(`apd_status_${reg.apd_status}`)}` : text;
}

export function ticketText(reg) {
    return reg.has_ticket ? t('ticket_yes') : t('ticket_no');
}
