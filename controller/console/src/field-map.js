// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// *Carregar o campo de um mapa* / *Load the field from a map* (the maintainer's idea MF-18, built as
// decisions MF-19 to MF-30). Opened from the Field tab (field-view.js) with the GM token the console
// keeps; the only page of the console that reaches the internet (its own Content-Security-Policy,
// api.py FIELD_MAP_HEADERS), and only while the GM sets the game up:
//
// 1. find the field on an interactive OpenStreetMap map (tile-map.js), or go to a typed
//    "latitude, longitude" (or the level's current map position);
// 2. trace the field's outline corner by corner: a press on the map, the map's centre (the cross,
//    with the keyboard) or a typed "latitude, longitude"; undo and start again; 3 to 12 corners;
// 3. *Draw the field image*: this browser fetches the area's OpenStreetMap data (Overpass) and, in
//    Portugal, the DGT orthophoto, once, and draws the image (field-render.js), shown with the outline;
// 4. *Use as the field*: one request to the controller (POST /api/v1/field/levels/{n}/from-map) sets
//    the level's plan, its map position (from the image's edges) and its field boundary together.
//
// The controller needs no internet for any of it; the rest of the console works offline as before.

import { html, render, Component, createRef, t, loadLanguage, api, savedToken } from './ui.js';
import { TileMap } from './components/tile-map.js';
import { areaFor, frameFor, inPortugal, fetchOsm, fetchOrthophoto, drawField, encode, base64, MapError }
    from './components/field-render.js';
import { parseLatLon, formatLatLon } from './components/georef-panel.js';
import { levelName, levelsInUse } from './components/field-levels.js';

const CORNERS_MAX = 12; // map_features.POLYGON_MAX
const FIELD_ZOOM = 17;

/** The map's element: Preact leaves it alone after the first render (TileMap owns what is inside). */
class MapHost extends Component {
    shouldComponentUpdate() {
        return false;
    }

    render(props) {
        return html`<div class="fm-map" ref=${props.hostRef} aria-describedby="fm-map-help"></div>`;
    }
}

function round7(v) {
    return Math.round(v * 1e7) / 1e7;
}

class FieldMap extends Component {
    constructor() {
        super();
        const level = Number(new URLSearchParams(window.location.search).get('level')) || 0;
        this.state = {
            ready: false, role: null, error: '', notice: '', levels: null, level, info: null, outline: [],
            corner: '', go: '', label: '', ortho: null, busy: '', result: null, done: null,
            online: navigator.onLine !== false,
        };
        this.mapEl = createRef();
        this.map = null;
        this.onLine = () => this.setState({ online: navigator.onLine !== false });
    }

    async componentDidMount() {
        await loadLanguage();
        document.title = `Atalaia · ${t('fieldmap.title')}`;
        window.addEventListener('online', this.onLine);
        window.addEventListener('offline', this.onLine);
        const token = savedToken();
        let role = null;
        try {
            role = token ? (await api(token, 'GET', '/whoami')).role : null;
        } catch (e) {
            role = null;
        }
        if (role !== 'gm') {
            this.setState({ ready: true, role });
            return;
        }
        const info = await api(token, 'GET', '/field');
        const levels = info.levels;
        const level = this.state.level < levelsInUse(levels) ? this.state.level : 0;
        this.setState({ ready: true, role, info, levels, level }, () => this.startMap(token, level));
    }

    componentWillUnmount() {
        window.removeEventListener('online', this.onLine);
        window.removeEventListener('offline', this.onLine);
        if (this.map) this.map.destroy();
        if (this.state.result) URL.revokeObjectURL(this.state.result.url);
    }

