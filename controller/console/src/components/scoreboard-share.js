// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// "Share with players" (decision PD13): a QR code of the scoreboard's address with the read-only access
// code, http://<controller>:8080/scoreboard#token=<read code> (https://... on a phone controller), which
// the app's Player > Follow a game takes by scanning it. An https address (the phone controller's, and the
// Pi's after its http ones) also has `&ca=<SHA-256 of the field CA, 64 hex>` in the fragment: the app checks
// the CA it fetches from /api/v1/controller/ca against it (the format: console/README.md, "The scoreboard").
// The controller makes the address from the
// addresses the check-in poster lists (GET /api/v1/scoreboard-link, GM token only). The code reads the
// game and changes nothing, but it is a secret all the same: the GM asks to see it, and it is not
// kept on the page.

import { html, Component, t } from '../ui.js';
import { QrCode } from './join-panel.js';

export class ScoreboardShare extends Component {
    constructor() {
        super();
        this.state = { links: null, which: 0, shown: false, failed: false };
    }

    async show() {
        const out = await this.props.app.call('GET', '/scoreboard-link');
        if (out) this.setState({ links: out.links, which: 0, shown: true, failed: false });
    }

    hide() {
        this.setState({ links: null, shown: false });
    }

    render(props, state) {
        if (props.app.state.role !== 'gm') return null;
        const links = state.links || [];
        const link = links[state.which] || null;
        return html`<section class="card" aria-labelledby="sbs-h" data-testid="scoreboard-share">
            <h2 id="sbs-h">${t('scoreboard_share.title')}</h2>
            <p class="muted">${t('scoreboard_share.intro')}</p>
            <div class="actions">
                ${state.shown
        ? html`<button type="button" data-testid="scoreboard-hide" onClick=${() => this.hide()}>${t('scoreboard_share.hide')}</button>`
        : html`<button type="button" class="primary" data-testid="scoreboard-show" onClick=${() => this.show()}>${t('scoreboard_share.show')}</button>`}
            </div>
            ${state.shown && links.length === 0 && html`<p class="warning" data-testid="scoreboard-none">${t('scoreboard_share.none')}</p>`}
            ${link && html`<div data-testid="scoreboard-link-box">
                ${links.length > 1 && html`<div class="field"><label for="sbs-addr">${t('scoreboard_share.address')}</label>
                    <select id="sbs-addr" data-testid="scoreboard-address" value=${state.which}
                        onChange=${(e) => this.setState({ which: Number(e.target.value) })}>
                        ${links.map((l, i) => html`<option value=${i}>${l.replace(/#.*$/, '').replace(/\/scoreboard$/, '')}</option>`)}
                    </select></div>`}
                <div class="qr-wrap"><${QrCode} text=${link} label=${t('scoreboard_share.qr_label')} testid="scoreboard-qr" /></div>
                <p class="small"><code data-testid="scoreboard-link">${link}</code></p>
                <p class="notice" data-testid="scoreboard-warning">${t('scoreboard_share.warning')}</p>
            </div>`}
        </section>`;
    }
}
