// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Boxes for the next game (protocol/field-frames.md, decisions RJ-1, RJ-2, RJ-13): a box whose
// game is over announces itself over the radio; this dialog lists the free boxes the
// controller has heard (name, device id, signal, when, the role it had), with the previous
// game's boxes ticked, a role per box where the game has several (its previous one by
// default), and invites the ticked ones into the live game: the controller sends each its
// join over the radio, sealed with the field's key. Each box's progress follows (invited,
// accepted, joined, refused and why, failed). Cards, QR codes and the serial console still
// work as before (Join tab).
//
// Readiness and Start (decisions GM-1 to GM-4): the dialog shows, live, what the start guard
// (the engine's start_check, carried in the game and pushed on every HELLO) says: "ready to
// start" with the joined count per role once every needed role has a box, the mode's unmet
// minimums as warnings, else the roles still waiting. Its Start asks "review the game's other
// settings first?": Review settings closes the dialog and opens the game's settings; Start now
// starts (Start anyway, with force, when a role has no box, as the game card's Start does).

import { html, Component, createRef, t, api } from '../ui.js';
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
        this.state = { picked: null, roles: {}, sending: false, asking: false, starting: false };
        this.startRef = createRef();
        this.choiceRef = createRef();
    }

    componentDidUpdate(prevProps, prevState) {
        // Focus follows the confirmation: onto its first choice, and back onto Start after it.
        if (this.state.asking && !prevState.asking && this.choiceRef.current) this.choiceRef.current.focus();
        if (!this.state.asking && prevState.asking && this.startRef.current) this.startRef.current.focus();
    }

    onKey(e) {
        if (e.key !== 'Escape') return;
        e.stopPropagation();
        if (this.state.asking) this.setState({ asking: false });
        else this.props.onClose();
    }

    /** Start now (or anyway, forced, when a needed role has no box): the game card's own path. */
    async start(force) {
        this.setState({ asking: false, starting: true });
        const started = await this.props.onStart(force);
        this.setState({ starting: false });
        if (started) this.props.onClose();
    }

    review() {
        this.setState({ asking: false });
        this.props.onReview();
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

    /** What the start guard says now, in words: ready (with the joined count per role), or the
     * roles still waiting; the mode's unmet minimums as warnings. */
    renderReadiness(check) {
        if (!check) return null;
        const joined = check.joined || {};
        const counts = check.needed.map((r) => `${joined[r] || 0} × ${r}`).join(', ') || t('invites.none_joined');
        let line;
        if (!check.missing.length) {
            line = html`<p class="ready" data-testid="invite-ready">${check.needed.length
                ? t('invites.ready', { counts }) : t('invites.no_roles')}</p>`;
        } else {
            line = html`<p class="notice" data-testid="invite-waiting">${t('invites.waiting',
                { roles: check.missing.join(', '), counts })}</p>`;
        }
        return html`${line}${check.warnings.length > 0 && html`<ul class="warning small" data-testid="invite-warnings">${
            check.warnings.map((w) => html`<li>${t(`game.start_warnings.${w.code}`,
                { role: w.role, have: w.have, value: w.value, param: w.param })}</li>`)}</ul>`}`;
    }

    /** Start from the dialog: asks first whether to review the game's settings. */
    renderStart(check) {
        const { state } = this;
        const missing = check.missing || [];
        const pending = this.props.pending || 0;
        if (!state.asking) {
            return html`<div class="actions"><button type="button" ref=${this.startRef} data-testid="invite-start"
                class=${missing.length ? 'danger' : 'primary'} disabled=${state.starting}
                onClick=${() => this.setState({ asking: true })}>${missing.length
                    ? t('game.start_anyway') : t('invites.start')}</button></div>`;
        }
        return html`<div class="confirm-box" role="group" aria-labelledby="inv-start-q" data-testid="invite-start-confirm">
            ${missing.length > 0 && html`<p class="warning" data-testid="invite-start-missing">${t('game.missing_short',
                { roles: missing.join(', ') })}</p>`}
            ${pending > 0 && html`<p class="warning">${t('invites.pending_note', { n: pending })}</p>`}
            <p class="confirm-q" id="inv-start-q">${t('invites.start_question')}</p>
            <div class="actions">
                <button type="button" ref=${this.choiceRef} class="primary" data-testid="invite-review"
                    onClick=${() => this.review()}>${t('invites.review')}</button>
                <button type="button" class=${missing.length ? 'danger' : ''} data-testid="invite-start-now"
                    onClick=${() => this.start(missing.length > 0)}>${missing.length
                        ? t('game.start_anyway') : t('invites.start_now')}</button>
                <button type="button" data-testid="invite-start-back"
                    onClick=${() => this.setState({ asking: false })}>${t('invites.back')}</button>
            </div>
        </div>`;
    }

    render(props, state) {
        const { app } = props;
        const check = app.state.game && app.state.game.start_check;
        const info = app.state.boxes;
        const boxes = this.boxes();
        const invites = this.invites();
        const picked = this.picked();
        const count = boxes.filter((b) => picked[b.device_id] && b.node_id == null).length;
        const taken = new Set();
        // Invites for boxes no longer announcing (they joined, or went quiet) stay visible.
        const gone = Object.values(invites).filter((i) => !boxes.some((b) => b.device_id === i.device_id));
        return html`<div class="modal-backdrop" onClick=${(e) => e.target === e.currentTarget && props.onClose()}>
            <div class="modal card" role="dialog" aria-modal="true" aria-labelledby="inv-h" data-testid="invite-dialog"
                onKeyDown=${(e) => this.onKey(e)}>
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
                <div role="status" aria-live="polite" data-testid="invite-readiness">${this.renderReadiness(check)}</div>
                <div class="actions">
                    <button type="button" class=${check && check.ok ? '' : 'primary'} data-testid="invite-send" disabled=${!count || state.sending}
                        onClick=${() => this.send()}>${t('invites.send', { n: count })}</button>
                    <button type="button" data-testid="invite-discover" onClick=${() => app.loadBoxes(true)}>${t('invites.discover')}</button>
                    <button type="button" data-testid="invite-close" onClick=${() => props.onClose()}>${t('invites.close')}</button>
                </div>
                ${props.onStart && check && this.renderStart(check)}
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
