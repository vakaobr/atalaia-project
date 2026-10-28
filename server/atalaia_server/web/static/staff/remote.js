// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The remote GM (plan phase 19's API): each connected controller's live view, pushed by the server as it changes
// (GET /api/v1/fields/{field}/remote-gm/stream, server-sent events read with fetch and the bearer token; decision
// FU9-6) and, while no stream delivers (the browser cannot read one, the connection failed), polled every few
// seconds (GET .../remote-gm, the field's gm in a TOTP session), the commands the site server
// may send (start, pause, resume, end, a GM message, a mode command the live game declares; POST
// .../remote-gm/commands, answered with the controller's own result) and the remote GM log (GET
// .../remote-gm/log, the field's admin or gm). Both stop while the tab is hidden. With the view come the live game's
// players' positions as a list (PKD-5): the controller sends them whenever players share them, the site server
// relays them in memory and keeps none.

import {
    $, api, boot, brief, clear, el, errorText, fieldApi, fillRows, gameTime, page, stateName, status, stream, t, when,
} from './staff.js';

const POLL_S = Math.max(2, Number.parseInt(page.poll, 10) || 5);
const LOG_S = 30;
const EVERY_NODE = 65535;
const MESSAGE_MAX = 100;
const REASON_MAX = 64;
const CAN = {
    start: (s) => s === 'ready',
    pause: (s) => s === 'running',
    resume: (s) => s === 'paused',
    end: (s) => s === 'running' || s === 'paused',
};
const RETRY_S = 30;          // after a failed stream, until the next try (the polling covers the time)
const STALE_MS = 45000;      // a stream silent this long (the server sends a line every 15 s) is replaced
let ctx = null;
let pushing = false;         // a stream is delivering the view: no polling
let following = false;
let abort = null;
let lastBeat = 0;
let busy = false;
let viewAllowed = true;
const shown = new Map();

function result(text, kind) {
    const box = clear($('command-result'));
    box.className = `status ${kind}`;
    if (text) box.append(el('p', { text }));
}

async function send(entry, command, params) {
    const live = entry.data.live;
    if (!live || busy) return;
    busy = true;
    update(entry);
    result(t('sending'), '');
    let startAnyway = false;
    try {
        await api('POST', fieldApi('/remote-gm/commands'),
            { game: live.game, command, params, controller_id: entry.data.controller_id });
        result(t('result_done', { command: t(`cmd_${command}`) }), 'ok');
    } catch (err) {
        if (err.status === 409 && err.body.detail === 'refused_by_controller') {
            // A start refused because roles have no joined box or prop (decision RG-1): the console's
            // "Start anyway?", then the same start again with force.
            const missing = err.body.missing;
            if (command === 'start' && !params.force && err.body.code === 'conflict' && Array.isArray(missing) && missing.length) {
                startAnyway = window.confirm(t('confirm_start_anyway', { roles: missing.join(', ') }));
            }
            if (!startAnyway) {
                result(t('result_refused', { code: err.body.code, detail: err.body.message ? `: ${err.body.message}` : '' }), 'error');
            }
        } else {
            result(errorText(err, ['gm']), 'error');
        }
    } finally {
        busy = false;
    }
    if (startAnyway) {
        await send(entry, 'start', { ...params, force: true });
        return;
    }
    await poll();
    await loadLog();
}

function commandForm(entry) {
    const key = entry.data.controller_id.replace(/[^A-Za-z0-9-]/g, '');
    const reasonId = `reason-${key}`;
    const messageId = `message-${key}`;
    const modeId = `mode-${key}`;
    const nodeId = `node-${key}`;
    const reason = el('input', { id: reasonId, maxlength: REASON_MAX });
    const message = el('input', { id: messageId, maxlength: MESSAGE_MAX });
    const mode = el('select', { id: modeId });
    const node = el('select', { id: nodeId });
    const buttons = {};
    for (const command of ['start', 'pause', 'resume', 'end']) {
        buttons[command] = el('button', {
            type: 'button', class: command === 'end' ? 'danger' : null, text: t(`cmd_${command}`),
            onclick: () => {
                const live = entry.data.live;
                if (command === 'end' && !window.confirm(t('confirm_end', { name: live ? live.name : '' }))) return;
                const params = {};
                if ((command === 'pause' || command === 'end') && reason.value.trim()) params.reason = reason.value.trim();
                send(entry, command, params);
            },
        });
    }
    buttons.message = el('button', {
        type: 'button', text: t('cmd_message'),
        onclick: () => {
            const text = message.value.trim();
            if (!text) {
                message.focus();
                return;
            }
            send(entry, 'message', { text });
            message.value = '';
        },
    });
    buttons.mode = el('button', {
        type: 'button', text: t('cmd_mode'),
        onclick: () => {
            if (!mode.value) return;
            send(entry, 'mode', { name: mode.value, node: Number.parseInt(node.value, 10) || EVERY_NODE });
        },
    });
    const modeRow = el('div', { class: 'mode-row' },
        el('div', { class: 'row' }, el('label', { for: modeId, text: t('mode_command') }), mode),
        el('div', { class: 'row' }, el('label', { for: nodeId, text: t('mode_node') }), node), buttons.mode);
    const form = el('fieldset', { class: 'commands' }, el('legend', { text: t('commands') }),
        el('div', { class: 'row' }, el('label', { for: reasonId, text: t('reason') }), reason),
        el('p', { class: 'buttons' }, buttons.start, ' ', buttons.pause, ' ', buttons.resume, ' ', buttons.end),
        el('div', { class: 'row' }, el('label', { for: messageId, text: t('message_text') }), message), buttons.message,
        modeRow);
    Object.assign(entry, { form, buttons, mode, node, modeRow, message, reason });
    return form;
}

