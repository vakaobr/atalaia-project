// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's branding and saved teams, which its controllers pull (GET, PATCH /api/v1/fields/{field}/branding,
// PUT, DELETE .../branding/{logo|wallpaper}; GET, POST .../teams, PATCH, DELETE .../teams/{id}, PUT, DELETE
// .../teams/{id}/crest). The field's name and accent colour and its two images are the admin's; the teams
// (own name, colour, crest, or a club's) are the admin's and the gm's. The limits are the API's.

import { $, api, boot, clear, el, enable, errorText, fieldApi, status, t } from './staff.js';
import { imageBlock } from './imageblock.js';

const ADMIN = ['admin'];

function teamItem(team) {
    const name = el('input', { id: `tn-${team.team_id}`, value: team.own_name || '', maxlength: $('t-name').maxLength,
        autocomplete: 'off', placeholder: team.club ? team.name : '' });
    const colour = el('input', { id: `tc-${team.team_id}`, value: team.colour || '', maxlength: $('t-colour').maxLength,
        autocapitalize: 'none', spellcheck: 'false', autocomplete: 'off' });
    const base = `/teams/${encodeURIComponent(team.team_id)}`;
    const save = el('button', {
        type: 'button', text: t('save'),
        onclick: async () => {
            try {
                await api('PATCH', fieldApi(base), { name: name.value, colour: colour.value });
                status(t('saved'), 'ok');
            } catch (err) {
                status(errorText(err), 'error');
            }
            await load();
        },
    });
    const remove = el('button', {
        type: 'button', class: 'danger', text: t('delete'),
        onclick: async () => {
            if (!window.confirm(t('team_delete_confirm', { name: team.name }))) return;
            try {
                await api('DELETE', fieldApi(base));
                status(t('saved'), 'ok');
            } catch (err) {
                status(errorText(err), 'error');
            }
            await load();
        },
    });
    const crest = imageBlock({
        title: t('team_crest'), image: team.crest, put: fieldApi(`${base}/crest`), del: fieldApi(`${base}/crest`),
        changed: load, roles: ['admin', 'gm'],
        note: team.club ? t(team.own_crest ? 'team_crest_own' : 'team_crest_club', { club: team.club.name }) : null,
    });
    return el('li', {}, el('fieldset', { class: 'team' },
        el('legend', { text: team.club ? `${team.name} (${team.club.name})` : team.name }),
        el('label', { for: `tn-${team.team_id}`, text: t('team_name') }), name,
        el('label', { for: `tc-${team.team_id}`, text: t('team_colour') }), colour,
        el('p', {}, save, ' ', remove), crest));
}

async function loadTeams() {
    let teams;
    try {
        teams = await api('GET', fieldApi('/teams'));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    const list = clear($('teams'));
    for (const team of teams) list.append(teamItem(team));
    $('teams-none').hidden = teams.length > 0;
}

async function load() {
    let branding;
    try {
        branding = await api('GET', fieldApi('/branding'));
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    if (document.activeElement !== $('b-name')) $('b-name').value = branding.field_name || '';
    if (document.activeElement !== $('b-accent')) $('b-accent').value = branding.accent || '';
    const images = clear($('branding-images'));
    for (const slot of ['logo', 'wallpaper']) {
        images.append(imageBlock({
            title: t(`image_${slot}`), image: branding[slot], put: fieldApi(`/branding/${slot}`),
            del: fieldApi(`/branding/${slot}`), changed: load, roles: ADMIN,
        }));
    }
    await loadTeams();
    return true;
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    const form = $('branding-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await api('PATCH', fieldApi('/branding'), { field_name: $('b-name').value, accent: $('b-accent').value });
            status(t('saved'), 'ok');
        } catch (err) {
            status(errorText(err, ADMIN), 'error');
        }
        await load();
    });
    const teamForm = $('team-form');
    teamForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const body = {};
        for (const [field, id] of [['name', 't-name'], ['colour', 't-colour'], ['club_slug', 't-club']]) {
            if ($(id).value.trim()) body[field] = $(id).value.trim();
        }
        try {
            await api('POST', fieldApi('/teams'), body);
            status(t('saved'), 'ok');
            teamForm.reset();
        } catch (err) {
            status(errorText(err), 'error');
        }
        await loadTeams();
    });
    if (await load()) {
        enable(form);
        enable(teamForm);
    }
}

main();
