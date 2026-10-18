// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Field view (ADR-P2-10): the field's own image (a photo, an aerial view or
// a floor plan the GM uploads) with a marker per box, dragged into place by
// the GM and kept by the controller (positions are fractions of the image).
// Without an image the markers sit on a plain grid. Works fully offline:
// no map tiles are fetched (OpenStreetMap is left for a later phase).

import { html, Component, createRef, t, teamColour, OFFLINE_MS } from '../ui.js';
import { linkBars } from './node-list.js';

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

export class FieldView extends Component {
    constructor() {
        super();
        this.state = { imageUrl: null, version: -1, drag: null, noImage: false };
        this.area = createRef();
    }

    componentDidMount() {
        this.loadImage();
    }

    componentDidUpdate() {
        const v = this.props.app.state.imageVersion || 0;
        if (v !== this.state.version) this.loadImage();
    }

    componentWillUnmount() {
        if (this.state.imageUrl) URL.revokeObjectURL(this.state.imageUrl);
    }

    async loadImage() {
        const app = this.props.app;
        const version = app.state.imageVersion || 0;
        this.setState({ version });
        let url = null;
        // Ask first, so a field without an image does not cost a 404.
        const info = await app.call('GET', '/field');
        if (info && info.image) {
            const blob = await app.call('GET', '/field/image');
            if (blob) url = URL.createObjectURL(blob);
        }
        if (this.state.imageUrl) URL.revokeObjectURL(this.state.imageUrl);
        this.setState({ imageUrl: url, noImage: !url });
    }

    async upload(e) {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        if (!IMAGE_TYPES.includes(file.type)) {
            this.props.app.showToast(t('field.bad_type'));
            return;
        }
        const out = await this.props.app.call('PUT', '/field/image', undefined, { type: file.type, data: file });
        if (out) this.loadImage();
    }

    async removeImage() {
        const out = await this.props.app.call('DELETE', '/field/image');
        if (out) this.loadImage();
    }

    where(node, index, count) {
        const p = this.props.app.state.positions[node.node_id];
        const drag = this.state.drag;
        if (drag && drag.id === node.node_id) return { x: drag.x, y: drag.y };
        if (p) return p;
        return { x: (index + 1) / (count + 1), y: 0.9 };
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

    async up() {
        const drag = this.state.drag;
        if (!drag) return;
        const { game } = this.props.app.state;
        const out = await this.props.app.call('PUT', `/games/${game.id}/positions/${drag.id}`,
                                              { x: drag.x, y: drag.y });
        if (out) this.props.app.setState((s) => ({ positions: { ...s.positions, [drag.id]: { x: out.x, y: out.y } } }));
        this.setState({ drag: null });
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

    render(props, state) {
        const app = props.app;
        const { nodes, game, role } = app.state;
        const list = Object.values(nodes).sort((a, b) => a.node_id - b.node_id);
        const teams = (game && game.teams) || [];
        return html`<section class="card" aria-labelledby="field-h">
            <h2 id="field-h">${t('field.title')}</h2>
            ${role === 'gm' && html`<div class="actions">
                <label class="button">${t('field.upload')}
                    <input type="file" class="sr-only" accept=${IMAGE_TYPES.join(',')} data-testid="field-upload"
                        onChange=${(e) => this.upload(e)} /></label>
                ${state.imageUrl && html`<button type="button" onClick=${() => this.removeImage()}>${t('field.remove')}</button>`}
            </div>`}
            <div class=${`field-area ${state.imageUrl ? 'with-image' : 'grid'}`} ref=${this.area} data-testid="field-area">
                ${state.imageUrl && html`<img src=${state.imageUrl} alt=${t('field.image_alt')} draggable="false" />`}
                ${list.map((n, i) => this.marker(n, i, list.length, teams))}
            </div>
            <p class="muted small">${state.noImage ? t('field.no_image') : ''} ${role === 'gm' && game ? t('field.drag_hint') : ''}</p>
            ${list.length === 0 && html`<p class="muted">${t('nodes.none')}</p>`}
        </section>`;
    }
}
