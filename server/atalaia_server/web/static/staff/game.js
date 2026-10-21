// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One game: its summary and score timeline (GET /api/v1/games/{game}/timeline), drawn as an SVG chart
// with the same points as a table; its event log by type, team and game time (GET .../log, 200 at a
// time); and, for the field's admin and gm, its boxes' health (GET .../devices).

import {
    $, api, boot, brief, clear, el, enable, errorText, fillRows, gameTime, page, stateName, status, t, when,
} from './staff.js';
import { deviceCells } from './devicerow.js';

const SVG = 'http://www.w3.org/2000/svg';
const COLOURS = ['#c0392b', '#2471a3', '#1e8449', '#b9770e', '#7d3c98', '#117a65', '#5d6d7e', '#a04000'];
const LOG_PAGE = 200;
const game = encodeURIComponent(page.game);
let ctx = null;
let teams = [];
let logRows = [];
let after = 0;

function teamName(team) {
    return team.display_name || team.team;
}

function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    for (const c of children) node.append(c);
    return node;
}

function chart(points) {
    const box = clear($('chart'));
    if (points.length < 2) return;
    const W = 640;
    const H = 240;
    const PAD = 36;
    const maxT = Math.max(1, ...points.map((p) => p.t));
    const values = points.flatMap((p) => Object.values(p.totals));
    const lo = Math.min(0, ...values);
    const hi = Math.max(1, ...values);
    const x = (v) => PAD + ((W - 2 * PAD) * v) / maxT;
    const y = (v) => H - PAD - ((H - 2 * PAD) * (v - lo)) / (hi - lo);
    const title = svg('title', {});
    title.textContent = t('timeline_chart');
    const root = svg('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-labelledby': 'chart-title', class: 'chart-svg' });
    title.setAttribute('id', 'chart-title');
    root.append(title);
    root.append(svg('line', { x1: PAD, y1: y(0), x2: W - PAD, y2: y(0), class: 'axis' }));
    root.append(svg('line', { x1: PAD, y1: PAD, x2: PAD, y2: H - PAD, class: 'axis' }));
    for (const [v, anchor] of [[hi, 'end'], [lo, 'end']]) {
        const label = svg('text', { x: PAD - 4, y: y(v) + 4, 'text-anchor': anchor, class: 'tick' });
        label.textContent = String(v);
        root.append(label);
    }
    const end = svg('text', { x: W - PAD, y: H - PAD + 16, 'text-anchor': 'end', class: 'tick' });
    end.textContent = gameTime(maxT * 1000);
    root.append(end);
    const legend = el('ul', { class: 'legend' });
    teams.forEach((team, i) => {
        const colour = COLOURS[i % COLOURS.length];
        const d = points.map((p) => `${x(p.t).toFixed(1)},${y(p.totals[team.team] || 0).toFixed(1)}`).join(' ');
        root.append(svg('polyline', { points: d, fill: 'none', stroke: colour, 'stroke-width': 2.5,
            'stroke-dasharray': i % 2 ? '6 3' : 'none' }));
        const swatch = el('span', { class: 'swatch', 'aria-hidden': 'true' });
        swatch.style.background = colour;
        legend.append(el('li', {}, swatch, teamName(team)));
    });
    box.append(root, legend);
}

function timelineTable(points) {
    const table = $('timeline');
    const head = clear(table.tHead);
    head.append(el('tr', {}, el('th', { scope: 'col', text: t('col_time') }), el('th', { scope: 'col', text: t('col_at') }),
        teams.map((team) => el('th', { scope: 'col', class: 'num', text: teamName(team) }))));
    fillRows(table, points.map((p) => [gameTime(p.t * 1000), when(p.at, ctx.zone),
        ...teams.map((team) => [String(p.totals[team.team] || 0), { class: 'num' }])]));
}

