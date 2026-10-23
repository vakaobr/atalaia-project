// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Draws the field image in the GM's browser (decisions MF-22 to MF-25), once, while the game is set up:
//
// - the area: the outline's bounding box and a margin (10 %, at least 20 m), at most AREA_MAX_M on a side;
// - in Portugal (or when the GM ticks it), the DGT's orthophoto as the base, from its open WMS
//   (OrtoSat 2023, 30 cm; EPSG:4326, so the picture is already in the image's frame), fetched with
//   fetch() so the canvas can still be exported (the WMS sends Access-Control-Allow-Origin: *);
//   a white picture (outside its coverage, e.g. in Spain) is dropped and OpenStreetMap drawn alone;
// - OpenStreetMap's data for the area from the Overpass API, one query with a size cap (MF-50 to MF-53:
//   when the main instance is busy, retried with exponential backoff and jitter, and asked of one other
//   public instance, within about a minute, cancellable), drawn on a canvas: woods, scrub, grass, farmland, water, bare ground, buildings, fences, walls and hedges,
//   streams, roads, tracks and paths, and names; over the orthophoto only the lines, the buildings'
//   outlines and the names, so the photo stays readable;
// - the attribution burned into the bottom-right corner ("© OpenStreetMap contributors" and, with the
//   orthophoto, "Ortofotomapas © DGT (CC BY 4.0)").
//
// The frame is north-up with latitude linear down the image and longitude linear across it (an
// equirectangular frame over the area): exactly the controller's two-corner map position (georef.py),
// so the map position set from the image's edges is exact; the pixels are square on the ground at the
// area's middle latitude (off by under 0.05 % at its top and bottom edges for an area of 4 km).

export const OVERPASS_URL = 'https://overpass-api.de/api/interpreter';
// MF-50, MF-51: the public Overpass instances asked, in this order, when the one before is busy or
// unreachable (from the OSM wiki's list of public instances with no key and no stated limit for this use;
// VK's instance in Russia was left out until the maintainer chooses, MF-51).
export const OVERPASS_URLS = [OVERPASS_URL, 'https://overpass.private.coffee/api/interpreter'];
// MF-50: how hard the page tries before saying the service is busy.
export const RETRY = { tries: 6, budgetMs: 60000, baseMs: 2000, capMs: 16000, refusedMs: 30000, requestMs: 35000 };
export const WMS_URL = 'https://ortos.dgterritorio.gov.pt/wms/ortosat2023';
export const WMS_LAYER = 'ortoSat2023-CorVerdadeira';
// The orthophoto's coverage as its WMS capabilities give it (mainland Portugal, a little of Spain too).
export const PT_BOUNDS = { south: 36.7643, north: 42.2796, west: -10.1934, east: -5.70954 };
export const ATTRIBUTION_OSM = '© OpenStreetMap contributors';
export const ATTRIBUTION_DGT = 'Ortofotomapas © DGT (CC BY 4.0)';
export const AREA_MAX_M = 4000;           // the outline's box, on its longer side
export const SIDE_MAX_PX = 4096;          // the image's longer side (also the WMS's MaxWidth/MaxHeight)
export const METRES_PER_PX = 0.5;         // the finest the image is drawn at
export const IMAGE_MAX = 4 * 1024 * 1024; // the controller's field image limit (store.FIELD_IMAGE_MAX)
const OVERPASS_MAX_BYTES = 32 * 1024 * 1024;
const OVERPASS_TIMEOUT_S = 25;
const MARGIN = 0.1;
const MARGIN_MIN_M = 20;
const EARTH_RADIUS_M = 6371000;
const DEG = Math.PI / 180;

/** Raised with a code the page turns into words (fieldmap.errors.<code>). */
export class MapError extends Error {
    constructor(code, detail) {
        super(detail || code);
        this.code = code;
    }
}

function metresPerDegree(lat) {
    const ns = EARTH_RADIUS_M * DEG;
    return { ns, ew: ns * Math.cos(lat * DEG) };
}

