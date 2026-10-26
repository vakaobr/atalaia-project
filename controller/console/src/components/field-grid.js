// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The field grid (decisions MF-81 to MF-93): the maintainer's milsim map grid over the field's plan,
// for calling positions on the radio ("C4"). Rows are letters from the top (A, B, ... Z, then AA, AB,
// ...), columns numbers from the left (1, 2, ...). Each level's plan has its own grid, kept by the
// controller (GET|PUT /api/v1/field/grid, .../levels/{n}/grid; field_grid.py) and set by the GM here
// or when loading the field from a map (field-map.js). It is drawn over the plan, never into the image,
// and divides the image's rectangle into equal cells (MF-84: image-aligned, so with a plan from a map,
// drawn north-up, the rows run east-west).
//
// GridLayer draws it: thin white lines on a dark halo and labels in white with a dark outline, which
// read on light and dark imagery; labels are thinned out when cells are too small for them. Any viewer
// may hide it in this browser (GridToggle, MF-89). gridCell and gridSpan name a place's cell or an
// area's cells (the map features' list, a box's label).

import { html, Component, createRef, t } from '../ui.js';

export const ROWS_MAX = 52; // field_grid.ROWS_MAX: A to AZ
export const COLS_MAX = 52;
export const GRID_OFF = { enabled: false, rows: 8, cols: 8 };
const SUGGESTED_ALONG = 8;  // MF-86: cells along the plan's longer side when the GM first turns it on
const HIDDEN_KEY = 'atalaia.fieldgrid.hidden'; // MF-89: this browser's viewer hid the grid
const LABEL_W = 20;         // px a column's number needs (two digits and their outline)
const LABEL_H = 15;         // px a row's letters need
const STEPS = [1, 2, 3, 4, 5, 10];

/** Row 0 is "A", 25 "Z", 26 "AA", 27 "AB", ... (as field_grid.row_label). */
export function rowLabel(row) {
    let out = '';
    let n = row + 1;
    while (n > 0) {
        const r = (n - 1) % 26;
        out = String.fromCharCode(65 + r) + out;
        n = Math.floor((n - 1) / 26);
    }
    return out;
}

/** The grid of a level from the levels' view (GET /field/levels), or the grid off. */
export function levelGrid(levels, level) {
    const lv = levels && levels.levels && levels.levels[level];
    return (lv && lv.grid) || GRID_OFF;
}

function index(v, n) {
    return Math.min(n - 1, Math.max(0, Math.floor(v * n)));
}

/** A place's cell ("C4"; x, y fractions of the plan; the far edges are in the last cell), or '' when the
 * grid is off or the place is not on the plan. As field_grid.cell. */
export function gridCell(grid, x, y) {
    if (!grid || !grid.enabled || !(x >= 0 && x <= 1 && y >= 0 && y <= 1)) return '';
    return `${rowLabel(index(y, grid.rows))}${index(x, grid.cols) + 1}`;
}

/** The cells an area's corners span: "C4" when one cell, else its top-left and bottom-right cells,
 * "B2–D5"; '' when the grid is off. */
export function gridSpan(grid, points) {
    const pts = (points || []).filter((p) => p && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1);
    if (!grid || !grid.enabled || !pts.length) return '';
    const xs = pts.map((p) => p.x);
    const ys = pts.map((p) => p.y);
    const a = gridCell(grid, Math.min(...xs), Math.min(...ys));
    const b = gridCell(grid, Math.max(...xs), Math.max(...ys));
    return a === b ? a : `${a}–${b}`;
}

/** MF-86: rows and columns with cells as near square as whole numbers allow, SUGGESTED_ALONG along the
 * longer side; ``aspect`` is the plan's width over its height (in metres when known). */
export function suggestGrid(aspect, along = SUGGESTED_ALONG) {
    const a = Number.isFinite(aspect) && aspect > 0 ? aspect : 1;
    if (a >= 1) return { rows: Math.min(ROWS_MAX, Math.max(1, Math.round(along / a))), cols: along };
    return { rows: along, cols: Math.min(COLS_MAX, Math.max(1, Math.round(along * a))) };
}

/** A cell's size on the ground, "50 × 48 m" (``scale``: the plan's {w, h} in metres), or ''. */
export function cellSize(grid, scale) {
    if (!grid || !scale) return '';
    const m = (v) => (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10);
    return `${m(scale.w / grid.cols)} × ${m(scale.h / grid.rows)} m`;
}

export function gridHidden() {
    try {
        return window.localStorage.getItem(HIDDEN_KEY) === '1';
    } catch (e) {
        return false;
    }
}

