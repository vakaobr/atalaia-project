// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Map features (decisions MF-0 to MF-16): what the GM marks on the field's plan besides the
// boxes, a safe zone, a team's respawn or HQ, the car park, first aid, an objective or anything
// else with a name. Each is a pin, a circle (a pin and a radius in metres) or an area traced
// on the plan, on one level's plan, and says who may see it: everyone, one team, or only the
// organisers. The controller keeps them (GET|POST /api/v1/field/features, PUT|DELETE .../{id})
// and gives each token only what it may see, here and on the live stream (map_features), so a
// read-only page shows only the features for everyone.
//
// On the plan: an SVG layer under the boxes draws the circles and areas, and a pin (a button,
// focusable, with its name) marks each feature. The editor below the plan places a pin by a
// click, a circle by pressing at its centre and dragging to its edge (to scale only when the
// plan has a map position: georef-panel.js; else the radius is typed and the circle is drawn at
// a nominal size, dashed), and an area corner by corner; the same can be done with the keyboard
// by typing a place across and down the plan.
//
// The field boundary (decisions MF-19 to MF-30) is a type of its own: an area only, at most one per
// level, no team, for everyone unless the GM says otherwise. The plan is dimmed outside it and its
// outline drawn dashed. It is drawn here by hand, or loaded with the plan from a map (field-map.js).

import { html, Component, t, teamColour, ConfirmButton } from '../ui.js';
import { gridCell, gridSpan } from './field-grid.js';

export const FEATURE_TYPES = ['safe_zone', 'respawn', 'hq', 'parking', 'first_aid', 'objective', 'other', 'boundary'];
export const BOUNDARY = 'boundary';
const TEAM_TYPES = ['respawn', 'hq'];
export const SHAPES = ['point', 'circle', 'polygon'];
const VISIBILITIES = ['everyone', 'team', 'organisers'];
const DEFAULT_SHAPE = { safe_zone: 'circle', respawn: 'circle', hq: 'point', parking: 'polygon',
                        first_aid: 'point', objective: 'point', other: 'point', boundary: 'polygon' };
// A feature's colour without a team (with one: the team's), as the ATAK feed's (atak.py FEATURE_COLOURS).
export const FEATURE_COLOURS = { safe_zone: '#14b8a6', respawn: '#6c757d', hq: '#6c757d', parking: '#546e7a',
                                 first_aid: '#e91e63', objective: '#f59e0b', other: '#94a3b8', boundary: '#84cc16' };
// The pins' icons, drawn in white on the colour (24 x 24).
const ICONS = {
    safe_zone: 'M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3z',
    respawn: 'M12 5V2L7 6l5 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z',
    hq: 'M5 21V3h2v1h11l-2 4 2 4H7v9H5z',
    parking: 'M7 3h6a5 5 0 0 1 0 10h-3v8H7V3zm3 3v4h3a2 2 0 0 0 0-4h-3z',
    first_aid: 'M9 3h6v6h6v6h-6v6H9v-6H3V9h6V3z',
    objective: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm0 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
    other: 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z',
    boundary: 'M3 3h6v2H5v4H3V3zm12 0h6v6h-2V5h-4V3zM3 15h2v4h4v2H3v-6zm16 0h2v6h-6v-2h4v-4z',
};
const NOMINAL_RADIUS = 0.04; // a circle's radius on a plan without a scale: 4 % of its width
const POLYGON_MAX = 12;      // map_features.POLYGON_MAX
const EARTH_RADIUS_M = 6371000;

/** A feature's colour: its team's, else its type's. */
export function featureColour(f, teams) {
    return f.team ? teamColour(f.team, teams) : FEATURE_COLOURS[f.type] || FEATURE_COLOURS.other;
}

/** A feature's name as shown: the GM's label, else its type's name. */
export function featureName(f) {
    return f.label || t(`features.types.${f.type}`);
}

export function featureIcon(type) {
    return html`<svg class="mf-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d=${ICONS[type] || ICONS.other} /></svg>`;
}

/** Where a feature's pin goes: its x, y, or an area's vertex average. */
export function featureCentre(f) {
    if (f.shape === 'polygon' && f.points && f.points.length) {
        const n = f.points.length;
        return { x: f.points.reduce((s, p) => s + p.x, 0) / n, y: f.points.reduce((s, p) => s + p.y, 0) / n };
    }
    return { x: f.x, y: f.y };
}

