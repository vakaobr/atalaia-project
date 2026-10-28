// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Field and team branding (decisions BR1-BR24). Settings: the field's name,
// logo, wallpaper and accent colour, and the saved teams (a name and a
// crest for teams that come back). The game form and the game card: each
// team colour's display name and crest for one game. FieldBrand: the
// field's logo and name in the console's header. The images are PNG, JPEG
// or WebP only; the controller checks them and strips their metadata, and
// whoever uploads them is responsible for having the rights (said here).

import { html, Component, t, teamColour, teamName, crestUrl, brandingUrl, textOn, ConfirmButton } from '../ui.js';
import { GlyphWarning } from './box-glyphs.js';

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const COLOURS = ['red', 'blue', 'green', 'yellow', 'orange', 'purple', 'black', 'white'];

/** Uploads a crest file (POST /api/v1/crests): its id, or null (the console shows the error). */
export async function uploadCrest(app, file) {
    if (!file) return null;
    if (!IMAGE_TYPES.includes(file.type)) {
        app.showToast(t('branding.bad_type'));
        return null;
    }
    const out = await app.call('POST', '/crests', undefined, { type: file.type, data: file });
    return out ? out.crest_id : null;
}

/** The field's logo (if any) and name, for the header and the login page. */
export function FieldBrand({ branding, fallback }) {
    if (!branding || (!branding.logo && (!branding.field_name || branding.field_name === 'Atalaia'))) {
        return html`<strong>${fallback}</strong>`;
    }
    return html`<span class="field-brand" data-testid="header-field">
        ${branding.logo && html`<img class="field-logo" src=${brandingUrl(branding.logo)} data-testid="header-logo"
            alt=${t('branding.logo_alt', { name: branding.field_name })} />`}
        <strong data-testid="header-field-name">${branding.field_name}</strong>
    </span>`;
}

/** Puts the field's accent colour on an element (the header) through the DOM: the CSP forbids inline styles. */
export function accentRef(branding) {
    return (el) => {
        if (!el) return;
        if (branding && branding.accent) {
            el.style.setProperty('--accent', branding.accent);
            el.style.setProperty('--accent-fg', textOn(branding.accent));
        } else {
            el.style.removeProperty('--accent');
            el.style.removeProperty('--accent-fg');
        }
    };
}

class ImageSlot extends Component {
    async upload(e) {
        const { app, slot } = this.props;
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        if (!IMAGE_TYPES.includes(file.type)) {
            app.showToast(t('branding.bad_type'));
            return;
        }
        const out = await app.call('PUT', `/field/branding/${slot}`, undefined, { type: file.type, data: file });
        if (out) app.setState({ branding: out });
    }

    async remove() {
        const { app, slot } = this.props;
        const out = await app.call('DELETE', `/field/branding/${slot}`);
        if (out) app.setState({ branding: out });
    }

    render(props) {
        const { branding, slot, gm } = props;
        const ref = branding && branding[slot];
        return html`<div class="field brand-slot" data-testid=${`branding-${slot}`}>
            <span class="label">${t(`branding.${slot}`)}</span>
            ${ref ? html`<img class=${`brand-preview brand-${slot}`} src=${brandingUrl(ref)} data-testid=${`branding-${slot}-img`}
                alt=${t(`branding.${slot}_alt`, { name: branding.field_name })} />
                <small class="muted">${ref.width}×${ref.height} px · ${Math.ceil(ref.bytes / 1024)} KB</small>`
            : html`<small class="muted">${t('branding.none')}</small>`}
            ${gm && html`<div class="actions">
                <label class="button">${t(`branding.upload_${slot}`)}
                    <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid=${`branding-${slot}-upload`}
                        onChange=${(e) => this.upload(e)} /></label>
                ${ref && html`<button type="button" data-testid=${`branding-${slot}-remove`}
                    onClick=${() => this.remove()}>${t('branding.remove')}</button>`}
            </div>`}
        </div>`;
    }
}

export class BrandingSettings extends Component {
    constructor() {
        super();
        this.state = { name: null, accent: null, saved: false };
    }