function saveHidden(hidden) {
    try {
        if (hidden) window.localStorage.setItem(HIDDEN_KEY, '1');
        else window.localStorage.removeItem(HIDDEN_KEY);
    } catch (e) {
        /* private mode: the choice is just not remembered */
    }
}

/** The fewest labels to skip so each has room: 1 (every one), 2, 3, ... */
function step(px, cells, need) {
    const cell = px / cells;
    return STEPS.find((s) => cell * s >= need) || Math.ceil(need / Math.max(cell, 0.1));
}

/** The grid over a plan: put it inside the plan's box (position: relative), above the image and the
 * features' shapes, under the pins and the boxes. Nothing when the grid is off. */
export class GridLayer extends Component {
    constructor() {
        super();
        this.state = { w: 0, h: 0 };
        this.el = createRef();
    }

    componentDidMount() {
        this.measure();
        if (typeof ResizeObserver === 'function') {
            this.observer = new ResizeObserver(() => this.measure());
            if (this.el.current) this.observer.observe(this.el.current);
            this.watched = this.el.current;
        }
    }

    componentDidUpdate() {
        if (this.observer && this.el.current && this.el.current !== this.watched) {
            this.observer.disconnect();
            this.observer.observe(this.el.current);
            this.watched = this.el.current;
        }
    }

    componentWillUnmount() {
        if (this.observer) this.observer.disconnect();
    }

    measure() {
        const el = this.el.current;
        if (!el) return;
        const w = el.clientWidth;
        const h = el.clientHeight;
        if (w !== this.state.w || h !== this.state.h) this.setState({ w, h });
    }

    render({ grid, testid = 'field-grid' }, { w, h }) {
        if (!grid || !grid.enabled) return null;
        const { rows, cols } = grid;
        const lines = [];
        for (let c = 1; c < cols; c += 1) lines.push(`M${(c * 100) / cols} 0V100`);
        for (let r = 1; r < rows; r += 1) lines.push(`M0 ${(r * 100) / rows}H100`);
        const d = lines.join('');
        const colStep = w ? step(w, cols, LABEL_W) : 1;
        const rowStep = h ? step(h, rows, LABEL_H) : 1;
        // Small cells put "A" and "1" in the same corner: the row's letter wins there, the numbers go on.
        const corner = w && h && w / cols / 2 < LABEL_W && h / rows / 2 < LABEL_H;
        const place = (x, y) => (el) => {
            if (!el) return;
            // Kept inside the plan: the last labels never cut by its right or bottom edge.
            if (x !== null) el.style.left = `min(${x.toFixed(3)}%, calc(100% - 0.8rem))`;
            if (y !== null) el.style.top = `min(${y.toFixed(3)}%, calc(100% - 0.5rem))`;
        };
        return html`<div class="fg-layer" ref=${this.el} aria-hidden="true" data-testid=${testid}
            data-rows=${rows} data-cols=${cols}>
            <svg class="fg-lines" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
                <path class="fg-halo" d=${d} vector-effect="non-scaling-stroke" />
                <path class="fg-line" d=${d} vector-effect="non-scaling-stroke" />
            </svg>
            ${Array.from({ length: cols }, (_, c) => (c % colStep || (c === 0 && corner) ? null : html`<span class="fg-label fg-col"
                data-col=${c + 1} ref=${place(((c + 0.5) * 100) / cols, null)}>${c + 1}</span>`))}
            ${Array.from({ length: rows }, (_, r) => (r % rowStep ? null : html`<span class="fg-label fg-row"
                data-row=${rowLabel(r)} ref=${place(null, ((r + 0.5) * 100) / rows)}>${rowLabel(r)}</span>`))}
        </div>`;
    }
}

/** Any viewer's switch (MF-89): show or hide the grid in this browser. Shown only when there is one. */
export class GridToggle extends Component {
    render({ grid, hidden, onChange }) {
        if (!grid || !grid.enabled) return null;
        return html`<label class="check fg-toggle" data-testid="grid-show-label"><input type="checkbox" data-testid="grid-show"
            checked=${!hidden} onChange=${(e) => {
                saveHidden(!e.target.checked);
                onChange(!e.target.checked);
            }} /> ${t('grid.show', { rows: `A–${rowLabel(grid.rows - 1)}`, cols: `1–${grid.cols}` })}</label>`;
    }
}

/** The GM's settings for the shown level's grid (MF-82, MF-86): on or off, rows and columns. */
export class GridSettings extends Component {
    constructor() {
        super();
        this.state = { rows: null, cols: null, error: '' };
    }

    componentDidUpdate(prev) {
        // Another level, or the grid changed elsewhere: the form shows the controller's values again.
        if (prev.level !== this.props.level || prev.grid !== this.props.grid) {
            if (this.state.rows !== null || this.state.cols !== null || this.state.error) {
                this.setState({ rows: null, cols: null, error: '' });
            }
        }
    }

