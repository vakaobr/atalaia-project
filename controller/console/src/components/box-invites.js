// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Boxes for the next game (protocol/field-frames.md, decisions RJ-1, RJ-2, RJ-13): a box whose
// game is over announces itself over the radio; this dialog lists the free boxes the
// controller has heard (name, device id, signal, when, the role it had), with the previous
// game's boxes ticked, a role per box where the game has several (its previous one by
// default), and invites the ticked ones into the live game: the controller sends each its
// join over the radio, sealed with the field's key. Each box's progress follows (invited,
// accepted, joined, refused and why, failed). Cards, QR codes and the serial console still
// work as before (Join tab).

import { html, Component, t, api } from '../ui.js';
import { gameRoles } from './preset-builder.js';

const DONE = new Set(['joined']);

/** The boxes a scenario's game names: [[name, role]] (game.scenario.nodes, staff only). */
function scenarioBoxes(game) {
    const nodes = (game && game.scenario && game.scenario.nodes) || {};
    return Object.entries(nodes).filter(([, spec]) => !spec.player).map(([name, spec]) => [name, spec.role]);
}

function shortId(id) {
    return id ? `${id.slice(0, 4)}·${id.slice(4, 8)}` : '';
}

export class BoxInvites extends Component {
    constructor(props) {
        super(props);
        this.state = { picked: null, roles: {}, sending: false };
    }

    componentDidMount() {
        this.props.app.loadBoxes(true);
        this.props.app.loadInvites();
        this.timer = setInterval(() => this.props.app.loadBoxes(false), 15000);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
    }

    /** What the game lets a box be: its roles, or a scenario's box names. */
    options() {
        const { game, modes } = this.props.app.state;
        const named = scenarioBoxes(game);
        if (named.length) {
            return { scenario: true, list: named.map(([name, role]) => ({ value: name, role, label: `${name} · ${role}` })) };
        }
        return { scenario: false, list: gameRoles(modes, game.mode_id).map((r) => ({ value: r, role: r, label: r })) };
    }

    boxes() {
        const b = this.props.app.state.boxes;
        return (b && b.boxes) || [];
    }

    invites() {
        const out = {};
        for (const i of this.props.app.state.invites || []) out[i.device_id] = i;
        return out;
    }

    /** Ticked by default: the previous game's boxes, free, not already in this game or invited. */
    picked() {
        if (this.state.picked) return this.state.picked;
        const inv = this.invites();
        const out = {};
        for (const b of this.boxes()) out[b.device_id] = !!(b.previous && b.node_id == null && !inv[b.device_id]);
        return out;
    }

    /** A box's choice: the GM's, else its previous role (or a scenario name with that role), else the first. */
    choice(box, taken) {
        if (this.state.roles[box.device_id]) return this.state.roles[box.device_id];
        const { list } = this.options();
        const same = list.filter((o) => o.role === box.previous_role && !taken.has(o.value));
        const first = list.find((o) => !taken.has(o.value)) || list[0];
        return (same[0] || first || {}).value || '';
    }

    toggle(id, on) {
        this.setState({ picked: { ...this.picked(), [id]: on } });
    }

    async send() {
        const { app } = this.props;
        const { game } = app.state;
        const { scenario } = this.options();
        const picked = this.picked();
        const taken = new Set();
        const boxes = [];
        for (const b of this.boxes()) {
            if (!picked[b.device_id]) continue;
            const value = this.choice(b, taken);
            taken.add(value);
            boxes.push(scenario ? { device_id: b.device_id, name: value } : { device_id: b.device_id, role: value });
        }
        if (!boxes.length) return;
        this.setState({ sending: true });
        const out = await app.call('POST', `/games/${game.id}/invites`, { boxes });
        this.setState({ sending: false, picked: null });
        if (out) app.loadInvites();
    }

    status(inv) {
        if (!inv) return '';
        const s = t(`invites.status.${inv.status}`);
        if (inv.status === 'refused') return `${s}: ${t(`invites.reasons.${inv.detail}`)}`;
        if (inv.status === 'failed' || inv.status === 'too_big') return inv.detail ? `${s}: ${inv.detail}` : s;
        if (inv.status === 'invited' && inv.attempts > 1) return `${s} (${inv.attempts})`;
        return s;
    }

