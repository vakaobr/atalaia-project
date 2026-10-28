// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Field view (ADR-P2-10): the field's own image (a photo, an aerial view or
// a floor plan the GM uploads) with a marker per box, dragged into place by
// the GM and kept by the controller (positions are fractions of the image).
// Without an image the markers sit on a plain grid. Works fully offline:
// no map tiles are fetched here.
// Below it, with an image, its place on the map for the ATAK feed
// (georef-panel.js), with a pin on the image per control point.
//
// A multi-story field (field-levels.js, decisions ML-0 to ML-12) has a tab per
// level, each with its own floor plan and the boxes on that level; the GM
// moves a box to another level with the level list under the plan.
//
// Map features (map-features.js, decisions MF-0 to MF-16): safe zones, respawns, HQs, the car
// park, first aid and objectives on the shown level's plan, under the boxes, with their editor
// below the plan. While the GM places one, a press on the plan places it (the boxes and pins
// let the press through).
//
// *Load the field from a map* (field-map.js, decisions MF-19 to MF-30) is its own page, the only one
// of the console allowed to reach the internet; it comes back here (#field) when done.
//
// Indoor BLE beacons (beacons-panel.js, decisions BLE-1 to BLE-9): the GM's registry of the beacons
// in the building, with a pin on the shown level's plan for each one placed, and their editor below.
//
// The field grid (field-grid.js, decisions MF-81 to MF-93): lettered rows and numbered columns over
// the shown level's plan, set by the GM under the plan; any viewer may hide it in this browser.

import { html, Component, createRef, t, teamColour, OFFLINE_MS } from '../ui.js';
import { linkBars } from './node-list.js';
import { GeorefPanel, georefPins } from './georef-panel.js';
import { LevelSettings, LevelTabs, levelName, levelsInUse, shownLevel, takeLoaded } from './field-levels.js';
import { MapFeatures, featureName, featurePins, featureShapes, planScale } from './map-features.js';
import { BeaconPanel, beaconPins } from './beacons-panel.js';
import { GridLayer, GridPrint, GridSettings, GridToggle, cellSize, gridCell, gridHidden, gridSpan, levelGrid } from './field-grid.js';

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const NO_LEVELS = { enabled: false, count: 1, names: [''], levels: [] };
const DEFAULT_TEAMS = ['red', 'blue'];
const POLYGON_MAX = 12; // map_features.POLYGON_MAX

/** The API path of a level's plan or georeference (level 0: the paths of a single image). */
function levelPath(level, what) {
    if (level === 0) return what === 'image' ? '/field/image' : '/field/georef';
    return `/field/levels/${level}/${what}`;
}

export class FieldView extends Component {
    constructor() {
        super();
        this.state = {
            imageUrl: null, version: -1, geoVersion: -1, georef: null, ownGeoref: true, drag: null,
            noImage: false, levels: NO_LEVELS, level: 0, draft: null, loadedNote: false,
            gridVersion: 0, gridHidden: gridHidden(), imageAspect: null, beaconDraft: null,
        };
        // MF-63: back from *Load the field from a map* after saving: that level, and a note saying so.
        this.loaded = takeLoaded();
        if (this.loaded !== null) this.state.level = this.loaded;
        this.radiusDrag = false;
        this.area = createRef();
        this.loads = 0;
    }

    componentDidMount() {
        this.loadImage();
        // The note goes into a status region already on the page, so screen readers announce it.
        if (this.loaded !== null) this.noteTimer = setTimeout(() => this.setState({ loadedNote: true }), 150);
    }

    componentDidUpdate() {
        const v = this.props.app.state.imageVersion || 0;
        if (v !== this.state.version) this.loadImage();
        else if ((this.props.app.state.georefVersion || 0) !== this.state.geoVersion) this.loadGeoref();
        else if ((this.props.app.state.gridVersion || 0) !== this.state.gridVersion) this.loadGrids();
    }

    /** MF-87: a grid changed (the stream's field_grid): the levels again, which carry each level's grid. */
    async loadGrids() {
        const app = this.props.app;
        this.setState({ gridVersion: app.state.gridVersion || 0 });
        const levels = await app.call('GET', '/field/levels');
        if (levels) this.setState({ levels });
    }

    /** The GM saved the shown level's grid: shown at once (the stream's message follows). */
    setGrid(level, grid) {
        const levels = this.state.levels;
        const list = (levels.levels || []).map((lv) => (lv.level === level ? { ...lv, grid } : lv));
        this.setState({ levels: { ...levels, levels: list } });
    }

    componentWillUnmount() {
        clearTimeout(this.noteTimer);
        if (this.state.imageUrl) URL.revokeObjectURL(this.state.imageUrl);
    }

