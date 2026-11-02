// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Access tokens (maintainer decision of 2026-11-01): short-lived, scoped, revocable tokens for a referee's
// phone for one game day, a visiting GM, an automated test run or a spectator screen, in Settings. The GM makes
// one (a label, what it may do, how long it lasts, optionally one game); the controller shows the token once,
// here, as text and as a QR code of the address that logs a phone in (the console for read-write scopes, the
// scoreboard for "read"); the list below shows each token's scope, expiry and last use and revokes it at once.
// Only the main GM token sees this panel (whoami says `access_tokens`): a token made here cannot make another,
// and the phone controller does not have it (GET /api/v1/tokens, the controller README).

import { html, Component, t, api } from '../ui.js';
import { QrCode } from './join-panel.js';

const SCOPES = ['read', 'marshals', 'gm'];
const LIFETIMES = [['1h', 3600], ['4h', 4 * 3600], ['8h', 8 * 3600], ['1d', 86400], ['3d', 3 * 86400], ['7d', 7 * 86400]];
const EVERY_MS = 15000;

function when(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleString() : '–';
}

export class AccessTokens extends Component {
    constructor() {
        super();
        this.state = { tokens: [], audit: [], games: [], label: '', scope: 'read', ttl: 8 * 3600, game: '',
                       made: null, which: 0, working: false, failed: false };
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
        if (app.state.role !== 'gm' || !app.state.accessTokens) return;
        try {
            const [list, audit, games] = await Promise.all([
                api(app.token, 'GET', '/tokens'), api(app.token, 'GET', '/tokens/audit?limit=10'),
                api(app.token, 'GET', '/games')]);
            this.setState({ tokens: list.tokens, audit: audit.audit, games, failed: false });
        } catch (e) {
            this.setState({ failed: true });
        }
    }

    async create(e) {
        e.preventDefault();
        const s = this.state;
        const body = { label: s.label, scope: s.scope, ttl_s: s.ttl };
        if (s.game && s.scope !== 'marshals') body.game_id = Number(s.game);
        this.setState({ working: true });
        const out = await this.props.app.call('POST', '/tokens', body);
        this.setState({ working: false });
        if (out) {
            this.setState({ made: out, which: 0, label: '' });
            this.load();
        }
    }

    async revoke(row) {
        if (!window.confirm(t('access_tokens.confirm_revoke', { label: row.label }))) return;
        const out = await this.props.app.call('DELETE', `/tokens/${row.id}`);
        if (out) {
            if (this.state.made && this.state.made.id === row.id) this.setState({ made: null });
            this.load();
        }
    }

