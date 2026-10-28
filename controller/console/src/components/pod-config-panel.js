// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The I/O pods' settings over the radio (protocol/pod-config.md, decision PODC), for the GM, under
// the Boxes tab: for each phone of the live game the buttons' colours, the ring's brightness, the
// sound's volume and the enclosure switch of the pod it serves, sent as CMD pod (opcode 10) before a
// game starts or after it ended. The pod takes them, keeps them in its flash and answers through its
// phone (node.setup_applied); until then the controller sends them again, then says the pod did not
// answer (the phone has no pod, its firmware is older, or it is out of reach).

import { html, Component, t } from '../ui.js';

const ACTIVE = ['sent'];
const BUTTONS = 4;

export class PodConfigPanel extends Component {
    constructor() {
        super();
        this.state = { cfg: null, forms: {}, busy: false };
    }

    componentDidMount() {
        this.load();
    }

    async load() {
        const cfg = await this.props.app.call('GET', '/pod-config');
        if (cfg) this.setState({ cfg });
    }

    form(node) {
        return this.state.forms[node] || { setButtons: false, btn: ['', '', '', ''], bright: '', vol: '', tamper: '',
                                           reset: false };
    }

    edit(node, patch) {
        this.setState((s) => ({ forms: { ...s.forms, [node]: { ...this.form(node), ...patch } } }));
    }

    /** The request body of a form: only what the GM chose to set. null when nothing is chosen. */
    static body(f) {
        const body = {};
        if (f.setButtons) body.btn = f.btn;
        if (f.bright !== '') body.bright = Number(f.bright);
        if (f.vol !== '') body.vol = Number(f.vol);
        if (f.tamper !== '') body.tamper = f.tamper === 'on';
        if (f.reset) body.reset = true;
        return Object.keys(body).length === 0 ? null : body;
    }

    async send(node) {
        const app = this.props.app;
        const body = PodConfigPanel.body(this.form(node));
        if (!body) {
            app.showToast(t('pod_config.nothing'));
            return;
        }
        this.setState({ busy: true });
        const out = await app.call('POST', `/pod-config/${node}`, body);
        this.setState({ busy: false });
        if (out) this.load();
    }

    async cancel() {
        if (await this.props.app.call('DELETE', '/pod-config')) this.load();
    }

    renderRow(cfg, n, canSend, push) {
        const f = this.form(n.node_id);
        const num = (key, label, id) => html`<label>${label}
            <input type="number" min="0" max="100" step="1" value=${f[key]} data-testid=${`pod-${key}-${id}`}
                onInput=${(e) => this.edit(n.node_id, { [key]: e.target.value })} /></label>`;
        return html`<tr data-node=${n.node_id}>
            <td>${n.node_id}</td><td>${n.name}</td>
            <td>
                <label><input type="checkbox" checked=${f.setButtons} data-testid=${`pod-setbtn-${n.node_id}`}
                    onChange=${(e) => this.edit(n.node_id, { setButtons: e.target.checked })} />
                    ${t('pod_config.set_buttons')}</label>
                ${f.setButtons && html`<div class="actions">${[0, 1, 2, 3].map((i) => html`<label>${t('pod_config.button', { n: i + 1 })}
                    <select value=${f.btn[i]} data-testid=${`pod-btn-${n.node_id}-${i + 1}`}
                        onChange=${(e) => this.edit(n.node_id, { btn: f.btn.map((c, j) => (j === i ? e.target.value : c)) })}>
                        <option value="">${t('pod_config.game_team')}</option>
                        ${cfg.colours.map((c) => html`<option value=${c}>${t(`pod_config.colours.${c}`)}</option>`)}
                    </select></label>`)}</div>`}
            </td>
            <td>${num('bright', t('pod_config.bright'), n.node_id)}</td>
            <td>${num('vol', t('pod_config.vol'), n.node_id)}</td>
            <td><label>${t('pod_config.tamper')}
                <select value=${f.tamper} data-testid=${`pod-tamper-${n.node_id}`}
                    onChange=${(e) => this.edit(n.node_id, { tamper: e.target.value })}>
                    <option value="">${t('pod_config.unchanged')}</option>
                    <option value="on">${t('pod_config.tamper_on')}</option>
                    <option value="off">${t('pod_config.tamper_off')}</option>
                </select></label>
                <label><input type="checkbox" checked=${f.reset} data-testid=${`pod-reset-${n.node_id}`}
                    onChange=${(e) => this.edit(n.node_id, { reset: e.target.checked })} />
                    ${t('pod_config.reset')}</label></td>
            <td data-testid=${`pod-state-${n.node_id}`}>
                ${push && html`<span class=${push.state === 'applied' ? 'ok' : (ACTIVE.includes(push.state) ? '' : 'warn')}>
                    ${t(`pod_config.states.${push.state}`, { tries: push.tries })}</span> `}
                <button type="button" class="small" data-testid=${`pod-send-${n.node_id}`}
                    disabled=${!canSend || this.state.busy} onClick=${() => this.send(n.node_id)}>
                    ${t('pod_config.send')}</button>
            </td>
        </tr>`;
    }

    render(props, state) {
        const app = props.app;
        if (app.state.role !== 'gm') return null;
        const cfg = state.cfg;
        if (!cfg) return null;
        const game = app.state.game;
        const canSend = Boolean(game && game.live && (game.state === 'ready' || game.state === 'ended'));
        const pushes = app.state.podPushes || cfg.pushes;
        const byNode = Object.fromEntries(pushes.map((p) => [p.node_id, p]));
        const active = pushes.some((p) => ACTIVE.includes(p.state));
        const missed = pushes.some((p) => p.state === 'no_answer');
        return html`<section class="card" aria-labelledby="pod-config-h" data-testid="pod-config-panel">
            <h2 id="pod-config-h">${t('pod_config.title')}</h2>
            <p class="muted small">${t('pod_config.hint')}</p>
            ${!canSend && html`<p class="notice" data-testid="pod-not-ready">${t('pod_config.not_ready')}</p>`}
            ${cfg.nodes.length === 0 ? html`<p class="muted" data-testid="pod-no-phones">${t('pod_config.no_phones')}</p>`
                : html`<div class="table-wrap"><table class="table" data-testid="pod-config-nodes">
                    <thead><tr>
                        <th>${t('nodes.id')}</th><th>${t('nodes.name')}</th><th>${t('pod_config.buttons')}</th>
                        <th>${t('pod_config.bright')}</th><th>${t('pod_config.vol')}</th>
                        <th>${t('pod_config.other')}</th><th>${t('pod_config.state')}</th>
                    </tr></thead>
                    <tbody>${cfg.nodes.map((n) => this.renderRow(cfg, n, canSend, byNode[n.node_id]))}</tbody>
                </table></div>`}
            ${missed && html`<p class="small warn" data-testid="pod-no-answer">${t('pod_config.no_answer_hint')}</p>`}
            ${active && html`<p><button type="button" class="link" data-testid="pod-cancel"
                onClick=${() => this.cancel()}>${t('pod_config.cancel')}</button></p>`}
        </section>`;
    }
}
