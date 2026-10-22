// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A multi-story field (decisions ML-0 to ML-12): the GM ticks "Multi-story building", sets the
// number of levels (2-10) and their names, and the field view gets a tab per level, each with
// its own floor plan. Saved with PUT /api/v1/field/levels; the controller keeps the levels' plans
// (PUT /api/v1/field/levels/{n}/image). Names start in the console's language ("R/C",
// "1.º andar", ...); a basement is a level the GM names so. Turning it off keeps everything and
// says so first; fewer levels delete the plans of the levels that go, and say so first.

import { html, Component, t } from '../ui.js';

export const LEVELS_MIN = 2;
export const LEVELS_MAX = 10;

/** A level's default name in the console's language: the ground floor, then floors 1, 2, ... */
export function defaultLevelName(level) {
    return level === 0 ? t('levels.ground') : t('levels.floor', { n: level });
}

/** A level's name as shown: the GM's, else the default. */
export function levelName(levels, level) {
    const name = levels && levels.names && levels.names[level];
    return name || defaultLevelName(level);
}

/** How many levels are in use (1 while levels are off). */
export function levelsInUse(levels) {
    return levels && levels.enabled ? levels.count : 1;
}

/** The level a position is shown on: its own while in use, else level 0 (as field_levels.shown). */
export function shownLevel(levels, level) {
    return Number.isInteger(level) && level >= 0 && level < levelsInUse(levels) ? level : 0;
}

/** The level tabs above the plan (a tablist: arrow keys, Home and End move between them). */
export function LevelTabs({ levels, current, onSelect }) {
    const count = levelsInUse(levels);
    if (count < 2) return null;
    const go = (e, level) => {
        const keys = { ArrowRight: level + 1, ArrowLeft: level - 1, Home: 0, End: count - 1 };
        if (!(e.key in keys)) return;
        e.preventDefault();
        const next = (keys[e.key] + count) % count;
        onSelect(next);
        const tab = e.currentTarget.parentElement.querySelector(`[data-level="${next}"]`);
        if (tab) tab.focus();
    };
    return html`<div class="level-tabs" role="tablist" aria-label=${t('levels.tabs')} data-testid="level-tabs">
        ${Array.from({ length: count }, (_, i) => html`<button type="button" role="tab" data-level=${i}
            data-testid=${`level-tab-${i}`} id=${`level-tab-${i}`} aria-controls="field-level-panel"
            aria-selected=${i === current ? 'true' : 'false'} tabindex=${i === current ? 0 : -1}
            class=${i === current ? 'active' : ''} onKeyDown=${(e) => go(e, i)}
            onClick=${() => onSelect(i)}>${levelName(levels, i)}</button>`)}
    </div>`;
}

/** The GM's settings: the checkbox, the number of levels and their names. */
export class LevelSettings extends Component {
    constructor() {
        super();
        this.state = { count: null, names: null, asking: null };
    }

    /** The form's values: what the GM typed, else what the controller has. */
    values() {
        const levels = this.props.levels;
        const count = this.state.count || Math.max(LEVELS_MIN, levels.count);
        const names = Array.from({ length: count }, (_, i) => {
            if (this.state.names && this.state.names[i] !== undefined) return this.state.names[i];
            return (levels.names && levels.names[i]) || defaultLevelName(i);
        });
        return { count, names };
    }

    async put(body) {
        const out = await this.props.app.call('PUT', '/field/levels', body);
        if (out) {
            this.setState({ count: null, names: null, asking: null });
            this.props.onChange(out);
        }
    }

    toggle(on) {
        if (on) {
            const { count, names } = this.values();
            this.put({ enabled: true, count, names });
        } else {
            this.setState({ asking: 'off' });
        }
    }

    /** The levels that would go, with a plan or map features (MF-8), if the GM saved the form's count. */
    losing(count) {
        const levels = this.props.levels;
        const featured = new Set((this.props.app.state.mapFeatures || []).map((f) => f.level));
        return (levels.levels || []).filter((l) => l.level >= count && (l.image || featured.has(l.level)))
            .map((l) => levelName(levels, l.level));
    }

    save(e) {
        e.preventDefault();
        const { count, names } = this.values();
        if (this.losing(count).length) this.setState({ asking: 'fewer' });
        else this.put({ enabled: true, count, names });
    }

    setName(i, value) {
        const { names } = this.values();
        names[i] = value;
        this.setState({ names });
    }

    renderAsk() {
        const { levels } = this.props;
        const { asking } = this.state;
        if (!asking) return null;
        const { count, names } = this.values();
        const question = asking === 'off'
            ? t('levels.confirm_off', { ground: levelName(levels, 0) })
            : t('levels.confirm_fewer', { names: this.losing(count).join(', '), ground: levelName(levels, 0) });
        const yes = asking === 'off' ? () => this.put({ enabled: false }) : () => this.put({ enabled: true, count, names });
        return html`<div class="confirm" role="group" aria-label=${question} data-testid="levels-confirm">
            <span class="confirm-q" role="alert">${question}</span>
            <button type="button" class="danger" data-testid="levels-confirm-yes" onClick=${yes}>${t('common.yes')}</button>
            <button type="button" data-testid="levels-confirm-no"
                onClick=${() => this.setState({ asking: null })}>${t('common.no')}</button>
        </div>`;
    }

    render(props) {
        const { levels } = props;
        const { count, names } = this.values();
        const on = levels.enabled;
        return html`<div class="levels-settings" data-testid="levels-settings">
            <label class="check"><input type="checkbox" data-testid="levels-toggle" checked=${on}
                onChange=${(e) => this.toggle(e.target.checked)} /> ${t('levels.toggle')}</label>
            <p class="muted small">${t(on ? 'levels.hint_on' : 'levels.hint_off')}</p>
            ${this.renderAsk()}
            ${on && html`<form class="form levels-form" onSubmit=${(e) => this.save(e)} data-testid="levels-form" novalidate>
                <div class="field">
                    <label for="levels-count">${t('levels.count')}</label>
                    <select id="levels-count" data-testid="levels-count" value=${count}
                        onChange=${(e) => this.setState({ count: Number(e.target.value) })}>
                        ${Array.from({ length: LEVELS_MAX - LEVELS_MIN + 1 }, (_, i) => i + LEVELS_MIN)
                            .map((n) => html`<option value=${n} selected=${n === count}>${n}</option>`)}
                    </select>
                </div>
                <div class="levels-names">
                    ${names.map((name, i) => html`<div class="field">
                        <label for=${`levels-name-${i}`}>${t('levels.name', { n: i })}</label>
                        <input id=${`levels-name-${i}`} data-testid=${`levels-name-${i}`} maxlength="32"
                            autocomplete="off" value=${name} onInput=${(e) => this.setName(i, e.target.value)} />
                    </div>`)}
                </div>
                <div class="actions">
                    <button type="submit" class="primary" data-testid="levels-save">${t('levels.save')}</button>
                </div>
            </form>`}
        </div>`;
    }
}
