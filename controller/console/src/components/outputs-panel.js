// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The boxes' outputs (draft RFC "The expansion port", increment 3; decisions EXP-27, EXP-30):
// sirens, strobes and smoke a box switches through a simple output or an expansion module. The
// GM turns one on for a few seconds (after a confirmation, 5 s by default, while the game runs)
// or off with one tap, and every output of the game off with "All outputs off". The controller
// sends CMD 12 (POST /games/{id}/nodes/{node}/output, POST /games/{id}/outputs/off) and holds a
// box's next start back for 2 s (429, said in a toast); off is never held back. What each output
// did comes back as the box's output.switched in the feed. Shown to the GM only.

import { html, Component, t, ConfirmButton } from '../ui.js';

const SECONDS_MAX = 600;

/** The output functions of a node's modules (a target's hit is not an output), with whether each
 * comes from a simple output the box cannot check. [{capability, simple, lost}] */
export function nodeOutputs(node) {
    const out = [];
    for (const m of (node && node.modules) || []) {
        for (const c of m.caps || []) {
            if (c === 'hit' || c.startsWith('hit.')) continue;
            out.push({ capability: c, simple: m.feedback === false, lost: Boolean(m.lost) });
        }
    }
    return out;
}

/** Whether the feed's latest output.switched of this node's capability says it is on now. */
export function outputOn(feed, nodeId, capability, gameTime) {
    const ev = (feed || []).find((e) => e.type === 'output.switched' && e.node === nodeId
        && e.data && e.data.capability === capability);
    if (!ev || !ev.data.ms || gameTime === null || gameTime === undefined) return false;
    return ev.t + ev.data.ms > gameTime;
}

export class OutputsPanel extends Component {
    constructor() {
        super();
        this.state = { seconds: {}, sent: '' };
    }

    seconds(key) {
        const v = this.state.seconds[key];
        return v === undefined ? 5 : v;
    }

    async send(node, capability, act) {
        const { game } = this.props.app.state;
        const body = { capability, act };
        if (act === 'pulse') body.ms = this.seconds(`${node.node_id}:${capability}`) * 1000;
        const out = await this.props.app.call('POST', `/games/${game.id}/nodes/${node.node_id}/output`, body);
        if (out) this.setState({ sent: `${node.node_id}:${capability}:${act}` });
    }

    async allOff() {
        const { game } = this.props.app.state;
        const out = await this.props.app.call('POST', `/games/${game.id}/outputs/off`);
        if (out) {
            this.setState({ sent: '*' });
            this.props.app.showToast(t('outputs.all_off_done'));
        }
    }

    render(props, state) {
        const app = props.app;
        const { game, nodes, role, status, feed } = app.state;
        const live = game && game.live && game.state !== 'ended';
        if (role !== 'gm' || !live) return null;
        const leading = status && status.role === 'leader';
        const running = game.state === 'running';
        const now = app.gameTime();
        const list = Object.values(nodes || {}).sort((a, b) => a.node_id - b.node_id)
            .map((n) => ({ node: n, outputs: nodeOutputs(n) })).filter((r) => r.outputs.length > 0);
        return html`<section class="card" aria-labelledby="outputs-h" data-testid="outputs-panel">
            <h2 id="outputs-h">${t('outputs.title')}</h2>
            <p class="muted small">${t('outputs.intro')}</p>
            <div class="actions">
                <button type="button" class="danger" data-testid="outputs-all-off" disabled=${!leading}
                    onClick=${() => this.allOff()}>${t('outputs.all_off')}</button>
            </div>
            ${!running && html`<p class="notice small" data-testid="outputs-not-running">${t('outputs.not_running')}</p>`}
            ${list.length === 0 ? html`<p class="muted" data-testid="outputs-none">${t('outputs.none')}</p>` : html`
            <ul class="outputs" data-testid="outputs-list">
                ${list.map(({ node, outputs }) => outputs.map((o) => {
                    const key = `${node.node_id}:${o.capability}`;
                    const s = this.seconds(key);
                    const on = outputOn(feed, node.node_id, o.capability, now);
                    return html`<li data-testid=${`output-${node.node_id}-${o.capability}`}>
                        <strong>${o.capability}</strong> · ${node.name || `${t('nodes.node')} ${node.node_id}`}
                        ${o.simple && html` <span class="chip muted small">${t('nodes.not_checked')}</span>`}
                        ${o.lost && html` <span class="chip warn small">${t('nodes.module_lost')}</span>`}
                        ${on && html` <span class="chip ok small" data-testid=${`output-on-${node.node_id}-${o.capability}`}>${t('outputs.on')}</span>`}
                        <span class="row">
                            <label class="small">${t('outputs.seconds')}
                                <input type="number" min="1" max=${SECONDS_MAX} step="1" value=${s} class="narrow"
                                    data-testid=${`output-seconds-${node.node_id}-${o.capability}`}
                                    onInput=${(e) => {
                                        const v = Math.max(1, Math.min(SECONDS_MAX, Math.round(Number(e.target.value) || 1)));
                                        this.setState({ seconds: { ...state.seconds, [key]: v } });
                                    }} /></label>
                            <${ConfirmButton} testid=${`output-pulse-${node.node_id}-${o.capability}`}
                                label=${t('outputs.pulse', { s })} disabled=${!leading || !running || o.lost}
                                question=${t('outputs.confirm_pulse', { capability: o.capability, name: node.name || node.node_id, s })}
                                onConfirm=${() => this.send(node, o.capability, 'pulse')} />
                            <button type="button" data-testid=${`output-off-${node.node_id}-${o.capability}`} disabled=${!leading}
                                onClick=${() => this.send(node, o.capability, 'off')}>${t('outputs.off')}</button>
                            ${state.sent === `${key}:pulse` || state.sent === `${key}:off`
                                ? html`<span class="ok small" role="status">${t('nodes.command_sent')}</span>` : ''}
                        </span>
                    </li>`;
                }))}
            </ul>`}
        </section>`;
    }
}