    renderRow(b, picked, inv, taken) {
        const { list } = this.options();
        const value = this.choice(b, taken);
        taken.add(value);
        const done = inv && DONE.has(inv.status);
        const inGame = b.node_id != null;
        return html`<tr data-testid=${`invite-row-${b.device_id}`}>
            <td><input type="checkbox" data-testid=${`invite-box-${b.device_id}`} aria-label=${b.name}
                checked=${!!picked[b.device_id] && !inGame} disabled=${inGame || done}
                onChange=${(e) => this.toggle(b.device_id, e.target.checked)} /></td>
            <td><strong>${b.name}</strong> <span class="muted small" title=${b.device_id}>${shortId(b.device_id)}</span>
                ${b.previous && html` <span class="pill small">${t('invites.previous')}</span>`}</td>
            <td class="muted small">${b.rssi != null ? `${b.rssi} dBm` : '–'} · ${t('invites.seen', { s: b.seen_s_ago })}
                ${b.last_role && html`<br />${t('invites.last_role', { role: b.last_role })}`}</td>
            <td>${list.length > 1
                ? html`<select data-testid=${`invite-role-${b.device_id}`} value=${value} disabled=${inGame || done}
                    aria-label=${t('invites.role')}
                    onChange=${(e) => this.setState({ roles: { ...this.state.roles, [b.device_id]: e.target.value } })}>
                    ${list.map((o) => html`<option value=${o.value}>${o.label}</option>`)}</select>`
                : html`<span>${value}</span>`}</td>
            <td data-testid=${`invite-status-${b.device_id}`} class=${inv && inv.status === 'joined' ? 'ok'
                : inv && (inv.status === 'refused' || inv.status === 'failed') ? 'error' : ''}>
                ${inGame && !inv ? t('invites.in_game', { node: b.node_id }) : this.status(inv)}</td>
        </tr>`;
    }

    render(props, state) {
        const { app } = props;
        const info = app.state.boxes;
        const boxes = this.boxes();
        const invites = this.invites();
        const picked = this.picked();
        const count = boxes.filter((b) => picked[b.device_id] && b.node_id == null).length;
        const taken = new Set();
        // Invites for boxes no longer announcing (they joined, or went quiet) stay visible.
        const gone = Object.values(invites).filter((i) => !boxes.some((b) => b.device_id === i.device_id));
        return html`<div class="modal-backdrop" onClick=${(e) => e.target === e.currentTarget && props.onClose()}>
            <div class="modal card" role="dialog" aria-modal="true" aria-labelledby="inv-h" data-testid="invite-dialog">
                <h2 id="inv-h">${t('invites.title')}</h2>
                <p class="muted small">${t('invites.intro')}</p>
                ${info && info.radio === false && html`<p class="warning" data-testid="invite-no-radio">${t('invites.no_radio')}</p>`}
                ${info && info.radio && info.field_frames === false && html`<p class="warning">${t('invites.old_modem')}</p>`}
                ${info && info.previous_game && html`<p class="small" data-testid="invite-previous">${t('invites.previous_game',
                    { name: info.previous_game.name })}</p>`}
                ${boxes.length === 0 && gone.length === 0
                    ? html`<p class="notice" data-testid="invite-empty">${t('invites.empty')}</p>`
                    : html`<div class="table-wrap"><table class="invites">
                        <thead><tr><th></th><th>${t('invites.box')}</th><th>${t('invites.heard')}</th>
                            <th>${t('invites.role')}</th><th>${t('invites.progress')}</th></tr></thead>
                        <tbody>${boxes.map((b) => this.renderRow(b, picked, invites[b.device_id], taken))}
                            ${gone.map((i) => html`<tr data-testid=${`invite-row-${i.device_id}`}><td></td>
                                <td><span class="muted small">${shortId(i.device_id)}</span></td><td></td>
                                <td>${i.name || i.role}</td>
                                <td data-testid=${`invite-status-${i.device_id}`} class=${i.status === 'joined' ? 'ok'
                                    : i.status === 'refused' || i.status === 'failed' ? 'error' : ''}>${this.status(i)}</td></tr>`)}
                        </tbody></table></div>`}
                <div class="actions">
                    <button type="button" class="primary" data-testid="invite-send" disabled=${!count || state.sending}
                        onClick=${() => this.send()}>${t('invites.send', { n: count })}</button>
                    <button type="button" data-testid="invite-discover" onClick=${() => app.loadBoxes(true)}>${t('invites.discover')}</button>
                    <button type="button" data-testid="invite-close" onClick=${() => props.onClose()}>${t('invites.close')}</button>
                </div>
                <p class="muted small">${t('invites.manual')}</p>
            </div>
        </div>`;
    }
}

/** The start guard (decision RJ-1): what Start would say, from the game's start_check. */
export function StartCheck({ game }) {
    const check = game && game.start_check;
    if (!check) return null;
    return html`${check.missing.length > 0 && html`<p class="warning" data-testid="start-missing">${t('game.missing_roles',
        { roles: check.missing.join(', ') })}</p>`}
        ${check.warnings.length > 0 && html`<ul class="notice small" data-testid="start-warnings">${check.warnings.map((w) => html`<li>${
            t(`game.start_warnings.${w.code}`, { role: w.role, have: w.have, value: w.value, param: w.param })}</li>`)}</ul>`}`;
}

/** Asks the free boxes to announce themselves; quietly does nothing without a radio. */
export async function discover(token) {
    try {
        await api(token, 'POST', '/boxes/discover');
    } catch (e) {
        /* no radio, or no join key: the dialog says so from GET /boxes */
    }
}
