// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The field image's place on the map (ADR-P4-7 as amended, decision P4R18):
// Field Boxes have no GPS, so the ATAK feed puts them on a map through the
// image. The GM gives two opposite corners of the (north-up) image their
// latitude and longitude, pasted from a map app as "latitude, longitude",
// saved with PUT /api/v1/field/georef; the controller answers with the four
// corners it worked out, shown back here and as pins on the image. With the
// API, 3-8 control points also work (a rotated image); the panel then shows
// them and offers to replace them with two corners.

import { html, Component, t, ConfirmButton } from '../ui.js';

const LATLON = /^\s*([+-]?\d{1,2}(?:\.\d+)?)\s*[,;]\s*([+-]?\d{1,3}(?:\.\d+)?)\s*$/;
const CORNERS = ['top_left', 'top_right', 'bottom_right', 'bottom_left'];
// The two corners the GM gives, as image positions (x across, y down).
const GIVEN = { top_left: { x: 0, y: 0 }, bottom_right: { x: 1, y: 1 } };

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
    const out = {};
    for (const [name, at] of Object.entries(GIVEN)) {
        const p = georef.points.find((q) => q.x === at.x && q.y === at.y);
        if (!p) return null;
        out[name] = formatLatLon(p);
    }
    return out;
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
        const out = await this.props.app.call('GET', '/atak');
        if (out) this.setState({ atak: out });
    }

    values() {
        return this.state.edit || givenCorners(this.props.georef) || { top_left: '', bottom_right: '' };
    }

    async save(e) {
        e.preventDefault();
        const v = this.values();
        const points = [];
        for (const name of Object.keys(GIVEN)) {
            const p = parseLatLon(v[name]);
            if (!p) {
                this.setState({ error: t('georef.bad_point', { corner: t(`georef.${name}`) }), saved: false });
                return;
            }
            points.push({ ...GIVEN[name], ...p });
        }
        const out = await this.props.app.call('PUT', '/field/georef', { points });
        if (out) {
            this.setState({ edit: null, error: '', saved: true });
            this.props.onChange(out.georef);
            this.loadAtak();
        }
    }

    async remove() {
        const out = await this.props.app.call('DELETE', '/field/georef');
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
            <h2 id="georef-h">${t('georef.title')}</h2>
            <p class="muted small">${t('georef.intro')}</p>
            ${georef ? html`<dl class="facts" data-testid="georef-corners">
                ${CORNERS.map((c) => html`<dt>${t(`georef.${c}`)}</dt>
                    <dd data-testid=${`georef-${c}`}>${formatLatLon(georef.corners[c])}</dd>`)}
            </dl>
            ${georef.kind !== 'corners' && html`<p class="muted small">${t('georef.points', {
                n: georef.points.length, residual: georef.residual_m })}</p>`}`
            : html`<p class="muted" data-testid="georef-none">${t('georef.none')}</p>`}
            ${gm && html`<form class="form" onSubmit=${(e) => this.save(e)} data-testid="georef-form" novalidate>
                ${Object.keys(GIVEN).map((name) => html`<div class="field">
                    <label for=${`georef-${name}-in`}>${t(`georef.${name}`)}</label>
                    <input id=${`georef-${name}-in`} data-testid=${`georef-${name}-input`} inputmode="decimal"
                        autocomplete="off" placeholder=${t('georef.placeholder')} value=${v[name]}
                        onInput=${(e) => this.set(name, e.target.value)} /></div>`)}
                ${state.error && html`<p class="error" role="alert" data-testid="georef-error">${state.error}</p>`}
                <div class="actions">
                    <button type="submit" class="primary" data-testid="georef-save">${t('common.save')}</button>
                    ${georef && html`<${ConfirmButton} label=${t('georef.remove')} question=${t('georef.confirm_remove')}
                        testid="georef-remove" onConfirm=${() => this.remove()} />`}
                    ${state.saved && html`<span class="ok" role="status">${t('georef.saved')}</span>`}
                </div>
            </form>`}
            <p class="muted small">${t('georef.privacy')}</p>
            ${this.renderAtak(state.atak)}
        </section>`;
    }
}
