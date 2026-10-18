// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Preset builder: forms drawn from each mode's parameter schema (mode.yaml
// "params": int with min/max, bool, team, string; default, optional, label),
// saved through POST /api/v1/presets. ParamFields is shared with the game form.

import { html, Component, t, brief } from '../ui.js';

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
        const label = spec.label || name;
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
            input = html`<select id=${id} value=${value} onChange=${(e) => this.set(name, e.target.value)}>
                ${teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}
            </select>`;
        } else {
            input = html`<input id=${id} type="text" value=${value === undefined ? '' : value}
                onInput=${(e) => this.set(name, e.target.value)} />`;
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
        this.state = { name: '', modeId: '', values: {}, saved: '' };
    }

    mode() {
        const { modes } = this.props.app.state;
        return modes.find((m) => m.id === this.state.modeId) || modes[0];
    }

    pickMode(modeId) {
        const mode = this.props.app.state.modes.find((m) => m.id === modeId);
        this.setState({ modeId, values: initialValues(mode ? mode.params : {}) });
    }

    copy(preset) {
        const mode = this.props.app.state.modes.find((m) => m.id === preset.mode_id);
        this.setState({ name: `${preset.name} (2)`, modeId: preset.mode_id,
                        values: initialValues(mode ? mode.params : {}, preset.params), saved: '' });
    }

    async save(e) {
        e.preventDefault();
        const mode = this.mode();
        if (!mode) return;
        const app = this.props.app;
        const body = { name: this.state.name.trim(), mode_id: mode.id, params: this.state.values };
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
        const values = state.modeId || !mode ? state.values : initialValues(mode.params);
        return html`<section class="card" aria-labelledby="presets-h">
            <h2 id="presets-h">${t('presets.title')}</h2>
            ${presets.length === 0 ? html`<p class="muted">${t('presets.none')}</p>` : html`
            <div class="table-wrap"><table class="table" data-testid="preset-list">
                <thead><tr><th>${t('presets.name')}</th><th>${t('presets.mode')}</th><th>${t('presets.params')}</th><th></th></tr></thead>
                <tbody>${presets.map((p) => html`<tr>
                    <td>${p.name}</td><td>${p.mode_id}</td><td class="small">${brief(p.params)}</td>
                    <td>${role === 'gm' && html`<button type="button" class="link" onClick=${() => this.copy(p)}>${t('presets.copy')}</button>`}</td>
                </tr>`)}</tbody>
            </table></div>`}
            ${role === 'gm' && mode && html`<form class="form" onSubmit=${(e) => this.save(e)} data-testid="preset-form">
                <h3>${t('presets.new')}</h3>
                <div class="field"><label for="preset-name">${t('presets.name')}</label>
                    <input id="preset-name" required maxlength="64" value=${state.name}
                        onInput=${(e) => this.setState({ name: e.target.value })} /></div>
                <div class="field"><label for="preset-mode">${t('presets.mode')}</label>
                    <select id="preset-mode" value=${mode.id} onChange=${(e) => this.pickMode(e.target.value)}>
                        ${modes.map((m) => html`<option value=${m.id}>${m.name} (${m.id})</option>`)}
                    </select></div>
                <p class="muted small">${mode.description}</p>
                <${ParamFields} schema=${mode.params} values=${values} prefix="preset"
                    onChange=${(v) => this.setState({ values: v, modeId: mode.id })} />
                <button type="submit" data-testid="preset-save">${t('presets.save')}</button>
                ${state.saved && html`<span class="ok" role="status">${state.saved}</span>`}
            </form>`}
        </section>`;
    }
}
