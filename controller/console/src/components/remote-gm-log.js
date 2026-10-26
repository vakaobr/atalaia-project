// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The remote GM's log (decision S19-11): a person with the GM role on the site server can run the live
// game from afar when [sync] remote_gm is on. This panel, in the Controller tab, says whether that is on,
// whether the stream to the site server is open, and lists every command it sent (who, what, to which game,
// and what came of it), from GET /api/v1/remote-gm (the Pi's controller and the phone's serve it alike).
// It asks again every 10 s while it is on screen; the GM token only.

import { html, Component, t, api } from '../ui.js';

const LIMIT = 200;
const EVERY_MS = 10000;
const COMMANDS = ['start', 'pause', 'resume', 'end', 'message', 'mode'];
const RESULTS = ['done', 'remote_gm_off', 'invalid', 'stale', 'not_live', 'not_found', 'conflict', 'unavailable', 'failed'];

/** A key's text, else the raw value (a command or result this console does not know). */
function known(prefix, value, list) {
    return list.includes(value) ? t(`${prefix}.${value}`) : String(value === null || value === undefined ? '–' : value);
}

/** What a command asked for, in words: the pause or end reason, the message, the box and mode command. */
export function commandParams(c) {
    const p = c.params || {};
    if (c.command === 'start') return p.force === true ? t('remote_gm.forced') : '';
    if (c.command === 'pause' || c.command === 'end') return p.reason ? `“${p.reason}”` : '';
    if (c.command === 'message') return p.text ? `“${p.text}”` : '';
    if (c.command === 'mode') return t('remote_gm.mode_to', { name: p.name || '', node: p.node === undefined ? '' : p.node });
    return '';
}

export class RemoteGmLog extends Component {
    constructor() {
        super();
        this.state = { view: null, failed: false };
    }

    componentDidMount() {
        this.load();
        this.timer = setInterval(() => this.load(), EVERY_MS);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
    }

    async load() {
        const { app } = this.props;
        if (app.state.role !== 'gm') return;
        try {
            const view = await api(app.token, 'GET', `/remote-gm?limit=${LIMIT}`);
            this.setState({ view, failed: false });
        } catch (e) {
            this.setState({ failed: true }); // the panel says so; no toast every 10 s
        }
    }

    renderStream(v) {
        const s = v.stream;
        if (!v.enabled) return html`<p class="notice" data-testid="remote-gm-off">${t('remote_gm.off')}</p>`;
        return html`<dl class="facts" data-testid="remote-gm-status">
            <dt>${t('remote_gm.stream')}</dt>
            <dd data-testid="remote-gm-stream">${s && s.connected ? t('remote_gm.connected') : t('remote_gm.disconnected')}</dd>
            ${s && s.connected && s.connected_at ? html`<dt>${t('remote_gm.since')}</dt>
                <dd>${new Date(s.connected_at * 1000).toLocaleString()}</dd>` : null}
            ${s && s.last_error ? html`<dt>${t('remote_gm.last_error')}</dt><dd data-testid="remote-gm-error">${s.last_error}</dd>` : null}
            <dt>${t('remote_gm.received')}</dt><dd>${s ? s.commands : 0}</dd>
        </dl>`;
    }

    render(props, state) {
        if (props.app.state.role !== 'gm') return null;
        const v = state.view;
        return html`<section class="card" aria-labelledby="rg-h" data-testid="remote-gm">
            <h2 id="rg-h">${t('remote_gm.title')}</h2>
            <p class="muted">${t('remote_gm.intro')}</p>
            ${state.failed && html`<p class="warning" role="status" data-testid="remote-gm-failed">${t('remote_gm.failed')}</p>`}
            ${v && this.renderStream(v)}
            ${v && (v.log.length === 0
        ? html`<p class="muted" data-testid="remote-gm-empty">${t('remote_gm.empty')}</p>`
        : html`<div class="table-wrap"><table data-testid="remote-gm-table">
                <caption class="sr-only">${t('remote_gm.log')}</caption>
                <thead><tr>
                    <th scope="col">${t('remote_gm.when')}</th><th scope="col">${t('remote_gm.who')}</th>
                    <th scope="col">${t('remote_gm.command')}</th><th scope="col">${t('remote_gm.game')}</th>
                    <th scope="col">${t('remote_gm.result')}</th>
                </tr></thead>
                <tbody>${v.log.map((c) => html`<tr data-testid="remote-gm-row" data-result=${c.result}>
                    <td>${new Date(c.received_at * 1000).toLocaleString()}</td>
                    <td>${c.username || '–'}</td>
                    <td>${known('remote_gm.commands', c.command, COMMANDS)}${commandParams(c) ? html` <span class="muted">${commandParams(c)}</span>` : null}</td>
                    <td>${c.game_id === null || c.game_id === undefined ? '–' : c.game_id}</td>
                    <td><span class=${c.result === 'done' ? 'ok' : 'refused'}>${known('remote_gm.results', c.result, RESULTS)}</span>${
    c.detail && c.result !== 'done' ? html` <span class="muted small">${c.detail}</span>` : null}</td>
                </tr>`)}</tbody>
            </table></div>`)}
            <div class="actions"><button type="button" data-testid="remote-gm-refresh" onClick=${() => this.load()}>${t('remote_gm.refresh')}</button></div>
        </section>`;
    }
}