    async startMap(token, level) {
        this.map = new TileMap(this.mapEl.current, {
            label: t('fieldmap.map_label'), attribution: '© OpenStreetMap contributors',
            onPress: (p) => this.addCorner(p),
        });
        // Start where the level's plan already is on the map, if it is.
        try {
            const path = level === 0 ? '/field/georef' : `/field/levels/${level}/georef`;
            const geo = (await api(token, 'GET', path)).georef;
            if (geo && geo.corners) {
                const c = geo.corners;
                this.map.view({ lat: (c.top_left.lat + c.bottom_right.lat) / 2, lon: (c.top_left.lon + c.bottom_right.lon) / 2 },
                    FIELD_ZOOM);
            }
        } catch (e) {
            /* no map position: the default view (Portugal) */
        }
    }

    setOutline(outline) {
        this.setState({ outline, error: '', result: this.dropResult() });
        if (this.map) this.map.setOutline(outline);
    }

    dropResult() {
        if (this.state.result) URL.revokeObjectURL(this.state.result.url);
        return null;
    }

    addCorner(p) {
        if (this.state.busy || this.state.done) return;
        if (this.state.outline.length >= CORNERS_MAX) {
            this.setState({ error: t('fieldmap.corners_max', { n: CORNERS_MAX }) });
            return;
        }
        this.setOutline([...this.state.outline, { lat: round7(p.lat), lon: round7(p.lon) }]);
    }

    typedCorner(e) {
        e.preventDefault();
        const p = parseLatLon(this.state.corner);
        if (!p) {
            this.setState({ error: t('fieldmap.bad_latlon') });
            return;
        }
        this.setState({ corner: '' });
        this.addCorner(p);
    }

    goTo(e) {
        e.preventDefault();
        const p = parseLatLon(this.state.go);
        if (!p) {
            this.setState({ error: t('fieldmap.bad_latlon') });
            return;
        }
        this.setState({ error: '' });
        this.map.view(p, FIELD_ZOOM);
    }

    useOrtho() {
        if (this.state.ortho !== null) return this.state.ortho;
        try {
            return this.state.outline.length >= 3 && inPortugal(areaFor(this.state.outline));
        } catch (e) {
            return false;
        }
    }

    mapError(e) {
        if (e instanceof MapError) return t(`fieldmap.errors.${e.code}`, { detail: e.message });
        return e && e.message ? e.message : String(e);
    }

    async drawImage() {
        const { outline } = this.state;
        if (outline.length < 3) {
            this.setState({ error: t('fieldmap.need_corners') });
            return;
        }
        this.setState({ error: '', notice: '', result: this.dropResult() });
        try {
            const bounds = areaFor(outline);
            const frame = frameFor(bounds);
            const ortho = this.useOrtho();
            this.setState({ busy: 'osm' });
            const elements = await fetchOsm(bounds);
            let photo = null;
            let notice = '';
            if (ortho) {
                this.setState({ busy: 'ortho' });
                try {
                    photo = await fetchOrthophoto(bounds, frame);
                    if (!photo) notice = t('fieldmap.no_ortho');
                } catch (e) {
                    notice = t('fieldmap.ortho_failed', { detail: this.mapError(e) });
                }
            }
            this.setState({ busy: 'draw' });
            const canvas = drawField(elements, bounds, frame, photo);
            const out = await encode(canvas, Boolean(photo));
            this.setState({ busy: '', notice, result: { ...out, url: URL.createObjectURL(out.blob), bounds,
                                                         photo: Boolean(photo), mpp: frame.mpp * (frame.width / out.width) } });
        } catch (e) {
            this.setState({ busy: '', error: this.mapError(e) });
        }
    }

    async upload() {
        const { result, outline, label, level } = this.state;
        this.setState({ busy: 'upload', error: '' });
        try {
            const body = { content_type: result.type, image: await base64(result.blob), bounds: result.bounds, outline,
                           label: label.trim() };
            const done = await api(savedToken(), 'POST', `/field/levels/${level}/from-map`, body);
            this.setState({ busy: '', done });
            if (this.map) this.map.setOutline([]);
        } catch (e) {
            this.setState({ busy: '', error: e.message });
        }
    }

    hasPlan() {
        const { info, levels, level } = this.state;
        if (!info) return false;
        return level === 0 ? Boolean(info.image) : Boolean((levels.levels[level] || {}).image);
    }

