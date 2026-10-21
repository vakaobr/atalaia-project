// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The GM console (ADR-P2-10): Preact + HTM, no build step. One App holds
// the state the controller streams over WS /api/v1/stream and hands it to
// the panels in components/. Every change goes through the REST API v1.

import { html, render, Component, t, loadLanguage, LANGS, api, ApiError, Stream,
         savedToken, saveToken, clock, OFFLINE_MS, fetchBranding, brandingUrl } from './ui.js';
import { GameControl, ControllerPanel } from './components/game-control.js';
import { ScorePanel } from './components/score-panel.js';
import { LiveFeed } from './components/live-feed.js';
import { NodeList } from './components/node-list.js';
import { FieldView } from './components/field-view.js';
import { JoinPanel } from './components/join-panel.js';
import { PresetBuilder } from './components/preset-builder.js';
import { ScenarioBuilder } from './components/scenario-builder.js';
import { RadioSettings } from './components/radio-settings.js';
import { CheckinPanel } from './components/checkin-panel.js';
import { BrandingSettings, TeamPresets, FieldBrand, accentRef } from './components/branding-settings.js';

const TABS = ['game', 'checkin', 'field', 'nodes', 'join', 'presets', 'scenarios', 'feed', 'controller', 'settings'];
const FEED_MAX = 500;
const ALERTS_MAX = 50;
const HISTORY_MAX = 240;

class App extends Component {
    constructor() {
        super();
        this.state = {
            ready: false, lang: 'pt', token: savedToken(), role: null, loginError: '',
            tab: 'game', connected: null, status: null, game: null, score: null,
            nodes: {}, seen: {}, feed: [], alerts: [], modes: [], presets: [],
            positions: {}, scoreHistory: [], clockBase: null, toast: '', now: Date.now(),
            radio: null, chronoCounts: null, branding: null, teamPresets: [],
        };
        this.checkinPanel = null;
        this.stream = null;
        this.token = '';
        this.offline = new Set();
        this.alertSeq = 0;
    }

    async componentDidMount() {
        const l = await loadLanguage();
        this.setState({ ready: true, lang: l });
        // The field's branding is public: the login page shows it before any token (decision BR3).
        fetchBranding().then((b) => { if (b && !this.state.branding) this.setState({ branding: b }); });
        if (this.state.token) this.login(this.state.token);
        this.ticker = setInterval(() => this.tick(), 1000);
        this.refresher = setInterval(() => this.refresh(), 10000);
    }

    componentWillUnmount() {
        clearInterval(this.ticker);
        clearInterval(this.refresher);
        if (this.stream) this.stream.close();
    }

    // ---- REST with error reporting --------------------------------------------

    async call(method, path, body, raw) {
        try {
            return await api(this.token, method, path, body, raw);
        } catch (e) {
            if (e instanceof ApiError && e.status === 401) {
                this.logout(t('login.expired'));
                return null;
            }
            this.showToast(e.message);
            return null;
        }
    }

    showToast(text) {
        clearTimeout(this.toastTimer);
        this.setState({ toast: text });
        this.toastTimer = setTimeout(() => this.setState({ toast: '' }), 8000);
    }

    // ---- login ----------------------------------------------------------------

    async login(token) {
        try {
            const who = await api(token, 'GET', '/whoami');
            saveToken(token);
            this.token = token; // used at once below: setState is applied later
            this.setState({ token, role: who.role, loginError: '' });
            this.startStream();
            this.loadCatalogue();
        } catch (e) {
            this.setState({ role: null, loginError: e.status === 401 ? t('login.bad') : e.message });
        }
    }

    logout(reason) {
        if (this.stream) this.stream.close();
        this.stream = null;
        this.token = '';
        saveToken('');
        this.setState({ token: '', role: null, connected: null, loginError: reason || '',
                        game: null, status: null, nodes: {}, feed: [], alerts: [], radio: null });
    }

    async loadCatalogue() {
        const [modes, presets] = await Promise.all([this.call('GET', '/modes'), this.call('GET', '/presets')]);
        this.setState({ modes: modes || [], presets: presets || [] });
    }

    async loadTeamPresets() {
        const list = await this.call('GET', '/team-presets');
        if (list) this.setState({ teamPresets: list });
    }

    async loadRadio() {
        const radio = await this.call('GET', '/radio');
        if (radio) this.setState({ radio });
    }