/** The image's edges for an outline ([{lat, lon}]): its box and a margin; throws MapError('too_big'). */
export function areaFor(outline) {
    const lats = outline.map((p) => p.lat);
    const lons = outline.map((p) => p.lon);
    let south = Math.min(...lats);
    let north = Math.max(...lats);
    let west = Math.min(...lons);
    let east = Math.max(...lons);
    const k = metresPerDegree((south + north) / 2);
    const h = (north - south) * k.ns;
    const w = (east - west) * k.ew;
    if (Math.max(w, h) > AREA_MAX_M) throw new MapError('too_big', `${Math.round(Math.max(w, h))} m`);
    const mh = Math.max(MARGIN * h, MARGIN_MIN_M) / k.ns;
    const mw = Math.max(MARGIN * w, MARGIN_MIN_M) / k.ew;
    south -= mh;
    north += mh;
    west -= mw;
    east += mw;
    const r = (v) => Math.round(v * 1e7) / 1e7;
    return { north: r(north), south: r(south), west: r(west), east: r(east) };
}

/** The image's size in pixels for its edges: METRES_PER_PX, or coarser to fit SIDE_MAX_PX. */
export function frameFor(b) {
    const k = metresPerDegree((b.north + b.south) / 2);
    const w = (b.east - b.west) * k.ew;
    const h = (b.north - b.south) * k.ns;
    const mpp = Math.max(METRES_PER_PX, Math.max(w, h) / SIDE_MAX_PX);
    return { width: Math.max(1, Math.round(w / mpp)), height: Math.max(1, Math.round(h / mpp)), mpp };
}

/** Whether the area is inside the orthophoto's coverage box (the GM may still untick it). */
export function inPortugal(b) {
    return b.south >= PT_BOUNDS.south && b.north <= PT_BOUNDS.north && b.west >= PT_BOUNDS.west
        && b.east <= PT_BOUNDS.east;
}

/** The Overpass QL query: one request for everything drawn, capped in time and size. */
export function overpassQuery(b) {
    const box = `${b.south},${b.west},${b.north},${b.east}`;
    return `[out:json][timeout:${OVERPASS_TIMEOUT_S}][maxsize:${OVERPASS_MAX_BYTES}][bbox:${box}];`
        + '(way[highway];way[building];relation[building];way[natural];relation[natural];way[landuse];'
        + 'relation[landuse];way[leisure];way[waterway];way[barrier];node[name];);out geom;';
}

/** An Overpass answer that says "busy, ask again later" (or no answer at all): worth retrying. */
class Busy extends Error {
    constructor(code, detail, wait = 0) {
        super(detail || code);
        this.code = code; // 'busy', or 'unreachable' (no answer the page can read)
        this.wait = wait; // at least this long before asking that instance again (a refusal: 429)
    }
}

/** The host of an instance's URL, as the page names it ("overpass-api.de"). */
export function overpassHost(url) {
    return new URL(url).host;
}

/** A pause of ms that says how many seconds are left, once a second (tick(s)); a cancel ends it. */
function pause(ms, signal, tick) {
    return new Promise((resolve, reject) => {
        const end = Date.now() + ms;
        let timer = null;
        const abort = () => {
            clearTimeout(timer);
            reject(new MapError('cancelled'));
        };
        const step = () => {
            const left = end - Date.now();
            if (left <= 0) {
                if (signal) signal.removeEventListener('abort', abort);
                resolve();
                return;
            }
            tick(Math.ceil(left / 1000));
            timer = setTimeout(step, Math.min(left, ((left - 1) % 1000) + 1));
        };
        if (signal) {
            if (signal.aborted) {
                reject(new MapError('cancelled'));
                return;
            }
            signal.addEventListener('abort', abort, { once: true });
        }
        step();
    });
}

