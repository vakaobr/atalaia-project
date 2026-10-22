// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The field image's place on the map (ADR-P4-7 as amended, decision P4R18):
// Field Boxes have no GPS, so the ATAK feed puts them on a map through the
// image. The GM gives any two opposite corners of the (north-up) image their
// latitude and longitude, pasted from a map app as "latitude, longitude"; the
// page works out which is at the top (the northern one) and on the left (the
// western one), so a south-west and a north-east corner work as well as the
// top-left and bottom-right ones (found on the bench, 2026-10-22, GR-1),
// saved with PUT /api/v1/field/georef; the controller answers with the four
// corners it worked out, shown back here and as pins on the image. With the
// API, 3-8 control points also work (a rotated image); the panel then shows
// them and offers to replace them with two corners.
//
// On a multi-story field (field-levels.js) the panel is the shown level's: a level
// without its own points shares level 0's (decision ML-6) and says so; the GM may
// give it its own (PUT /api/v1/field/levels/{n}/georef).

import { html, Component, t, ConfirmButton } from '../ui.js';

const LATLON = /^\s*([+-]?\d{1,2}(?:\.\d+)?)\s*[,;]\s*([+-]?\d{1,3}(?:\.\d+)?)\s*$/;
const CORNERS = ['top_left', 'top_right', 'bottom_right', 'bottom_left'];
// The two corners the GM gives (the field names are kept from when they had to be the
// top-left and bottom-right ones); their image positions follow from their coordinates.
const GIVEN = { top_left: 'corner_a', bottom_right: 'corner_b' };

/** Two opposite corners, as control points: the northern one at the top (y 0), the western
 * one on the left (x 0), as on a north-up image. Two points level in latitude or longitude
 * are left for the controller to refuse. */
export function orientCorners(a, b) {
    const ya = a.lat >= b.lat ? 0 : 1;
    const xa = a.lon <= b.lon ? 0 : 1;
    return [{ x: xa, y: ya, ...a }, { x: 1 - xa, y: 1 - ya, ...b }];
}

