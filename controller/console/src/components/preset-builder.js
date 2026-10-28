// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Preset builder: forms drawn from each mode's parameter schema (mode.yaml
// "params": int with min/max, bool, team, string; default, optional, label),
// saved through POST /api/v1/presets. ParamFields, ModifierPicker and the
// helpers for "main+modifier" mode ids are shared with the game form. A
// game's parts after its main mode are modifiers (kind "modifier": they run
// on the main mode's boxes) and role packages (kind "role", the Medic Kit:
// boxes given their role run them alone, modes/README.md).

import { html, Component, t, brief, modeText, paramLabel, commandLabel } from '../ui.js';
import { GlyphWarning } from './box-glyphs.js';

/** Main modes (kind "mode", and role packages, which may run alone), modifiers (kind
 * "modifier") and role packages (kind "role") of the catalogue. */
export function mainModes(modes) {
    return modes.filter((m) => m.kind !== 'modifier');
}

export function modifierModes(modes) {
    return modes.filter((m) => m.kind === 'modifier');
}

export function roleModes(modes) {
    return modes.filter((m) => m.kind === 'role');
}

/** The roles of a game: its main mode's and its role packages' (modifiers add none). */
export function gameRoles(modes, modeId) {
    const { main, mods } = partsOf(modes, modeId);
    const parts = [main, ...mods.filter((m) => m.kind === 'role')].filter(Boolean);
    return parts.flatMap((m) => Object.keys(m.roles || {}));
}

/** The GM commands of a game for a node of this role (mode.yaml "commands"), with labels. */
export function commandsFor(modes, modeId, role) {
    const { main, mods } = partsOf(modes, modeId);
    const out = [];
    for (const m of [main, ...mods]) {
        if (!m) continue;
        for (const [name, spec] of Object.entries(m.commands || {})) {
            if ((spec.roles || []).includes(role)) out.push({ name, label: commandLabel(m, name) });
        }
    }
    return out;
}

/** The main mode and the modifiers a mode id names ("main+modifier+..."). */
export function partsOf(modes, modeId) {
    const ids = String(modeId || '').split('+');
    return {
        main: modes.find((m) => m.id === ids[0]),
        mods: ids.slice(1).map((id) => modes.find((m) => m.id === id)).filter(Boolean),
    };
}

/** The id a game or preset gets: the main mode, then the chosen modifiers and role packages
 * in catalogue order. */
export function composedId(modes, main, selected) {
    if (main.kind === 'role') return main.id; // a role package on its own takes no other parts
    const mods = modes.filter((m) => m.kind !== 'mode' && m.id !== main.id && selected.includes(m.id))
        .map((m) => m.id);
    return [main.id, ...mods].join('+');
}

/** Parameter schema and labels of a main mode with its modifiers. */
export function schemaOf(main, mods) {
    const schema = {};
    const labels = {};
    for (const m of [main, ...mods]) {
        if (!m) continue;
        for (const [name, spec] of Object.entries(m.params || {})) {
            schema[name] = spec;
            labels[name] = paramLabel(m, name);
        }
    }
    return { schema, labels };
}

/** A mode id as people read it: the translated names, joined with "+". */
export function modeName(modes, modeId) {
    const { main, mods } = partsOf(modes, modeId);
    return main ? [main, ...mods].map((m) => modeText(m, 'name')).join(' + ') : modeId;
}

/** Checkboxes for the modifiers that run alongside the main mode, and for the role
 * packages (boxes of their own role, such as medic kits). None for a role package that
 * is the game on its own (props.main). */
export class ModifierPicker extends Component {
    toggle(id, on) {
        const selected = this.props.selected.filter((x) => x !== id);
        this.props.onChange(on ? [...selected, id] : selected);
    }

    group(list, key, testid) {
        if (!list.length) return null;
        const props = this.props;
        return html`<fieldset class="field modifiers" data-testid=${testid}>
            <legend>${t(`game.${key}`)}</legend>
            ${list.map((m) => html`<label class="check" title=${modeText(m, 'description')}>
                <input type="checkbox" value=${m.id} checked=${props.selected.includes(m.id)}
                    onChange=${(e) => this.toggle(m.id, e.target.checked)} /> ${modeText(m, 'name')}
            </label>`)}
            <small class="muted">${t(`game.${key}_hint`)}</small>
        </fieldset>`;
    }

    render(props) {
        if (props.main && props.main.kind === 'role') return null;
        return html`${this.group(modifierModes(props.modes), 'modifiers', `${props.prefix}-modifiers`)}
            ${this.group(roleModes(props.modes), 'role_packages', `${props.prefix}-roles`)}`;
    }
}

/** The values a form starts with: the preset's, else the schema defaults. */
export function initialValues(schema, values) {
    const out = {};
    for (const [name, spec] of Object.entries(schema || {})) {
        if (values && values[name] !== undefined) out[name] = values[name];
        else if (spec.default !== undefined) out[name] = spec.default;
    }
    return out;
}

/** Inputs for a mode's parameters. teams (optional) fills the team pickers. */
export class ParamFields extends Component {
    set(name, value) {
        const values = { ...this.props.values };
        if (value === undefined || value === '') delete values[name];
        else values[name] = value;
        this.props.onChange(values);
    }

