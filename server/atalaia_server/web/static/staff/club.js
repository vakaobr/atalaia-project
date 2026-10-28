// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One club (GET, PATCH, DELETE /api/v1/clubs/{id}; PUT, DELETE .../images/{logo|crest}; GET, PUT .../members,
// DELETE .../members/{user_id}; and, for a server administrator, PUT, DELETE /api/v1/admin/clubs/{id}/hidden).
// A club is an organisation's profile, not an account; its admins edit it and its members, any member may leave.
// What each role may do is the API's: the forms are shown by the role the API names (my_role), as a hint.

import { $, api, boot, clear, el, enable, errorText, fillRows, link, page, status, t, when } from './staff.js';
import { imageBlock } from './imageblock.js';

const CLUB = `/api/v1/clubs/${encodeURIComponent(page.club)}`;
const ROLES = ['admin', 'member'];
const roleLabel = (role) => t(`club_role_${role}`);
let ctx = null;

function details(club) {
    const dl = clear($('club-details'));
    const rows = [[t('club_slug'), club.slug], [t('club_short'), club.short_name],
        [t('club_public'), club.public_page ? t('yes') : t('no')], [t('col_role'), club.my_role ? roleLabel(club.my_role) : t('none')]];
    if (club.hidden) rows.push([t('club_hidden_by_admin'), club.hidden_reason || t('none')]);
    for (const [k, v] of rows) dl.append(el('dt', { text: k }), el('dd', { text: v }));
}

/** The fields where the club plays (GET .../clubs/{id} `fields`: a member sees all, anyone else those with a public page). */
function fields(list) {
    const ul = clear($('club-fields-list'));
    for (const f of list || []) {
        const name = f.public_page ? el('a', { href: link(`/f/${encodeURIComponent(f.slug)}/`), text: f.name })
            : document.createTextNode(f.name);
        ul.append(el('li', {}, name, ` (${t(f.public_page ? 'club_field_public' : 'club_field_private')})`));
    }
    $('club-fields-none').hidden = Boolean(list && list.length);
}

async function loadMembers(club) {
    let members;
    try {
        members = await api('GET', `${CLUB}/members`);
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    const admin = club.my_role === 'admin';
    const me = ctx.session.user.username;
    fillRows($('members-table'), members.map((m) => {
        const self = m.username === me;
        const buttons = [];
        if (admin && !self) {
            const next = m.role === 'admin' ? 'member' : 'admin';
            buttons.push(el('button', {
                type: 'button', text: t(`club_make_${next}`), 'aria-label': `${t(`club_make_${next}`)}: ${m.username}`,
                onclick: () => act('PUT', `${CLUB}/members`, { username: m.username, role: next }, 'saved'),
            }));
        }
        if (admin || self) {
            buttons.push(el('button', {
                type: 'button', class: 'danger', text: t(self ? 'club_leave' : 'club_remove'),
                'aria-label': `${t(self ? 'club_leave' : 'club_remove')}: ${m.username}`,
                onclick: async () => {
                    if (!window.confirm(t(self ? 'club_leave_confirm' : 'club_remove_confirm', { user: m.username }))) return;
                    await act('DELETE', `${CLUB}/members/${encodeURIComponent(m.user_id)}`, undefined, 'saved', self);
                },
            }));
        }
        return [m.username, roleLabel(m.role), m.accepted ? t('club_member_joined', { when: when(m.accepted_at, ctx.zone) })
            : t('club_member_invited'), el('span', { class: 'actions' }, buttons)];
    }));
    $('members-table').hidden = members.length === 0;
}

async function act(method, path, body, ok, leaves = false) {
    try {
        await api(method, path, body);
        status(t(ok), 'ok');
        if (leaves) {
            location.assign(link('/staff/clubs'));
            return;
        }
    } catch (err) {
        status(errorText(err), 'error');
    }
    await load();
}

async function load() {
    let club;
    try {
        club = await api('GET', CLUB);
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    $('club-heading').textContent = club.name;
    details(club);
    fields(club.fields);
    const admin = club.my_role === 'admin';
    const member = Boolean(club.my_role);
    $('club-edit').hidden = !admin;
    $('club-members').hidden = !member;
    $('invite-form').hidden = !admin;
    $('club-delete').hidden = !admin;
    $('club-moderation').hidden = !(ctx.session.mfa && ctx.session.user.server_admin);
    if (admin) {
        if (!$('club-form').contains(document.activeElement)) {
            $('c-name').value = club.name;
            $('c-short').value = club.short_name;
            $('c-colour').value = club.colour || '';
            $('c-description').value = club.description || '';
            $('c-public').checked = club.public_page;
        }
        const images = clear($('club-images'));
        for (const slot of ['logo', 'crest']) {
            images.append(imageBlock({
                title: t(`club_image_${slot}`), image: club[slot], put: `${CLUB}/images/${slot}`,
                del: `${CLUB}/images/${slot}`, changed: load, roles: ['admin'],
            }));
        }
    }
    if (member) await loadMembers(club);
    return true;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    const form = $('club-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await act('PATCH', CLUB, {
            name: $('c-name').value, short_name: $('c-short').value, colour: $('c-colour').value,
            description: $('c-description').value, public_page: $('c-public').checked,
        }, 'saved');
    });
    const invite = $('invite-form');
    for (const role of ROLES) $('i-role').append(el('option', { value: role, text: roleLabel(role) }));
    invite.addEventListener('submit', async (event) => {
        event.preventDefault();
        await act('PUT', `${CLUB}/members`, { username: $('i-user').value.trim(), role: $('i-role').value }, 'club_invited');
        $('i-user').value = '';
    });
    $('club-delete-button').addEventListener('click', async () => {
        if (!window.confirm(t('club_delete_confirm', { name: $('club-heading').textContent }))) return;
        try {
            await api('DELETE', CLUB);
            location.assign(link('/staff/clubs'));
        } catch (err) {
            status(errorText(err), 'error');
        }
    });
    $('club-hide').addEventListener('click', () => act('PUT', `/api/v1/admin/clubs/${encodeURIComponent(page.club)}/hidden`,
        $('m-reason').value.trim() ? { reason: $('m-reason').value.trim() } : {}, 'club_hidden_done'));
    $('club-show').addEventListener('click', () => act('DELETE', `/api/v1/admin/clubs/${encodeURIComponent(page.club)}/hidden`,
        undefined, 'club_shown_done'));
    if (await load()) {
        enable(form);
        enable(invite);
    }
}

main();
