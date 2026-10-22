// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Game control: create a game from a mode or a preset, start, pause,
// resume and end it (each confirmed in place), send a message to every
// box, adjust a team's score. ControllerPanel: role, term, radio, promote.

import { html, Component, createRef, t, lang, clock, ConfirmButton, modeText, teamName } from '../ui.js';
import { FirstSetupNotice, mhz } from './radio-settings.js';
import { TeamFields, TeamsEditor, teamInfoBody } from './branding-settings.js';
import { BoxInvites, StartCheck } from './box-invites.js';
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
        this.state = { name: '', source: '', teams: 'red, blue', minutes: '20', squads: '0', values: null, mods: [],
                       teamInfo: {} };
    }

    componentDidMount() {
        this.props.app.loadTeamPresets();
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
        // The boxes' screens take this console's language unless the field fixes one (Settings).
        body.console_lang = lang();
        const info = teamInfoBody(this.state.teamInfo, teams);
        if (info) body.team_info = info;
        if (preset) {
            body.preset_id = preset.id;
        } else {
            body.mode_id = mode.id;
            if (mods.length) body.modifiers = mods.map((m) => m.id);
        }
        const game = await this.props.app.call('POST', '/games', body);
        if (game) {
            const app = this.props.app;
            app.setGame(game);
            app.setState({ invites: [] });
            // The boxes for this game: when free boxes have been heard over the radio, the
            // dialog opens with the last game's ticked (always there with "Invite boxes").
            await app.loadBoxes(true);
            const boxes = (app.state.boxes && app.state.boxes.boxes) || [];
            if (boxes.length) app.setState({ invitePicker: true });
        }
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
            <details class="team-branding" data-testid="game-team-branding">
                <summary>${t('teams.for_game')}</summary>
                <p class="muted small">${t('teams.for_game_hint')}</p>
                <${TeamFields} app=${props.app} teams=${teams} prefix="game" value=${state.teamInfo}
                    onChange=${(teamInfo) => this.setState({ teamInfo })} />
                <p class="muted small">${t('branding.rights')}</p>
            </details>
            <div class="field"><label for="g-minutes">${t('game.duration')}</label>
                <input id="g-minutes" type="number" min="0" step="1" value=${state.minutes}
                    onInput=${(e) => this.setState({ minutes: e.target.value })} />
                <small class="muted">${t('game.duration_hint')}</small></div>
            <div class="field"><label for="g-squads">${t('game.squads')}</label>
                <input id="g-squads" data-testid="game-squads" type="number" min="0" max="16" step="1" value=${state.squads}
                    onInput=${(e) => this.setState({ squads: e.target.value })} />
                <small class="muted">${t('game.squads_hint')}</small></div>
            ${mode && !preset && html`<${ModifierPicker} modes=${modes} main=${mode} selected=${state.mods} prefix="game"
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
                ${game.teams.map((tm) => html`<option value=${tm}>${teamName(game, tm)}</option>`)}
            </select>
            <input type="number" step="1" aria-label=${t('game.amount')} placeholder=${t('game.amount')}
                value=${state.amount} onInput=${(e) => this.setState({ amount: e.target.value })} />
            <input maxlength="64" aria-label=${t('game.reason')} placeholder=${t('game.reason')}
                value=${state.reason} onInput=${(e) => this.setState({ reason: e.target.value })} />
            <button type="submit">${t('game.apply')}</button>
        </form>`;
    }
}

/** The live game's settings as created: its parameters (labels in the current language). Opened
 * and focused when the invite dialog's "Review settings" is chosen (props.review counts those). */
class GameSettings extends Component {
    constructor() {
        super();
        this.state = { open: false };
        this.summary = createRef();
        this.box = createRef();
    }

    componentDidUpdate(prev) {
        if (this.props.review !== prev.review && this.props.review) this.reveal();
    }

    reveal() {
        this.setState({ open: true }, () => {
            const card = this.box.current && this.box.current.closest('section');
            if (card && card.scrollIntoView) card.scrollIntoView({ block: 'start' });
            if (this.summary.current) this.summary.current.focus();
        });
    }

    value(spec, v) {
        if (v === undefined || v === null || v === '') return '–';
        if (spec && spec.type === 'bool') return v ? t('common.yes') : t('common.no');
        return String(v);
    }

    render(props, state) {
        const { modes } = props.app.state;
        const { game } = props;
        const { main, mods } = partsOf(modes, game.mode_id);
        const { schema, labels } = schemaOf(main, mods);
        const params = game.params || {};
        const names = [...Object.keys(schema), ...Object.keys(params).filter((n) => !(n in schema))];
        return html`<details class="game-settings" data-testid="game-settings" ref=${this.box} open=${state.open}
            onToggle=${(e) => this.setState({ open: e.currentTarget.open })}>
            <summary ref=${this.summary} data-testid="game-settings-summary">${t('game.settings')}</summary>
            ${names.length === 0 ? html`<p class="muted">${t('presets.no_params')}</p>`
                : html`<dl class="settings-list" data-testid="game-params">${names.map((n) => html`
                    <dt>${labels[n] || n}</dt><dd data-testid=${`game-param-${n}`}>${this.value(schema[n], params[n])}</dd>`)}</dl>`}
            <p class="muted small">${t('game.settings_hint')}</p>
        </details>`;
    }
}

