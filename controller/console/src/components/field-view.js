// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Field view (ADR-P2-10): the field's own image (a photo, an aerial view or
// a floor plan the GM uploads) with a marker per box, dragged into place by
// the GM and kept by the controller (positions are fractions of the image).
// Without an image the markers sit on a plain grid. Works fully offline:
// no map tiles are fetched (OpenStreetMap is left for a later phase).
// Below it, with an image, its place on the map for the ATAK feed
// (georef-panel.js), with a pin on the image per control point.
//
// A multi-story field (field-levels.js, decisions ML-0 to ML-12) has a tab per
// level, each with its own floor plan and the boxes on that level; the GM
// moves a box to another level with the level list under the plan.

import { html, Component, createRef, t, teamColour, OFFLINE_MS } from '../ui.js';
import { linkBars } from './node-list.js';
import { GeorefPanel, georefPins } from './georef-panel.js';
import { LevelSettings, LevelTabs, levelName, levelsInUse, shownLevel } from './field-levels.js';

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const NO_LEVELS = { enabled: false, count: 1, names: [''], levels: [] };

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
            noImage: false, levels: NO_LEVELS, level: 0,
        };
        this.area = createRef();
        this.loads = 0;
    }

    componentDidMount() {
        this.loadImage();
    }

    componentDidUpdate() {
        const v = this.props.app.state.imageVersion || 0;
        if (v !== this.state.version) this.loadImage();
        else if ((this.props.app.state.georefVersion || 0) !== this.state.geoVersion) this.loadGeoref();
    }

    componentWillUnmount() {
        if (this.state.imageUrl) URL.revokeObjectURL(this.state.imageUrl);
    }

    async loadImage(level = this.state.level) {
        const app = this.props.app;
        const version = app.state.imageVersion || 0;
        this.loads += 1;
        const mine = this.loads;
        this.setState({ version });
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
        this.setState({ imageUrl: url, noImage: !url, levels, level: shown });
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
        this.setState({ level });
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

    canEdit() {
        const { role, game } = this.props.app.state;
        return role === 'gm' && game;
    }

    marker(node, i, count, teams) {
        const { seen, now } = this.props.app.state;
        const p = this.where(node, i, count);
        const offline = seen[node.node_id] !== undefined && now - seen[node.node_id] > OFFLINE_MS;
        const label = t('field.marker', { node: node.node_id, owner: node.owner || t('nodes.no_owner') });
        return html`<button type="button" class=${`marker ${offline ? 'offline' : ''}`} aria-label=${label}
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
        return html`<section class="card" aria-labelledby="field-h">
            <h2 id="field-h">${t('field.title')}</h2>
            ${role === 'gm' && html`<${LevelSettings} app=${app} levels=${state.levels}
                onChange=${() => this.loadImage()} />`}
            <${LevelTabs} levels=${state.levels} current=${state.level} onSelect=${(lv) => this.selectLevel(lv)} />
            <div id="field-level-panel" role=${multi ? 'tabpanel' : undefined}
                aria-labelledby=${multi ? `level-tab-${state.level}` : undefined}>
            ${role === 'gm' && html`<div class="actions">
                <label class="button">${multi ? t('levels.upload', { name }) : t('field.upload')}
                    <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid="field-upload"
                        onChange=${(e) => this.upload(e)} /></label>
                ${state.imageUrl && html`<button type="button" data-testid="field-remove"
                    onClick=${() => this.removeImage()}>${multi ? t('levels.remove') : t('field.remove')}</button>`}
            </div>`}
            <div class=${`field-area ${state.imageUrl ? 'with-image' : 'grid'}`} ref=${this.area} data-testid="field-area"
                data-level=${state.level}>
                ${state.imageUrl && html`<img src=${state.imageUrl} draggable="false"
                    alt=${multi ? t('levels.image_alt', { name }) : t('field.image_alt')} />`}
                ${state.imageUrl && georefPins(state.georef)}
                ${here.map((n) => this.marker(n, list.indexOf(n), list.length, teams))}
            </div>
            <p class="muted small">${state.noImage ? t(multi ? 'levels.no_image' : 'field.no_image', { name }) : ''}
                ${' '}${role === 'gm' && game ? t('field.drag_hint') : ''}</p>
            ${list.length === 0 && html`<p class="muted">${t('nodes.none')}</p>`}
            ${this.renderNodeLevels(list)}
            </div>
        </section>
        ${state.imageUrl && html`<${GeorefPanel} app=${app} georef=${state.georef} level=${state.level}
            own=${state.ownGeoref} levelName=${multi ? name : null} groundName=${levelName(state.levels, 0)}
            onChange=${() => this.loadGeoref()} />`}`;
    }
}
