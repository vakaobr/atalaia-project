// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A small slippy map for finding the field (decision MF-21): OpenStreetMap's standard tiles
// (Web Mercator, 256 px), viewed interactively only, as OSM's tile usage policy allows: the
// tiles of the current view and nothing else (no prefetching, no offline copy), the browser's
// own cache, the attribution always visible, and the page's origin as the Referer the policy
// asks for (the console otherwise sends none). Hand-written rather than a vendored library
// (MF-21): panning by dragging or with the arrow keys, zooming with the wheel, + and - or the
// buttons, a press without a drag reports where it was (the GM's next corner), and an SVG
// layer draws the outline being traced. Nothing here is drawn into the field image: that is
// drawn from OpenStreetMap data (field-render.js).

export const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE = 256;
const ZOOM_MIN = 2;
const ZOOM_MAX = 19; // tile.openstreetmap.org's highest zoom
const MAX_LAT = 85.0511287798;
const SVG = 'http://www.w3.org/2000/svg';
const DRAG_PX = 5;   // a press that moves less than this is a press, not a pan
const KEY_PAN = 80;  // pixels per arrow key

/** Longitude and latitude to world pixels at zoom z (Web Mercator). */
export function project(lat, lon, z) {
    const size = TILE * 2 ** z;
    const phi = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
    return { x: ((lon + 180) / 360) * size, y: ((1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2) * size };
}

/** World pixels at zoom z to {lat, lon}. */
export function unproject(x, y, z) {
    const size = TILE * 2 ** z;
    const lon = (x / size) * 360 - 180;
    const n = Math.PI - (2 * Math.PI * y) / size;
    return { lat: (180 / Math.PI) * Math.atan(Math.sinh(n)), lon };
}

function el(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    return e;
}

export class TileMap {
    /** root: an empty element; opts: {label, attribution, onPress(latlon), onView({lat, lon, zoom})}. */
    constructor(root, opts) {
        this.root = root;
        this.opts = opts;
        this.centre = { lat: 39.6, lon: -8.0 };
        this.zoom = 6;
        this.tiles = new Map();
        this.outline = [];
        this.box = el('div', 'tm');
        this.box.tabIndex = 0;
        this.box.setAttribute('role', 'application');
        this.box.setAttribute('aria-label', opts.label);
        this.box.setAttribute('data-testid', 'tm');
        this.layer = el('div', 'tm-tiles');
        this.svg = document.createElementNS(SVG, 'svg');
        this.svg.setAttribute('class', 'tm-outline');
        this.svg.setAttribute('aria-hidden', 'true');
        this.svg.setAttribute('data-testid', 'tm-outline');
        const cross = el('span', 'tm-cross');
        cross.setAttribute('aria-hidden', 'true');
        const credit = el('div', 'tm-credit');
        const link = el('a');
        link.href = 'https://www.openstreetmap.org/copyright';
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = opts.attribution;
        credit.append(link);
        this.box.append(this.layer, this.svg, cross, credit);
        root.append(this.box);
        this.press = null;
        this.box.addEventListener('pointerdown', (e) => this.down(e));
        this.box.addEventListener('pointermove', (e) => this.move(e));
        this.box.addEventListener('pointerup', (e) => this.up(e));
        this.box.addEventListener('pointercancel', () => { this.press = null; });
        this.box.addEventListener('wheel', (e) => this.wheel(e), { passive: false });
        this.box.addEventListener('keydown', (e) => this.key(e));
        this.resize = () => this.draw();
        window.addEventListener('resize', this.resize);
        this.draw();
    }

    destroy() {
        window.removeEventListener('resize', this.resize);
        this.root.textContent = '';
    }

    size() {
        return { w: this.box.clientWidth || 300, h: this.box.clientHeight || 300 };
    }

    /** The world pixel at the view's top-left corner. */
    origin() {
        const c = project(this.centre.lat, this.centre.lon, this.zoom);
        const { w, h } = this.size();
        return { x: c.x - w / 2, y: c.y - h / 2 };
    }

    /** {lat, lon} at a point of the map (pixels from its top-left corner). */
    at(px, py) {
        const o = this.origin();
        return unproject(o.x + px, o.y + py, this.zoom);
    }

    /** Where {lat, lon} is on the map, in pixels from its top-left corner. */
    where(p) {
        const o = this.origin();
        const w = project(p.lat, p.lon, this.zoom);
        return { x: w.x - o.x, y: w.y - o.y };
    }

    view(centre, zoom = this.zoom) {
        this.centre = { lat: Math.max(-MAX_LAT, Math.min(MAX_LAT, centre.lat)), lon: ((centre.lon + 540) % 360) - 180 };
        this.zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(zoom)));
        this.draw();
        if (this.opts.onView) this.opts.onView({ ...this.centre, zoom: this.zoom });
    }

    zoomBy(step, px, py) {
        const z = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, this.zoom + step));
        if (z === this.zoom) return;
        const { w, h } = this.size();
        // Keep the point under the cursor (or the centre) where it is.
        const ax = px === undefined ? w / 2 : px;
        const ay = py === undefined ? h / 2 : py;
        const anchor = this.at(ax, ay);
        const a = project(anchor.lat, anchor.lon, z);
        this.view(unproject(a.x - ax + w / 2, a.y - ay + h / 2, z), z);
    }

    panBy(dx, dy) {
        const c = project(this.centre.lat, this.centre.lon, this.zoom);
        this.view(unproject(c.x + dx, c.y + dy, this.zoom));
    }

    setOutline(points) {
        this.outline = points;
        this.drawOutline();
    }

    point(e) {
        const r = this.box.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    down(e) {
        if (e.button !== undefined && e.button !== 0) return;
        this.press = { ...this.point(e), moved: false, centre: project(this.centre.lat, this.centre.lon, this.zoom) };
        this.box.setPointerCapture(e.pointerId);
    }

    move(e) {
        const p = this.press;
        if (!p) return;
        const q = this.point(e);
        if (!p.moved && Math.hypot(q.x - p.x, q.y - p.y) < DRAG_PX) return;
        p.moved = true;
        this.centre = unproject(p.centre.x - (q.x - p.x), p.centre.y - (q.y - p.y), this.zoom);
        this.draw();
    }

    up(e) {
        const p = this.press;
        this.press = null;
        if (!p) return;
        if (p.moved) {
            this.view(this.centre);
        } else if (this.opts.onPress) {
            const q = this.point(e);
            this.opts.onPress(this.at(q.x, q.y));
        }
    }

    wheel(e) {
        e.preventDefault();
        const q = this.point(e);
        this.zoomBy(e.deltaY < 0 ? 1 : -1, q.x, q.y);
    }

    key(e) {
        const moves = { ArrowLeft: [-KEY_PAN, 0], ArrowRight: [KEY_PAN, 0], ArrowUp: [0, -KEY_PAN], ArrowDown: [0, KEY_PAN] };
        if (moves[e.key]) {
            this.panBy(...moves[e.key]);
        } else if (e.key === '+' || e.key === '=') {
            this.zoomBy(1);
        } else if (e.key === '-' || e.key === '_') {
            this.zoomBy(-1);
        } else {
            return;
        }
        e.preventDefault();
    }

    draw() {
        const { w, h } = this.size();
        const o = this.origin();
        const z = this.zoom;
        const n = 2 ** z;
        const want = new Set();
        const y0 = Math.max(0, Math.floor(o.y / TILE));
        const y1 = Math.min(n - 1, Math.floor((o.y + h) / TILE));
        for (let ty = y0; ty <= y1; ty += 1) {
            for (let tx = Math.floor(o.x / TILE); tx <= Math.floor((o.x + w) / TILE); tx += 1) {
                const wx = ((tx % n) + n) % n;
                const key = `${z}/${wx}/${ty}/${tx}`;
                want.add(key);
                let img = this.tiles.get(key);
                if (!img) {
                    img = el('img', 'tm-tile');
                    img.alt = '';
                    img.draggable = false;
                    img.decoding = 'async';
                    img.referrerPolicy = 'strict-origin-when-cross-origin'; // the Referer OSM's policy asks for
                    img.src = TILE_URL.replace('{z}', z).replace('{x}', wx).replace('{y}', ty);
                    this.tiles.set(key, img);
                    this.layer.append(img);
                }
                img.style.left = `${Math.round(tx * TILE - o.x)}px`;
                img.style.top = `${Math.round(ty * TILE - o.y)}px`;
            }
        }
        for (const [key, img] of this.tiles) {
            if (!want.has(key)) {
                img.remove();
                this.tiles.delete(key);
            }
        }
        this.drawOutline();
    }

    drawOutline() {
        const { w, h } = this.size();
        this.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
        this.svg.textContent = '';
        const pts = this.outline.map((p) => this.where(p));
        if (pts.length >= 2) {
            const shape = document.createElementNS(SVG, pts.length >= 3 ? 'polygon' : 'polyline');
            shape.setAttribute('points', pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '));
            shape.setAttribute('class', 'tm-shape');
            this.svg.append(shape);
        }
        pts.forEach((p, i) => {
            const c = document.createElementNS(SVG, 'circle');
            c.setAttribute('cx', p.x.toFixed(1));
            c.setAttribute('cy', p.y.toFixed(1));
            c.setAttribute('r', '6');
            c.setAttribute('class', 'tm-corner');
            const label = document.createElementNS(SVG, 'text');
            label.setAttribute('x', (p.x + 9).toFixed(1));
            label.setAttribute('y', (p.y - 9).toFixed(1));
            label.setAttribute('class', 'tm-corner-n');
            label.textContent = String(i + 1);
            this.svg.append(c, label);
        });
    }
}
