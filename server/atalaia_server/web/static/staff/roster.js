// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One scheduled game's game-day roster, as the controller pulls it (GET /api/v1/sync/roster: the game's
// active registrations with a name, in the order they were made, each with only what the check-in holds; the
// federation number only when the game asks for one), made from the staff list the API gives the field's admin
// and gm (the controller's own endpoint wants the field's API key, which no page has). Printable: the page's
// print style sheet keeps the table. The ticket's hash is never shown, only whether there is one.
// The server records when a controller last pulled the roster, with the key it used and its program (FU7).

import { $, boot, errorText, fieldPage, fillRows, page, status, t, when } from './staff.js';
import { loadBoth, replicaCell, summarise, ticketText } from './registrants.js';

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    let loaded;
    try {
        loaded = await loadBoth();
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    const { game, list } = loaded;
    const id = encodeURIComponent(page.game);
    $('back').setAttribute('href', fieldPage('/schedule'));
    $('regs-href').setAttribute('href', fieldPage(`/schedule/${id}/registrations`));
    $('roster-heading').textContent = t('roster_heading', { title: game.title });
    summarise($('summary'), game, ctx.zone);
    const meta = [t('roster_as_of', { at: when(new Date().toISOString(), ctx.zone) }),
        `${t('roster_linked')}: ${game.controller_game ? t('roster_linked_yes') : t('roster_linked_no')}`];
    if (game.walkins !== null && game.walkins !== undefined) meta.push(`${t('roster_walkins')}: ${game.walkins}`);
    const pull = game.roster_pull;
    if (game.status === 'draft') {
        $('roster-pull').hidden = true;
    } else if (pull) {
        const key = pull.key_label ? `${pull.key_label} (${pull.key_fingerprint})` : (pull.key_fingerprint
            ? `${t('roster_key_unnamed')} (${pull.key_fingerprint})` : t('none'));
        $('roster-pull').textContent = `${t('roster_pulled', { at: when(pull.at, ctx.zone) })} ${t('roster_pulled_by', {
            key, agent: pull.agent || t('none') })}`;
    } else {
        $('roster-pull').textContent = t('roster_not_pulled');
    }
    const asks = game.federation !== 'off';
    $('th-fed').hidden = !asks;
    $('print').disabled = false;
    $('print').addEventListener('click', () => window.print());
    if (game.status === 'draft') {
        $('roster-draft').hidden = false;
        $('roster-meta').textContent = meta.join(' · ');
        return;
    }
    const roster = (list.registrations || []).filter((r) => r.status === 'registered' && r.display_name);
    meta.unshift(t('roster_count', { n: roster.length }));
    $('roster-meta').textContent = meta.join(' · ');
    fillRows($('roster'), roster.map((r, i) => [
        [String(i + 1), { class: 'num' }], r.display_name, r.team_preference || t('none'), r.player_id,
        ...(asks ? [r.federation_number || t('none')] : []), replicaCell(r.replicas, false), ticketText(r), '☐']));
    $('roster').hidden = roster.length === 0;
    $('roster-none').hidden = roster.length > 0;
}

main();
