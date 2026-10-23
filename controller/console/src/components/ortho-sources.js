// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The open orthophotos of the field-map page (decisions MF-25 and MF-54 for Portugal, MF-65 to MF-72 for
// the others, after the maintainer's answer to MF-57: "open source would be nice"). One row per national
// orthophoto: who makes it, where it has pictures (its coverage, ortho-coverage.js), its WMS for the drawn
// image (a GetMap in EPSG:4326 at the image's size, at most maxSide on a side, fetched so the canvas stays
// exportable: every one sends Access-Control-Allow-Origin: *), the map's *Ortofoto* tiles (its WMTS in
// Web Mercator where it has one, else a WMS GetMap per 256-pixel tile in EPSG:3857), and its credit, shown
// in the map's corner and burned into the image. The page's Content-Security-Policy names each origin
// (api.py FIELD_MAP_ORIGINS); test_console.py checks the two lists agree.
//
// Which one: the source whose coverage contains the point (the map's centre while finding the field; the
// outline's centroid when drawing), else the nearest within NEAR_M (a field on the coast or by a border,
// where the simplified coverage is off by up to about a kilometre); none further away. Each country's
// coverage is its own land, so a border is decided by the country the point is in (MF-67).

import { COVERAGE } from './ortho-coverage.js';

const HALF = 20037508.342789244; // half the Web Mercator world, in metres
export const NEAR_M = 1500;

/** A WMS GetMap of exactly one 256-pixel Web Mercator tile (z/x/y, as OpenStreetMap's), JPEG. */
function wmsTile(wms, layer) {
    return (z, x, y) => {
        const side = (2 * HALF) / 2 ** z;
        const r = (v) => (Math.round(v * 100) / 100).toFixed(2);
        const box = [-HALF + x * side, HALF - (y + 1) * side, -HALF + (x + 1) * side, HALF - y * side].map(r);
        const q = new URLSearchParams({ SERVICE: 'WMS', VERSION: '1.3.0', REQUEST: 'GetMap', LAYERS: layer,
                                        STYLES: '', CRS: 'EPSG:3857', BBOX: box.join(','), WIDTH: '256',
                                        HEIGHT: '256', FORMAT: 'image/jpeg' });
        return `${wms}?${q}`;
    };
}

/** A WMTS GetTile (KVP) in a Web Mercator tile matrix set whose levels are the zooms. */
function wmtsTile(wmts, layer, set, style) {
    return (z, x, y) => `${wmts}?${new URLSearchParams({
        SERVICE: 'WMTS', REQUEST: 'GetTile', VERSION: '1.0.0', LAYER: layer, STYLE: style, TILEMATRIXSET: set,
        TILEMATRIX: String(z), TILEROW: String(y), TILECOL: String(x), FORMAT: 'image/jpeg' })}`;
}

/** The sources, in the order a tie is decided (none overlaps another's land). */
export const ORTHO_SOURCES = [
    {
        // MF-25, MF-54: OrtoSat 2023, 30 cm, Pléiades Neo; no WMTS for this layer.
        id: 'dgt', name: 'DGT', coverage: COVERAGE.PRT,
        wms: 'https://ortos.dgterritorio.gov.pt/wms/ortosat2023', layer: 'ortoSat2023-CorVerdadeira', maxSide: 4096,
        credit: 'Ortofotomapas © DGT (CC BY 4.0)', imageCredit: 'Ortofotomapas © DGT (CC BY 4.0)',
        href: 'https://www.dgterritorio.gov.pt/dados-abertos',
    },
    {
        // MF-68: PNOA máxima actualidad (25-50 cm aerial photographs), IGN/CNIG; CC BY 4.0 with IGN's own
        // wording (its licence's formula; "Obra derivada de" for an image drawn over it).
        id: 'ign-es', name: 'IGN España', coverage: COVERAGE.ESP,
        wms: 'https://www.ign.es/wms-inspire/pnoa-ma', layer: 'OI.OrthoimageCoverage', maxSide: 4096,
        tile: wmtsTile('https://www.ign.es/wmts/pnoa-ma', 'OI.OrthoimageCoverage', 'GoogleMapsCompatible', 'default'),
        credit: 'PNOA CC-BY 4.0 scne.es', imageCredit: 'Obra derivada de PNOA CC-BY 4.0 scne.es',
        href: 'https://www.scne.es/productos.html',
    },
    {
        // MF-69: BD ORTHO and the IGN's other aerial photographs (20-50 cm), Géoplateforme; Licence Ouverte 2.0.
        id: 'ign-fr', name: 'IGN France', coverage: COVERAGE.FRA,
        wms: 'https://data.geopf.fr/wms-r', layer: 'ORTHOIMAGERY.ORTHOPHOTOS', maxSide: 4096,
        tile: wmtsTile('https://data.geopf.fr/wmts', 'ORTHOIMAGERY.ORTHOPHOTOS', 'PM_0_19', 'normal'),
        credit: 'Orthophotos © IGN (Licence Ouverte 2.0)', imageCredit: 'Orthophotos © IGN (Licence Ouverte 2.0)',
        href: 'https://cartes.gouv.fr/rechercher-une-donnee/dataset/IGNF_BD-ORTHO',
    },
    {
        // MF-70: Beeldmateriaal Nederland, the latest year, 25 cm, served by PDOK; CC BY 4.0, "Naamsvermelding
        // verplicht, Beeldmateriaal.nl". Its WMS draws at most 2500 pixels on a side.
        id: 'pdok', name: 'PDOK', coverage: COVERAGE.NLD,
        wms: 'https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0', layer: 'Actueel_ortho25', maxSide: 2500,
        tile: (z, x, y) => `https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_ortho25/EPSG:3857/${z}/${x}/${y}.jpeg`,
        credit: 'Luchtfoto © Beeldmateriaal.nl / PDOK (CC BY 4.0)',
        imageCredit: 'Luchtfoto © Beeldmateriaal.nl / PDOK (CC BY 4.0)', href: 'https://www.beeldmateriaal.nl/',
    },
];