    async save(e) {
        e.preventDefault();
        const { app } = this.props;
        const b = app.state.branding || {};
        const body = {};
        if (this.state.name !== null && this.state.name.trim() !== b.field_name) body.field_name = this.state.name.trim();
        if (this.state.accent !== null) body.accent = this.state.accent;
        const out = await app.call('PUT', '/field/branding', body);
        if (out) {
            app.setState({ branding: out });
            this.setState({ name: null, accent: null, saved: true });
        }
    }

    render(props, state) {
        const app = props.app;
        const b = app.state.branding;
        const gm = app.state.role === 'gm';
        if (!b) return html`<section class="card"><p class="muted">…</p></section>`;
        const name = state.name !== null ? state.name : b.field_name;
        const accent = state.accent !== null ? state.accent : b.accent;
        return html`<section class="card" aria-labelledby="branding-h" data-testid="branding-settings">
            <h2 id="branding-h">${t('branding.title')}</h2>
            <p class="muted small">${t('branding.intro')}</p>
            ${gm ? html`<form class="form" onSubmit=${(e) => this.save(e)} data-testid="branding-form">
                <div class="field"><label for="b-name">${t('branding.field_name')}</label>
                    <input id="b-name" data-testid="branding-name" required maxlength="48" value=${name}
                        onInput=${(e) => this.setState({ name: e.target.value, saved: false })} />
                    <small class="muted">${t('branding.field_name_hint')}</small>
                    <${GlyphWarning} text=${name} testid="glyph-field-name" /></div>
                <div class="field"><label for="b-accent">${t('branding.accent')}</label>
                    <div class="actions">
                        <input id="b-accent" type="color" data-testid="branding-accent" value=${accent || '#ffb300'}
                            onInput=${(e) => this.setState({ accent: e.target.value, saved: false })} />
                        <span class="muted small" data-testid="branding-accent-value">${accent || t('branding.accent_default')}</span>
                        ${accent && html`<button type="button" class="link" data-testid="branding-accent-clear"
                            onClick=${() => this.setState({ accent: '', saved: false })}>${t('branding.accent_default')}</button>`}
                    </div>
                    <small class="muted">${t('branding.accent_hint')}</small></div>
                <div class="actions"><button type="submit" class="primary" data-testid="branding-save">${t('common.save')}</button>
                    ${state.saved && html`<span class="ok" role="status">${t('branding.saved')}</span>`}</div>
            </form>` : html`<p class="muted">${t('branding.read_only')}</p>`}
            <${ImageSlot} app=${app} branding=${b} slot="logo" gm=${gm} />
            <${ImageSlot} app=${app} branding=${b} slot="wallpaper" gm=${gm} />
            <p class="muted small">${t('branding.limits')}</p>
            ${gm && html`<p class="small" data-testid="branding-rights">${t('branding.rights')}</p>`}
        </section>`;
    }
}

export class TeamPresets extends Component {
    constructor() {
        super();
        this.state = { name: '', colour: '', crest: null };
    }

    componentDidMount() {
        this.props.app.loadTeamPresets();
    }

    async crest(e) {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        const id = await uploadCrest(this.props.app, file);
        if (id) this.setState({ crest: id });
    }

    async add(e) {
        e.preventDefault();
        const app = this.props.app;
        const out = await app.call('POST', '/team-presets', {
            name: this.state.name.trim(), colour: this.state.colour || null, crest_id: this.state.crest });
        if (out) {
            this.setState({ name: '', colour: '', crest: null });
            app.loadTeamPresets();
        }
    }

    async remove(p) {
        const app = this.props.app;
        if (await app.call('DELETE', `/team-presets/${p.id}`)) app.loadTeamPresets();
    }

