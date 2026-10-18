// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The example scoreboard (plan phase E): a read-only page for a TV or a
// laptop at the safe zone. It needs only the READ token, given in the
// address (#token=...; &lang=en for English) or kept from the console, and
// follows the game over WS /api/v1/stream: team totals, state and clock.

import { html, render, Component, t, loadLanguage, Stream, savedToken, teamColour, clock } from './ui.js';

function fromHash() {
    const out = {};
    for (const part of location.hash.replace(/^#/, '').split('&')) {
        const [k, v] = part.split('=');
        if (k) out[decodeURIComponent(k)] = decodeURIComponent(v || '');
    }
    return out;
}

class Board extends Component {
    constructor() {
        super();
        const hash = fromHash();
        this.state = { ready: false, token: hash.token || savedToken(), hashLang: hash.lang, connected: null,
                       game: null, score: null, base: null, now: Date.now(), denied: false };
    }

    async componentDidMount() {
        await loadLanguage(this.state.hashLang);
        this.setState({ ready: true });
        document.title = `Atalaia · ${t('scoreboard.title')}`;
        if (this.state.token) {
            this.stream = new Stream(this.state.token, (m) => this.onMessage(m), (s) => {
                if (s === 'denied') this.setState({ denied: true, connected: false });
                else this.setState({ connected: s === 'open' });
            });
        }
        this.timer = setInterval(() => this.setState({ now: Date.now() }), 500);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
        if (this.stream) this.stream.close();
    }

    setGame(game) {
        const base = game && game.game_time_ms !== undefined
            ? { ms: game.game_time_ms, at: Date.now(), running: game.state === 'running' } : null;
        this.setState({ game, base });
    }

    onMessage(msg) {
        if (msg.type === 'hello') {
            this.setGame(msg.game);
            this.setState({ score: msg.score });
        } else if (msg.type === 'game') {
            if (!this.state.game || msg.game.live || msg.game.id === this.state.game.id) this.setGame(msg.game);
        } else if (msg.type === 'score') {
            this.setState({ score: { game: msg.game, teams: msg.teams } });
        }
    }

    gameTime() {
        const b = this.state.base;
        if (!b) return null;
        return b.running ? b.ms + (this.state.now - b.at) : b.ms;
    }

    result(teams, totals) {
        const ranked = teams.map((tm) => [totals[tm] || 0, tm]).sort((a, b) => b[0] - a[0]);
        if (!ranked.length || ranked[0][0] <= 0) return '';
        if (ranked.length > 1 && ranked[0][0] === ranked[1][0]) return t('scoreboard.tie');
        return t('scoreboard.winner', { team: ranked[0][1] });
    }

    render(props, s) {
        if (!s.ready) return null;
        if (!s.token || s.denied) {
            return html`<main class="board"><h1>${t('scoreboard.title')}</h1>
                <p class="note" data-testid="board-token">${t('scoreboard.token_needed')}</p></main>`;
        }
        const g = s.game;
        const teams = (g && g.teams) || [];
        const totals = (s.score && g && s.score.game === g.id && s.score.teams) || {};
        let remaining = null;
        if (g && g.duration_ms) remaining = Math.max(0, g.duration_ms - (this.gameTime() || 0));
        return html`<main class="board">
            <header>
                <h1 data-testid="board-title">${g ? g.name : t('scoreboard.title')}</h1>
                ${g && html`<p class="status"><span data-testid="board-state">${t(`game.states.${g.state}`)}</span>${' · '}<span
                    class="clock" data-testid="board-clock">${clock(remaining !== null ? remaining : this.gameTime())}</span></p>`}
            </header>
            ${s.connected === false && html`<p class="note" role="status">${t('scoreboard.offline')}</p>`}
            ${s.connected === null && html`<p class="note" role="status">${t('scoreboard.connecting')}</p>`}
            ${!g && s.connected && html`<p class="note">${t('scoreboard.no_game')}</p>`}
            ${g && html`<ul class="teams">
                ${teams.map((tm) => html`<li class="team" ref=${(el) => { if (el) el.style.borderColor = teamColour(tm, teams); }}>
                    <span class="name">${tm}</span>
                    <strong class="points" data-testid=${`board-score-${tm}`}>${totals[tm] || 0}</strong>
                </li>`)}
            </ul>`}
            ${g && g.state === 'ended' && html`<p class="result" data-testid="board-result">${this.result(teams, totals)}</p>`}
        </main>`;
    }
}

render(html`<${Board} />`, document.getElementById('board'));
