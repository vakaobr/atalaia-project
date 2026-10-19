// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Game control: create a game from a mode or a preset, start, pause,
// resume and end it (each confirmed in place), send a message to every
// box, adjust a team's score. ControllerPanel: role, term, radio, promote.

import { html, Component, t, clock, ConfirmButton, modeText } from '../ui.js';
import { FirstSetupNotice, mhz } from './radio-settings.js';
import {
    ParamFields, ModifierPicker, initialValues, mainModes, partsOf, schemaOf, modeName,
} from './preset-builder.js';

const BROADCAST = 65535;

function parseTeams(text) {
    return text.split(',').map((s) => s.trim()).filter(Boolean);
}

class CreateGame extends Component {
    constructor(props) {
        super(props);
        this.state = { name: '', source: '', teams: 'red, blue', minutes: '20', squads: '0', values: null, mods: [] };
    }

    /** The mode or preset picked, its modifiers, and their parameter schema and labels. */
    choice() {
        const { modes, presets } = this.props.app.state;
        const mains = mainModes(modes);
        const src = this.state.source || (mains[0] ? `mode:${mains[0].id}` : '');
        let preset = null;
        let mode;
        let mods;
        if (src.startsWith('preset:')) {
            preset = presets.find((p) => String(p.id) === src.slice(7)) || null;
            ({ main: mode, mods } = partsOf(modes, preset ? preset.mode_id : ''));
        } else {
            mode = mains.find((m) => `mode:${m.id}` === src);
            mods = this.state.mods.map((id) => modes.find((m) => m.id === id)).filter(Boolean);
        }
        return { src, preset, mode, mods, ...schemaOf(mode, mods) };
    }

    pick(source) {
        this.setState({ source, values: null, mods: [] });
    }

    async submit(e) {
        e.preventDefault();
        const { preset, mode, mods, schema } = this.choice();
        if (!mode) return;
        const teams = parseTeams(this.state.teams);
        const values = this.state.values || initialValues(schema, preset ? preset.params : null);
        const body = { name: this.state.name.trim(), teams, params: values,
                       duration_ms: Math.max(0, Math.round(parseFloat(this.state.minutes || '0') * 60000)),
                       squads: Math.max(0, Math.min(16, parseInt(this.state.squads || '0', 10) || 0)) };
        if (preset) {
            body.preset_id = preset.id;
        } else {
            body.mode_id = mode.id;
            if (mods.length) body.modifiers = mods.map((m) => m.id);
        }
        const game = await this.props.app.call('POST', '/games', body);
        if (game) this.props.app.setGame(game);
    }

    render(props, state) {
        const { modes, presets } = props.app.state;
        const { src, preset, mode, schema, labels } = this.choice();
        const teams = parseTeams(state.teams);
        const values = state.values || (mode ? initialValues(schema, preset ? preset.params : null) : {});
        return html`<form class="form" onSubmit=${(e) => this.submit(e)} data-testid="create-game">
            <h3>${t('game.new')}</h3>
            <div class="field"><label for="g-name">${t('game.name')}</label>
                <input id="g-name" data-testid="game-name" required maxlength="64" value=${state.name}
                    onInput=${(e) => this.setState({ name: e.target.value })} /></div>
            <div class="field"><label for="g-source">${t('game.source')}</label>
                <select id="g-source" data-testid="game-source" value=${src} onChange=${(e) => this.pick(e.target.value)}>
                    <optgroup label=${t('game.modes')}>
                        ${mainModes(modes).map((m) => html`<option value=${`mode:${m.id}`}>${modeText(m, 'name')}</option>`)}
                    </optgroup>
                    ${presets.length > 0 && html`<optgroup label=${t('game.presets')}>
                        ${presets.map((p) => html`<option value=${`preset:${p.id}`}>${p.name}</option>`)}
                    </optgroup>`}
                </select></div>
            <div class="field"><label for="g-teams">${t('game.teams')}</label>
                <input id="g-teams" data-testid="game-teams" required value=${state.teams}
                    onInput=${(e) => this.setState({ teams: e.target.value })} />
                <small class="muted">${t('game.teams_hint')}</small></div>
            <div class="field"><label for="g-minutes">${t('game.duration')}</label>
                <input id="g-minutes" type="number" min="0" step="1" value=${state.minutes}
                    onInput=${(e) => this.setState({ minutes: e.target.value })} />
                <small class="muted">${t('game.duration_hint')}</small></div>
            <div class="field"><label for="g-squads">${t('game.squads')}</label>
                <input id="g-squads" data-testid="game-squads" type="number" min="0" max="16" step="1" value=${state.squads}
                    onInput=${(e) => this.setState({ squads: e.target.value })} />
                <small class="muted">${t('game.squads_hint')}</small></div>
            ${mode && !preset && html`<${ModifierPicker} modes=${modes} selected=${state.mods} prefix="game"
                onChange=${(mods) => this.setState({ mods, values: null })} />`}
            ${mode && html`<details open=${!preset}>
                <summary>${t('game.params')}</summary>
                <p class="muted small">${modeText(mode, 'description')}</p>
                <${ParamFields} schema=${schema} labels=${labels} values=${values} teams=${teams} prefix="game"
                    onChange=${(v) => this.setState({ values: v })} />
            </details>`}
            <button type="submit" data-testid="game-create">${t('game.create')}</button>
        </form>`;
    }
}

