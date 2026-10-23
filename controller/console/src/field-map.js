// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// *Carregar o campo de um mapa* / *Load the field from a map* (the maintainer's idea MF-18, built as
// decisions MF-19 to MF-30). Opened from the Field tab (field-view.js) with the GM token the console
// keeps; the only page of the console that reaches the internet (its own Content-Security-Policy,
// api.py FIELD_MAP_HEADERS), and only while the GM sets the game up:
//
// 1. find the field on an interactive OpenStreetMap map (tile-map.js), or over an open orthophoto where
//    there is one (the *Mapa* / *Ortofoto* switch, MF-54 to MF-57: the DGT's in mainland Portugal, and
//    since MF-65 IGN España's, IGN France's and PDOK's, ortho-sources.js): the level's current map
//    position, else the GM's own location when the browser already allows it (MF-41, MF-42), a typed
//    "latitude, longitude", *Use my location*, or a place's name searched with OpenStreetMap's
//    Nominatim (MF-44 to MF-46; place-search.js);
// 2. trace the field's outline corner by corner: a press on the map, the map's centre (the cross,
//    with the keyboard) or a typed "latitude, longitude"; undo and start again; 3 to 12 corners;
// 3. *Draw the field image*: this browser fetches the area's OpenStreetMap data (Overpass; when busy,
//    retried and asked of other public instances, MF-50 to MF-53) and, where there is one, the
//    orthophoto of the country the outline is in (MF-67), once, and draws the image (field-render.js),
//    shown with the outline;
//    MF-59: the preview then scrolls into view with the focus on its heading; MF-60: leaving the page
//    with a drawn image not yet used asks first;
// 4. *Use as the field*: one request to the controller (POST /api/v1/field/levels/{n}/from-map) sets
//    the level's plan, its map position (from the image's edges) and its field boundary together.
//
// The controller needs no internet for any of it; the rest of the console works offline as before.

import { html, render, Component, createRef, t, loadLanguage, lang, api, savedToken } from './ui.js';
import { TileMap, OSM_SOURCE } from './components/tile-map.js';
import { areaFor, frameFor, fetchOsm, fetchOrthophoto, drawField, encode, base64, MapError, OVERPASS_URL,
         overpassHost, attribution, RETRY } from './components/field-render.js';
import { sourceAt, sourcesFor, tileSource } from './components/ortho-sources.js';
import { parseLatLon, formatLatLon } from './components/georef-panel.js';
import { levelName, levelsInUse, LOADED_KEY } from './components/field-levels.js';
import { PlaceSearch, SearchError, locate, locationGranted } from './components/place-search.js';

const CORNERS_MAX = 12; // map_features.POLYGON_MAX
const FIELD_ZOOM = 17;
const LOCATE_ZOOM = 17; // where a field is recognisable (clamped to the tile server's highest)
const LAYER_KEY = 'atalaia.fieldmap.layer'; // MF-56: the GM's choice, in this browser only

function savedLayer() {
    try {
        return window.localStorage.getItem(LAYER_KEY) === 'ortho' ? 'ortho' : 'map';
    } catch (e) {
        return 'map';
    }
}

function saveLayer(layer) {
    try {
        window.localStorage.setItem(LAYER_KEY, layer);
    } catch (e) {
        /* private mode: the choice is just not remembered */
    }
}

// MF-61: the outline's corners (only they, not the image) kept across a reload of the page, per level,
// for this tab only (sessionStorage): a page stuck waiting can be reloaded without tracing again.
const OUTLINE_KEY = 'atalaia.fieldmap.outline.';

function savedOutline(level) {
    try {
        const v = JSON.parse(window.sessionStorage.getItem(OUTLINE_KEY + level) || '[]');
        if (!Array.isArray(v) || v.length > CORNERS_MAX) return [];
        return v.every((p) => p && Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90
            && Math.abs(p.lon) <= 180) ? v.map((p) => ({ lat: p.lat, lon: p.lon })) : [];
    } catch (e) {
        return [];
    }
}

function saveOutline(level, outline) {
    try {
        if (outline.length) window.sessionStorage.setItem(OUTLINE_KEY + level, JSON.stringify(outline));
        else window.sessionStorage.removeItem(OUTLINE_KEY + level);
    } catch (e) {
        /* storage blocked: a reload just starts again */
    }
}