function fillSelect(select, options) {
    const keep = select.value;
    const same = select.options.length === options.length
        && options.every(([value], i) => select.options[i].value === String(value));
    if (same) return;
    clear(select);
    for (const [value, text] of options) select.append(el('option', { value, text }));
    if (options.some(([value]) => String(value) === keep)) select.value = keep;
}

function update(entry) {
    const { data } = entry;
    const live = data.live;
    const state = live ? live.state : null;
    const off = !data.remote_gm || !live;
    for (const [command, can] of Object.entries(CAN)) entry.buttons[command].disabled = off || busy || !can(state);
    entry.buttons.message.disabled = off || busy;
    const commands = live && Array.isArray(live.mode_commands) ? live.mode_commands : [];
    entry.modeRow.hidden = commands.length === 0;
    entry.buttons.mode.disabled = off || busy || commands.length === 0;
    fillSelect(entry.mode, commands.map((c) => [c.name, c.name]));
    const nodes = live ? live.nodes || [] : [];
    fillSelect(entry.node, [[EVERY_NODE, t('every_node')], ...nodes.map((n) => [n.node_id, `${n.name} (#${n.node_id})`])]);
    entry.reason.disabled = off;
    entry.message.disabled = off;
}

function liveView(data) {
    const box = el('div', { class: 'live' });
    const live = data.live;
    if (!live) {
        box.append(el('p', { text: t('no_live') }));
        return box;
    }
    const time = live.game_time_ms === null || live.game_time_ms === undefined ? t('none')
        : `${gameTime(live.game_time_ms)}${live.duration_ms ? ` / ${gameTime(live.duration_ms)}` : ''}`;
    box.append(el('h3', { text: live.name }));
    const dl = el('dl', { class: 'details' });
    for (const [k, v] of [[t('game_mode'), el('code', { text: live.mode_id })], [t('game_state'), stateName(live.state)],
        [t('in_charge'), live.in_charge ? t('yes') : t('standby')], [t('game_time'), time]]) {
        dl.append(el('dt', { text: k }), el('dd', {}, v));
    }
    box.append(dl);
    const totals = el('table', { class: 'data scores-table' },
        el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: t('team') }),
            el('th', { scope: 'col', class: 'num', text: t('score') }))),
        el('tbody', {}, live.teams.map((team) => el('tr', {}, el('th', { scope: 'row', text: team }),
            el('td', { class: 'num', text: String(live.totals[team] ?? 0) })))));
    box.append(el('div', { class: 'table-wrap' }, totals));
    if (live.nodes && live.nodes.length) {
        box.append(el('h4', { text: t('nodes') }), el('ul', { class: 'compact' }, live.nodes.map((n) => {
            const info = n.info || {};
            const battery = typeof info.battery_pct === 'number' ? `, ${info.battery_pct} %` : '';
            return el('li', { text: `${n.name} (#${n.node_id}, ${n.role}${battery})` });
        })));
    }
    if (live.events && live.events.length) {
        box.append(el('h4', { text: t('latest_events') }), el('ul', { class: 'compact events' },
            live.events.slice(-10).reverse().map((e) => el('li', {}, `${gameTime(e.t)} `, el('code', { text: e.type }),
                e.team ? ` ${e.team}` : '', ` ${brief(e.data, 80)}`))));
    }
    return box;
}

/** The players' positions the controller sent while they share them (PKD-5): a list, as this page has no plan.
 * The site server keeps none of them; they come with the view and go with it. */
function positionPlace(p) {
    if (p.source === 'ble') {
        const level = Number.isInteger(p.level) ? `, ${t('pos_level', { n: p.level })}` : '';
        return `${p.room}${p.zone ? ` (${p.zone})` : ''}${level}`;
    }
    const accuracy = typeof p.accuracy_m === 'number' ? ` ${t('pos_accuracy', { n: Math.round(p.accuracy_m) })}` : '';
    return `${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}${accuracy}`;
}