export class GameControl extends Component {
    lifecycle(action, body) {
        const { game } = this.props.app.state;
        return this.props.app.call('POST', `/games/${game.id}/${action}`, body).then((g) => {
            if (g) this.props.app.setGame(g);
            else if (action === 'start') this.props.app.refreshGame(); // what is missing now
            // A game ended without its key: say whether its boxes heard GAME_OVER (decision OT-13).
            if (g && action === 'end' && game.key_lost && g.game_over_frame) {
                this.props.app.showToast(g.game_over_frame === 'sent' ? t('game.over_told')
                    : t('game.over_not_told', { why: g.game_over_frame }));
            }
            return !!g;
        });
    }

    /** The invite dialog's "Review settings" (decision GM-3): close it, open the game's settings. */
    reviewSettings() {
        this.props.app.setState({ invitePicker: false, reviewSettings: (this.props.app.state.reviewSettings || 0) + 1 });
    }

    /** Start, or Start anyway when a role has no joined node yet (decision RJ-1). */
    renderStart(game, pending, leading) {
        const missing = (game.start_check && game.start_check.missing) || [];
        const roles = missing.join(', ');
        let question = pending ? t('game.confirm_start_pending', { n: pending }) : t('game.confirm_start');
        if (missing.length) {
            question = `${t('game.missing_short', { roles })} ${pending ? question : t('game.confirm_start_anyway')}`;
        }
        return html`<${ConfirmButton} testid="game-start" class=${missing.length ? 'danger' : 'primary'}
            label=${missing.length ? t('game.start_anyway') : t('game.start')} question=${question}
            disabled=${!leading} onConfirm=${() => this.lifecycle('start', missing.length ? { force: true } : undefined)} />`;
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
                <dt>${t('game.teams')}</dt><dd data-testid="game-teams-list">${game.teams.map((tm) => teamName(game, tm) === tm ? tm
                    : `${teamName(game, tm)} (${tm})`).join(', ')}${game.squads
                    ? ` · ${t('game.squads_each', { n: game.squads })}` : ''}</dd>
                <dt>${t('game.id')}</dt><dd>${game.id}</dd>
                ${game.channel_hz && html`<dt>${t('radio.channel')}</dt><dd data-testid="game-channel">${mhz(game.channel_hz)} MHz</dd>`}
            </dl>
            <${GameSettings} app=${app} game=${game} review=${app.state.reviewSettings || 0} />
            ${game.joined && html`<p class="notice">${t('game.standby_notice')}</p>`}
            ${game.key_lost && html`<p class="notice" data-testid="game-key-lost">${t('game.key_lost_notice')}</p>`}
            ${s === 'ready' && !game.joined && html`<${StartCheck} game=${game} />`}
            ${gm && html`<div class="actions" data-testid="game-actions">
                ${s === 'ready' && this.renderStart(game, pending, leading)}
                ${s === 'ready' && leading && !game.joined && html`<button type="button" data-testid="game-invite"
                    onClick=${() => app.setState({ invitePicker: true })}>${t('invites.open')}</button>`}
                ${s === 'running' && html`<${ConfirmButton} testid="game-pause" label=${t('game.pause')}
                    question=${t('game.confirm_pause')} disabled=${!leading} onConfirm=${() => this.lifecycle('pause', {})} />`}
                ${s === 'paused' && html`<${ConfirmButton} testid="game-resume" class="primary" label=${t('game.resume')}
                    question=${t('game.confirm_resume')} disabled=${!leading} onConfirm=${() => this.lifecycle('resume')} />`}
                <${ConfirmButton} testid="game-end" class="danger" label=${game.joined && !leading ? t('game.leave') : t('game.end')}
                    question=${game.key_lost ? t('game.confirm_end_key_lost') : t('game.confirm_end')}
                    onConfirm=${() => this.lifecycle('end', {})} />
            </div>`}
            ${gm && !leading && html`<p class="notice">${t('game.not_leader')}</p>`}
            ${gm && leading && html`<${Broadcast} app=${app} />`}
            ${gm && leading && html`<${Adjust} app=${app} />`}
            ${gm && s !== 'ended' && html`<${TeamsEditor} app=${app} />`}
            ${gm && leading && s === 'ready' && !game.joined && app.state.invitePicker
                && html`<${BoxInvites} app=${app} onClose=${() => app.setState({ invitePicker: false })} pending=${pending}
                    onStart=${(force) => this.lifecycle('start', force ? { force: true } : undefined)}
                    onReview=${() => this.reviewSettings()} />`}
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