    startStream() {
        if (this.stream) this.stream.close();
        this.stream = new Stream(this.token, (m) => this.onMessage(m), (s) => {
            if (s === 'denied') this.logout(t('login.expired'));
            else this.setState({ connected: s === 'open' });
        });
    }

    // ---- the live stream --------------------------------------------------------

    onMessage(msg) {
        const now = Date.now();
        switch (msg.type) {
        case 'hello': {
            const nodes = {};
            const seen = {};
            for (const n of msg.nodes || []) {
                nodes[n.node_id] = n;
                seen[n.node_id] = n.seen_ms_ago !== null && n.seen_ms_ago !== undefined ? now - n.seen_ms_ago : now;
            }
            this.setState({ status: msg.status, score: msg.score, nodes, seen });
            if (msg.branding) this.setState({ branding: msg.branding });
            this.setGame(msg.game);
            if (msg.game) {
                this.loadLog(msg.game.id);
                this.loadPositions(msg.game.id);
                this.loadChronoCounts(msg.game);
            }
            break;
        }
        case 'checkin':
        case 'checkin_open':
        case 'checkin_settings':
        case 'roster':
            if (this.checkinPanel) this.checkinPanel.onStream(msg);
            break;
        case 'chrono_list':
            if (this.state.game && msg.game === this.state.game.id) this.setState({ chronoCounts: msg.counts });
            if (this.checkinPanel) this.checkinPanel.onStream(msg);
            break;
        case 'event': {
            const ev = { ...msg.event, game: msg.game, at: now };
            this.setState((s) => ({ feed: [ev, ...s.feed].slice(0, FEED_MAX) }));
            if (ev.prio === 'critical') this.alert('crit', `${ev.type} · ${t('nodes.node')} ${ev.node}`);
            break;
        }
        case 'score':
            this.setState((s) => ({
                score: { game: msg.game, teams: msg.teams },
                scoreHistory: [...s.scoreHistory, { at: now, teams: msg.teams }].slice(-HISTORY_MAX),
            }));
            break;
        case 'node': {
            // A link event (node.offline) is news about a box that said nothing: its own last-heard time.
            const ago = msg.node.seen_ms_ago;
            this.setState((s) => {
                const seen = { ...s.seen };
                if (ago === null) delete seen[msg.node.node_id];
                else seen[msg.node.node_id] = ago === undefined ? now : now - ago;
                return { nodes: { ...s.nodes, [msg.node.node_id]: msg.node }, seen };
            });
            break;
        }
        case 'game':
            if (!this.state.game || msg.game.live || msg.game.id === this.state.game.id) {
                const isNew = !this.state.game || this.state.game.id !== msg.game.id;
                this.setGame(msg.game);
                if (isNew) this.setState({ chronoCounts: null });
                if (isNew && msg.game.live) this.loadChronoCounts(msg.game);
                if (isNew) this.setState({ feed: [], scoreHistory: [], positions: {}, nodes: {}, seen: {} });
                if (isNew && msg.game.live) {
                    this.loadPositions(msg.game.id);
                    this.reloadNodes();
                }
            }
            this.refreshStatus();
            if (this.state.radio) this.loadRadio(); // a live game locks the channel
            break;
        case 'modes':
            this.loadCatalogue(); // a scenario was installed (here or in another console)
            break;
        case 'radio':
            this.setState({ radio: msg.radio });
            break;
        case 'radio_scan':
            this.setState((s) => ({ radio: s.radio ? { ...s.radio, scan: msg.scan } : s.radio }));
            if (msg.scan.state !== 'running') this.loadRadio();
            break;
        case 'system':
            this.onSystem(msg);
            break;
        case 'join':
            this.reloadNodes();
            this.refreshGame();
            break;
        case 'position':
            this.setState((s) => ({ positions: { ...s.positions, [msg.node_id]: { x: msg.x, y: msg.y } } }));
            break;
        case 'branding':
            this.setState({ branding: msg.branding });
            break;
        case 'field_image':
            this.setState((s) => ({ imageVersion: (s.imageVersion || 0) + 1 }));
            break;
        case 'field_georef':
            this.setState((s) => ({ georefVersion: (s.georefVersion || 0) + 1 }));
            break;
        default:
            break;
        }
    }