/** The origins the page reaches for a source's tiles and its image (api.py lists the same). */
export function sourceOrigins() {
    return [...new Set(ORTHO_SOURCES.map((s) => new URL(s.wms).origin))];
}

/** The map's tiles of a source, as tile-map.js takes them (MF-54). */
export function tileSource(s) {
    return { id: `ortho-${s.id}`, url: s.tile || wmsTile(s.wms, s.layer), credit: s.credit, href: s.href,
             referrer: 'no-referrer' };
}

/** Whether ring ([lon, lat, ...]) contains the point (even-odd). */
function inRing(ring, lon, lat) {
    let inside = false;
    for (let i = 0, j = ring.length - 2; i < ring.length; j = i, i += 2) {
        const xi = ring[i];
        const yi = ring[i + 1];
        const xj = ring[j];
        const yj = ring[j + 1];
        if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
}

/** The distance in metres from the point to the ring's edge (a local flat approximation). */
function toRing(ring, lon, lat) {
    const ky = 111320;
    const kx = ky * Math.cos((lat * Math.PI) / 180);
    let best = Infinity;
    for (let i = 0, j = ring.length - 2; i < ring.length; j = i, i += 2) {
        const ax = (ring[j] - lon) * kx;
        const ay = (ring[j + 1] - lat) * ky;
        const bx = (ring[i] - lon) * kx;
        const by = (ring[i + 1] - lat) * ky;
        const dx = bx - ax;
        const dy = by - ay;
        const len = dx * dx + dy * dy;
        const t = len ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len)) : 0;
        best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
    }
    return best;
}

/** The sources for a point ({lat, lon}), best first: those containing it, then those within NEAR_M,
 * nearest first. Empty outside every coverage. */
export function sourcesAt(p) {
    if (!p || !Number.isFinite(p.lat) || !Number.isFinite(p.lon)) return [];
    const inside = [];
    const near = [];
    for (const s of ORTHO_SOURCES) {
        if (s.coverage.some((r) => inRing(r, p.lon, p.lat))) {
            inside.push(s);
            continue;
        }
        const d = Math.min(...s.coverage.map((r) => toRing(r, p.lon, p.lat)));
        if (d <= NEAR_M) near.push({ s, d });
    }
    near.sort((a, b) => a.d - b.d);
    return [...inside, ...near.map((n) => n.s)];
}

/** The best source for a point, or null. */
export function sourceAt(p) {
    return sourcesAt(p)[0] || null;
}

/** An outline's centroid ([{lat, lon}], 3 corners or more): its area's, or its corners' mean when flat. */
export function centroid(outline) {
    const lat0 = outline[0].lat;
    const lon0 = outline[0].lon;
    let a = 0;
    let cx = 0;
    let cy = 0;
    outline.forEach((p, i) => {
        const q = outline[(i + 1) % outline.length];
        const x1 = p.lon - lon0;
        const y1 = p.lat - lat0;
        const x2 = q.lon - lon0;
        const y2 = q.lat - lat0;
        const c = x1 * y2 - x2 * y1;
        a += c;
        cx += (x1 + x2) * c;
        cy += (y1 + y2) * c;
    });
    if (Math.abs(a) < 1e-14) {
        return { lat: outline.reduce((s, p) => s + p.lat, 0) / outline.length,
                 lon: outline.reduce((s, p) => s + p.lon, 0) / outline.length };
    }
    return { lat: lat0 + cy / (3 * a), lon: lon0 + cx / (3 * a) };
}

/** The sources for an outline, best first: by its centroid (MF-67). */
export function sourcesFor(outline) {
    return outline && outline.length >= 3 ? sourcesAt(centroid(outline)) : [];
}

/** The WMS GetMap URL of a source for the image's edges (EPSG:4326: south, west, north, east) at
 * width × height (already within its maxSide). */
export function imageUrl(s, b, width, height) {
    const q = new URLSearchParams({ SERVICE: 'WMS', VERSION: '1.3.0', REQUEST: 'GetMap', LAYERS: s.layer, STYLES: '',
                                    CRS: 'EPSG:4326', BBOX: `${b.south},${b.west},${b.north},${b.east}`,
                                    WIDTH: String(width), HEIGHT: String(height), FORMAT: 'image/jpeg' });
    return `${s.wms}?${q}`;
}
