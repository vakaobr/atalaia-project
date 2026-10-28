// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The roles table and the grant form, shared by a field's roles page and a game's: both APIs have the same
// three calls under their base path (GET list, PUT {username, role}, DELETE .../{user_id}/{role}) and the same
// rules, which the API keeps (who may grant which role, TOTP for admin, gm and marshal): the page offers every
// role and shows the API's refusal in words.

import { $, api, el, enable, errorText, fillRows, roleName, status, t, when } from './staff.js';

const ROLES = ['player', 'squad_leader', 'vip', 'marshal', 'gm', 'spectator', 'admin'];

export async function mount(base, zone) {
    const select = $('g-role');
    for (const role of ROLES) select.append(el('option', { value: role, text: roleName(role) }));

    async function load() {
        let rows;
        try {
            rows = await api('GET', base);
        } catch (err) {
            status(errorText(err), 'error');
            return false;
        }
        fillRows($('roles-table'), rows.map((r) => [r.username, roleName(r.role), when(r.granted_at, zone), el('button', {
            type: 'button', class: 'danger', text: t('revoke'),
            'aria-label': `${t('revoke')}: ${r.username}, ${roleName(r.role)}`,
            onclick: () => revoke(r),
        })]));
        $('roles-table').hidden = rows.length === 0;
        $('roles-none').hidden = rows.length > 0;
        return true;
    }

    async function revoke(row) {
        if (!window.confirm(t('roles_revoke_confirm', { user: row.username, role: roleName(row.role) }))) return;
        try {
            await api('DELETE', `${base}/${encodeURIComponent(row.user_id)}/${encodeURIComponent(row.role)}`);
            status(t('roles_revoked', { user: row.username, role: roleName(row.role) }), 'ok');
        } catch (err) {
            status(errorText(err), 'error');
        }
        await load();
    }

    const form = $('grant-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const username = $('g-user').value.trim();
        const role = select.value;
        try {
            await api('PUT', base, { username, role });
            status(t('roles_granted', { user: username, role: roleName(role) }), 'ok');
            $('g-user').value = '';
        } catch (err) {
            status(errorText(err), 'error');
        }
        await load();
    });
    if (await load()) enable(form);
}