/** One question to one instance: the elements, or Busy (retry), or MapError (stop). */
async function askOverpass(url, query, fetcher, signal) {
    // Each request has its own time limit (the query's own is 25 s), and the GM's cancel ends it too.
    const ctl = new AbortController();
    const cancel = () => ctl.abort();
    if (signal) signal.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(() => ctl.abort(), RETRY.requestMs);
    let r;
    let data;
    try {
        try {
            r = await fetcher(url, { method: 'POST', body: new URLSearchParams({ data: query }),
                                     referrerPolicy: 'no-referrer', signal: ctl.signal });
        } catch (e) {
            if (signal && signal.aborted) throw new MapError('cancelled');
            if (navigator.onLine === false) throw new MapError('offline');
            // MF-52: no answer the page may read: the server is down, the request timed out, or an error
            // answer without Access-Control-Allow-Origin (the browser then reports a network error, not
            // the 502): busy or unreachable, and worth asking again.
            throw new Busy('unreachable', e && e.name === 'AbortError' ? 'timeout' : 'network');
        }
        if ([429, 502, 503, 504].includes(r.status)) {
            const after = Number(r.headers.get('retry-after'));
            throw new Busy('busy', `HTTP ${r.status}`,
                           Math.max(r.status === 429 ? RETRY.refusedMs : 0, after > 0 ? after * 1000 : 0));
        }
        if (!r.ok) throw new MapError('osm_failed', `HTTP ${r.status}`);
        try {
            data = await r.json();
        } catch (e) {
            if (signal && signal.aborted) throw new MapError('cancelled');
            if (e && e.name === 'AbortError') throw new Busy('unreachable', 'timeout');
            throw new MapError('osm_failed', 'not JSON');
        }
    } finally {
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', cancel);
    }
    const remark = String(data.remark || '');
    if (/maxsize|out of memory/i.test(remark)) throw new MapError('too_much');
    // "runtime error: Query timed out ...", "... rate_limited", "... too busy": the server's load, not the area.
    if (/timed out|timeout|rate_limited|too busy|capacity/i.test(remark)) throw new Busy('busy', remark);
    if (!Array.isArray(data.elements)) throw new MapError('osm_failed', remark);
    return data.elements;
}

/** OSM data for the area from the Overpass API: {elements, url} (the instance that answered).
 *
 * MF-50 to MF-52: one POST to the main instance; when it is busy (429, 502, 503, 504, a busy or timeout
 * remark) or does not answer, the page asks again, each instance at most every so often: after a busy
 * answer an instance rests a backoff that doubles with each try (RETRY.baseMs, up to RETRY.capMs), with
 * jitter (a random half of it, so many pages do not come back together), at least 30 s after a 429 (the
 * main instance's own rule) or its Retry-After; meanwhile the next instance in OVERPASS_URLS that is
 * free is asked. At most RETRY.tries requests and RETRY.budgetMs in all; opts.onWait({seconds, host})
 * says each second of a wait, opts.onTry({host, n}) each request; opts.signal cancels. */
export async function fetchOsm(b, opts = {}) {
    const { fetcher = fetch, signal = null, onWait = () => {}, onTry = () => {}, urls = OVERPASS_URLS,
            random = Math.random } = typeof opts === 'function' ? { fetcher: opts } : opts;
    const query = overpassQuery(b);
    const start = Date.now();
    const free = urls.map(() => 0); // when each instance may be asked again
    let last = null;
    let busy = false; // an instance answered "busy" (else none could be reached)
    for (let n = 0; n < RETRY.tries; n += 1) {
        let i = 0;
        for (let k = 1; k < urls.length; k += 1) if (free[k] < free[i]) i = k; // the soonest free, in order
        const wait = Math.max(0, free[i] - Date.now());
        if (n > 0 && Date.now() + wait - start > RETRY.budgetMs) break;
        const host = overpassHost(urls[i]);
        if (wait > 0) await pause(wait, signal, (seconds) => onWait({ seconds, host }));
        if (signal && signal.aborted) throw new MapError('cancelled');
        onTry({ host, n });
        try {
            return { elements: await askOverpass(urls[i], query, fetcher, signal), url: urls[i] };
        } catch (e) {
            if (!(e instanceof Busy)) throw e;
            last = e;
            busy = busy || e.code === 'busy';
            const backoff = Math.min(RETRY.capMs, RETRY.baseMs * 2 ** n);
            free[i] = Date.now() + Math.max(e.wait, backoff / 2 + random() * (backoff / 2));
        }
    }
    throw new MapError(busy ? 'busy' : 'unreachable', last ? last.message : '');
}