    field(name, spec) {
        const { values, teams, prefix } = this.props;
        const id = `${prefix || 'p'}-${name}`;
        const label = (this.props.labels && this.props.labels[name]) || spec.label || name;
        const value = values[name];
        let input;
        if (spec.type === 'int') {
            input = html`<input id=${id} type="number" step="1" min=${spec.min} max=${spec.max}
                value=${value === undefined ? '' : value} required=${!spec.optional}
                onInput=${(e) => this.set(name, e.target.value === '' ? undefined : parseInt(e.target.value, 10))} />`;
        } else if (spec.type === 'bool') {
            input = html`<input id=${id} type="checkbox" checked=${!!value}
                onChange=${(e) => this.set(name, e.target.checked)} />`;
        } else if (spec.type === 'team' && teams && teams.length) {
            // An optional team left empty means every team (a medic kit's team).
            input = html`<select id=${id} value=${value === undefined ? '' : value}
                onChange=${(e) => this.set(name, e.target.value)}>
                ${spec.optional && html`<option value="">${t('presets.any_team')}</option>`}
                ${teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}
            </select>`;
        } else {
            input = html`<input id=${id} type="text" value=${value === undefined ? '' : value}
                maxlength=${spec.max} onInput=${(e) => this.set(name, e.target.value)} />`;
        }
        const range = spec.type === 'int' && (spec.min !== undefined || spec.max !== undefined)
            ? `${spec.min !== undefined ? spec.min : '…'}–${spec.max !== undefined ? spec.max : '…'}` : '';
        return html`<div class=${`field ${spec.type === 'bool' ? 'field-check' : ''}`}>
            <label for=${id}>${label}${spec.optional ? html` <small>(${t('presets.optional')})</small>` : ''}</label>
            ${input}
            ${range && html`<small class="muted">${range}</small>`}
        </div>`;
    }

    render(props) {
        const entries = Object.entries(props.schema || {});
        if (!entries.length) return html`<p class="muted">${t('presets.no_params')}</p>`;
        return html`<div class="params">${entries.map(([n, s]) => this.field(n, s))}</div>`;
    }
}

export class PresetBuilder extends Component {
    constructor(props) {
        super(props);
        this.state = { name: '', modeId: '', mods: [], values: {}, saved: '' };
    }

    mode() {
        const modes = mainModes(this.props.app.state.modes);
        return modes.find((m) => m.id === this.state.modeId) || modes[0];
    }

    schema(mode, mods) {
        const all = this.props.app.state.modes;
        return schemaOf(mode, (mods || this.state.mods).map((id) => all.find((m) => m.id === id)).filter(Boolean));
    }

    pickMode(modeId) {
        const mode = this.props.app.state.modes.find((m) => m.id === modeId);
        this.setState({ modeId, values: initialValues(this.schema(mode).schema) });
    }

    pickMods(mods) {
        const mode = this.mode();
        this.setState({ mods, modeId: mode.id,
                        values: initialValues(this.schema(mode, mods).schema, this.state.values) });
    }

    copy(preset) {
        const { main, mods } = partsOf(this.props.app.state.modes, preset.mode_id);
        this.setState({ name: `${preset.name} (2)`, modeId: main ? main.id : preset.mode_id,
                        mods: mods.map((m) => m.id),
                        values: initialValues(schemaOf(main, mods).schema, preset.params), saved: '' });
    }

    async save(e) {
        e.preventDefault();
        const mode = this.mode();
        if (!mode) return;
        const app = this.props.app;
        const body = { name: this.state.name.trim(), mode_id: composedId(app.state.modes, mode, this.state.mods),
                       params: this.state.values };
        const out = await app.call('POST', '/presets', body);
        if (out) {
            this.setState({ saved: t('presets.saved', { name: out.name }) });
            app.loadCatalogue();
        }
    }

    render(props, state) {
        const app = props.app;
        const { modes, presets, role } = app.state;
        const mode = this.mode();
        const { schema, labels } = this.schema(mode);
        const values = state.modeId || !mode ? state.values : initialValues(schema);
        return html`<section class="card" aria-labelledby="presets-h">
            <h2 id="presets-h">${t('presets.title')}</h2>
            ${presets.length === 0 ? html`<p class="muted">${t('presets.none')}</p>` : html`
            <div class="table-wrap"><table class="table" data-testid="preset-list">
                <thead><tr><th>${t('presets.name')}</th><th>${t('presets.mode')}</th><th>${t('presets.params')}</th><th></th></tr></thead>
                <tbody>${presets.map((p) => html`<tr>
                    <td>${p.name}</td><td>${modeName(modes, p.mode_id)}</td><td class="small">${brief(p.params)}</td>
                    <td>${role === 'gm' && html`<button type="button" class="link" onClick=${() => this.copy(p)}>${t('presets.copy')}</button>`}</td>
                </tr>`)}</tbody>
            </table></div>`}
            ${role === 'gm' && mode && html`<form class="form" onSubmit=${(e) => this.save(e)} data-testid="preset-form">
                <h3>${t('presets.new')}</h3>
                <div class="field"><label for="preset-name">${t('presets.name')}</label>
                    <input id="preset-name" required maxlength="64" value=${state.name}
                        onInput=${(e) => this.setState({ name: e.target.value })} />
                    <${GlyphWarning} text=${state.name} testid="glyph-preset" /></div>
                <div class="field"><label for="preset-mode">${t('presets.mode')}</label>
                    <select id="preset-mode" value=${mode.id} onChange=${(e) => this.pickMode(e.target.value)}>
                        ${mainModes(modes).map((m) => html`<option value=${m.id}>${modeText(m, 'name')} (${m.id})</option>`)}
                    </select></div>
                <p class="muted small">${modeText(mode, 'description')}</p>
                <${ModifierPicker} modes=${modes} main=${mode} selected=${state.mods} prefix="preset"
                    onChange=${(mods) => this.pickMods(mods)} />
                <${ParamFields} schema=${schema} labels=${labels} values=${values} prefix="preset"
                    onChange=${(v) => this.setState({ values: v, modeId: mode.id })} />
                <button type="submit" data-testid="preset-save">${t('presets.save')}</button>
                ${state.saved && html`<span class="ok" role="status">${state.saved}</span>`}
            </form>`}
        </section>`;
    }
}