function positionsView(data) {
    const box = el('div', { class: 'positions' });
    if (!data.live) return box;
    const list = Array.isArray(data.positions) ? data.positions : [];
    box.append(el('h4', { text: t('pos_title') }));
    if (list.length === 0) {
        box.append(el('p', { text: t('pos_none') }));
    } else {
        const rows = list.map((p) => el('tr', {}, el('th', { scope: 'row', text: p.player_id }),
            el('td', { text: p.team || t('none') }), el('td', { text: p.role || t('none') }),
            el('td', { text: positionPlace(p) }), el('td', { class: 'num', text: t('pos_age_value', { n: Math.round(p.age_s) }) })));
        box.append(el('div', { class: 'table-wrap' }, el('table', { class: 'data positions-table' },
            el('thead', {}, el('tr', {}, el('th', { scope: 'col', text: t('pos_player') }),
                el('th', { scope: 'col', text: t('team') }), el('th', { scope: 'col', text: t('pos_role') }),
                el('th', { scope: 'col', text: t('pos_place') }), el('th', { scope: 'col', class: 'num', text: t('pos_age') }))),
            el('tbody', {}, rows))));
    }
    box.append(el('p', { class: 'hint', text: t('pos_note') }));
    return box;
}

function render(data) {
    let entry = shown.get(data.controller_id);
    if (!entry) {
        entry = { data };
        const head = el('h2', { text: t('controller', { id: data.controller_id }) });
        entry.meta = el('dl', { class: 'details' });
        entry.live = el('div');
        entry.positions = el('div');
        entry.off = el('p', { class: 'notice', text: t('remote_off') });
        entry.root = el('article', { class: 'controller' }, head, entry.meta, entry.off, entry.live, entry.positions, commandForm(entry));
        shown.set(data.controller_id, entry);
        $('controllers').append(entry.root);
    }
    entry.data = data;
    clear(entry.meta);
    for (const [k, v] of [['Version', data.version], [t('takes_commands'), data.remote_gm ? t('yes') : t('no')],
        [t('connected_at'), when(data.connected_at, ctx.zone)], [t('live_at'), when(data.live_at, ctx.zone)]]) {
        entry.meta.append(el('dt', { text: k }), el('dd', { text: v }));
    }
    entry.off.hidden = data.remote_gm;
    entry.live.replaceChildren(liveView(data));
    entry.positions.replaceChildren(positionsView(data));
    update(entry);
}

async function poll() {
    if (!viewAllowed) return;
    let body;
    try {
        body = await api('GET', fieldApi('/remote-gm'));
    } catch (err) {
        status(errorText(err, ['gm']), 'error');
        if (err.status === 403) viewAllowed = false;
        return;
    }
    status('');
    showView(body);
}

function showView(body) {
    const ids = new Set(body.controllers.map((c) => c.controller_id));
    for (const [id, entry] of shown) {
        if (!ids.has(id)) {
            entry.root.remove();
            shown.delete(id);
        }
    }
    body.controllers.forEach(render);
    $('controllers-none').hidden = body.controllers.length > 0;
}

/** The push: one stream at a time while the tab is visible, a new one when the server ends it (it does after five
 * minutes) and, after a failure, again after RETRY_S; meanwhile the polling shows the view. */
async function follow() {
    if (following || document.hidden || !viewAllowed) return;
    following = true;
    try {
        while (!document.hidden && viewAllowed) {
            abort = new AbortController();
            let got = false;
            try {
                await stream(fieldApi('/remote-gm/stream'), (name, data) => {
                    lastBeat = Date.now();
                    if (name !== 'view') return;
                    got = true;
                    pushing = true;
                    status('');
                    showView(data);
                }, abort.signal);
            } catch (err) {
                if (err.status === 403) {
                    status(errorText(err, ['gm']), 'error');
                    viewAllowed = false;
                }
            }
            pushing = false;
            if (!got && !document.hidden && viewAllowed) {
                await new Promise((resolve) => window.setTimeout(resolve, RETRY_S * 1000));
            }
        }
    } finally {
        pushing = false;
        following = false;
    }
}

function logRow(row) {
    const d = row.details || {};
    const what = d.command ? [el('code', { text: d.command }), d.params && Object.keys(d.params).length ? ` ${brief(d.params, 120)}` : '']
        : t('none');
    const outcome = row.action === 'remote_gm_command' ? `${t('log_sent')}: ${d.result || t('none')}${d.message ? ` (${d.message})` : ''}`
        : `${t('log_denied')}: ${d.reason || t('none')}`;
    return [when(row.at, ctx.zone), row.username || t('none'), el('span', {}, what), outcome];
}

async function loadLog() {
    let rows;
    try {
        rows = await api('GET', fieldApi('/remote-gm/log'));
    } catch (err) {
        if (viewAllowed) status(errorText(err, ['admin', 'gm']), 'error'); // else the view's refusal says it
        return;
    }
    fillRows($('remote-log'), rows.map(logRow));
    $('remote-log').hidden = rows.length === 0;
    $('remote-log-none').hidden = rows.length > 0;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    await poll();
    await loadLog();
    $('log-refresh').addEventListener('click', loadLog);
    let ticks = 0;
    // The polling below is the fallback: it asks only while no stream is delivering (S19-11, FU9-6).
    window.setInterval(() => {
        if (document.hidden || busy) return;
        ticks += 1;
        if (pushing && Date.now() - lastBeat > STALE_MS && abort) abort.abort(); // silent too long: open a new one
        if (!pushing) poll();
        if ((ticks * POLL_S) % LOG_S < POLL_S) loadLog();
    }, POLL_S * 1000);
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            if (abort) abort.abort();
        } else {
            poll();
            follow();
        }
    });
    follow();
}

main();