/** The DGT orthophoto for the area at the image's size, as an ImageBitmap, or null where it has no
 * picture (all white: outside its coverage). */
export async function fetchOrthophoto(b, frame, fetcher = fetch) {
    const q = new URLSearchParams({ SERVICE: 'WMS', VERSION: '1.3.0', REQUEST: 'GetMap', LAYERS: WMS_LAYER,
                                    STYLES: '', CRS: 'EPSG:4326', BBOX: `${b.south},${b.west},${b.north},${b.east}`,
                                    WIDTH: String(frame.width), HEIGHT: String(frame.height), FORMAT: 'image/jpeg' });
    let r;
    try {
        r = await fetcher(`${WMS_URL}?${q}`, { referrerPolicy: 'no-referrer' });
    } catch (e) {
        throw new MapError('offline');
    }
    if (!r.ok || !(r.headers.get('content-type') || '').startsWith('image/')) {
        throw new MapError('ortho_failed', `HTTP ${r.status}`);
    }
    const bitmap = await createImageBitmap(await r.blob());
    return mostlyWhite(bitmap) ? null : bitmap;
}

/** MF-54: one 256-pixel tile (z/x/y, Web Mercator, as OpenStreetMap's) of the DGT orthophoto for the
 * map's *Ortofoto* layer: a WMS GetMap of exactly that tile's box in EPSG:3857 (which the WMS offers), so
 * it lies on the map like any tile; JPEG, the same URL for the same tile (the browser's cache). */
export function orthoTileUrl(z, x, y) {
    const half = 20037508.342789244; // half the Web Mercator world, in metres
    const side = (2 * half) / 2 ** z;
    const r = (v) => (Math.round(v * 100) / 100).toFixed(2);
    const box = [-half + x * side, half - (y + 1) * side, -half + (x + 1) * side, half - y * side].map(r);
    const q = new URLSearchParams({ SERVICE: 'WMS', VERSION: '1.3.0', REQUEST: 'GetMap', LAYERS: WMS_LAYER,
                                    STYLES: '', CRS: 'EPSG:3857', BBOX: box.join(','), WIDTH: '256', HEIGHT: '256',
                                    FORMAT: 'image/jpeg' });
    return `${WMS_URL}?${q}`;
}

function mostlyWhite(bitmap) {
    const c = document.createElement('canvas');
    c.width = 64;
    c.height = 64;
    const g = c.getContext('2d');
    g.drawImage(bitmap, 0, 0, 64, 64);
    const d = g.getImageData(0, 0, 64, 64).data;
    let white = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 245 && d[i + 1] > 245 && d[i + 2] > 245) white += 1;
    return white > 0.9 * 64 * 64;
}

// ---- drawing OSM data ----

const AREAS = [ // [test, style key], first match wins; drawn in this order
    [(t) => t.landuse === 'farmland' || t.landuse === 'orchard' || t.landuse === 'vineyard', 'farmland'],
    [(t) => ['grass', 'meadow', 'recreation_ground', 'village_green'].includes(t.landuse)
        || t.natural === 'grassland' || ['park', 'pitch', 'garden'].includes(t.leisure), 'grass'],
    [(t) => ['residential', 'industrial', 'commercial', 'farmyard', 'retail'].includes(t.landuse), 'built'],
    [(t) => ['bare_rock', 'sand', 'scree', 'shingle'].includes(t.natural) || t.landuse === 'quarry', 'bare'],
    [(t) => t.natural === 'scrub' || t.natural === 'heath', 'scrub'],
    [(t) => t.natural === 'wood' || t.landuse === 'forest', 'wood'],
    [(t) => t.natural === 'wetland', 'wetland'],
    [(t) => t.natural === 'water' || ['reservoir', 'basin'].includes(t.landuse) || t.waterway === 'riverbank', 'water'],
    [(t) => t.building !== undefined && t.building !== 'no', 'building'],
];
const AREA_FILL = { farmland: '#eef0d5', grass: '#cdebb0', built: '#e0dfdf', bare: '#e5ddd5', scrub: '#c8d7ab',
                    wood: '#9dca8a', wetland: '#d6e8d4', water: '#aad3df', building: '#d9d0c9' };