class Broadcast extends Component {
    constructor() {
        super();
        this.state = { text: '', sent: '' };
    }

    async submit(e) {
        e.preventDefault();
        const text = this.state.text.trim();
        if (!text) return;
        const out = await this.props.app.call('POST', `/nodes/${BROADCAST}/cmd`, { cmd: 'message', params: { text } });
        if (out) this.setState({ text: '', sent: t('game.message_sent') });
    }

    render(props, state) {
        return html`<form class="form inline" onSubmit=${(e) => this.submit(e)}>
            <label for="g-msg">${t('game.message')}</label>
            <input id="g-msg" maxlength="100" value=${state.text} placeholder=${t('game.message_hint')}
                onInput=${(e) => this.setState({ text: e.target.value, sent: '' })} />
            <button type="submit">${t('game.send')}</button>
            ${state.sent && html`<span class="ok" role="status">${state.sent}</span>`}
        </form>`;
    }
}

class Adjust extends Component {
    constructor() {
        super();
        this.state = { team: '', amount: '', reason: '' };
    }

    async submit(e) {
        e.preventDefault();
        const { game } = this.props.app.state;
        const team = this.state.team || game.teams[0];
        const amount = parseInt(this.state.amount, 10);
        if (!amount) return;
        const out = await this.props.app.call('POST', `/games/${game.id}/score`,
                                              { team, amount, reason: this.state.reason.trim() });
        if (out) this.setState({ amount: '', reason: '' });
    }

    render(props, state) {
        const { game } = props.app.state;
        return html`<form class="form inline" onSubmit=${(e) => this.submit(e)} data-testid="adjust">
            <label for="adj-team">${t('game.adjust')}</label>
            <select id="adj-team" value=${state.team || game.teams[0]} onChange=${(e) => this.setState({ team: e.target.value })}>
                ${game.teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}
            </select>
            <input type="number" step="1" aria-label=${t('game.amount')} placeholder=${t('game.amount')}
                value=${state.amount} onInput=${(e) => this.setState({ amount: e.target.value })} />
            <input maxlength="64" aria-label=${t('game.reason')} placeholder=${t('game.reason')}
                value=${state.reason} onInput=${(e) => this.setState({ reason: e.target.value })} />
            <button type="submit">${t('game.apply')}</button>
        </form>`;
    }
}

export class GameControl extends Component {
    lifecycle(action, body) {
        const { game } = this.props.app.state;
        return this.props.app.call('POST', `/games/${game.id}/${action}`, body).then((g) => {
            if (g) this.props.app.setGame(g);
        });
    }