    values() {
        const g = this.props.grid || GRID_OFF;
        return { rows: this.state.rows ?? g.rows, cols: this.state.cols ?? g.cols };
    }

    path() {
        const { level } = this.props;
        return level === 0 ? '/field/grid' : `/field/levels/${level}/grid`;
    }

    async put(body) {
        const out = await this.props.app.call('PUT', this.path(), body);
        if (out) {
            this.setState({ rows: null, cols: null, error: '' });
            this.props.onChange(out.grid);
        }
    }

    toggle(on) {
        const g = this.props.grid || GRID_OFF;
        // A grid never set (8 by 8, off) starts with cells about square for this plan (MF-86).
        const fresh = on && !g.enabled && g.rows === GRID_OFF.rows && g.cols === GRID_OFF.cols
            && this.state.rows === null && this.state.cols === null;
        this.put(fresh ? { enabled: true, ...suggestGrid(this.props.aspect) } : { enabled: on, ...this.values() });
    }

    number(v, top) {
        const n = Number(v);
        return Number.isInteger(n) && n >= 1 && n <= top ? n : null;
    }

    save(e) {
        e.preventDefault();
        const { rows, cols } = this.values();
        const r = this.number(rows, ROWS_MAX);
        const c = this.number(cols, COLS_MAX);
        if (r === null || c === null) {
            this.setState({ error: t('grid.bad', { rows: ROWS_MAX, cols: COLS_MAX }) });
            return;
        }
        this.put({ enabled: true, rows: r, cols: c });
    }

    /** Square cells: the columns kept on a wide plan (the rows on a tall one), the other count fitted. */
    square() {
        const a = Number.isFinite(this.props.aspect) && this.props.aspect > 0 ? this.props.aspect : 1;
        const { rows, cols } = this.values();
        const fit = (v, top) => Math.min(top, Math.max(1, Math.round(v)));
        if (a >= 1) {
            const c = this.number(cols, COLS_MAX) || GRID_OFF.cols;
            this.setState({ cols: c, rows: fit(c / a, ROWS_MAX), error: '' });
        } else {
            const r = this.number(rows, ROWS_MAX) || GRID_OFF.rows;
            this.setState({ rows: r, cols: fit(r * a, COLS_MAX), error: '' });
        }
    }

    render({ grid, scale }) {
        const g = grid || GRID_OFF;
        const { rows, cols } = this.values();
        const r = this.number(rows, ROWS_MAX);
        const c = this.number(cols, COLS_MAX);
        const size = r && c ? cellSize({ rows: r, cols: c }, scale) : '';
        return html`<div class="grid-settings" data-testid="grid-settings">
            <label class="check"><input type="checkbox" data-testid="grid-toggle" checked=${g.enabled}
                onChange=${(e) => this.toggle(e.target.checked)} /> ${t('grid.toggle')}</label>
            <p class="muted small">${t(g.enabled ? 'grid.hint_on' : 'grid.hint_off')}</p>
            ${g.enabled && html`<form class="form grid-form" novalidate data-testid="grid-form" onSubmit=${(e) => this.save(e)}>
                <div class="params">
                    <div class="field"><label for="grid-rows">${t('grid.rows', { max: ROWS_MAX })}</label>
                        <input id="grid-rows" data-testid="grid-rows" type="number" inputmode="numeric" min="1"
                            max=${ROWS_MAX} value=${rows} aria-describedby="grid-rows-note"
                            onInput=${(e) => this.setState({ rows: e.target.value, error: '' })} />
                        <span class="muted small" id="grid-rows-note">${r ? t('grid.rows_note', { last: rowLabel(r - 1) }) : ''}</span></div>
                    <div class="field"><label for="grid-cols">${t('grid.cols', { max: COLS_MAX })}</label>
                        <input id="grid-cols" data-testid="grid-cols" type="number" inputmode="numeric" min="1"
                            max=${COLS_MAX} value=${cols}
                            onInput=${(e) => this.setState({ cols: e.target.value, error: '' })} /></div>
                </div>
                ${size && html`<p class="muted small" data-testid="grid-size">${t('grid.size', { size })}</p>`}
                ${this.state.error && html`<p class="error" role="alert" data-testid="grid-error">${this.state.error}</p>`}
                <div class="actions">
                    <button type="submit" class="primary" data-testid="grid-save">${t('grid.save')}</button>
                    <button type="button" data-testid="grid-square" onClick=${() => this.square()}>${t('grid.square')}</button>
                </div>
            </form>`}
        </div>`;
    }
}