const ROAD_MAJOR = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'motorway_link', 'trunk_link',
                    'primary_link', 'secondary_link', 'tertiary_link'];
const ROAD_MINOR = ['residential', 'unclassified', 'service', 'living_street', 'road', 'pedestrian'];
const PATHS = ['path', 'footway', 'bridleway', 'cycleway', 'steps'];
// Line styles: width in metres (with a floor in pixels), colour, dash (in widths), casing colour.
const LINES = {
    major: { m: 8, min: 3, colour: '#f7d26a', casing: '#8a6d1c' },
    minor: { m: 5, min: 2.5, colour: '#ffffff', casing: '#9a9a9a' },
    track: { m: 2.5, min: 2, colour: '#a0642c', dash: [3, 2] },
    path: { m: 1.2, min: 1.5, colour: '#d2453a', dash: [2, 2] },
    river: { m: 6, min: 2, colour: '#6fa8dc' },
    stream: { m: 2, min: 1.5, colour: '#6fa8dc' },
    ditch: { m: 1, min: 1, colour: '#8fbfe6' },
    fence: { m: 0.6, min: 1, colour: '#5a5a5a' },
    wall: { m: 1, min: 1.5, colour: '#3f3f3f' },
    hedge: { m: 1.5, min: 1.5, colour: '#5f8f35' },
};
// Over the orthophoto: brighter lines with a dark edge, no area fills (MF-23).
const OVER_PHOTO = { major: '#ffd54f', minor: '#ffffff', track: '#ffcc80', path: '#ff8a80', river: '#81d4fa',
                     stream: '#81d4fa', ditch: '#81d4fa', fence: '#eeeeee', wall: '#ffffff', hedge: '#c5e1a5' };

function lineKind(t) {
    if (t.highway) {
        if (ROAD_MAJOR.includes(t.highway)) return 'major';
        if (ROAD_MINOR.includes(t.highway)) return 'minor';
        if (t.highway === 'track') return 'track';
        if (PATHS.includes(t.highway)) return 'path';
        return null;
    }
    if (t.waterway === 'river' || t.waterway === 'canal') return 'river';
    if (t.waterway === 'stream') return 'stream';
    if (t.waterway === 'ditch' || t.waterway === 'drain') return 'ditch';
    if (['fence', 'guard_rail'].includes(t.barrier)) return 'fence';
    if (['wall', 'retaining_wall', 'city_wall'].includes(t.barrier)) return 'wall';
    if (t.barrier === 'hedge') return 'hedge';
    if (t.natural === 'tree_row') return 'hedge';
    return null;
}

function areaKind(t) {
    for (const [test, key] of AREAS) if (test(t)) return key;
    return null;
}

/** Rings of an element as arrays of {lat, lon}: a closed way's one, a multipolygon's members. */
function rings(e) {
    if (e.type === 'way' && Array.isArray(e.geometry)) return [e.geometry];
    if (e.type === 'relation' && Array.isArray(e.members)) {
        return e.members.filter((m) => m.type === 'way' && Array.isArray(m.geometry)).map((m) => m.geometry);
    }
    return [];
}

function closed(g) {
    return g.length >= 4 && g[0].lat === g[g.length - 1].lat && g[0].lon === g[g.length - 1].lon;
}