    render(props) {
        const app = props.app;
        const { game, role, status } = app.state;
        const gm = role === 'gm';
        const live = game && game.live && game.state !== 'ended';
        const leading = status && status.role === 'leader';
        if (!live) {
            return html`<section class="card" aria-labelledby="game-h">
                <h2 id="game-h">${t('game.title')}</h2>
                ${game && game.state === 'ended' && html`<p data-testid="game-ended">${t('game.ended', { name: game.name })}</p>`}
                ${!game && html`<p class="muted">${t('game.none')}</p>`}
                <${FirstSetupNotice} app=${app} />
                ${gm ? html`<${CreateGame} app=${app} />` : html`<p class="muted">${t('game.wait_gm')}</p>`}
            </section>`;
        }
        const s = game.state;
        const pending = (app.state.chronoCounts && app.state.chronoCounts.pending) || 0;
        return html`<section class="card" aria-labelledby="game-h">
            <h2 id="game-h">${game.name}</h2>
            <dl class="facts">
                <dt>${t('game.state')}</dt><dd><span class=${`state state-${s}`} data-testid="game-state">${t(`game.states.${s}`)}</span></dd>
                <dt>${t('game.clock')}</dt><dd class="big-clock" data-testid="game-clock">${clock(app.gameTime())}</dd>
                <dt>${t('game.length')}</dt><dd>${game.duration_ms ? clock(game.duration_ms) : t('game.no_limit')}</dd>
                <dt>${t('game.mode')}</dt><dd>${modeName(props.app.state.modes, game.mode_id)}</dd>
                <dt>${t('game.teams')}</dt><dd>${game.teams.join(', ')}${game.squads
                    ? ` · ${t('game.squads_each', { n: game.squads })}` : ''}</dd>
                <dt>${t('game.id')}</dt><dd>${game.id}</dd>
                ${game.channel_hz && html`<dt>${t('radio.channel')}</dt><dd data-testid="game-channel">${mhz(game.channel_hz)} MHz</dd>`}
            </dl>
            ${game.joined && html`<p class="notice">${t('game.standby_notice')}</p>`}
            ${gm && html`<div class="actions" data-testid="game-actions">
                ${s === 'ready' && html`<${ConfirmButton} testid="game-start" class="primary" label=${t('game.start')}
                    question=${pending ? t('game.confirm_start_pending', { n: pending }) : t('game.confirm_start')}
                    disabled=${!leading} onConfirm=${() => this.lifecycle('start')} />`}
                ${s === 'running' && html`<${ConfirmButton} testid="game-pause" label=${t('game.pause')}
                    question=${t('game.confirm_pause')} disabled=${!leading} onConfirm=${() => this.lifecycle('pause', {})} />`}
                ${s === 'paused' && html`<${ConfirmButton} testid="game-resume" class="primary" label=${t('game.resume')}
                    question=${t('game.confirm_resume')} disabled=${!leading} onConfirm=${() => this.lifecycle('resume')} />`}
                <${ConfirmButton} testid="game-end" class="danger" label=${game.joined && !leading ? t('game.leave') : t('game.end')}
                    question=${t('game.confirm_end')} onConfirm=${() => this.lifecycle('end', {})} />
            </div>`}
            ${gm && !leading && html`<p class="notice">${t('game.not_leader')}</p>`}
            ${gm && leading && html`<${Broadcast} app=${app} />`}
            ${gm && leading && html`<${Adjust} app=${app} />`}
        </section>`;
    }
}

export class ControllerPanel extends Component {
    render(props) {
        const app = props.app;
        const { status, role, game } = app.state;
        if (!status) return html`<section class="card"><p class="muted">…</p></section>`;
        const modem = status.modem || {};
        const ident = modem.ident || {};
        const tx = Object.entries(status.tx_status || {}).map(([k, v]) => `${k}: ${v}`).join(', ') || '–';
        const canPromote = role === 'gm' && game && game.live && status.role && status.role !== 'leader';
        return html`<section class="card" aria-labelledby="ctl-h">
            <h2 id="ctl-h">${t('controller.title')}</h2>
            <dl class="facts" data-testid="controller-status">
                <dt>${t('controller.node_id')}</dt><dd>${status.node_id}</dd>
                <dt>${t('controller.role')}</dt><dd data-testid="controller-role">${status.role ? t(`controller.roles.${status.role}`) : '–'}</dd>
                <dt>${t('controller.term')}</dt><dd>${status.term === null ? '–' : status.term}</dd>
                <dt>${t('controller.leader')}</dt><dd>${status.leader === null || status.leader === undefined ? '–' : status.leader}</dd>
                <dt>${t('controller.failover')}</dt><dd>${t(`controller.failover_modes.${status.failover_mode}`)}</dd>
                <dt>${t('controller.priority')}</dt><dd>${status.priority}</dd>
                <dt>${t('controller.radio')}</dt><dd>${t(`controller.radio_states.${status.radio}`)}</dd>
                <dt>${t('controller.modem')}</dt><dd>${ident.fw ? `${ident.fw} ${ident.fw_version || ''}` : '–'}</dd>
                <dt>${t('controller.reconnects')}</dt><dd>${modem.reconnects || 0}</dd>
                <dt>${t('controller.tx_epoch')}</dt><dd>${status.tx_epoch === null ? '–' : status.tx_epoch}</dd>
                <dt>${t('controller.tx_status')}</dt><dd>${tx}</dd>
                <dt>${t('controller.joined')}</dt><dd>${status.joined ? t('common.yes') : t('common.no')}</dd>
            </dl>
            ${canPromote && html`<div class="actions"><${ConfirmButton} testid="promote" class="danger" label=${t('controller.promote')}
                question=${t('controller.confirm_promote')} onConfirm=${() => app.call('POST', '/controller/promote').then((s) => s && app.setState({ status: s }))} /></div>`}
            <p class="muted small">${t('controller.promote_hint')}</p>
        </section>`;
    }
}