    render(props, state) {
        const app = props.app;
        const gm = app.state.role === 'gm';
        const presets = app.state.teamPresets || [];
        return html`<section class="card" aria-labelledby="teams-h" data-testid="team-presets">
            <h2 id="teams-h">${t('teams.title')}</h2>
            <p class="muted small">${t('teams.intro')}</p>
            ${presets.length === 0 ? html`<p class="muted">${t('teams.none')}</p>` : html`<ul class="team-presets">
                ${presets.map((p) => html`<li class="team-preset" data-testid=${`team-preset-${p.id}`}>
                    ${p.crest_url ? html`<img class="crest" src=${p.crest_url} alt=${t('teams.crest_alt', { team: p.name })} />`
                        : html`<span class="crest crest-empty" aria-hidden="true"></span>`}
                    <strong>${p.name}</strong>
                    ${p.colour && html`<span class="swatch" aria-hidden="true"
                        ref=${(el) => { if (el) el.style.background = teamColour(p.colour); }}></span>`}
                    <span class="muted small">${p.colour || ''}</span>
                    ${gm && html`<${ConfirmButton} label=${t('teams.delete')} question=${t('teams.confirm_delete')}
                        testid=${`team-preset-delete-${p.id}`} onConfirm=${() => this.remove(p)} />`}
                </li>`)}
            </ul>`}
            ${gm && html`<form class="form" onSubmit=${(e) => this.add(e)} data-testid="team-preset-form">
                <div class="field"><label for="tp-name">${t('teams.name')}</label>
                    <input id="tp-name" data-testid="team-preset-name" required maxlength="32" value=${state.name}
                        onInput=${(e) => this.setState({ name: e.target.value })} />
                    <${GlyphWarning} text=${state.name} testid="glyph-team-preset" /></div>
                <div class="field"><label for="tp-colour">${t('teams.colour')}</label>
                    <select id="tp-colour" data-testid="team-preset-colour" value=${state.colour}
                        onChange=${(e) => this.setState({ colour: e.target.value })}>
                        <option value="">${t('teams.no_colour')}</option>
                        ${COLOURS.map((c) => html`<option value=${c}>${c}</option>`)}
                    </select></div>
                <div class="field"><span class="label">${t('teams.crest')}</span>
                    <div class="actions">
                        ${state.crest && html`<img class="crest" src=${`/api/v1/crests/${state.crest}`} data-testid="team-preset-crest-img"
                            alt=${t('teams.crest_alt', { team: state.name })} />`}
                        <label class="button">${t('teams.upload_crest')}
                            <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid="team-preset-crest"
                                onChange=${(e) => this.crest(e)} /></label>
                    </div>
                    <small class="muted">${t('teams.crest_limits')}</small></div>
                <div class="actions"><button type="submit" data-testid="team-preset-add">${t('teams.add')}</button></div>
            </form>`}
        </section>`;
    }
}

/**
 * Each team colour's display name and crest for one game: a saved team, or a name and a
 * crest of its own. value: {team: {display_name, crest_id, team_preset_id}}.
 */
export class TeamFields extends Component {
    set(team, change) {
        const value = { ...(this.props.value || {}) };
        value[team] = { ...(value[team] || {}), ...change };
        this.props.onChange(value);
    }

    pick(team, id) {
        const p = (this.props.app.state.teamPresets || []).find((x) => String(x.id) === id);
        this.set(team, p ? { team_preset_id: p.id, display_name: p.name, crest_id: p.crest_id || null }
            : { team_preset_id: null });
    }

    async crest(team, e) {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        const id = await uploadCrest(this.props.app, file);
        if (id) this.set(team, { crest_id: id, team_preset_id: null });
    }

