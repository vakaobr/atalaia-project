// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's settings, for its admin (GET /api/v1/fields for what is set now, PATCH /api/v1/fields/{field} to change
// it, GET /api/v1/apds?country= for the shipped list of the field's country): the public page, the check-in rules, the
// membership rule (protocol/apd.md: the accepted list or any, register, check-in, expiry, the field's own entries),
// chrono sharing, the country and how long chrono records and games are kept (decisions RET-1, RET-2). Each section is saved on its own and sends only its own members. Nothing here
// knows a rule: every refusal is the API's, shown in words (errorText). The membership words follow the country
// (membershipWording) and change on this page as soon as a new country is saved, with the list offered for it.

import { $, api, boot, clear, el, enable, errorText, fieldApi, membershipWording, status, t } from './staff.js';

const ADMIN = ['admin'];
// The elements whose text is an APD text with an association twin (redone when the country changes).
const WORDS = [['#fs-member-title', 'fs_member_title'], ['#fs-member-intro', 'fs_member_intro'],
    ['#m-any-label', 'fs_member_any'], ['#m-only-label', 'fs_member_only'], ['#fs-custom-title', 'fs_member_custom_title'],
    ['#fs-custom-intro', 'fs_member_custom_intro']];

let field = null;
let apds = [];  // the shipped entries of the field's country
let draft = null;  // the membership rule as edited here, not yet saved
let lastAccepted = [];  // the list kept while "any" is chosen

function copyRule(rule) {
    const r = rule || {};
    return {
        accepted: Array.isArray(r.accepted) ? [...r.accepted] : null, register: Boolean(r.register),
        checkin: Boolean(r.checkin), expiry: Boolean(r.expiry), custom: (r.custom || []).map((e) => ({ ...e })),
    };
}

async function save(body, done) {
    try {
        const updated = await api('PATCH', fieldApi(''), body);
        field = { ...field, ...updated };
        status(t(done), 'ok');
        return true;
    } catch (err) {
        status(errorText(err, ADMIN), 'error');
        return false;
    }
}

// The sharing terms (LEG-41): the version asked for, who accepted which version and when, and the box to tick.
function fillTerms() {
    const terms = field.sharing_terms || {};
    const version = terms.version || '';
    $('f-terms-doc').textContent = t('fs_terms_doc', { version });
    $('f-terms-label').textContent = t('fs_terms_accept', { version });
    $('f-terms').checked = Boolean(terms.current);  // already accepted at this version: ticked, nothing to repeat
    let state;
    if (!terms.accepted_version) state = t('fs_terms_none');
    else if (terms.current) {
        state = t('fs_terms_ok', { version, date: (terms.accepted_at || '').slice(0, 10), who: terms.accepted_by || '-' });
    } else state = t('fs_terms_stale', { accepted: terms.accepted_version, version });
    $('f-terms-state').textContent = state;
    $('f-chrono-state').textContent = field.chrono_sharing_enabled
        ? t(field.sharing_live ? 'fs_chrono_live' : 'fs_chrono_suspended') : '';
}

function fillForms() {
    $('f-public').checked = Boolean(field.public_page);
    $('f-description').value = field.description || '';
    $('f-address').value = field.address_text || '';
    $('f-fedlabel').value = field.federation_label || '';
    const select = $('f-template');
    if (field.limit_template && ![...select.options].some((o) => o.value === field.limit_template)) {
        select.append(el('option', { value: field.limit_template, text: field.limit_template }));
    }
    select.value = field.limit_template || '';
    $('f-replicas').value = field.max_replicas === null || field.max_replicas === undefined ? '' : field.max_replicas;
    $('f-chrono').checked = Boolean(field.chrono_sharing_enabled);
    fillTerms();
    $('f-country').value = field.country || '';
    $('f-chrono-days').value = field.chrono_retention_days ?? '';
    $('f-game-days').value = field.game_retention_days ?? '';
}

// ---- the membership section -----------------------------------------------------------------

function entryLabel(entry) {
    return entry.name ? `${entry.short_name} — ${entry.name}` : entry.id;
}