/** Draws the field image on a canvas: {canvas, orthophoto: whether it is the base}. */
export function drawField(elements, b, frame, photo) {
    const canvas = document.createElement('canvas');
    canvas.width = frame.width;
    canvas.height = frame.height;
    const g = canvas.getContext('2d');
    const px = (p) => [((p.lon - b.west) / (b.east - b.west)) * frame.width,
                       ((b.north - p.lat) / (b.north - b.south)) * frame.height];
    const trace = (pts) => {
        pts.forEach((p, i) => {
            const [x, y] = px(p);
            if (i) g.lineTo(x, y);
            else g.moveTo(x, y);
        });
    };
    const mpp = frame.mpp;
    if (photo) {
        g.drawImage(photo, 0, 0, frame.width, frame.height);
    } else {
        g.fillStyle = '#f2efe9';
        g.fillRect(0, 0, frame.width, frame.height);
    }
    // Areas: filled on the plain map; over the photo only the buildings, outlined.
    const areas = [];
    for (const e of elements) {
        const tags = e.tags || {};
        const kind = areaKind(tags);
        if (!kind) continue;
        const rs = rings(e).filter((r) => e.type === 'relation' || closed(r));
        if (rs.length) areas.push({ kind, rs, e });
    }
    const order = AREAS.map(([, k]) => k);
    areas.sort((a, z) => order.indexOf(a.kind) - order.indexOf(z.kind));
    for (const a of areas) {
        if (photo && a.kind !== 'building' && a.kind !== 'water') continue;
        g.beginPath();
        a.rs.forEach((r) => { trace(r); g.closePath(); });
        if (photo) {
            g.lineWidth = Math.max(1.5, 0.6 / mpp);
            g.strokeStyle = a.kind === 'water' ? OVER_PHOTO.river : '#ffb74d';
            g.stroke();
        } else {
            g.fillStyle = AREA_FILL[a.kind];
            g.fill('evenodd');
            if (a.kind === 'building') {
                g.lineWidth = Math.max(1, 0.3 / mpp);
                g.strokeStyle = '#b5a99e';
                g.stroke();
            }
        }
    }
    // Lines: the casing first, then the line.
    const lines = [];
    for (const e of elements) {
        if (e.type !== 'way' || !Array.isArray(e.geometry)) continue;
        const kind = lineKind(e.tags || {});
        if (kind) lines.push({ kind, e });
    }
    const lineOrder = ['ditch', 'stream', 'river', 'hedge', 'fence', 'wall', 'path', 'track', 'minor', 'major'];
    lines.sort((a, z) => lineOrder.indexOf(a.kind) - lineOrder.indexOf(z.kind));
    g.lineCap = 'round';
    g.lineJoin = 'round';
    for (const pass of ['casing', 'line']) {
        for (const { kind, e } of lines) {
            const s = LINES[kind];
            const width = Math.max(s.min, s.m / mpp);
            const casing = photo ? '#202020' : s.casing;
            if (pass === 'casing' && !casing) continue;
            g.beginPath();
            trace(e.geometry);
            g.setLineDash(pass === 'line' && s.dash ? s.dash.map((d) => d * width) : []);
            g.lineWidth = pass === 'casing' ? width + Math.max(1.5, width * 0.4) : width;
            g.strokeStyle = pass === 'casing' ? casing : photo ? OVER_PHOTO[kind] : s.colour;
            g.stroke();
        }
    }
    g.setLineDash([]);
    drawNames(g, elements, px, frame, photo);
    drawAttribution(g, frame, photo);
    return canvas;
}

