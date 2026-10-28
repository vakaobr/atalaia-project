// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The account's clubs (GET /api/v1/clubs: the clubs it belongs to, every club for a server administrator; GET
// /api/v1/me/clubs and POST .../me/clubs/{id}/accept: its invitations; POST /api/v1/clubs: a new club, whose
// admin the account becomes). Any account may; a club's page is /staff/clubs/{id}.

import { $, api, boot, el, enable, errorText, fillRows, link, status, t } from './staff.js';

const roleLabel = (role) => t(`club_role_${role}`);

async function accept(invite) {
    try {
        await api('POST', `/api/v1/me/clubs/${encodeURIComponent(invite.club_id)}/accept`, {});
        status(t('clubs_joined', { club: invite.name }), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
    }
    await load();
}

async function load() {
    let mine;
    let memberships;
    try {
        [mine, memberships] = await Promise.all([api('GET', '/api/v1/clubs'), api('GET', '/api/v1/me/clubs')]);
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    const invites = memberships.filter((m) => !m.accepted);
    $('invites').hidden = invites.length === 0;
    fillRows($('invites-table'), invites.map((m) => [m.name, roleLabel(m.role), el('button', {
        type: 'button', text: t('clubs_accept'), 'aria-label': `${t('clubs_accept')}: ${m.name}`, onclick: () => accept(m),
    })]));
    fillRows($('clubs-table'), mine.map((c) => [
        el('a', { href: link(`/staff/clubs/${encodeURIComponent(c.id)}`), text: c.name }), c.slug,
        roleLabel(c.my_role), c.hidden ? t('club_hidden_by_admin') : (c.public_page ? t('yes') : t('no'))]));
    $('clubs-table').hidden = mine.length === 0;
    $('clubs-none').hidden = mine.length > 0;
    return true;
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    const form = $('club-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = { name: $('c-name').value, short_name: $('c-short').value, slug: $('c-slug').value.trim() };
        if ($('c-description').value.trim()) body.description = $('c-description').value;
        if ($('c-colour').value.trim()) body.colour = $('c-colour').value.trim();
        try {
            const made = await api('POST', '/api/v1/clubs', body);
            location.assign(link(`/staff/clubs/${encodeURIComponent(made.id)}`));
            return;
        } catch (err) {
            status(errorText(err), 'error');
        }
        await load();
    });
    if (await load()) enable(form);
}

main();
