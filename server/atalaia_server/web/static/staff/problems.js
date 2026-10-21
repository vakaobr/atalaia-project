// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A scenario check's answer in words: whether it passed, every problem the server found (level, where,
// code, the validator's message), and what the manifest declares.

import { clear, el, t } from './staff.js';

export function problemTable(problems) {
    const rows = problems.map((p) => el('tr', { class: p.level === 'error' ? 'error' : 'warning' },
        el('th', { scope: 'row', text: t(`problem_level_${p.level === 'error' ? 'error' : 'warning'}`) }),
        el('td', {}, el('code', { text: p.path || '/' })), el('td', {}, el('code', { text: p.code })),
        el('td', { text: p.message })));
    return el('div', { class: 'table-wrap' }, el('table', { class: 'data problems' },
        el('thead', {}, el('tr', {}, ['col_level', 'col_where', 'col_code', 'col_message'].map(
            (k) => el('th', { scope: 'col', text: t(k) })))),
        el('tbody', {}, rows)));
}

/** Shows an answer of POST .../scenarios/check (or a refused save's problems) in box. */
export function showCheck(box, answer) {
    clear(box);
    const problems = answer.problems || [];
    const errors = problems.filter((p) => p.level === 'error').length;
    let headline;
    let kind;
    if (answer.ok) {
        headline = t('check_ok');
        kind = 'ok';
    } else if (errors === 0 && answer.checked_in_core === false && answer.scenario_id) {
        headline = t('check_ok_no_core');
        kind = 'error';
    } else {
        headline = t('check_errors', { n: Math.max(errors, problems.length ? 1 : 0) });
        kind = 'error';
    }
    box.append(el('p', { class: `status ${kind}`, text: headline }));
    if (answer.saved_revision) box.append(el('p', { text: t('check_saved_revision', { n: answer.saved_revision }) }));
    if (answer.nodes || answer.objectives) {
        const nodes = (answer.nodes || []).map((n) => `${n.name} (${n.role})`).join(', ') || t('none');
        const objectives = (answer.objectives || []).map((o) => o.name || o.id).join(', ') || t('none');
        if (answer.scenario_id) box.append(el('p', {}, el('code', { text: answer.scenario_id }), answer.name ? ` · ${answer.name}` : ''));
        box.append(el('p', { class: 'hint', text: t('check_summary', { nodes, objectives }) }));
    }
    if (problems.length) box.append(problemTable(problems));
}