    render(props) {
        const { teams, value, prefix } = props;
        const presets = props.app.state.teamPresets || [];
        return html`<div class="team-fields" data-testid=${`${prefix}-team-fields`}>
            ${teams.map((tm) => {
                const v = (value || {})[tm] || {};
                return html`<div class="team-row" data-team=${tm}>
                    <span class="swatch" aria-hidden="true" ref=${(el) => { if (el) el.style.background = teamColour(tm, teams); }}></span>
                    <span class="team-colour">${tm}</span>
                    ${presets.length > 0 && html`<select aria-label=${`${t('teams.preset')} · ${tm}`} data-testid=${`${prefix}-team-preset-${tm}`}
                        value=${v.team_preset_id ? String(v.team_preset_id) : ''} onChange=${(e) => this.pick(tm, e.target.value)}>
                        <option value="">${t('teams.preset')}: ${t('teams.no_preset')}</option>
                        ${presets.map((p) => html`<option value=${String(p.id)}>${p.name}</option>`)}
                    </select>`}
                    <input maxlength="32" aria-label=${`${t('teams.display_name')} · ${tm}`} placeholder=${t('teams.display_name')}
                        data-testid=${`${prefix}-team-name-${tm}`} value=${v.display_name || ''}
                        onInput=${(e) => this.set(tm, { display_name: e.target.value, team_preset_id: null })} />
                    ${v.crest_id && html`<img class="crest" src=${`/api/v1/crests/${v.crest_id}`} data-testid=${`${prefix}-team-crest-img-${tm}`}
                        alt=${t('teams.crest_alt', { team: v.display_name || tm })} />`}
                    <label class="button small-button">${t('teams.upload_crest')}
                        <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid=${`${prefix}-team-crest-${tm}`}
                            onChange=${(e) => this.crest(tm, e)} /></label>
                    ${v.crest_id && html`<button type="button" class="link" onClick=${() => this.set(tm, { crest_id: null, team_preset_id: null })}>${t('teams.remove_crest')}</button>`}
                </div>`;
            })}
        </div>`;
    }
}

/** The body's team_info for POST /api/v1/games, or undefined when nothing is set. */
export function teamInfoBody(value, teams) {
    const out = {};
    for (const tm of teams) {
        const v = (value || {})[tm];
        if (!v) continue;
        if (v.team_preset_id) {
            out[tm] = { team_preset_id: v.team_preset_id };
            continue;
        }
        const entry = {};
        if (v.display_name && v.display_name.trim()) entry.display_name = v.display_name.trim();
        if (v.crest_id) entry.crest_id = v.crest_id;
        if (Object.keys(entry).length) out[tm] = entry;
    }
    return Object.keys(out).length ? out : undefined;
}

/** The game card's team names and crests, saved with PUT /api/v1/games/{id}/teams/{team}. */
export class TeamsEditor extends Component {
    constructor() {
        super();
        this.state = { value: null, saved: false };
    }

    componentDidMount() {
        this.props.app.loadTeamPresets();
    }

    async save() {
        const app = this.props.app;
        const game = app.state.game;
        const value = this.state.value || {};
        let last = null;
        for (const tm of game.teams) {
            const v = value[tm];
            if (!v) continue;
            const body = v.team_preset_id ? { team_preset_id: v.team_preset_id }
                : { display_name: (v.display_name || '').trim() || null, crest_id: v.crest_id || null };
            last = await app.call('PUT', `/games/${game.id}/teams/${encodeURIComponent(tm)}`, body);
            if (!last) return;
        }
        if (last) app.setGame({ ...game, team_info: last.team_info });
        this.setState({ value: null, saved: true });
    }

    render(props, state) {
        const app = props.app;
        const game = app.state.game;
        const current = {};
        for (const tm of game.teams) current[tm] = { ...((game.team_info || {})[tm] || {}) };
        return html`<details class="teams-editor" data-testid="teams-editor">
            <summary>${t('teams.edit')}</summary>
            <p class="muted small">${t('teams.for_game_hint')}</p>
            <${TeamFields} app=${app} teams=${game.teams} prefix="live" value=${state.value || current}
                onChange=${(value) => this.setState({ value, saved: false })} />
            <div class="actions"><button type="button" data-testid="teams-save" disabled=${!state.value}
                onClick=${() => this.save()}>${t('teams.save')}</button>
                ${state.saved && html`<span class="ok" role="status">${t('teams.saved')}</span>`}</div>
            <p class="muted small">${t('branding.rights')}</p>
        </details>`;
    }
}

/** A team's crest (or its colour) and display name, as the scores show it. */
export function TeamLabel({ game, team, teams }) {
    const crest = crestUrl(game, team);
    return html`<span class="team-label">
        ${crest ? html`<img class="crest" src=${crest} alt=${t('teams.crest_alt', { team: teamName(game, team) })} />`
            : html`<span class="swatch" aria-hidden="true" ref=${(el) => { if (el) el.style.background = teamColour(team, teams); }}></span>`}
        <span class="team-name">${teamName(game, team)}</span>
    </span>`;
}