    renderPreview() {
        const r = this.state.result;
        const b = r.bounds;
        const pts = this.state.outline.map((p) => `${(((p.lon - b.west) / (b.east - b.west)) * 100).toFixed(3)},${
            (((b.north - p.lat) / (b.north - b.south)) * 100).toFixed(3)}`).join(' ');
        return html`<section class="card" aria-labelledby="fm-preview-h" data-testid="fm-preview">
            <h2 id="fm-preview-h">${t('fieldmap.preview')}</h2>
            <div class="fm-preview">
                <img src=${r.url} alt=${t('fieldmap.preview_alt')} data-testid="fm-image" />
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                    <polygon class="fm-outline" points=${pts} vector-effect="non-scaling-stroke" /></svg>
            </div>
            <p class="muted small" data-testid="fm-size">${t('fieldmap.size', {
                width: r.width, height: r.height, mpp: r.mpp.toFixed(2), kb: Math.round(r.blob.size / 1024) })}
                ${' '}${t(r.photo ? 'fieldmap.source_both' : 'fieldmap.source_osm')}</p>
            ${this.hasPlan() && html`<p class="warning small" data-testid="fm-replaces">${
                levelsInUse(this.state.levels) > 1
                    ? t('fieldmap.replaces_level', { name: levelName(this.state.levels, this.state.level) })
                    : t('fieldmap.replaces')}</p>`}
            <div class="actions">
                <button type="button" class="primary" data-testid="fm-upload" disabled=${Boolean(this.state.busy)}
                    onClick=${() => this.upload()}>${t('fieldmap.use')}</button>
                <button type="button" data-testid="fm-redraw" disabled=${Boolean(this.state.busy)}
                    onClick=${() => this.setState({ result: this.dropResult() })}>${t('fieldmap.change')}</button>
            </div>
        </section>`;
    }

    renderDone() {
        return html`<section class="card" aria-labelledby="fm-done-h" data-testid="fm-done">
            <h2 id="fm-done-h">${t('fieldmap.done_title')}</h2>
            <p role="status">${t('fieldmap.done')}</p>
            <div class="actions"><a class="button primary" href="./#field" data-testid="fm-back-done">${t('fieldmap.back')}</a></div>
        </section>`;
    }

    renderOutline() {
        const s = this.state;
        const n = s.outline.length;
        const multi = s.levels && levelsInUse(s.levels) > 1;
        return html`<section class="card" aria-labelledby="fm-outline-h">
            <h2 id="fm-outline-h">${t('fieldmap.outline')}</h2>
            <p class="small" role="status" data-testid="fm-count">${t('fieldmap.corners', { n, max: CORNERS_MAX })}</p>
            ${n > 0 && html`<ol class="fm-corners small" data-testid="fm-corners">
                ${s.outline.map((p) => html`<li>${formatLatLon(p)}</li>`)}</ol>`}
            <div class="actions">
                <button type="button" data-testid="fm-centre" disabled=${n >= CORNERS_MAX}
                    onClick=${() => this.addCorner(this.map.centre)}>${t('fieldmap.add_centre')}</button>
                <button type="button" data-testid="fm-undo" disabled=${!n}
                    onClick=${() => this.setOutline(s.outline.slice(0, -1))}>${t('fieldmap.undo')}</button>
                <button type="button" data-testid="fm-clear" disabled=${!n}
                    onClick=${() => this.setOutline([])}>${t('fieldmap.clear')}</button>
            </div>
            <form class="form inline" novalidate onSubmit=${(e) => this.typedCorner(e)}>
                <label for="fm-corner">${t('fieldmap.typed_corner')}</label>
                <input id="fm-corner" data-testid="fm-corner" inputmode="decimal" autocomplete="off"
                    placeholder="39.600000, -8.400000" value=${s.corner} onInput=${(e) => this.setState({ corner: e.target.value })} />
                <button type="submit" data-testid="fm-corner-add" disabled=${n >= CORNERS_MAX}>${t('fieldmap.add_corner')}</button>
            </form>
            <div class="params">
                ${multi && html`<div class="field"><label for="fm-level">${t('fieldmap.level')}</label>
                    <select id="fm-level" data-testid="fm-level" value=${s.level}
                        onChange=${(e) => this.setState({ level: Number(e.target.value) })}>
                        ${Array.from({ length: levelsInUse(s.levels) }, (_, lv) => html`<option value=${lv}
                            selected=${lv === s.level}>${levelName(s.levels, lv)}</option>`)}
                    </select></div>`}
                <div class="field"><label for="fm-label">${t('fieldmap.label')}</label>
                    <input id="fm-label" data-testid="fm-label" maxlength="48" autocomplete="off" value=${s.label}
                        onInput=${(e) => this.setState({ label: e.target.value })} /></div>
            </div>
            <label class="check fm-ortho"><input type="checkbox" data-testid="fm-ortho" checked=${this.useOrtho()}
                onChange=${(e) => this.setState({ ortho: e.target.checked, result: this.dropResult() })} />
                ${t('fieldmap.ortho')}</label>
            <div class="actions">
                <button type="button" class="primary" data-testid="fm-draw" disabled=${Boolean(s.busy) || n < 3}
                    onClick=${() => this.drawImage()}>${t('fieldmap.draw')}</button>
                ${s.busy && html`<span class="muted small" role="status" data-testid="fm-busy">${t(`fieldmap.busy.${s.busy}`)}</span>`}
            </div>
        </section>`;
    }

