// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's chrono violations and the rules on them (PRIV-2): GET /api/v1/fields/{field}/chrono/violations, the outcome a
// field's admin or gm records (PATCH .../chrono/violations/{id}), and the two rules in PATCH /api/v1/fields/{field}
// (how long a ban lasts). The "earlier violation" mark is
// shown as a notice for whoever decides, never as a verdict: the wording is in the page's texts, not decided here.

import { $, api, boot, el, enable, errorText, fieldApi, fillRows, status, t, when } from './staff.js';

const OUTCOMES = ['warning', 'pulled', 'ban'];
let ctx = null;

function banCell(v) {
    if (v.outcome !== 'ban') return '';
    if (!v.ban_expires_at) return t('none');
    return v.ban_active ? t('chrono_ban_until', { when: when(v.ban_expires_at, ctx.zone) })
        : t('chrono_ban_ended', { when: when(v.ban_expires_at, ctx.zone) });
}

function flagCell(v) {
    if (!v.repeat_offender) return '';
    return el('span', { class: 'hint', title: t('chrono_flag_repeat_note'), text: t('chrono_flag_repeat') });
}

function decideCell(v) {
    if (!(ctx.roles.has('admin') || ctx.roles.has('gm'))) return '';
    const select = el('select', { 'aria-label': t('chrono_choose') },
        ...OUTCOMES.map((o) => el('option', { value: o, text: t(`chrono_outcome_${o}`) })));
    select.value = v.outcome || 'warning';
    const button = el('button', {
        type: 'button', text: t('chrono_record'), onclick: async () => {
            try {
                await api('PATCH', fieldApi(`/chrono/violations/${encodeURIComponent(v.id)}`), { outcome: select.value });
                status(t('chrono_recorded'), 'ok');
            } catch (err) {
                status(errorText(err, ['admin', 'gm']), 'error');
            }
            await load();
        },
    });
    return el('span', {}, select, ' ', button);
}

async function load() {
    let rows;
    try {
        rows = await api('GET', fieldApi('/chrono/violations'));
    } catch (err) {
        status(errorText(err, ['admin', 'gm', 'marshal']), 'error');
        return false;
    }
    fillRows($('viol-table'), rows.map((v) => [
        when(v.created_at, ctx.zone), [el('code', { class: 'data', text: v.player_id }), {}],
        t(`chrono_type_${v.violation_type}`),
        [v.energy_j === null ? t('none') : v.energy_j.toFixed(2), { class: 'num' }],
        [v.delta_j === null ? t('none') : v.delta_j.toFixed(2), { class: 'num' }],
        flagCell(v), v.outcome ? t(`chrono_outcome_${v.outcome}`) : t('chrono_outcome_open'), banCell(v), decideCell(v)]));
    $('viol-table').hidden = rows.length === 0;
    $('viol-none').hidden = rows.length > 0;
    return true;
}

function fillRules(field) {
    $('r-ban-days').value = field.chrono_ban_days ?? '';
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (!ctx.field) {
        status(t('err_not_found'), 'error');
        return;
    }
    fillRules(ctx.field);
    const form = $('rules-form');
    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const text = $('r-ban-days').value.trim();
        try {
            const saved = await api('PATCH', fieldApi(''), {
                chrono_ban_days: text === '' ? null : Number(text),
            });
            ctx.field = saved;
            fillRules(saved);
            status(t('chrono_rules_saved'), 'ok');
        } catch (err) {
            status(errorText(err, ['admin']), 'error');
        }
        await load();
    });
    if (ctx.roles.has('admin')) enable(form);
    await load();
}

main();