/** "latitude, longitude" as {lat, lon}, or null. */
export function parseLatLon(text) {
    const m = LATLON.exec(text || '');
    if (!m) return null;
    const lat = Number(m[1]);
    const lon = Number(m[2]);
    if (!(Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) return null;
    return { lat, lon };
}

export function formatLatLon(p) {
    return `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;
}

/** The GM's two corners, when the georeference is exactly those (else null). */
function givenCorners(georef) {
    if (!georef || georef.kind !== 'corners' || georef.points.length !== 2) return null;
    const [a, b] = georef.points;
    const corner = (q) => (q.x === 0 || q.x === 1) && (q.y === 0 || q.y === 1);
    if (!corner(a) || !corner(b) || a.x === b.x || a.y === b.y) return null;
    return { top_left: formatLatLon(a), bottom_right: formatLatLon(b) };
}

/** Pins on the field image where the georeference's control points are. */
export function georefPins(georef) {
    if (!georef) return null;
    return georef.points.map((p, i) => html`<span class="georef-pin" aria-hidden="true" data-testid=${`georef-pin-${i}`}
        ref=${(el) => {
            if (!el) return;
            el.style.left = `${(p.x * 100).toFixed(2)}%`;
            el.style.top = `${(p.y * 100).toFixed(2)}%`;
        }}>${i + 1}</span>`);
}

export class GeorefPanel extends Component {
    constructor() {
        super();
        this.state = { edit: null, error: '', saved: false, atak: null };
    }

    componentDidMount() {
        this.loadAtak();
    }

    async loadAtak() {
        if (!this.props.app.serves('atak')) return;
        const out = await this.props.app.call('GET', '/atak');
        if (out) this.setState({ atak: out });
    }

    componentDidUpdate(prev) {
        if (prev.level !== this.props.level) this.setState({ edit: null, error: '', saved: false });
    }

    path() {
        const level = this.props.level || 0;
        return level === 0 ? '/field/georef' : `/field/levels/${level}/georef`;
    }

    /** This level's own points (null while it shares level 0's). */
    own() {
        return this.props.own === false ? null : this.props.georef;
    }

    values() {
        return this.state.edit || givenCorners(this.own()) || { top_left: '', bottom_right: '' };
    }

    async save(e) {
        e.preventDefault();
        const v = this.values();
        const given = [];
        for (const [name, label] of Object.entries(GIVEN)) {
            const p = parseLatLon(v[name]);
            if (!p) {
                this.setState({ error: t('georef.bad_point', { corner: t(`georef.${label}`) }), saved: false });
                return;
            }
            given.push(p);
        }
        const points = orientCorners(given[0], given[1]);
        const out = await this.props.app.call('PUT', this.path(), { points });
        if (out) {
            this.setState({ edit: null, error: '', saved: true });
            this.props.onChange(out.georef);
            this.loadAtak();
        }
    }

    async remove() {
        const out = await this.props.app.call('DELETE', this.path());
        if (out) {
            this.setState({ edit: null, error: '', saved: false });
            this.props.onChange(null);
        }
    }

    set(name, value) {
        this.setState({ edit: { ...this.values(), [name]: value }, error: '', saved: false });
    }

    renderAtak(atak) {
        if (!atak) return null;
        if (!atak.enabled) return html`<p class="muted small" data-testid="atak-status">${t('georef.atak_off')}</p>`;
        return html`<p class="muted small" data-testid="atak-status">${t('georef.atak_on', {
            markers: atak.markers, sent: atak.udp_events + atak.tcp_events })}</p>`;
    }

    render(props, state) {
        const { app, georef } = props;
        const gm = app.state.role === 'gm';
        const v = this.values();
        return html`<section class="card" aria-labelledby="georef-h" data-testid="georef">
            <h2 id="georef-h">${props.levelName ? t('levels.georef_title', { name: props.levelName }) : t('georef.title')}</h2>
            <p class="muted small">${t('georef.intro')}</p>
            ${props.levelName && props.own === false && georef && html`<p class="muted small" data-testid="georef-shared">${
                t('levels.georef_shared', { ground: props.groundName })}</p>`}
            ${georef ? html`<dl class="facts" data-testid="georef-corners">
                ${CORNERS.map((c) => html`<dt>${t(`georef.${c}`)}</dt>
                    <dd data-testid=${`georef-${c}`}>${formatLatLon(georef.corners[c])}</dd>`)}
            </dl>
            ${georef.kind !== 'corners' && html`<p class="muted small">${t('georef.points', {
                n: georef.points.length, residual: georef.residual_m })}</p>`}`
            : html`<p class="muted" data-testid="georef-none">${t('georef.none')}</p>`}
            ${gm && html`<form class="form" onSubmit=${(e) => this.save(e)} data-testid="georef-form" novalidate>
                ${Object.entries(GIVEN).map(([name, label]) => html`<div class="field">
                    <label for=${`georef-${name}-in`}>${t(`georef.${label}`)}</label>
                    <input id=${`georef-${name}-in`} data-testid=${`georef-${name}-input`} inputmode="decimal"
                        autocomplete="off" placeholder=${t('georef.placeholder')} value=${v[name]}
                        onInput=${(e) => this.set(name, e.target.value)} /></div>`)}
                ${state.error && html`<p class="error" role="alert" data-testid="georef-error">${state.error}</p>`}
                <div class="actions">
                    <button type="submit" class="primary" data-testid="georef-save">${t('common.save')}</button>
                    ${this.own() && html`<${ConfirmButton} label=${t('georef.remove')} question=${t('georef.confirm_remove')}
                        testid="georef-remove" onConfirm=${() => this.remove()} />`}
                    ${state.saved && html`<span class="ok" role="status">${t('georef.saved')}</span>`}
                </div>
            </form>`}
            <p class="muted small">${t('georef.privacy')}</p>
            ${this.renderAtak(state.atak)}
        </section>`;
    }
}