    async loadImage(level = this.state.level) {
        const app = this.props.app;
        const version = app.state.imageVersion || 0;
        this.loads += 1;
        const mine = this.loads;
        const gridVersion = app.state.gridVersion || 0;
        this.setState({ version, gridVersion });
        let url = null;
        // Ask first, so a field without an image does not cost a 404.
        const info = await app.call('GET', '/field');
        const levels = (info && info.levels) || NO_LEVELS;
        const shown = level < levelsInUse(levels) ? level : 0;
        const has = shown === 0 ? info && info.image : (levels.levels[shown] || {}).image;
        if (has) {
            const blob = await app.call('GET', levelPath(shown, 'image'));
            if (blob) url = URL.createObjectURL(blob);
        }
        if (mine !== this.loads) {
            if (url) URL.revokeObjectURL(url); // a later load (another tab) won
            return;
        }
        if (this.state.imageUrl) URL.revokeObjectURL(this.state.imageUrl);
        this.setState({ imageUrl: url, noImage: !url, levels, level: shown, imageAspect: null });
        // A grid changed while this load ran: its levels may be older than that (MF-87).
        if ((app.state.gridVersion || 0) !== gridVersion) this.loadGrids();
        if (url) this.loadGeoref(shown);
        else this.setState({ georef: null, geoVersion: app.state.georefVersion || 0 });
    }

    async loadGeoref(level = this.state.level) {
        const app = this.props.app;
        this.setState({ geoVersion: app.state.georefVersion || 0 });
        const out = await app.call('GET', levelPath(level, 'georef'));
        if (out && level === this.state.level) this.setState({ georef: out.georef, ownGeoref: out.own !== false });
    }

    selectLevel(level) {
        if (level === this.state.level) return;
        this.setState({ level, draft: null, beaconDraft: null });
        this.loadImage(level);
    }

    async upload(e) {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        if (!IMAGE_TYPES.includes(file.type)) {
            this.props.app.showToast(t('field.bad_type'));
            return;
        }
        const out = await this.props.app.call('PUT', levelPath(this.state.level, 'image'), undefined,
                                              { type: file.type, data: file });
        if (out) this.loadImage();
    }

    async removeImage() {
        const out = await this.props.app.call('DELETE', levelPath(this.state.level, 'image'));
        if (out) this.loadImage();
    }

    where(node, index, count) {
        const p = this.props.app.state.positions[node.node_id];
        const drag = this.state.drag;
        if (drag && drag.id === node.node_id) return { x: drag.x, y: drag.y };
        if (p) return p;
        return { x: (index + 1) / (count + 1), y: 0.9 };
    }

    /** The level a box is shown on: its position's, else level 0. */
    nodeLevel(node) {
        const p = this.props.app.state.positions[node.node_id];
        return shownLevel(this.state.levels, p ? p.level : 0);
    }