async function summary() {
    let body;
    try {
        body = await api('GET', `/api/v1/games/${game}/timeline`);
    } catch (err) {
        status(errorText(err, ['admin', 'gm', 'marshal', 'player', 'spectator']), 'error');
        return false;
    }
    const g = body.game;
    teams = g.teams;
    document.title = `${g.name} · ${document.title}`;
    $('game-name').textContent = g.name;
    const winner = g.teams.find((team) => team.team === g.winner);
    const rows = [[t('game_mode'), el('code', { text: g.mode_id })], [t('game_state'), stateName(g.state)],
        [t('game_started'), when(g.started_at, ctx.zone)], [t('game_ended'), when(g.ended_at, ctx.zone)]];
    if (g.state === 'ended') rows.push([t('game_winner'), winner ? teamName(winner) : t('draw')]);
    const dl = clear($('summary'));
    for (const [k, v] of rows) dl.append(el('dt', { text: k }), el('dd', {}, v));
    fillRows($('teams'), g.teams.map((team) => [teamName(team), [String(team.score), { class: 'num' }]]));
    if (body.delayed_until) {
        $('delayed').textContent = t('delayed_until', { at: when(body.delayed_until, ctx.zone) });
        $('delayed').hidden = false;
    }
    const points = body.points || [];
    $('timeline-none').hidden = points.length > 1;
    $('timeline-details').hidden = points.length < 2;
    chart(points);
    timelineTable(points);
    const select = $('l-team');
    for (const team of teams) select.append(el('option', { value: team.team, text: teamName(team) }));
    return true;
}

function logQuery() {
    const q = new URLSearchParams({ limit: String(LOG_PAGE) });
    if ($('l-type').value) q.set('type', $('l-type').value);
    if ($('l-team').value) q.set('team', $('l-team').value);
    const from = Number.parseInt($('l-from').value, 10);
    const to = Number.parseInt($('l-to').value, 10);
    if (Number.isFinite(from) && from >= 0) q.set('from_ms', String(from * 1000));
    if (Number.isFinite(to) && to >= 0) q.set('to_ms', String(to * 1000));
    if (after) q.set('after', String(after));
    return q;
}

let typesShown = false;

async function log(more = false) {
    if (!more) {
        logRows = [];
        after = 0;
    }
    let body;
    try {
        body = await api('GET', `/api/v1/games/${game}/log?${logQuery()}`);
    } catch (err) {
        status(errorText(err, ['admin', 'gm', 'marshal', 'player', 'spectator']), 'error');
        return;
    }
    if (!typesShown) {
        typesShown = true;
        const select = $('l-type');
        for (const [type, count] of Object.entries(body.types || {})) {
            select.append(el('option', { value: type, text: `${type} (${count})` }));
        }
    }
    const names = Object.fromEntries(teams.map((team) => [team.team, teamName(team)]));
    logRows = logRows.concat(body.events.map((e) => [gameTime(e.t), el('code', { text: e.type }),
        e.team ? names[e.team] || e.team : t('none'), e.node === null || e.node === undefined ? t('none') : String(e.node),
        el('code', { class: 'data', text: brief(e.data) })]));
    after = body.next || 0;
    fillRows($('log'), logRows);
    $('log').hidden = logRows.length === 0;
    $('log-none').hidden = logRows.length > 0;
    $('log-more').hidden = !body.next;
}

async function devices() {
    let body;
    try {
        body = await api('GET', `/api/v1/games/${game}/devices`);
    } catch (err) {
        return; // for the field's admin and gm only
    }
    if (!body.devices.length) return;
    fillRows($('game-devices'), body.devices.map((d) => deviceCells(d, ctx.zone)));
    $('game-devices-section').hidden = false;
}

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (!(await summary())) return;
    const filters = $('log-filters');
    enable(filters);
    filters.addEventListener('submit', (event) => {
        event.preventDefault();
        log();
    });
    $('log-more').addEventListener('click', () => log(true));
    await log();
    if (ctx.roles.has('admin') || ctx.roles.has('gm')) await devices();
}

main();