    onSystem(msg) {
        if (msg.kind === 'radio.down') this.alert('crit', t('alerts.radio_down'));
        else if (msg.kind === 'radio.up') this.alert('info', t('alerts.radio_up'));
        else if (msg.kind === 'tx.failed') this.alert('warn', t('alerts.tx_failed', { status: msg.status, seq: msg.seq }));
        else if (msg.kind === 'modem.error') this.alert('warn', t('alerts.modem_error', { message: msg.message }));
        else if (msg.kind === 'role') this.alert('info', t('alerts.role', { role: t(`controller.roles.${msg.role}`), term: msg.term }));
        this.refreshStatus();
    }

    alert(level, text) {
        this.alertSeq += 1;
        const a = { id: this.alertSeq, level, text, at: Date.now() };
        this.setState((s) => ({ alerts: [a, ...s.alerts].slice(0, ALERTS_MAX) }));
    }

    dismissAlert(id) {
        this.setState((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) }));
    }

    setGame(game) {
        const clockBase = game && game.game_time_ms !== undefined
            ? { ms: game.game_time_ms, at: Date.now(), running: game.state === 'running' } : null;
        this.setState({ game, clockBase });
    }

    gameTime() {
        const b = this.state.clockBase;
        if (!b) return null;
        return b.running ? b.ms + (this.state.now - b.at) : b.ms;
    }

    async loadLog(gameId) {
        const log = await this.call('GET', `/games/${gameId}/log`);
        if (!log) return;
        const now = Date.now();
        const feed = log.slice(-FEED_MAX).reverse().map((e) => ({ ...e, game: gameId, at: now }));
        this.setState((s) => ({ feed: [...s.feed.filter((e) => e.game === gameId && e.at > now), ...feed]
            .slice(0, FEED_MAX) }));
    }

    async loadChronoCounts(game) {
        // The start warning (ADR-P3-13): replicas declared and not chronographed yet.
        if (this.state.role !== 'gm' || !game.live || game.state === 'ended') return;
        const list = await this.call('GET', `/games/${game.id}/chrono-list`);
        if (list) this.setState({ chronoCounts: list.counts });
    }

    async loadPositions(gameId) {
        const p = await this.call('GET', `/games/${gameId}/positions`);
        if (p) this.setState({ positions: p });
    }

    async reloadNodes() {
        const list = await this.call('GET', '/nodes');
        if (!list) return;
        const now = Date.now();
        const nodes = {};
        const seen = { ...this.state.seen };
        for (const n of list) {
            nodes[n.node_id] = n;
            if (n.seen_ms_ago !== null && n.seen_ms_ago !== undefined) seen[n.node_id] = now - n.seen_ms_ago;
        }
        this.setState({ nodes, seen });
    }

    async refreshStatus() {
        const status = await this.call('GET', '/controller');
        if (status) this.setState({ status });
    }

    async refreshGame() {
        const g = this.state.game;
        if (!g) return;
        const game = await this.call('GET', `/games/${g.id}`);
        if (game) this.setGame(game);
    }

    refresh() {
        if (!this.state.role || !this.state.connected) return;
        this.refreshStatus();
        if (this.state.game && this.state.game.live) this.refreshGame();
    }

    tick() {
        const now = Date.now();
        const { nodes, seen } = this.state;
        for (const id of Object.keys(nodes)) {
            const off = seen[id] !== undefined && now - seen[id] > OFFLINE_MS;
            if (off && !this.offline.has(id)) {
                this.offline.add(id);
                this.alert('warn', t('alerts.node_offline', { node: id }));
            } else if (!off && this.offline.has(id)) {
                this.offline.delete(id);
            }
        }
        this.setState({ now });
    }

    // ---- views ------------------------------------------------------------------

    async switchLang(l) {
        const got = await loadLanguage(l);
        this.setState({ lang: got });
    }

    renderLogin() {
        const submit = (e) => {
            e.preventDefault();
            const token = e.target.elements.token.value.trim();
            if (token) this.login(token);
        };
        const b = this.state.branding;
        return html`<main class="login">
            ${b && b.logo && html`<img class="login-logo" src=${brandingUrl(b.logo)} data-testid="login-logo"
                alt=${t('branding.logo_alt', { name: b.field_name })} />`}
            ${b && b.field_name && b.field_name !== 'Atalaia' && html`<p class="login-field" data-testid="login-field">${b.field_name}</p>`}
            <h1>${t('app.title')}</h1>
            <p>${t('login.intro')}</p>
            <form onSubmit=${submit}>
                <label for="token">${t('login.token')}</label>
                <input id="token" name="token" type="password" autocomplete="current-password"
                    data-testid="token" required />
                <button type="submit" data-testid="login">${t('login.enter')}</button>
            </form>
            ${this.state.loginError && html`<p class="error" role="alert">${this.state.loginError}</p>`}
            <p class="hint">${t('login.hint')}</p>
            ${this.renderLangPicker()}
        </main>`;
    }

    renderLangPicker() {
        return html`<label class="lang">
            <span class="sr-only">${t('app.language')}</span>
            <select data-testid="lang" value=${this.state.lang} onChange=${(e) => this.switchLang(e.target.value)}>
                ${LANGS.map((l) => html`<option value=${l}>${t(`app.lang_${l}`)}</option>`)}
            </select>
        </label>`;
    }

    renderHeader() {
        const { status, connected, game, role, alerts, branding } = this.state;
        const radio = status ? status.radio : 'none';
        return html`<header class="top" ref=${accentRef(branding)} data-testid="header">
            <div class="brand">
                <${FieldBrand} branding=${branding} fallback=${t('app.title')} />
                ${game && html`<span class="game-name" data-testid="header-game">${game.name}${' · '}<span
                    class=${`state state-${game.state}`}>${t(`game.states.${game.state}`)}</span>${' · '}<span
                    data-testid="header-clock">${clock(this.gameTime())}</span></span>`}
            </div>
            <div class="top-right">
                <span class=${`pill radio-${radio}`} title=${t('controller.radio')}>${t('controller.radio')}: ${t(`controller.radio_states.${radio}`)}</span>
                ${role === 'read' && html`<span class="pill" data-testid="readonly">${t('login.readonly')}</span>`}
                ${alerts.length > 0 && html`<button type="button" class="pill alert-pill"
                    onClick=${() => this.setState({ tab: 'feed' })}>${t('alerts.count', { n: alerts.length })}</button>`}
                ${this.renderLangPicker()}
                <button type="button" class="link" data-testid="logout" onClick=${() => this.logout()}>${t('login.leave')}</button>
            </div>
            ${connected === false && html`<div class="banner" role="status" data-testid="reconnecting">${t('app.reconnecting')}</div>`}
        </header>`;
    }

    renderTab(tab) {
        switch (tab) {
        case 'game':
            return html`<${GameControl} app=${this} /><${ScorePanel} app=${this} />`;
        case 'checkin':
            return html`<${CheckinPanel} app=${this} ref=${(c) => { this.checkinPanel = c; }} />`;
        case 'field':
            return html`<${FieldView} app=${this} />`;
        case 'nodes':
            return html`<${NodeList} app=${this} />`;
        case 'join':
            return html`<${JoinPanel} app=${this} />`;
        case 'presets':
            return html`<${PresetBuilder} app=${this} />`;
        case 'scenarios':
            return html`<${ScenarioBuilder} app=${this} />`;
        case 'feed':
            return html`<${LiveFeed} app=${this} />`;
        case 'controller':
            return html`<${ControllerPanel} app=${this} />`;
        case 'settings':
            return html`<${RadioSettings} app=${this} /><${BrandingSettings} app=${this} /><${TeamPresets} app=${this} />`;
        default:
            return null;
        }
    }

    render(props, state) {
        if (!state.ready) return html`<main class="loading">…</main>`;
        if (!state.role) return this.renderLogin();
        return html`<div class=${`app ${state.role === 'gm' ? 'is-gm' : 'is-read'}`}>
            ${this.renderHeader()}
            <nav class="tabs" aria-label=${t('app.sections')}>
                ${TABS.map((tab) => html`<button type="button" data-testid=${`tab-${tab}`}
                    class=${tab === state.tab ? 'active' : ''} aria-current=${tab === state.tab ? 'page' : undefined}
                    onClick=${() => this.setState({ tab })}>${t(`tabs.${tab}`)}</button>`)}
            </nav>
            <main class="content">${this.renderTab(state.tab)}</main>
            ${state.toast && html`<div class="toast" role="alert" data-testid="toast">
                ${state.toast} <button type="button" class="link" onClick=${() => this.setState({ toast: '' })}>×</button></div>`}
        </div>`;
    }
}

render(html`<${App} />`, document.getElementById('app'));

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {
        /* without a service worker the console still works, only not offline */
    });
}