    point(e) {
        const r = this.area.current.getBoundingClientRect();
        const clamp = (v) => Math.min(1, Math.max(0, v));
        return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) };
    }

    down(e, node) {
        if (!this.canEdit()) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        this.setState({ drag: { id: node.node_id, ...this.point(e) } });
    }

    move(e) {
        if (!this.state.drag) return;
        this.setState({ drag: { ...this.state.drag, ...this.point(e) } });
    }

    async place(id, body) {
        const { game } = this.props.app.state;
        const out = await this.props.app.call('PUT', `/games/${game.id}/positions/${id}`, body);
        if (out) {
            this.props.app.setState((s) => ({
                positions: { ...s.positions, [id]: { x: out.x, y: out.y, level: out.level } },
            }));
        }
    }

    async up() {
        const drag = this.state.drag;
        if (!drag) return;
        // On a level's plan the box goes to that level; with levels off it keeps the one it has (ML-3).
        const body = { x: drag.x, y: drag.y };
        if (levelsInUse(this.state.levels) > 1) body.level = this.state.level;
        await this.place(drag.id, body);
        this.setState({ drag: null });
    }

    /** Moves a box to another level, at the same place on the plan. */
    toLevel(node, index, count, level) {
        const p = this.where(node, index, count);
        this.place(node.node_id, { x: p.x, y: p.y, level });
    }

    // ---- map features: placing the draft on the plan ----

    /** A place for the draft: a pin's or a circle's centre, or an area's next corner. */
    placeDraft(p) {
        const d = this.state.draft;
        if (!d) return;
        if (d.shape === 'polygon') {
            if (d.points.length < POLYGON_MAX) this.setState({ draft: { ...d, points: [...d.points, p] } });
        } else {
            this.setState({ draft: { ...d, x: p.x, y: p.y } });
        }
    }

    /** BLE-7: the beacon being edited as the GM has it; a press on the plan places it while she places it. */
    setBeaconDraft(beaconDraft) {
        // One thing is placed at a time: placing a beacon leaves any map feature's place aside.
        this.setState({ beaconDraft, ...(beaconDraft && beaconDraft.placing ? { draft: null } : {}) });
    }

    placeBeacon(p) {
        const b = this.state.beaconDraft;
        if (b) this.setState({ beaconDraft: { ...b, x: p.x, y: p.y } });
    }

    shownBeacons() {
        const b = this.state.beaconDraft;
        const list = (this.props.app.state.beacons || []).filter((x) => !(b && b.id === x.id));
        return b && b.level === this.state.level ? [...list, b] : list;
    }

    editBeacon(b) {
        if (this.props.app.state.role !== 'gm') return;
        this.setState({ beaconDraft: { ...b, draft: true, placing: false, x: b.x ?? null, y: b.y ?? null }, draft: null });
    }

    areaDown(e) {
        const bd = this.state.beaconDraft;
        if (bd && bd.placing && this.props.app.state.role === 'gm') {
            e.preventDefault();
            this.placeBeacon(this.point(e));
            return;
        }
        const d = this.state.draft;
        if (!d || !d.placing || this.props.app.state.role !== 'gm') return;
        e.preventDefault();
        this.placeDraft(this.point(e));
        if (d.shape === 'circle' && planScale(this.state.georef)) {
            // Press at the centre and drag to the edge: the radius, to the plan's scale.
            this.radiusDrag = true;
            e.currentTarget.setPointerCapture(e.pointerId);
        }
    }

    areaMove(e) {
        const d = this.state.draft;
        const scale = planScale(this.state.georef);
        if (!this.radiusDrag || !d || !scale) return;
        const p = this.point(e);
        const r = Math.hypot((p.x - d.x) * scale.w, (p.y - d.y) * scale.h);
        this.setState({ draft: { ...d, radius_m: Math.min(2000, Math.max(1, Math.round(r))) } });
    }

    areaUp() {
        this.radiusDrag = false;
    }

    /** The features shown on this level's plan: the stored ones, the one being edited as the GM has it. */
    shownFeatures() {
        const d = this.state.draft;
        const list = (this.props.app.state.mapFeatures || []).filter((f) => f.level === this.state.level
            && !(d && d.id === f.id));
        return d && d.level === this.state.level ? [...list, d] : list;
    }

    editFeature(f) {
        if (this.props.app.state.role !== 'gm') return;
        this.setState({ draft: { ...f, draft: true, points: f.points ? [...f.points] : [], x: f.x ?? null,
                                 y: f.y ?? null, radius_m: f.radius_m ?? 25, placing: false } });
    }

    setDraft(draft) {
        this.setState({ draft, ...(draft && draft.placing ? { beaconDraft: null } : {}) });
        if (draft === null) this.props.app.loadFeatures();
    }

    canEdit() {
        const { role, game } = this.props.app.state;
        return role === 'gm' && game;
    }

    /** The box Progressive Domination has active now (decision PD-MODE-15): the feed's newest
     * progressive.activated, unless that box was completed since; its name, else null. */
    activeBox() {
        for (const e of this.props.app.state.feed || []) {
            if (e.type === 'progressive.completed') return null;
            if (e.type === 'progressive.activated') return (e.data && e.data.zone) || null;
        }
        return null;
    }

    marker(node, i, count, teams, grid) {
        const { seen, now } = this.props.app.state;
        const p = this.where(node, i, count);
        const offline = seen[node.node_id] !== undefined && now - seen[node.node_id] > OFFLINE_MS;
        const active = node.name !== undefined && node.name === this.activeBox();
        // MF-90: with a grid, the box's cell too ("Box 7, owner: red, grid C4").
        const cell = gridCell(grid, p.x, p.y);
        const label = t(active ? 'field.marker_active' : 'field.marker',
                        { node: node.node_id, owner: node.owner || t('nodes.no_owner') })
            + (cell ? `, ${t('grid.cell', { cell })}` : '');
        return html`<button type="button" class=${`marker ${offline ? 'offline' : ''} ${active ? 'active' : ''}`} aria-label=${label}
            data-node=${node.node_id} title=${label}
            ref=${(el) => {
                if (!el) return;
                el.style.left = `${(p.x * 100).toFixed(2)}%`;
                el.style.top = `${(p.y * 100).toFixed(2)}%`;
                el.style.background = node.owner ? teamColour(node.owner, teams) : '';
            }}
            onPointerDown=${(e) => this.down(e, node)} onPointerMove=${(e) => this.move(e)}
            onPointerUp=${() => this.up()} onPointerCancel=${() => this.setState({ drag: null })}>
            <span class="marker-id">${node.node_id}</span>
            <span class="marker-info">${node.battery_pct === null || node.battery_pct === undefined ? '' : `${node.battery_pct}%`}
                <span class=${`bars bars-${linkBars(node.rssi)}`} aria-hidden="true"></span></span>
        </button>`;
    }

    /** What the printed grid map lists (PKE-2): each box placed on this level's plan and each map feature on it,
     * with its cell ("C4"; an area's span "B2–D5"). A box not placed has no cell and is not listed. */
    printEntries(here, features, grid) {
        const { positions } = this.props.app.state;
        const boxes = here.filter((n) => positions[n.node_id]).map((n) => ({
            label: t('field.marker', { node: n.node_id, owner: n.owner || t('nodes.no_owner') }),
            where: gridCell(grid, positions[n.node_id].x, positions[n.node_id].y) }));
        const marks = features.filter((f) => !f.draft).map((f) => ({
            label: `${featureName(f)}${f.team ? ` (${f.team})` : ''}`,
            where: f.shape === 'polygon' ? gridSpan(grid, f.points) : (typeof f.x === 'number' ? gridCell(grid, f.x, f.y) : '') }));
        return [...boxes, ...marks].filter((e) => e.where);
    }

    /** The plan as the sheet draws it: the image, the features, the pins and the boxes, not interactive. */
    printLayers(here, features, featureTeams, teams, list, scale) {
        const { imageUrl } = this.state;
        return html`${imageUrl && html`<img src=${imageUrl} alt="" />`}${featureShapes(features, featureTeams, scale)}
            ${featurePins(features, featureTeams, () => {})}
            ${here.map((n) => html`<span class="marker gp-marker" ref=${(el) => {
        if (!el) return;
        const p = this.where(n, list.indexOf(n), list.length);
        el.style.left = `${(p.x * 100).toFixed(2)}%`;
        el.style.top = `${(p.y * 100).toFixed(2)}%`;
        el.style.background = n.owner ? teamColour(n.owner, teams) : '';
    }}>${n.node_id}</span>`)}`;
    }

    /** Each box's level, changeable by the GM (the keyboard's way to move a box between levels). */
    renderNodeLevels(list) {
        const { levels } = this.state;
        const count = levelsInUse(levels);
        if (count < 2 || list.length === 0) return null;
        const edit = this.canEdit();
        return html`<details class="node-levels" data-testid="node-levels">
            <summary>${t('levels.boxes')}</summary>
            <ul>${list.map((n, i) => {
                const id = `node-level-${n.node_id}`;
                const at = this.nodeLevel(n);
                return html`<li><label for=${id}>${t('levels.box', { node: n.node_id })}</label>
                    ${edit ? html`<select id=${id} data-testid=${id} value=${at}
                        onChange=${(e) => this.toLevel(n, i, list.length, Number(e.target.value))}>
                        ${Array.from({ length: count }, (_, lv) => html`<option value=${lv} selected=${lv === at}>${
                            levelName(levels, lv)}</option>`)}
                    </select>` : html`<span id=${id} data-testid=${id}>${levelName(levels, at)}</span>`}</li>`;
            })}</ul>
        </details>`;
    }

    render(props, state) {
        const app = props.app;
        const { nodes, game, role } = app.state;
        const list = Object.values(nodes).sort((a, b) => a.node_id - b.node_id);
        const teams = (game && game.teams) || [];
        const multi = levelsInUse(state.levels) > 1;
        const here = list.filter((n) => this.nodeLevel(n) === state.level);
        const name = levelName(state.levels, state.level);
        const featureTeams = teams.length ? teams : DEFAULT_TEAMS;
        const features = this.shownFeatures();
        const scale = planScale(state.georef);
        const placing = (state.draft && state.draft.placing) || (state.beaconDraft && state.beaconDraft.placing);
        const grid = levelGrid(state.levels, state.level);
        const showGrid = grid.enabled && !state.gridHidden;
        // The plan's shape for square cells (MF-86): on the ground when it has a map position, else the
        // image's, else the placeholder's 3:2.
        const aspect = scale ? scale.w / scale.h : state.imageAspect || 1.5;
        return html`<section class="card" aria-labelledby="field-h">
            <h2 id="field-h">${t('field.title')}</h2>
            ${this.loaded !== null && html`<p class=${state.loadedNote ? 'notice' : ''} role="status"
                data-testid="field-loaded">${state.loadedNote ? (multi ? t('fieldmap.loaded_level', { name })
                    : t('fieldmap.loaded')) : ''}</p>`}
            ${role === 'gm' && html`<${LevelSettings} app=${app} levels=${state.levels}
                onChange=${() => this.loadImage()} />`}
            <${LevelTabs} levels=${state.levels} current=${state.level} onSelect=${(lv) => this.selectLevel(lv)} />
            <div id="field-level-panel" role=${multi ? 'tabpanel' : undefined}
                aria-labelledby=${multi ? `level-tab-${state.level}` : undefined}>
            ${role === 'gm' && html`<div class="actions">
                <label class="button">${multi ? t('levels.upload', { name }) : t('field.upload')}
                    <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid="field-upload"
                        onChange=${(e) => this.upload(e)} /></label>
                <a class="button" href=${`field-map.html?level=${state.level}`} data-testid="field-from-map">${
                    t('fieldmap.open')}</a>
                ${state.imageUrl && html`<button type="button" data-testid="field-remove"
                    onClick=${() => this.removeImage()}>${multi ? t('levels.remove') : t('field.remove')}</button>`}
            </div>`}
            <div class=${`field-area ${state.imageUrl ? 'with-image' : 'grid'}${placing ? ' placing' : ''}${
                showGrid ? ' with-field-grid' : ''}`} ref=${this.area}
                data-testid="field-area" data-level=${state.level}
                onPointerDown=${(e) => this.areaDown(e)} onPointerMove=${(e) => this.areaMove(e)}
                onPointerUp=${() => this.areaUp()} onPointerCancel=${() => this.areaUp()}>
                ${state.imageUrl && html`<img src=${state.imageUrl} draggable="false"
                    alt=${multi ? t('levels.image_alt', { name }) : t('field.image_alt')}
                    onLoad=${(e) => this.setState({ imageAspect: e.target.naturalWidth / e.target.naturalHeight || null })} />`}
                ${state.imageUrl && georefPins(state.georef)}
                ${featureShapes(features, featureTeams, scale)}
                ${showGrid && html`<${GridLayer} grid=${grid} />`}
                ${featurePins(features, featureTeams, (f) => this.editFeature(f))}
                ${beaconPins(this.shownBeacons(), state.level, (b) => this.editBeacon(b))}
                ${here.map((n) => this.marker(n, list.indexOf(n), list.length, teams, grid))}
            </div>
            <${GridToggle} grid=${grid} hidden=${state.gridHidden} onChange=${(h) => this.setState({ gridHidden: h })} />
            ${state.imageUrl && html`<${GridPrint} grid=${grid} title=${printTitle(app.state.branding)}
                levelName=${multi ? name : ''} size=${cellSize(grid, scale)}
                entries=${this.printEntries(here, features, grid)}
                layers=${() => this.printLayers(here, features, featureTeams, teams, list, scale)} />`}
            <p class="muted small">${state.noImage ? t(multi ? 'levels.no_image' : 'field.no_image', { name }) : ''}
                ${' '}${role === 'gm' && game ? t('field.drag_hint') : ''}</p>
            ${list.length === 0 && html`<p class="muted">${t('nodes.none')}</p>`}
            ${this.renderNodeLevels(list)}
            ${role === 'gm' && html`<${GridSettings} app=${app} level=${state.level} grid=${grid} aspect=${aspect}
                scale=${scale} onChange=${(g) => this.setGrid(state.level, g)} />`}
            </div>
        </section>
        <${MapFeatures} app=${app} features=${app.state.mapFeatures || []} level=${state.level} teams=${featureTeams}
            canEdit=${role === 'gm'} draft=${state.draft} scale=${scale} grid=${grid}
            onDraft=${(d) => this.setDraft(d)} onPlace=${(p) => this.placeDraft(p)} />
        ${role === 'gm' && app.serves('positions') && html`<${BeaconPanel} app=${app} beacons=${app.state.beacons || []}
            levels=${state.levels} level=${state.level} canEdit=${true} draft=${state.beaconDraft}
            onDraft=${(d) => this.setBeaconDraft(d)} onPlace=${(p) => this.placeBeacon(p)} />`}
        ${state.imageUrl && html`<${GeorefPanel} app=${app} georef=${state.georef} level=${state.level}
            own=${state.ownGeoref} levelName=${multi ? name : null} groundName=${levelName(state.levels, 0)}
            onChange=${() => this.loadGeoref()} />`}`;
    }
}

/** The field's name for the printed grid map: the branding's, else the product's. */
function printTitle(branding) {
    return (branding && branding.field_name) || 'Atalaia';
}
