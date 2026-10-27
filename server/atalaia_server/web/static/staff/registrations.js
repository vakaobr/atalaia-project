// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Who registered for one scheduled game (GET /api/v1/fields/{field}/scheduled-games/{id}/registrations, for
// the field's admin and gm), and what the API lets staff do until the game starts: change a registration's
// display name, team preference or federation number (PATCH .../registrations/{reg}) and withdraw it (DELETE).
// Nothing else is offered: the controller decides on the day, and the outcomes come from it.

import { $, boot, clear, el, enable, errorText, api, fieldApi, fieldPage, fillRows, page, status, t } from './staff.js';
import { changeable, loadBoth, replicaCell, summarise, ticketText } from './registrants.js';

const base = () => `/scheduled-games/${encodeURIComponent(page.game)}/registrations`;
let ctx = null;
let game = null;
let editing = null;

function closeEdit() {
    editing = null;
    $('reg-edit').hidden = true;
}

function edit(reg) {
    editing = reg;
    $('reg-edit-title').textContent = t('reg_edit_title', { name: reg.display_name || '' });
    $('r-name').value = reg.display_name || '';
    const select = clear($('r-team'));
    select.append(el('option', { value: '', text: t('reg_team_none') }));
    for (const team of game.teams || []) select.append(el('option', { value: team, text: team }));
    select.value = reg.team_preference || '';
    $('r-fed-row').hidden = game.federation === 'off';
    $('r-fed').value = reg.federation_number || '';
    $('reg-edit').hidden = false;
    $('reg-edit-title').scrollIntoView({ block: 'start' });
    $('r-name').focus();
}

async function withdraw(reg) {
    if (!window.confirm(t('reg_withdraw_confirm', { name: reg.display_name || '' }))) return;
    try {
        await api('DELETE', fieldApi(`${base()}/${encodeURIComponent(reg.id)}`));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    if (editing && editing.id === reg.id) closeEdit();
    status(t('reg_withdrawn'), 'ok');
    await load();
}

function actions(reg) {
    if (reg.status !== 'registered' || !changeable(game)) return '';
    const who = reg.display_name || '';
    return el('span', { class: 'actions' },
        el('button', { type: 'button', text: t('edit'), 'aria-label': `${t('edit')}: ${who}`, onclick: () => edit(reg) }), ' ',
        el('button', { type: 'button', class: 'danger', text: t('reg_withdraw'), 'aria-label': `${t('reg_withdraw')}: ${who}`,
            onclick: () => withdraw(reg) }));
}

async function load() {
    let loaded;
    try {
        loaded = await loadBoth();
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    game = loaded.game;
    const { list } = loaded;
    $('regs-heading').textContent = t('regs_heading', { title: game.title });
    summarise($('summary'), game, ctx.zone);
    const counts = list.counts || {};
    const text = t('regs_counts', {
        registered: counts.registered || 0, checked_in: counts.checked_in || 0, no_show: counts.no_show || 0,
        cancelled: counts.cancelled || 0,
    });
    $('counts').textContent = list.walkins === null || list.walkins === undefined ? text
        : `${text} ${t('regs_walkins', { n: list.walkins })}`;
    $('locked').hidden = changeable(game);
    const roster = $('roster-link');
    roster.hidden = game.status === 'draft';
    roster.firstChild.setAttribute('href', fieldPage(`/schedule/${encodeURIComponent(page.game)}/roster`));
    const asks = game.federation !== 'off';
    $('th-fed').hidden = !asks;
    const regs = list.registrations || [];
    fillRows($('regs'), regs.map((r) => [
        r.display_name || t('none'), r.team_preference || t('none'), ...(asks ? [r.federation_number || t('none')] : []),
        replicaCell(r.replicas, true), ticketText(r), t(`reg_status_${r.status}`), r.source === 'site' ? t('source_site') : r.source,
        actions(r)]));
    $('regs').hidden = regs.length === 0;
    $('regs-none').hidden = regs.length > 0;
    return true;
}

async function submit(event) {
    event.preventDefault();
    if (!editing) return;
    const reg = editing;
    const body = {};
    const name = $('r-name').value.trim();
    if (name !== (reg.display_name || '')) body.display_name = name;
    const team = $('r-team').value;
    if (team !== (reg.team_preference || '')) body.team_preference = team === '' ? null : team;
    const fed = $('r-fed').value.trim();
    if (game.federation !== 'off' && fed !== (reg.federation_number || '')) body.federation_number = fed === '' ? null : fed;
    if (Object.keys(body).length) {
        try {
            await api('PATCH', fieldApi(`${base()}/${encodeURIComponent(reg.id)}`), body);
        } catch (err) {
            status(errorText(err), 'error');
            return;
        }
    }
    closeEdit();
    status(t('saved'), 'ok');
    await load();
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (!(await load())) return;
    $('back').setAttribute('href', fieldPage('/schedule'));
    enable($('reg-form'));
    $('reg-form').addEventListener('submit', submit);
    $('r-cancel').addEventListener('click', closeEdit);
}

main();