function metres(a, b) {
    const rad = Math.PI / 180;
    const dlat = (b.lat - a.lat) * rad;
    const dlon = (b.lon - a.lon) * rad;
    const h = Math.sin(dlat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dlon / 2) ** 2;
    return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

/** The plan's size on the ground from its map position (the API's corners): {w, h} in metres, or null. */
export function planScale(georef) {
    const c = georef && georef.corners;
    if (!c) return null;
    const w = metres(c.top_left, c.top_right);
    const h = metres(c.top_left, c.bottom_left);
    return w > 0 && h > 0 ? { w, h } : null;
}

/** The SVG layer of circles and areas, under the pins and the boxes (viewBox 0-100 on both axes). */
export function featureShapes(features, teams, scale) {
    const shapes = features.filter((f) => f.shape !== 'point' && (f.shape !== 'polygon' || (f.points || []).length >= 2));
    if (!shapes.length) return null;
    // The field boundary: what is outside it dimmed (the whole plan less the area, even-odd), under the rest.
    const outside = shapes.filter((f) => f.type === BOUNDARY && f.points.length >= 3).map((f) => html`<path
        class="mf-outside" data-testid="mf-outside" fill-rule="evenodd"
        d=${`M0 0H100V100H0Z M${f.points.map((p) => `${p.x * 100} ${p.y * 100}`).join(' L')}Z`} />`);
    return html`<svg class="mf-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"
        data-testid="mf-layer">
        ${outside}
        ${shapes.map((f) => {
            const colour = featureColour(f, teams);
            const cls = `mf-shape${f.draft ? ' draft' : ''}${f.type === BOUNDARY ? ' mf-boundary' : ''}`;
            if (f.shape === 'circle') {
                if (typeof f.x !== 'number') return null;
                const rx = scale ? (f.radius_m / scale.w) * 100 : NOMINAL_RADIUS * 100;
                const ry = scale ? (f.radius_m / scale.h) * 100 : NOMINAL_RADIUS * 100;
                return html`<ellipse class=${`${cls}${scale ? '' : ' no-scale'}`} data-feature=${f.id}
                    cx=${f.x * 100} cy=${f.y * 100} rx=${rx} ry=${ry} fill=${colour} stroke=${colour}
                    vector-effect="non-scaling-stroke" />`;
            }
            const pts = f.points.map((p) => `${p.x * 100},${p.y * 100}`).join(' ');
            return f.points.length >= 3
                ? html`<polygon class=${cls} data-feature=${f.id} points=${pts} fill=${colour} stroke=${colour}
                    vector-effect="non-scaling-stroke" />`
                : html`<polyline class=${cls} points=${pts} fill="none" stroke=${colour}
                    vector-effect="non-scaling-stroke" />`;
        })}
    </svg>`;
}

/** A pin per feature: a button with its name (the GM edits it from the list below the plan). */
export function featurePins(features, teams, onSelect) {
    return features.filter((f) => typeof featureCentre(f).x === 'number').map((f) => {
        const p = featureCentre(f);
        const label = t('features.pin', { type: t(`features.types.${f.type}`), name: featureName(f) });
        return html`<button type="button" class=${`mf-pin${f.draft ? ' draft' : ''}`} data-testid=${`mf-pin-${f.id}`}
            data-type=${f.type} aria-label=${label} title=${f.note ? `${label}: ${f.note}` : label}
            onClick=${() => onSelect && onSelect(f)}
            ref=${(el) => {
                if (!el) return;
                el.style.left = `${(p.x * 100).toFixed(2)}%`;
                el.style.top = `${(p.y * 100).toFixed(2)}%`;
                el.style.background = featureColour(f, teams);
            }}>${featureIcon(f.type)}</button>`;
    });
}

/** The legend: each type's icon and colour; a team's features in its colour. */
export function FeatureLegend() {
    return html`<details class="mf-legend" data-testid="mf-legend">
        <summary>${t('features.legend')}</summary>
        <ul>${FEATURE_TYPES.map((type) => html`<li>
            <span class="mf-swatch" ref=${(el) => { if (el) el.style.background = FEATURE_COLOURS[type]; }}>
                ${featureIcon(type)}</span> ${t(`features.types.${type}`)}</li>`)}</ul>
        <p class="muted small">${t('features.legend_team')}</p>
    </details>`;
}

/** A new feature's form values for a type: its usual shape, and a team for a team's own type. */
export function newDraft(type, level, teams) {
    const team = TEAM_TYPES.includes(type) && teams.length ? teams[0] : null; // never the boundary's
    return { id: 'new', draft: true, level, type, label: '', shape: DEFAULT_SHAPE[type], x: null, y: null,
             radius_m: 25, points: [], team, visibility: team ? 'team' : 'everyone', note: '' };
}

/** The editor under the plan: the features on this level, and the GM's form. */
export class MapFeatures extends Component {
    constructor() {
        super();
        this.state = { error: '', across: '', down: '' };
    }

    set(change) {
        this.setState({ error: '' });
        this.props.onDraft({ ...this.props.draft, ...change });
    }

    setType(type) {
        const d = this.props.draft;
        const fresh = newDraft(type, d.level, this.props.teams);
        // A type that is a team's own picks a team; the shape follows the type until the GM chose one or
        // placed something (an area chosen before the type stayed a circle: found on the bench, MF-17).
        const placed = d.x !== null || d.points.length;
        if (type === BOUNDARY) {
            // The field boundary is an area of no team (MF-20).
            this.set({ type, shape: 'polygon', team: null, visibility: d.visibility === 'team' ? 'everyone' : d.visibility });
            return;
        }
        this.set({ type, shape: placed || d.shapeChosen ? d.shape : fresh.shape, team: d.team || fresh.team,
                   visibility: d.team || fresh.team ? 'team' : d.visibility === 'team' ? 'everyone' : d.visibility });
    }

    setTeam(team) {
        const d = this.props.draft;
        const visibility = !team && d.visibility === 'team' ? 'everyone' : team && !d.team ? 'team' : d.visibility;
        this.set({ team: team || null, visibility });
    }

    setShape(shape) {
        this.set({ shape, shapeChosen: true, placing: true });
    }

    /** A place typed with the keyboard: across and down the plan, in %. */
    typedPlace() {
        const across = Number(this.state.across);
        const down = Number(this.state.down);
        if (this.state.across === '' || this.state.down === '' || !(across >= 0 && across <= 100)
            || !(down >= 0 && down <= 100)) {
            this.setState({ error: t('features.bad_place') });
            return;
        }
        this.props.onPlace({ x: across / 100, y: down / 100 });
        this.setState({ across: '', down: '' });
    }

    body() {
        const d = this.props.draft;
        const out = { level: d.level, type: d.type, label: d.label, shape: d.shape, team: d.team,
                      visibility: d.visibility, note: d.note };
        if (d.shape === 'polygon') out.points = d.points;
        else Object.assign(out, { x: d.x, y: d.y });
        if (d.shape === 'circle') out.radius_m = Number(d.radius_m);
        return out;
    }

    async save(e) {
        e.preventDefault();
        const d = this.props.draft;
        if (d.shape === 'polygon' ? d.points.length < 3 : d.x === null) {
            this.setState({ error: t(d.shape === 'polygon' ? 'features.need_corners' : 'features.need_place') });
            return;
        }
        if (d.type === 'other' && !d.label.trim()) {
            this.setState({ error: t('features.need_label') });
            return;
        }
        const path = d.id === 'new' ? '/field/features' : `/field/features/${d.id}`;
        const out = await this.props.app.call(d.id === 'new' ? 'POST' : 'PUT', path, this.body());
        if (out) this.props.onDraft(null);
    }

    async remove(f) {
        await this.props.app.call('DELETE', `/field/features/${f.id}`);
    }

    edit(f) {
        this.setState({ error: '' });
        this.props.onDraft({ ...f, draft: true, points: f.points ? [...f.points] : [], x: f.x ?? null,
                             y: f.y ?? null, radius_m: f.radius_m ?? 25, placing: false });
    }

    /** Whether this level has a field boundary other than the one being edited (one per level, MF-20). */
    hasBoundary(exceptId) {
        return this.props.features.some((f) => f.level === this.props.level && f.type === BOUNDARY && f.id !== exceptId);
    }

    /** MF-90: where a feature is on the field grid: a pin's or a circle's cell, an area's span ("B2–D5"). */
    where(f) {
        const grid = this.props.grid;
        if (f.shape === 'polygon') return gridSpan(grid, f.points);
        return typeof f.x === 'number' ? gridCell(grid, f.x, f.y) : '';
    }

    renderList(here) {
        const { canEdit, teams } = this.props;
        if (!here.length) return html`<p class="muted small" data-testid="mf-none">${t('features.none')}</p>`;
        return html`<ul class="mf-list" data-testid="mf-list">${here.map((f) => html`<li data-testid=${`mf-item-${f.id}`}>
            <span class="mf-swatch" ref=${(el) => { if (el) el.style.background = featureColour(f, teams); }}>
                ${featureIcon(f.type)}</span>
            <span class="mf-what"><strong>${featureName(f)}</strong>
                <span class="muted small">${t(`features.types.${f.type}`)} · ${t(`features.shapes.${f.shape}`)}${
                    f.shape === 'circle' ? ` ${f.radius_m} m` : ''} · ${
                    f.visibility === 'team' ? t('features.only_team', { team: f.team }) : t(`features.vis.${f.visibility}`)}${
                    this.where(f) ? html` · <span data-testid=${`mf-cell-${f.id}`}>${t('grid.cell', { cell: this.where(f) })}</span>` : ''}</span>
                ${f.note && html`<span class="small">${f.note}</span>`}</span>
            ${canEdit && html`<span class="mf-actions">
                <button type="button" data-testid=${`mf-edit-${f.id}`} onClick=${() => this.edit(f)}>${t('features.edit')}</button>
                <${ConfirmButton} label=${t('features.delete')} testid=${`mf-delete-${f.id}`}
                    question=${t('features.confirm_delete', { name: featureName(f) })} onConfirm=${() => this.remove(f)} />
            </span>`}
        </li>`)}</ul>`;
    }

    renderPlacing() {
        const d = this.props.draft;
        const hint = d.shape === 'polygon' ? t('features.placing_polygon', { n: d.points.length })
            : t(`features.placing_${d.shape}`);
        return html`<div class="mf-placing" data-testid="mf-placing">
            <p class="small" role="status" data-testid="mf-hint">${hint}</p>
            ${d.shape === 'polygon' && d.points.length > 0 && html`<div class="actions">
                <button type="button" data-testid="mf-undo" onClick=${() => this.set({ points: d.points.slice(0, -1) })}>
                    ${t('features.undo_point')}</button>
                <button type="button" onClick=${() => this.set({ points: [] })}>${t('features.clear_points')}</button>
            </div>`}
            <fieldset class="mf-keys">
                <legend>${t('features.keyboard')}</legend>
                <div class="field"><label for="mf-across">${t('features.across')}</label>
                    <input id="mf-across" data-testid="mf-across" type="number" min="0" max="100" step="0.1"
                        inputmode="decimal" value=${this.state.across}
                        onInput=${(e) => this.setState({ across: e.target.value })} /></div>
                <div class="field"><label for="mf-down">${t('features.down')}</label>
                    <input id="mf-down" data-testid="mf-down" type="number" min="0" max="100" step="0.1"
                        inputmode="decimal" value=${this.state.down}
                        onInput=${(e) => this.setState({ down: e.target.value })} /></div>
                <button type="button" data-testid="mf-put" disabled=${d.shape === 'polygon' && d.points.length >= POLYGON_MAX}
                    onClick=${() => this.typedPlace()}>${t(d.shape === 'polygon' ? 'features.add_corner' : 'features.set_point')}</button>
            </fieldset>
        </div>`;
    }

    renderForm() {
        const { draft: d, teams, scale } = this.props;
        const teamChoices = [...new Set([...teams, ...(d.team ? [d.team] : [])])];
        const isBoundary = d.type === BOUNDARY;
        return html`<form class="form mf-form" data-testid="mf-form" novalidate onSubmit=${(e) => this.save(e)}
            aria-labelledby="mf-form-h">
            <h3 id="mf-form-h">${t(d.id === 'new' ? 'features.add' : 'features.editing', { name: featureName(d) })}</h3>
            <div class="params">
                <div class="field"><label for="mf-type">${t('features.type')}</label>
                    <select id="mf-type" data-testid="mf-type" value=${d.type} onChange=${(e) => this.setType(e.target.value)}>
                        ${FEATURE_TYPES.map((k) => html`<option value=${k} selected=${k === d.type}
                            disabled=${k === BOUNDARY && k !== d.type && this.hasBoundary(d.id)}>${t(`features.types.${k}`)}</option>`)}
                    </select></div>
                <div class="field"><label for="mf-label">${t(d.type === 'other' ? 'features.label_other' : 'features.label')}</label>
                    <input id="mf-label" data-testid="mf-label" maxlength="48" autocomplete="off" value=${d.label}
                        onInput=${(e) => this.set({ label: e.target.value })} /></div>
                <div class="field"><label for="mf-team">${t('features.team')}</label>
                    <select id="mf-team" data-testid="mf-team" value=${d.team || ''} disabled=${isBoundary}
                        onChange=${(e) => this.setTeam(e.target.value)}>
                        <option value="" selected=${!d.team}>${t('features.no_team')}</option>
                        ${teamChoices.map((k) => html`<option value=${k} selected=${k === d.team}>${k}</option>`)}
                    </select></div>
                <div class="field"><label for="mf-visibility">${t('features.visibility')}</label>
                    <select id="mf-visibility" data-testid="mf-visibility" value=${d.visibility}
                        onChange=${(e) => this.set({ visibility: e.target.value })}>
                        ${VISIBILITIES.map((k) => html`<option value=${k} selected=${k === d.visibility}
                            disabled=${k === 'team' && !d.team}>${
                            k === 'team' && d.team ? t('features.only_team', { team: d.team }) : t(`features.vis.${k}`)}</option>`)}
                    </select></div>
            </div>
            <fieldset class="mf-shapes">
                <legend>${t('features.shape')}</legend>
                ${SHAPES.map((k) => html`<label class="check"><input type="radio" name="mf-shape" value=${k}
                    data-testid=${`mf-shape-${k}`} checked=${d.shape === k} disabled=${isBoundary && k !== 'polygon'}
                    onChange=${() => this.setShape(k)} /> ${t(`features.shapes.${k}`)}</label>`)}
                ${isBoundary && html`<p class="muted small">${t('features.boundary_hint')}</p>`}
            </fieldset>
            ${d.shape === 'circle' && html`<div class="field"><label for="mf-radius">${t('features.radius')}</label>
                <input id="mf-radius" data-testid="mf-radius" type="number" min="1" max="2000" step="1"
                    inputmode="numeric" value=${d.radius_m} onInput=${(e) => this.set({ radius_m: e.target.value })} />
                ${!scale && html`<span class="muted small" data-testid="mf-no-scale">${t('features.no_scale')}</span>`}</div>`}
            <div class="field"><label for="mf-note">${t('features.note')}</label>
                <input id="mf-note" data-testid="mf-note" maxlength="200" autocomplete="off" value=${d.note}
                    onInput=${(e) => this.set({ note: e.target.value })} /></div>
            <div class="actions">
                <button type="button" data-testid="mf-place" aria-pressed=${d.placing ? 'true' : 'false'}
                    onClick=${() => this.set({ placing: !d.placing })}>${t('features.place')}</button>
            </div>
            ${d.placing && this.renderPlacing()}
            ${this.state.error && html`<p class="error" role="alert" data-testid="mf-error">${this.state.error}</p>`}
            <div class="actions">
                <button type="submit" class="primary" data-testid="mf-save">${t('common.save')}</button>
                <button type="button" data-testid="mf-cancel" onClick=${() => this.props.onDraft(null)}>${t('common.cancel')}</button>
            </div>
        </form>`;
    }

    render(props) {
        const { features, level, canEdit, draft, teams } = props;
        const here = features.filter((f) => f.level === level);
        return html`<section class="card mf" aria-labelledby="mf-h" data-testid="map-features">
            <h2 id="mf-h">${t('features.title')}</h2>
            <p class="muted small">${t(canEdit ? 'features.intro' : 'features.intro_read')}</p>
            <${FeatureLegend} />
            ${this.renderList(here)}
            ${canEdit && !draft && html`<div class="actions">
                <label for="mf-new-type" class="sr-only">${t('features.type')}</label>
                <select id="mf-new-type" data-testid="mf-new-type" class="mf-new-type">
                    ${FEATURE_TYPES.map((k) => html`<option value=${k} disabled=${k === BOUNDARY && this.hasBoundary(null)}>${
                        t(`features.types.${k}`)}</option>`)}
                </select>
                <button type="button" class="primary" data-testid="mf-add" onClick=${(e) => {
                    const type = e.currentTarget.parentElement.querySelector('select').value;
                    this.setState({ error: '' });
                    props.onDraft({ ...newDraft(type, level, teams), placing: true });
                }}>${t('features.add')}</button>
            </div>`}
            ${canEdit && draft && this.renderForm()}
        </section>`;
    }
}
