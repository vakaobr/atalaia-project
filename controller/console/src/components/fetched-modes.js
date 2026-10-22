// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Modes fetched by boxes (phase 5 plan phase 13, protocol/mode-packages.md, decisions P5B-15,
// P5B-16, P5D-*), for the GM, under the Boxes tab: each box's fetched signed modes from its last
// report, and a mark that makes it forget them at its next invite (join key 17). The mode keys
// built into the boxes' firmware ([modes] box_keys) decide what can be sent to them at all.

import { html, Component, t } from '../ui.js';

function shortId(id) {
    return id ? `${id.slice(0, 4)}·${id.slice(4, 8)}` : '';
}

export class FetchedModes extends Component {
    componentDidMount() {
        this.props.app.loadModeFetch();
    }

    async forget(device, on) {
        const app = this.props.app;
        if (await app.call('PUT', `/mode-fetch/forget/${device}`, { forget: on })) app.loadModeFetch();
    }

    renderRow(b) {
        const kept = b.kept ? Object.entries(b.kept) : null;
        const key = b.device_id || `node-${b.node_id}`;
        return html`<tr data-testid=${`fetched-${key}`}>
            <td>${b.device_id ? html`<code title=${b.device_id}>${shortId(b.device_id)}</code>`
                : t('mode_fetch.unknown_box', { node: b.node_id })}</td>
            <td>${kept === null ? '–' : kept.length === 0 ? html`<span class="muted">${t('mode_fetch.kept_none')}</span>`
                : kept.map(([id, version]) => html`<span class="pill small">${id} ${version}</span> `)}</td>
            <td class="muted small">${b.game != null ? t('mode_fetch.reported_game', { game: b.game, node: b.node_id }) : '–'}</td>
            <td>${b.device_id && (b.forget
                ? html`<span class="notice small">${t('mode_fetch.will_forget')}</span>
                    <button type="button" class="small link" data-testid=${`fetched-undo-${b.device_id}`}
                        onClick=${() => this.forget(b.device_id, false)}>${t('mode_fetch.undo')}</button>`
                : html`<button type="button" class="small" data-testid=${`fetched-forget-${b.device_id}`}
                    disabled=${!kept || kept.length === 0}
                    onClick=${() => this.forget(b.device_id, true)}>${t('mode_fetch.forget')}</button>`)}</td>
        </tr>`;
    }

    render(props) {
        const app = props.app;
        const mf = app.state.modeFetch;
        if (app.state.role !== 'gm' || !mf) return null;
        return html`<section class="card" aria-labelledby="fetched-h" data-testid="fetched-modes">
            <h2 id="fetched-h">${t('mode_fetch.boxes_title')}</h2>
            <p class="muted small">${t('mode_fetch.boxes_hint')}</p>
            ${mf.box_keys.length === 0
                ? html`<p class="warning" data-testid="fetched-no-keys">${t('mode_fetch.no_box_keys')}</p>`
                : html`<p class="small" data-testid="fetched-keys">${t('mode_fetch.box_keys')} ${
                    mf.box_keys.map((k) => html`<code>${k}</code> `)}</p>`}
            ${mf.boxes.length === 0
                ? html`<p class="muted" data-testid="fetched-none">${t('mode_fetch.none')}</p>`
                : html`<div class="table-wrap"><table class="table">
                    <thead><tr><th>${t('mode_fetch.box')}</th><th>${t('mode_fetch.kept')}</th>
                        <th>${t('mode_fetch.reported')}</th><th><span class="sr-only">${t('mode_fetch.forget')}</span></th></tr></thead>
                    <tbody>${mf.boxes.map((b) => this.renderRow(b))}</tbody>
                </table></div>`}
        </section>`;
    }
}
