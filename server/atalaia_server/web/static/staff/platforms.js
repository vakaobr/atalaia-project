// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's links to third-party platforms (GET /api/v1/integrations/adapters: what this server offers; GET
// /api/v1/fields/{field}/integrations, PUT, DELETE .../integrations/{adapter}), for the field's admin: each
// adapter's name, what it can do and the basis it uses (a documented API or an agreement, as the adapter states
// it), a link that is off until turned on, and its configuration, which is stored encrypted and never shown
// again (only which names are set, and the values that are not secret). Which names an adapter wants and which
// are secret come from the adapter.

import { $, api, boot, clear, el, errorText, fieldApi, status, t, when } from './staff.js';

let ctx = null;

async function call(method, adapter, body, done) {
    try {
        await api(method, fieldApi(`/integrations/${encodeURIComponent(adapter.id)}`), body);
        status(t(done, { name: adapter.name }), 'ok');
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
    }
    await load();
}

function adapterItem(adapter, link) {
    const prefix = `pl-${adapter.id.replace(/[^A-Za-z0-9_-]/g, '')}`;
    const inputs = adapter.config_keys.map((key) => {
        const secret = adapter.secret_keys.includes(key);
        const shown = link && link.config ? link.config[key] : undefined;
        const input = el('input', {
            id: `${prefix}-${key}`, name: key, type: secret ? 'password' : 'text', autocomplete: 'off',
            autocapitalize: 'none', spellcheck: 'false', value: secret || shown === undefined ? null : String(shown),
            placeholder: secret && shown === 'set' ? t('platform_secret_set') : null,
        });
        return [el('label', { for: `${prefix}-${key}`, text: key }), input, key];
    });
    const state = !link ? t('platform_not_linked')
        : t('platform_state', { enabled: link.enabled ? t('yes') : t('no'),
            configured: link.configured ? t('yes') : t('no') });
    const body = [el('h2', { text: adapter.name }),
        el('p', { class: 'hint', text: `${adapter.id} · ${adapter.capabilities.join(', ')}` }),
        el('p', { text: t('platform_basis', { basis: adapter.basis }) }), el('p', { text: state })];
    if (link && link.config_unreadable) body.push(el('p', { class: 'status error', text: t('platform_unreadable') }));
    if (link) body.push(el('p', { class: 'hint', text: t('platform_updated', { when: when(link.updated_at, ctx.zone) }) }));
    const save = el('button', {
        type: 'button', text: t('platform_save_config'),
        onclick: () => {
            const config = {};
            for (const [, input, key] of inputs) config[key] = input.value;
            return call('PUT', adapter, { config }, 'platform_config_saved');
        },
    });
    const form = el('fieldset', { class: 'commands' }, el('legend', { text: t('platform_config') }),
        el('p', { class: 'hint', text: t('platform_config_hint') }),
        inputs.flatMap(([label, input]) => [label, input]), inputs.length ? el('p', {}, save) : el('p', { text: t('platform_no_config') }));
    body.push(form);
    if (link) {
        const toggle = el('button', {
            type: 'button', text: t(link.enabled ? 'platform_disable' : 'platform_enable'),
            onclick: () => call('PUT', adapter, { enabled: !link.enabled }, link.enabled ? 'platform_disabled' : 'platform_enabled'),
        });
        const remove = el('button', {
            type: 'button', class: 'danger', text: t('platform_remove'),
            onclick: () => {
                if (window.confirm(t('platform_remove_confirm', { name: adapter.name }))) call('DELETE', adapter, undefined, 'platform_removed');
            },
        });
        body.push(el('p', {}, toggle, ' ', remove));
    }
    return el('article', { class: 'controller' }, body);
}

async function load() {
    let adapters;
    let links;
    try {
        [adapters, links] = await Promise.all([api('GET', '/api/v1/integrations/adapters'),
            api('GET', fieldApi('/integrations'))]);
    } catch (err) {
        status(errorText(err, ['admin']), 'error');
        return;
    }
    const box = clear($('adapters'));
    const byId = new Map(links.map((l) => [l.adapter_id, l]));
    for (const adapter of adapters) box.append(adapterItem(adapter, byId.get(adapter.id) || null));
    $('adapters-none').hidden = adapters.length > 0;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    await load();
}

main();
