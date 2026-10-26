// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The fields the account has a role on (GET /api/v1/fields; every field for a server admin), each
// with the sections its roles reach in this session.

import { $, api, boot, clear, effectiveRoles, el, errorText, link, page, roleName, sectionAllowed, status, t } from './staff.js';

const SECTIONS = [
    ['history', '/history', 'nav_history'], ['scenarios', '/scenarios', 'nav_scenarios'],
    ['presets', '/presets', 'nav_presets'], ['devices', '/devices', 'nav_devices'], ['remote', '/remote-gm', 'nav_remote'],
    ['atak', '/atak', 'nav_atak'],
];

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    const list = $('fields');
    if (page.preview === '1' && ctx.session.user.server_admin) {  // a preview server's feedback (PV-8)
        $('feedback-link').hidden = false;
        $('feedback-link').firstChild.setAttribute('href', link('/staff/feedback'));
    }
    let fields;
    try {
        fields = await api('GET', '/api/v1/fields');
    } catch (err) {
        list.removeAttribute('aria-busy');
        status(errorText(err), 'error');
        return;
    }
    list.removeAttribute('aria-busy');
    clear(list);
    const privileged = fields.some((f) => (f.my_roles || []).some((r) => ['admin', 'gm', 'marshal'].includes(r)));
    $('mfa-note').hidden = ctx.session.mfa || !(privileged || ctx.session.user.server_admin);
    if (!fields.length) {
        list.replaceWith(el('p', { text: t('home_none') }));
        return;
    }
    for (const field of fields) {
        const roles = effectiveRoles(field, ctx.session);
        const names = (field.my_roles || []).map(roleName);
        if (ctx.session.user.server_admin) names.push(t('server_admin'));
        const links = SECTIONS.filter(([name]) => sectionAllowed(name, roles)).map(([, path, label]) => el('li', {},
            el('a', { href: link(`/staff/fields/${encodeURIComponent(field.id)}${path}`), text: t(label) })));
        list.append(el('li', {},
            el('span', { class: 'title', text: field.name }), ' ',
            el('span', { class: 'when', text: `${t('roles')}: ${names.join(', ') || t('none')}` }),
            links.length ? el('ul', { class: 'links' }, links) : null));
    }
}

main();