function drawNames(g, elements, px, frame, photo) {
    const size = Math.max(13, Math.round(Math.min(frame.width, frame.height) / 70));
    g.font = `600 ${size}px system-ui, sans-serif`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.lineJoin = 'round';
    const put = (text, x, y, angle = 0) => {
        if (x < 0 || y < 0 || x > frame.width || y > frame.height) return;
        g.save();
        g.translate(x, y);
        g.rotate(angle);
        g.lineWidth = Math.max(3, size / 4);
        g.strokeStyle = photo ? 'rgba(0,0,0,0.85)' : 'rgba(255,255,255,0.9)';
        g.strokeText(text, 0, 0);
        g.fillStyle = photo ? '#ffffff' : '#222222';
        g.fillText(text, 0, 0);
        g.restore();
    };
    const seen = new Set();
    for (const e of elements) {
        const name = e.tags && e.tags.name;
        if (!name) continue;
        if (e.type === 'node' && typeof e.lat === 'number') {
            const [x, y] = px(e);
            put(name, x, y);
        } else if (e.type === 'way' && Array.isArray(e.geometry) && e.geometry.length >= 2 && (e.tags || {}).highway) {
            if (seen.has(name)) continue; // a road's name once
            seen.add(name);
            let best = null;
            for (let i = 1; i < e.geometry.length; i += 1) {
                const [x1, y1] = px(e.geometry[i - 1]);
                const [x2, y2] = px(e.geometry[i]);
                const len = Math.hypot(x2 - x1, y2 - y1);
                if (!best || len > best.len) best = { len, x: (x1 + x2) / 2, y: (y1 + y2) / 2, a: Math.atan2(y2 - y1, x2 - x1) };
            }
            if (best && best.len > g.measureText(name).width) {
                let a = best.a;
                if (a > Math.PI / 2) a -= Math.PI;
                if (a < -Math.PI / 2) a += Math.PI;
                put(name, best.x, best.y, a);
            }
        } else {
            const rs = rings(e);
            const pts = rs.flat();
            if (!pts.length) continue;
            const [x, y] = px({ lat: pts.reduce((s, p) => s + p.lat, 0) / pts.length,
                                lon: pts.reduce((s, p) => s + p.lon, 0) / pts.length });
            put(name, x, y);
        }
    }
}

function drawAttribution(g, frame, photo) {
    const text = photo ? `${ATTRIBUTION_DGT} · ${ATTRIBUTION_OSM}` : ATTRIBUTION_OSM;
    const size = Math.max(14, Math.round(Math.min(frame.width, frame.height) / 60));
    g.font = `${size}px system-ui, sans-serif`;
    g.textAlign = 'right';
    g.textBaseline = 'bottom';
    const pad = Math.round(size / 2);
    const w = Math.min(frame.width, g.measureText(text).width + 2 * pad);
    const h = size + 2 * pad;
    g.fillStyle = 'rgba(255,255,255,0.85)';
    g.fillRect(frame.width - w, frame.height - h, w, h);
    g.fillStyle = '#111111';
    g.fillText(text, frame.width - pad, frame.height - pad, frame.width - 2 * pad);
}

function toBlob(canvas, type, quality) {
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/** The canvas as PNG (a drawn map) or JPEG (over the photo), made smaller until under IMAGE_MAX. */
export async function encode(canvas, photo) {
    let c = canvas;
    for (let tries = 0; tries < 6; tries += 1) {
        const attempts = photo || tries > 0 ? [['image/jpeg', 0.85], ['image/jpeg', 0.7]] : [['image/png'], ['image/jpeg', 0.85]];
        for (const [type, quality] of attempts) {
            const blob = await toBlob(c, type, quality);
            if (blob && blob.size <= IMAGE_MAX) return { blob, type, width: c.width, height: c.height };
        }
        const smaller = document.createElement('canvas');
        smaller.width = Math.max(1, Math.round(c.width * 0.75));
        smaller.height = Math.max(1, Math.round(c.height * 0.75));
        smaller.getContext('2d').drawImage(c, 0, 0, smaller.width, smaller.height);
        c = smaller;
    }
    throw new MapError('too_big_image');
}

/** A blob as base64 (no data: prefix). */
export function base64(blob) {
    return new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result).split(',', 2)[1]);
        r.onerror = () => reject(r.error);
        r.readAsDataURL(blob);
    });
}