/** MF-63: tells the console's Field tab, once, that the field was loaded on this level. */
function markLoaded(level) {
    try {
        window.sessionStorage.setItem(LOADED_KEY, JSON.stringify({ level }));
        return true;
    } catch (e) {
        return false;
    }
}

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
            online: navigator.onLine !== false, finding: '', places: null, placeStatus: '',
            layer: savedLayer(), orthoHere: null, wait: null, osmTry: null, orthoName: '',
        };
        this.osmAbort = null;
        this.mapEl = createRef();
        this.map = null;
        this.search = new PlaceSearch();
        this.views = 0; // the map's moves: an automatic location does not override the GM's own
        this.searchSeq = 0;
        this.onLine = () => this.setState({ online: navigator.onLine !== false });
        // MF-60: closing the tab or reloading with a drawn image not yet used asks first (the browser's own
        // words: browsers no longer show a page's text there).
        this.onLeave = (e) => {
            if (!this.unsaved() || this.leaving) return;
            e.preventDefault();
            e.returnValue = '';
        };
    }

    async componentDidMount() {
        await loadLanguage();
        document.title = `Atalaia · ${t('fieldmap.title')}`;
        window.addEventListener('online', this.onLine);
        window.addEventListener('offline', this.onLine);
        window.addEventListener('beforeunload', this.onLeave);
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
        window.removeEventListener('beforeunload', this.onLeave);
        if (this.osmAbort) this.osmAbort.abort();
        if (this.map) this.map.destroy();
        if (this.state.result) URL.revokeObjectURL(this.state.result.url);
    }

    async startMap(token, level) {
        this.map = new TileMap(this.mapEl.current, {
            label: t('fieldmap.map_label'), source: OSM_SOURCE,
            onPress: (p) => this.addCorner(p),
            onView: (v) => {
                this.views += 1;
                this.showLayer(this.state.layer, sourceAt(v));
            },
        });
        this.showLayer(this.state.layer, sourceAt(this.map.centre));
        // MF-61: an outline traced before a reload comes back, and the map shows it.
        const kept = savedOutline(level);
        if (kept.length) {
            this.setOutline(kept);
            const lats = kept.map((p) => p.lat);
            const lons = kept.map((p) => p.lon);
            this.map.fit({ south: Math.min(...lats), north: Math.max(...lats), west: Math.min(...lons),
                           east: Math.max(...lons) }, FIELD_ZOOM);
            this.setState({ placeStatus: t('fieldmap.restored', { n: kept.length }) });
            return;
        }
        // Start where the level's plan already is on the map, if it is.
        try {
            const path = level === 0 ? '/field/georef' : `/field/levels/${level}/georef`;
            const geo = (await api(token, 'GET', path)).georef;
            if (geo && geo.corners) {
                const c = geo.corners;
                this.map.view({ lat: (c.top_left.lat + c.bottom_right.lat) / 2, lon: (c.top_left.lon + c.bottom_right.lon) / 2 },
                    FIELD_ZOOM);
                return;
            }
        } catch (e) {
            /* no map position: the GM's location if already allowed, else the default view (Portugal) */
        }
        // MF-42: without a map position, the GM's own location, but only if the browser already allows it
        // (no permission prompt the GM did not ask for).
        if (await locationGranted()) this.useLocation(true);
    }

    /** MF-41: one fix from the browser; the map moves there. The position stays in this browser. */
    async useLocation(auto = false) {
        if (this.state.finding) return;
        const views = this.views;
        // On open (auto) the page stays usable meanwhile: nothing is disabled and nothing is said yet.
        if (!auto) this.setState({ finding: 'locate', error: '', placeStatus: t('fieldmap.locating') });
        const done = auto ? {} : { finding: '' };
        try {
            const p = await locate();
            // On open, whatever the GM did meanwhile wins (moved the map, searched).
            if (!this.map || (auto && (this.views !== views || this.state.finding || this.state.places))) {
                if (!auto) this.setState({ ...done, placeStatus: '' });
                return;
            }
            this.map.view(p, Math.min(LOCATE_ZOOM, this.map.maxZoom));
            this.setState({ ...done, places: null, placeStatus: t('fieldmap.located', {
                m: Math.max(1, Math.round(p.accuracy || 0)) }) });
        } catch (e) {
            if (auto && (this.views !== views || this.state.finding || this.state.places)) return;
            const code = e instanceof SearchError ? e.code : 'unavailable';
            this.setState({ ...done, placeStatus: '', error: t(`fieldmap.locate_errors.${code}`) });
        }
    }

    /** MF-54, MF-55, MF-65: the map's tiles: the orthophoto of the map's centre (orthoHere, a row of
     * ortho-sources.js, or null) when chosen, else OpenStreetMap's (outside every coverage the switch is
     * hidden and the choice kept for when the map comes back). */
    showLayer(layer, orthoHere) {
        if (this.map) this.map.setSource(layer === 'ortho' && orthoHere ? tileSource(orthoHere) : OSM_SOURCE);
        if (layer !== this.state.layer || orthoHere !== this.state.orthoHere) this.setState({ layer, orthoHere });
    }

    chooseLayer(layer) {
        saveLayer(layer);
        this.showLayer(layer, this.state.orthoHere);
    }

    renderLayers() {
        const s = this.state;
        if (!s.orthoHere) {
            return html`<p class="muted small fm-layer-note" data-testid="fm-layer-none">${t('fieldmap.layer_none')}</p>`;
        }
        const option = (value, label) => html`<label class="fm-layer">
            <input type="radio" name="fm-layer" value=${value} data-testid=${`fm-layer-${value}`}
                checked=${s.layer === value} onChange=${() => this.chooseLayer(value)} />
            <span>${label}</span></label>`;
        return html`<div class="fm-layers" role="radiogroup" aria-labelledby="fm-layers-h" data-testid="fm-layers">
            <span id="fm-layers-h" class="small">${t('fieldmap.layer')}</span>
            ${option('map', t('fieldmap.layer_map'))}
            ${option('ortho', t('fieldmap.layer_ortho', { name: s.orthoHere.name }))}
        </div>`;
    }

    setOutline(outline) {
        saveOutline(this.state.level, outline);
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

    /** The search box: "latitude, longitude" goes straight there (no request); anything else is a place's
     * name for Nominatim, only now that the GM pressed Search (MF-44). */
    async goTo(e) {
        e.preventDefault();
        if (this.state.finding) return;
        const text = this.state.go.trim();
        const p = parseLatLon(text);
        if (p) {
            this.setState({ error: '', places: null, placeStatus: '' });
            this.map.view(p, FIELD_ZOOM);
            return;
        }
        if (!text) {
            this.setState({ error: t('fieldmap.place_errors.empty') });
            return;
        }
        const seq = ++this.searchSeq;
        this.setState({ finding: 'search', error: '', places: null, placeStatus: t('fieldmap.searching') });
        try {
            const places = await this.search.search(text, lang());
            if (seq !== this.searchSeq) return;
            this.setState({ finding: '', places, placeStatus: places.length
                ? t('fieldmap.found', { n: places.length }) : t('fieldmap.not_found', { q: text }) });
        } catch (err) {
            if (seq !== this.searchSeq) return;
            const code = err instanceof SearchError ? err.code : 'failed';
            this.setState({ finding: '', placeStatus: '',
                            error: t(`fieldmap.place_errors.${code}`, { detail: err.message }) });
        }
    }

    choosePlace(place) {
        if (place.bounds) {
            this.map.fit(place.bounds, FIELD_ZOOM);
        } else {
            this.map.view(place, FIELD_ZOOM);
        }
        this.setState({ places: null, error: '', placeStatus: t('fieldmap.showing', { name: place.name }) });
        // Keyboard users carry on on the map (the list they chose from is gone).
        const box = this.mapEl.current && this.mapEl.current.querySelector('.tm');
        if (box) box.focus();
    }

    renderPlaces() {
        const s = this.state;
        return html`${s.placeStatus && html`<p class="small" role="status" data-testid="fm-place-status">${s.placeStatus}</p>`}
            ${s.places && s.places.length > 0 && html`<ul class="fm-places" aria-label=${t('fieldmap.results')}
                data-testid="fm-places">
                ${s.places.map((p) => html`<li><button type="button" class="fm-place" data-testid="fm-place"
                    onClick=${() => this.choosePlace(p)}>${p.name}</button></li>`)}</ul>`}
            ${s.places && html`<p class="muted small" data-testid="fm-search-credit">${t('fieldmap.search_credit')}${' '}
                <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a></p>`}`;
    }

    /** MF-67: the orthophotos for the outline, best first (its centroid's country; empty when none). */
    orthoSources() {
        return sourcesFor(this.state.outline);
    }

    useOrtho() {
        if (!this.orthoSources().length) return false;
        return this.state.ortho !== null ? this.state.ortho : true;
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
            // MF-67: the outline's country's orthophoto; a white answer (no picture there: the coverage is
            // simplified) asks the next one near, if any, once.
            const sources = this.useOrtho() ? this.orthoSources().slice(0, 2) : [];
            this.setState({ busy: 'osm', wait: null, osmTry: null });
            this.osmAbort = new AbortController();
            let osm;
            try {
                osm = await fetchOsm(bounds, {
                    signal: this.osmAbort.signal,
                    onWait: (wait) => this.setState({ wait }),
                    onTry: (osmTry) => this.setState({ wait: null, osmTry }),
                });
            } finally {
                this.osmAbort = null;
            }
            const { elements } = osm;
            let photo = null;
            let used = null;
            let notice = osm.url === OVERPASS_URL ? '' : t('fieldmap.osm_from', { host: overpassHost(osm.url) });
            let failed = '';
            for (const source of sources) {
                this.setState({ busy: 'ortho', orthoName: source.name });
                try {
                    photo = await fetchOrthophoto(bounds, frame, source);
                } catch (e) {
                    failed = t('fieldmap.ortho_failed', { name: source.name, detail: this.mapError(e) });
                    break;
                }
                if (photo) {
                    used = source;
                    break;
                }
            }
            if (sources.length && !photo) {
                notice = `${notice} ${failed || t('fieldmap.no_ortho', { name: sources[0].name })}`.trim();
            }
            this.setState({ busy: 'draw' });
            const credit = used ? used.imageCredit : '';
            const canvas = drawField(elements, bounds, frame, photo, credit);
            const out = await encode(canvas, Boolean(photo));
            this.setState({ busy: '', notice, result: { ...out, url: URL.createObjectURL(out.blob), bounds,
                                                         photo: used ? used.name : '', credit: attribution(credit),
                                                         mpp: frame.mpp * (frame.width / out.width) } },
                          () => this.showPreview());
        } catch (e) {
            if (e instanceof MapError && e.code === 'cancelled') {
                this.setState({ busy: '', wait: null, notice: t('fieldmap.cancelled') });
            } else {
                this.setState({ busy: '', wait: null, error: this.mapError(e) });
            }
        }
    }

    changeLevel(level) {
        saveOutline(this.state.level, []);
        saveOutline(level, this.state.outline);
        this.setState({ level });
    }

    /** MF-59: the drawn image is easy to miss below the fold: bring it into view and put the keyboard (and
     * a screen reader) on its heading, from where *Use as the field* is the next button. */
    showPreview() {
        this.showHeading('fm-preview-h');
    }

    /** Scrolls a section (by its heading's id) into view and focuses the heading. */
    showHeading(id) {
        const h = document.getElementById(id);
        if (!h) return;
        const smooth = !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        h.closest('section').scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'auto' });
        h.focus({ preventScroll: true });
    }

    /** A drawn image that was not used yet (MF-60). */
    unsaved() {
        return Boolean(this.state.result) && !this.state.done;
    }

    /** MF-60: the back link asks before leaving a drawn image behind. */
    leave(e) {
        if (!this.unsaved()) return;
        if (window.confirm(t('fieldmap.leave_confirm'))) {
            this.leaving = true; // no second question from beforeunload
        } else {
            e.preventDefault();
        }
    }

    /** What the page is doing, for the status line beside *Draw* (MF-53: a wait says how long). */
    busyText() {
        const s = this.state;
        if (s.busy !== 'osm') return t(`fieldmap.busy.${s.busy}`, { name: s.orthoName });
        if (s.wait) return t('fieldmap.busy.osm_retry', { s: s.wait.seconds, host: s.wait.host });
        // MF-62: from the second try on, which try and where, and that the page is waiting for its answer.
        if (s.osmTry && s.osmTry.n > 0) {
            return t('fieldmap.busy.osm_from', { host: s.osmTry.host, n: s.osmTry.n + 1, max: RETRY.tries });
        }
        return t('fieldmap.busy.osm');
    }

    async upload() {
        const { result, outline, label, level } = this.state;
        this.setState({ busy: 'upload', error: '' });
        try {
            const body = { content_type: result.type, image: await base64(result.blob), bounds: result.bounds, outline,
                           label: label.trim() };
            const done = await api(savedToken(), 'POST', `/field/levels/${level}/from-map`, body);
            saveOutline(level, []);
            this.setState({ busy: '', done }, () => this.showHeading('fm-done-h'));
            if (this.map) this.map.setOutline([]);
            // MF-63: back to the console's Field tab at once, on the level just loaded, which says it was saved
            // (a one-time note for that tab, field-view.js); this page's *Field loaded* stays only if the note
            // cannot be kept (storage blocked), with its link back.
            if (markLoaded(level)) {
                this.leaving = true;
                window.location.assign('./#field');
            }
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
        return html`<section class="card fm-wide" aria-labelledby="fm-preview-h" data-testid="fm-preview">
            <h2 id="fm-preview-h" tabindex="-1">${t('fieldmap.preview')}</h2>
            <p class="small" data-testid="fm-preview-next">${t('fieldmap.preview_next')}</p>
            ${this.hasPlan() && html`<p class="warning small" data-testid="fm-replaces">${
                levelsInUse(this.state.levels) > 1
                    ? t('fieldmap.replaces_level', { name: levelName(this.state.levels, this.state.level) })
                    : t('fieldmap.replaces')}</p>`}
            <div class="actions">
                <button type="button" class="primary fm-use" data-testid="fm-upload" disabled=${Boolean(this.state.busy)}
                    onClick=${() => this.upload()}>${t('fieldmap.use')}</button>
                <button type="button" data-testid="fm-redraw" disabled=${Boolean(this.state.busy)}
                    onClick=${() => this.setState({ result: this.dropResult() })}>${t('fieldmap.change')}</button>
                ${this.state.busy === 'upload' && html`<span class="muted small" role="status">${t('fieldmap.busy.upload')}</span>`}
            </div>
            <div class="fm-preview">
                <img src=${r.url} alt=${t('fieldmap.preview_alt')} data-testid="fm-image" />
                <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                    <polygon class="fm-outline" points=${pts} vector-effect="non-scaling-stroke" /></svg>
            </div>
            <p class="muted small" data-testid="fm-size">${t('fieldmap.size', {
                width: r.width, height: r.height, mpp: r.mpp.toFixed(2), kb: Math.round(r.blob.size / 1024) })}
                ${' '}${t(r.photo ? 'fieldmap.source_both' : 'fieldmap.source_osm', { name: r.photo })}</p>
            <p class="muted small" data-testid="fm-image-credit">${t('fieldmap.image_credit', { credit: r.credit })}</p>
        </section>`;
    }

    renderDone() {
        return html`<section class="card" aria-labelledby="fm-done-h" data-testid="fm-done">
            <h2 id="fm-done-h" tabindex="-1">${t('fieldmap.done_title')}</h2>
            <p role="status">${t('fieldmap.done')}</p>
            <div class="actions"><a class="button primary" href="./#field" data-testid="fm-back-done">${t('fieldmap.back')}</a></div>
        </section>`;
    }

    renderOutline() {
        const s = this.state;
        const n = s.outline.length;
        const multi = s.levels && levelsInUse(s.levels) > 1;
        const ortho = this.orthoSources();
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
                        onChange=${(e) => this.changeLevel(Number(e.target.value))}>
                        ${Array.from({ length: levelsInUse(s.levels) }, (_, lv) => html`<option value=${lv}
                            selected=${lv === s.level}>${levelName(s.levels, lv)}</option>`)}
                    </select></div>`}
                <div class="field"><label for="fm-label">${t('fieldmap.label')}</label>
                    <input id="fm-label" data-testid="fm-label" maxlength="48" autocomplete="off" value=${s.label}
                        onInput=${(e) => this.setState({ label: e.target.value })} /></div>
            </div>
            ${ortho.length > 0 && html`<label class="check fm-ortho"><input type="checkbox" data-testid="fm-ortho"
                checked=${this.useOrtho()} onChange=${(e) => this.setState({ ortho: e.target.checked, result: this.dropResult() })} />
                ${t('fieldmap.ortho', { name: ortho[0].name })}</label>`}
            <div class="actions">
                <button type="button" class="primary" data-testid="fm-draw" disabled=${Boolean(s.busy) || n < 3}
                    onClick=${() => this.drawImage()}>${t('fieldmap.draw')}</button>
                ${s.busy === 'osm' && html`<button type="button" data-testid="fm-cancel"
                    onClick=${() => this.osmAbort && this.osmAbort.abort()}>${t('fieldmap.cancel')}</button>`}
                ${s.busy && html`<span class="muted small" role="status" data-testid="fm-busy">${this.busyText()}</span>`}
                ${!s.busy && s.result && html`<button type="button" data-testid="fm-show-preview"
                    onClick=${() => this.showPreview()}>${t('fieldmap.show_preview')}</button>`}
            </div>
        </section>`;
    }

    /** MF-59: at the top of the page, kept in view while scrolling: what is being done while busy (said
     * aloud by the status beside *Draw*, so hidden from screen readers here), then that the image is
     * ready and not yet used, with the way to it. */
    renderBanner() {
        const s = this.state;
        if (s.done || !(s.busy || s.result)) return null;
        if (s.busy) {
            return html`<div class="fm-banner" aria-hidden="true" data-testid="fm-banner">
                <span>${this.busyText()}</span></div>`;
        }
        return html`<div class="fm-banner fm-banner-ready" data-testid="fm-banner">
            <span>${t('fieldmap.ready')}</span>
            <button type="button" class="primary" data-testid="fm-banner-show"
                onClick=${() => this.showPreview()}>${t('fieldmap.show_preview')}</button></div>`;
    }

    render(props, s) {
        if (!s.ready) return html`<main class="content"><p class="muted">…</p></main>`;
        const header = html`<header class="top"><div class="brand"><strong>${t('fieldmap.title')}</strong></div>
            <div class="top-right"><a class="button fm-back" href="./#field" data-testid="fm-back" onClick=${(e) => this.leave(e)}>${t('fieldmap.back')}</a></div>
        </header>`;
        if (s.role !== 'gm') {
            return html`${header}<main class="content"><p class="error" data-testid="fm-login">${t('fieldmap.login')}</p></main>`;
        }
        return html`${header}<main class="content fm">
            ${this.renderBanner()}
            <section class="card fm-find-card" aria-labelledby="fm-h">
                <h1 id="fm-h" class="sr-only">${t('fieldmap.title')}</h1>
                <p>${t('fieldmap.intro')}</p>
                <p class="muted small">${t('fieldmap.sources')}</p>
                ${!s.online && html`<p class="warning" role="alert" data-testid="fm-offline">${t('fieldmap.offline')}</p>`}
                ${s.done ? null : html`<form class="form inline fm-find" novalidate role="search"
                    onSubmit=${(e) => this.goTo(e)}>
                    <label for="fm-go">${t('fieldmap.go')}</label>
                    <input id="fm-go" data-testid="fm-go" type="search" autocomplete="off" enterkeyhint="search"
                        placeholder=${t('fieldmap.go_placeholder')} aria-describedby="fm-search-note"
                        value=${s.go} onInput=${(e) => this.setState({ go: e.target.value })} />
                    <button type="submit" data-testid="fm-go-button" disabled=${Boolean(s.finding)}>${t('fieldmap.go_button')}</button>
                    <button type="button" data-testid="fm-locate" disabled=${Boolean(s.finding)}
                        onClick=${() => this.useLocation()}>${t('fieldmap.locate')}</button>
                </form>
                <p class="muted small" id="fm-search-note">${t('fieldmap.search_note')}</p>
                ${this.renderPlaces()}`}
                <p class="muted small" id="fm-map-help">${t('fieldmap.map_help')}</p>
                <${MapHost} hostRef=${this.mapEl} />
                <div class="actions fm-map-actions">
                    <button type="button" data-testid="fm-zoom-in" aria-label=${t('fieldmap.zoom_in')}
                        onClick=${() => this.map.zoomBy(1)}>+</button>
                    <button type="button" data-testid="fm-zoom-out" aria-label=${t('fieldmap.zoom_out')}
                        onClick=${() => this.map.zoomBy(-1)}>−</button>
                    ${this.renderLayers()}
                </div>
            </section>
            <div class="fm-side">
                ${s.error && html`<p class="error" role="alert" data-testid="fm-error">${s.error}</p>`}
                ${s.notice && html`<p class="notice" role="status" data-testid="fm-notice">${s.notice}</p>`}
                ${s.done ? this.renderDone() : this.renderOutline()}
            </div>
            ${!s.done && s.result && this.renderPreview()}
        </main>`;
    }
}

render(html`<${FieldMap} />`, document.getElementById('app'));