    renderMade(made, which) {
        const links = made.links || [];
        const link = links[which] || null;
        return html`<div class="notice" data-testid="token-made">
            <p><strong>${t('access_tokens.made', { label: made.label })}</strong></p>
            <p class="small">${t('access_tokens.once')}</p>
            <p><code data-testid="token-value">${made.token}</code></p>
            <p class="small" data-testid="token-summary">${t('access_tokens.summary', {
        scope: t(`access_tokens.scopes.${made.scope}`), until: when(made.expires_at) })}${
    made.game_id ? ` ${t('access_tokens.summary_game', { game: made.game_id })}` : ''}</p>
            ${link ? html`<div>
                ${links.length > 1 && html`<div class="field"><label for="tok-addr">${t('access_tokens.address')}</label>
                    <select id="tok-addr" data-testid="token-address" value=${which}
                        onChange=${(e) => this.setState({ which: Number(e.target.value) })}>
                        ${links.map((l, i) => html`<option value=${i}>${l.replace(/#.*$/, '')}</option>`)}
                    </select></div>`}
                <div class="qr-wrap"><${QrCode} text=${link} label=${t('access_tokens.qr_label')} testid="token-qr" /></div>
                <p class="small">${t('access_tokens.qr_help')}</p>
            </div>` : html`<p class="muted small" data-testid="token-no-link">${t('access_tokens.no_link')}</p>`}
            <div class="actions"><button type="button" data-testid="token-done" onClick=${() => this.setState({ made: null })}>${t('access_tokens.done')}</button></div>
        </div>`;
    }

    render(props, state) {
        if (props.app.state.role !== 'gm' || !props.app.state.accessTokens) return null;
        const gameOk = state.scope !== 'marshals';
        return html`<section class="card" aria-labelledby="tok-h" data-testid="access-tokens">
            <h2 id="tok-h">${t('access_tokens.title')}</h2>
            <p class="muted">${t('access_tokens.intro')}</p>
            ${state.failed && html`<p class="warning" role="status" data-testid="tokens-failed">${t('access_tokens.failed')}</p>`}
            <form onSubmit=${(e) => this.create(e)} data-testid="token-form">
                <div class="field"><label for="tok-label">${t('access_tokens.label')}</label>
                    <input id="tok-label" data-testid="token-label" maxlength="60" required value=${state.label}
                        placeholder=${t('access_tokens.label_hint')} onInput=${(e) => this.setState({ label: e.target.value })} /></div>
                <div class="field"><label for="tok-scope">${t('access_tokens.scope')}</label>
                    <select id="tok-scope" data-testid="token-scope" value=${state.scope}
                        onChange=${(e) => this.setState({ scope: e.target.value, game: e.target.value === 'marshals' ? '' : state.game })}>
                        ${SCOPES.map((s) => html`<option value=${s} selected=${s === state.scope}>${t(`access_tokens.scopes.${s}`)}</option>`)}
                    </select>
                    <p class="muted small" data-testid="token-scope-help">${t(`access_tokens.scope_help.${state.scope}`)}</p></div>
                <div class="field"><label for="tok-ttl">${t('access_tokens.lifetime')}</label>
                    <select id="tok-ttl" data-testid="token-ttl" value=${state.ttl}
                        onChange=${(e) => this.setState({ ttl: Number(e.target.value) })}>
                        ${LIFETIMES.map(([k, s]) => html`<option value=${s} selected=${s === state.ttl}>${t(`access_tokens.lifetimes.${k}`)}</option>`)}
                    </select></div>
                <div class="field"><label for="tok-game">${t('access_tokens.game')}</label>
                    <select id="tok-game" data-testid="token-game" disabled=${!gameOk} value=${state.game}
                        onChange=${(e) => this.setState({ game: e.target.value })}>
                        <option value="" selected=${state.game === ''}>${t('access_tokens.all_games')}</option>
                        ${state.games.map((g) => html`<option value=${g.id} selected=${String(g.id) === state.game}>${g.id} · ${g.name}</option>`)}
                    </select>
                    <p class="muted small">${t('access_tokens.game_help')}</p></div>
                <div class="actions"><button type="submit" class="primary" data-testid="token-create" disabled=${state.working}>${t('access_tokens.create')}</button></div>
            </form>
            ${state.made && this.renderMade(state.made, state.which)}
            ${state.tokens.length === 0
        ? html`<p class="muted" data-testid="tokens-empty">${t('access_tokens.empty')}</p>`
        : html`<div class="table-wrap"><table data-testid="tokens-table">
                <caption class="sr-only">${t('access_tokens.list')}</caption>
                <thead><tr>
                    <th scope="col">${t('access_tokens.label')}</th><th scope="col">${t('access_tokens.scope')}</th>
                    <th scope="col">${t('access_tokens.game')}</th><th scope="col">${t('access_tokens.expires')}</th>
                    <th scope="col">${t('access_tokens.last_used')}</th><th scope="col">${t('access_tokens.status')}</th>
                    <th scope="col"><span class="sr-only">${t('access_tokens.revoke')}</span></th>
                </tr></thead>
                <tbody>${state.tokens.map((r) => html`<tr data-testid="token-row" data-status=${r.status} data-id=${r.id}>
                    <td>${r.label}</td><td>${t(`access_tokens.scopes.${r.scope}`)}</td><td>${r.game_id || '–'}</td>
                    <td>${when(r.expires_at)}</td><td>${when(r.last_used_at)}</td>
                    <td><span class=${r.status === 'active' ? 'ok' : 'refused'}>${t(`access_tokens.statuses.${r.status}`)}</span></td>
                    <td>${r.status === 'active' && html`<button type="button" data-testid="token-revoke"
                        onClick=${() => this.revoke(r)}>${t('access_tokens.revoke')}</button>`}</td>
                </tr>`)}</tbody>
            </table></div>`}
            ${state.audit.length > 0 && html`<details data-testid="tokens-audit"><summary>${t('access_tokens.activity')}</summary>
                <ul class="small">${state.audit.map((a) => html`<li>${when(a.at)} · ${t(`access_tokens.audit.${a.kind}`)} · ${a.label || a.token_id}${a.detail ? html` <span class="muted">${a.detail}</span>` : null}</li>`)}</ul>
            </details>`}
        </section>`;
    }
}