function renderMembership() {
    const any = draft.accepted === null;
    $('m-any').checked = any;
    $('m-only').checked = !any;
    $('m-register').checked = draft.register;
    $('m-checkin').checked = draft.checkin;
    $('m-expiry').checked = draft.expiry;
    $('m-offered').textContent = field.country ? t('fs_member_offered', { country: field.country })
        + (apds.length ? '' : ` ${t('fs_member_no_shipped')}`) : t('fs_member_no_country');
    // The offered entries, then the field's own, then any accepted id the lists do not have (kept, not lost).
    const entries = [...apds, ...draft.custom];
    const known = new Set(entries.map((e) => e.id));
    for (const id of draft.accepted || []) if (!known.has(id)) entries.push({ id });
    const list = clear($('m-entries'));
    entries.forEach((entry, i) => {
        const box = el('input', {
            type: 'checkbox', id: `m-e-${i}`, checked: !any && draft.accepted.includes(entry.id) ? true : null,
            disabled: any ? true : null,
            onchange: (event) => {
                const ids = new Set(draft.accepted);
                if (event.target.checked) ids.add(entry.id);
                else ids.delete(entry.id);
                draft.accepted = [...ids];
            },
        });
        list.append(el('li', { class: 'check' }, box, ' ', el('label', { for: `m-e-${i}`, text: entryLabel(entry) })));
    });
    const own = clear($('m-custom'));
    for (const entry of draft.custom) {
        own.append(el('li', { class: 'check' }, el('span', { text: `${entry.id} · ${entryLabel(entry)}` }), ' ',
            el('button', {
                type: 'button', class: 'danger', text: t('fs_remove'),
                onclick: () => {
                    draft.custom = draft.custom.filter((e) => e.id !== entry.id);
                    renderMembership();
                },
            })));
    }
    $('m-custom-none').hidden = draft.custom.length > 0;
}

async function loadApds() {
    apds = [];
    if (field.country) {
        try {
            const list = await api('GET', `/api/v1/apds?country=${encodeURIComponent(field.country)}`);
            apds = list.apds || [];
        } catch (err) {
            status(errorText(err, ADMIN), 'error');
        }
    }
}

function wireMembership() {
    for (const [id, key] of [['m-register', 'register'], ['m-checkin', 'checkin'], ['m-expiry', 'expiry']]) {
        $(id).addEventListener('change', (event) => {
            draft[key] = event.target.checked;
        });
    }
    $('m-any').addEventListener('change', () => {
        if (draft.accepted !== null) lastAccepted = draft.accepted;
        draft.accepted = null;
        renderMembership();
    });
    $('m-only').addEventListener('change', () => {
        draft.accepted = [...lastAccepted];
        renderMembership();
    });
    $('member-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!(await save({ apd: draft }, 'fs_saved_controllers'))) return;
        draft = copyRule(field.apd);
        renderMembership();
    });
    $('custom-form').addEventListener('submit', (event) => {
        event.preventDefault();
        const entry = { id: $('c-id').value.trim(), name: $('c-name').value.trim(), short_name: $('c-short').value.trim(),
            website: $('c-website').value.trim() || null };
        draft.custom = [...draft.custom, entry];
        $('custom-form').reset();
        status('');
        renderMembership();
    });
}

// ---- the other sections ---------------------------------------------------------------------

function wire() {
    $('public-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        await save({
            public_page: $('f-public').checked, description: $('f-description').value, address_text: $('f-address').value,
            federation_label: $('f-fedlabel').value,
        }, 'saved');
        fillForms();
    });
    $('checkin-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const replicas = $('f-replicas').value.trim();
        await save({ limit_template: $('f-template').value || null, max_replicas: replicas === '' ? null : Number(replicas) },
            'fs_saved_controllers');
        fillForms();
    });
    $('chrono-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        // Switching sharing on needs the box ticked: the acceptance (version, date, account) is recorded by the
        // server; it is also sent while sharing is on and the terms changed, to accept the new version.
        const accept = $('f-terms').checked ? { sharing_terms_accepted: (field.sharing_terms || {}).version } : {};
        // A refusal leaves the boxes as they are, so the person can tick the terms and press save again.
        if (await save({ chrono_sharing_enabled: $('f-chrono').checked, ...accept }, 'saved')) fillForms();
    });
    $('country-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!(await save({ country: $('f-country').value }, 'fs_saved_controllers'))) return;
        fillForms();
        membershipWording(field.country, WORDS);  // the words and the list change at once
        await loadApds();
        renderMembership();
    });
    $('retention-form').addEventListener('submit', async (event) => {
        event.preventDefault();
        const days = (id) => ($(id).value.trim() === '' ? null : Number(($(id).value.trim())));
        await save({ chrono_retention_days: days('f-chrono-days'), game_retention_days: days('f-game-days') },
            'fs_saved_controllers');
        fillForms();
    });
    wireMembership();
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    if (!ctx.field) {
        status(t('err_not_found'), 'error');
        return;
    }
    field = ctx.field;
    membershipWording(field.country, WORDS);
    draft = copyRule(field.apd);
    lastAccepted = draft.accepted || [];
    fillForms();
    await loadApds();
    renderMembership();
    wire();
    for (const id of ['public-form', 'checkin-form', 'member-form', 'custom-form', 'chrono-form', 'country-form', 'retention-form']) {
        enable($(id));
    }
}

main();