    render(props, s) {
        if (!s.ready) return html`<main class="content"><p class="muted">…</p></main>`;
        const header = html`<header class="top"><div class="brand"><strong>${t('fieldmap.title')}</strong></div>
            <div class="top-right"><a class="button fm-back" href="./#field" data-testid="fm-back">${t('fieldmap.back')}</a></div>
        </header>`;
        if (s.role !== 'gm') {
            return html`${header}<main class="content"><p class="error" data-testid="fm-login">${t('fieldmap.login')}</p></main>`;
        }
        return html`${header}<main class="content fm">
            <section class="card" aria-labelledby="fm-h">
                <h1 id="fm-h" class="sr-only">${t('fieldmap.title')}</h1>
                <p>${t('fieldmap.intro')}</p>
                <p class="muted small">${t('fieldmap.sources')}</p>
                ${!s.online && html`<p class="warning" role="alert" data-testid="fm-offline">${t('fieldmap.offline')}</p>`}
                ${s.done ? null : html`<form class="form inline" novalidate onSubmit=${(e) => this.goTo(e)}>
                    <label for="fm-go">${t('fieldmap.go')}</label>
                    <input id="fm-go" data-testid="fm-go" inputmode="decimal" autocomplete="off" placeholder="39.600000, -8.400000"
                        value=${s.go} onInput=${(e) => this.setState({ go: e.target.value })} />
                    <button type="submit" data-testid="fm-go-button">${t('fieldmap.go_button')}</button>
                </form>`}
                <p class="muted small" id="fm-map-help">${t('fieldmap.map_help')}</p>
                <${MapHost} hostRef=${this.mapEl} />
                <div class="actions">
                    <button type="button" data-testid="fm-zoom-in" aria-label=${t('fieldmap.zoom_in')}
                        onClick=${() => this.map.zoomBy(1)}>+</button>
                    <button type="button" data-testid="fm-zoom-out" aria-label=${t('fieldmap.zoom_out')}
                        onClick=${() => this.map.zoomBy(-1)}>−</button>
                </div>
            </section>
            ${s.error && html`<p class="error" role="alert" data-testid="fm-error">${s.error}</p>`}
            ${s.notice && html`<p class="notice" role="status" data-testid="fm-notice">${s.notice}</p>`}
            ${s.done ? this.renderDone() : html`${this.renderOutline()}${s.result && this.renderPreview()}`}
        </main>`;
    }
}

render(html`<${FieldMap} />`, document.getElementById('app'));
