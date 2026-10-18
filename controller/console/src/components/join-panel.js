// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Join flow (ADR-P2-12, protocol/join.md): the GM asks the controller for a
// join payload for a box or a standby controller and gets it three ways:
// a QR code, the text form (atalaia:join:...) to copy, and the bytes to
// write on an NTAG215/216 card. A second controller joins as standby by
// pasting such a text here.

import { html, Component, createRef, t } from '../ui.js';
import qrcode from '../lib/qrcode.module.js';

/** The QR code of text as SVG modules (error correction L, byte mode, 4-module quiet zone). */
export function QrCode({ text, label }) {
    const qr = qrcode(0, 'L');
    qr.addData(text, 'Byte');
    qr.make();
    const n = qr.getModuleCount();
    const q = 4;
    let d = '';
    for (let r = 0; r < n; r += 1) {
        for (let c = 0; c < n; c += 1) {
            if (qr.isDark(r, c)) d += `M${c + q} ${r + q}h1v1h-1z`;
        }
    }
    const size = n + 2 * q;
    return html`<svg class="qr" data-testid="join-qr" viewBox=${`0 0 ${size} ${size}`} role="img"
        aria-label=${label} shape-rendering="crispEdges">
        <rect width=${size} height=${size} fill="#fff" />
        <path d=${d} fill="#000" />
    </svg>`;
}

export class JoinPanel extends Component {
    constructor() {
        super();
        this.state = { kind: 'node', role: '', nodeId: '', result: null, copied: false,
                       standbyText: '', standbyGame: null };
        this.text = createRef();
    }

    roles() {
        const { game, modes } = this.props.app.state;
        // A game with modifiers ("main+modifier") has the main mode's roles.
        const mode = game && modes.find((m) => m.id === String(game.mode_id).split('+')[0]);
        return mode ? Object.keys(mode.roles || {}) : [];
    }

    async generate(e) {
        e.preventDefault();
        const body = { kind: this.state.kind };
        const roles = this.roles();
        if (this.state.kind === 'node') body.role = this.state.role || roles[0];
        if (this.state.nodeId) body.node_id = parseInt(this.state.nodeId, 10);
        const result = await this.props.app.call('POST', '/join', body);
        if (result) this.setState({ result, copied: false });
    }

    async copy() {
        const text = this.state.result.text;
        let ok = false;
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
                ok = true;
            }
        } catch (e) {
            ok = false;
        }
        if (!ok && this.text.current) {
            this.text.current.select();
            try {
                ok = document.execCommand('copy');
            } catch (e) {
                ok = false;
            }
        }
        this.setState({ copied: ok });
        if (!ok) this.props.app.showToast(t('join.copy_failed'));
    }

    async joinStandby(e) {
        e.preventDefault();
        const game = await this.props.app.call('POST', '/controller/join', { text: this.state.standbyText.trim() });
        if (game) {
            this.setState({ standbyGame: game, standbyText: '' });
            this.props.app.setGame(game);
            this.props.app.refreshStatus();
        }
    }

    renderIssue() {
        const { state } = this;
        const roles = this.roles();
        const r = state.result;
        return html`<section class="card" aria-labelledby="join-h">
            <h2 id="join-h">${t('join.title')}</h2>
            <p class="muted">${t('join.intro')}</p>
            <form class="form" onSubmit=${(e) => this.generate(e)} data-testid="join-form">
                <div class="field"><label for="j-kind">${t('join.kind')}</label>
                    <select id="j-kind" data-testid="join-kind" value=${state.kind}
                        onChange=${(e) => this.setState({ kind: e.target.value })}>
                        <option value="node">${t('join.kinds.node')}</option>
                        <option value="controller">${t('join.kinds.controller')}</option>
                    </select></div>
                ${state.kind === 'node' && html`<div class="field"><label for="j-role">${t('join.role')}</label>
                    <select id="j-role" value=${state.role || roles[0]} onChange=${(e) => this.setState({ role: e.target.value })}>
                        ${roles.map((ro) => html`<option value=${ro}>${ro}</option>`)}
                    </select></div>`}
                <div class="field"><label for="j-node">${t('join.node_id')}</label>
                    <input id="j-node" type="number" min="1" max="65534" placeholder=${t('join.node_id_auto')}
                        value=${state.nodeId} onInput=${(e) => this.setState({ nodeId: e.target.value })} /></div>
                <button type="submit" class="primary" data-testid="join-generate">${t('join.generate')}</button>
            </form>
            ${r && html`<div class="join-result" data-testid="join-result">
                <p class="warning" role="note">${t('join.warning')}</p>
                <p><strong>${r.kind === 'node' ? t('join.for_node', { node: r.node_id, role: r.role })
                    : t('join.for_controller', { node: r.node_id })}</strong>${` · ${t('join.bytes', { n: r.bytes })} · ${
                    t('join.channel', { mhz: (r.channel_hz / 1e6).toFixed(3) })}`}</p>
                <div class="qr-wrap"><${QrCode} text=${r.text} label=${t('join.qr_label')} /></div>
                <label for="j-text">${t('join.text')}</label>
                <textarea id="j-text" ref=${this.text} readonly rows="4" data-testid="join-text" value=${r.text}></textarea>
                <div class="actions"><button type="button" onClick=${() => this.copy()}>${t('join.copy')}</button>
                    ${state.copied && html`<span class="ok" role="status">${t('join.copied')}</span>`}</div>
                <details><summary>${t('join.nfc')}</summary>
                    <p class="muted small">${t('join.nfc_hint')}</p>
                    <code class="hex" data-testid="join-ndef">${r.ndef_tag_hex}</code>
                </details>
            </div>`}
        </section>`;
    }

    renderStandby() {
        const { state } = this;
        return html`<section class="card" aria-labelledby="standby-h">
            <h2 id="standby-h">${t('join.standby_title')}</h2>
            <p class="muted">${t('join.standby_intro')}</p>
            <form class="form" onSubmit=${(e) => this.joinStandby(e)} data-testid="standby-form">
                <label for="j-standby">${t('join.text')}</label>
                <textarea id="j-standby" rows="3" required placeholder="atalaia:join:…" value=${state.standbyText}
                    onInput=${(e) => this.setState({ standbyText: e.target.value })}></textarea>
                <button type="submit">${t('join.standby_join')}</button>
            </form>
            ${state.standbyGame && html`<p class="ok" role="status">${t('join.standby_done', { game: state.standbyGame.id })}</p>`}
        </section>`;
    }

    render(props) {
        const { role, game, status } = props.app.state;
        if (role !== 'gm') return html`<section class="card"><p class="muted">${t('join.gm_only')}</p></section>`;
        const live = game && game.live && game.state !== 'ended';
        const leading = status && status.role === 'leader';
        return html`<div>
            ${live && leading && this.renderIssue()}
            ${live && !leading && html`<section class="card"><p class="notice">${t('join.standby_cannot_issue')}</p></section>`}
            ${!live && html`<section class="card"><p class="muted">${t('join.no_game')}</p></section>`}
            ${!live && this.renderStandby()}
        </div>`;
    }
}
