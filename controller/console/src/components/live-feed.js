// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Live feed: the game's events as they arrive (newest first), filterable,
// with critical events highlighted, and the alerts the console raises:
// radio down, failed transmissions, modem errors, boxes gone quiet,
// controller role changes and critical events.

import { html, Component, t, clock, brief, eventWords } from '../ui.js';

export class LiveFeed extends Component {
    constructor() {
        super();
        this.state = { filter: '', criticalOnly: false };
    }

    render(props, state) {
        const app = props.app;
        const { feed, alerts, status } = app.state;
        const self = status ? status.node_id : null;
        const f = state.filter.trim().toLowerCase();
        const shown = feed.filter((e) => (!state.criticalOnly || e.prio === 'critical')
            && (!f || `${e.type} ${e.team || ''} ${e.node} ${brief(e.data)} ${eventWords(e)}`
                .toLowerCase().includes(f)));
        return html`<section class="card" aria-labelledby="feed-h">
            <h2 id="feed-h">${t('feed.title')}</h2>
            ${alerts.length > 0 && html`<ul class="alerts" data-testid="alerts" aria-live="polite">
                ${alerts.slice(0, 8).map((a) => html`<li class=${`alert alert-${a.level}`}>
                    <span>${new Date(a.at).toLocaleTimeString()}</span> ${a.text}
                    <button type="button" class="link" aria-label=${t('feed.dismiss')}
                        onClick=${() => app.dismissAlert(a.id)}>×</button>
                </li>`)}
            </ul>`}
            <div class="filters">
                <label for="feed-filter" class="sr-only">${t('feed.filter')}</label>
                <input id="feed-filter" type="search" placeholder=${t('feed.filter')} value=${state.filter}
                    data-testid="feed-filter" onInput=${(e) => this.setState({ filter: e.target.value })} />
                <label class="check"><input type="checkbox" checked=${state.criticalOnly}
                    onChange=${(e) => this.setState({ criticalOnly: e.target.checked })} /> ${t('feed.critical_only')}</label>
                <span class="muted small">${t('feed.count', { n: shown.length })}</span>
            </div>
            ${shown.length === 0 ? html`<p class="muted">${t('feed.empty')}</p>` : html`
            <ol class="feed" data-testid="feed">
                ${shown.slice(0, 200).map((e) => html`<li class=${`ev prio-${e.prio || 'normal'}`} data-type=${e.type}>
                    <span class="ev-t">${clock(e.t)}</span>
                    <span class="ev-type">${e.type}</span>
                    ${e.team && html`<span class="ev-team">${e.team}</span>`}
                    <span class="ev-node">${e.node === self ? t('nodes.controller') : `${t('nodes.node')} ${e.node}`}</span>
                    ${eventWords(e) ? html`<span class="ev-words">${eventWords(e)}</span>`
                        : html`<span class="ev-data">${brief(e.data)}</span>`}
                </li>`)}
            </ol>`}
        </section>`;
    }
}
