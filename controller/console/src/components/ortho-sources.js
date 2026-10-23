// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The open orthophotos of the field-map page (decisions MF-25 and MF-54 for Portugal, MF-65 to MF-72 for
// Spain, France and the Netherlands, after the maintainer's answer to MF-57: "open source would be nice",
// MF-73 to MF-80 for the others). One row per orthophoto, national or regional (Belgium's regions,
// Germany's Länder): who makes it, where it has pictures (its coverage, ortho-coverage.js), its WMS for the
// drawn image (a GetMap in EPSG:4326 at the image's size, at most maxSide on a side, fetched so the canvas
// stays exportable: every one sends Access-Control-Allow-Origin, * or the page's own origin), the map's
// *Ortofoto* tiles (its WMTS in Web Mercator where it has one, else a WMS GetMap per 256-pixel tile in
// EPSG:3857), and its credit, shown in the map's corner and burned into the image. The page's
// Content-Security-Policy names each origin (api.py FIELD_MAP_ORIGINS); test_console.py checks the two lists
// agree.
//
// Which one: the source whose coverage contains the point (the map's centre while finding the field; the
// outline's centroid when drawing), else the nearest within NEAR_M (a field on the coast or by a border,
// where the simplified coverage is off by up to about a kilometre); none further away. Each coverage is its
// own land, so a border is decided by the country (or Land, or region) the point is in (MF-67, MF-73).

import { COVERAGE } from './ortho-coverage.js';

const HALF = 20037508.342789244; // half the Web Mercator world, in metres
export const NEAR_M = 1500;
// The year in a credit that asks for the year the data was obtained (MF-76: Mecklenburg-Vorpommern's,
// Rheinland-Pfalz's, ČÚZK's): this page's year, as the image is drawn now.
const YEAR = new Date().getFullYear();

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

/** A WMTS GetTile (KVP) in a Web Mercator tile matrix set; its levels are the zooms, named by matrix
 * (the zoom itself unless said), in format (JPEG unless said). */
function wmtsTile(wmts, layer, set, style, { matrix = String, format = 'image/jpeg' } = {}) {
    return (z, x, y) => `${wmts}?${new URLSearchParams({
        SERVICE: 'WMTS', REQUEST: 'GetTile', VERSION: '1.0.0', LAYER: layer, STYLE: style, TILEMATRIXSET: set,
        TILEMATRIX: matrix(z), TILEROW: String(y), TILECOL: String(x), FORMAT: format })}`;
}

/** tile for the zooms from zmin to zmax (a WMTS with fewer levels than the map's 2-19), else fallback. */
function zooms(zmin, zmax, tile, fallback) {
    return (z, x, y) => (z >= zmin && z <= zmax ? tile : fallback)(z, x, y);
}

const NRW_WMS = 'https://www.wms.nrw.de/geobasis/wms_nw_dop';
const CUZK_WMS = 'https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer';
const DL_BY = 'https://www.govdata.de/dl-de/by-2-0';
const DL_ZERO = 'https://www.govdata.de/dl-de/zero-2-0';

/** The sources, in the order a tie is decided: a region inside another's outer ring (Berlin in
 * Brandenburg, Brussels in Flemish Brabant) comes first; no other two overlap. */
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
        // MF-78: the same layer covers the overseas departments and collectivities.
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
    {
        // MF-74: Brussels, the NGI's national mosaic (2023; CC BY 4.0, the NGI's formula "© NGI-IGN, jaar,
        // licentie CC BY 4.0"); at most 4000 pixels; no WMTS of it.
        id: 'ngi', name: 'NGI-IGN', coverage: COVERAGE.BE_BRU,
        wms: 'https://wms.ngi.be/inspire/ortho/service', layer: 'orthoimage_coverage', maxSide: 4000,
        credit: '© NGI-IGN 2023, CC BY 4.0', imageCredit: '© NGI-IGN 2023, CC BY 4.0',
        href: 'https://ngi.be/beleid-rond-openheid-en-hergebruik-van-geografische-gegevens-van-het-ngi/',
    },
    {
        // MF-74: Flanders, the latest winter orthophoto (2025), Digitaal Vlaanderen; Modellicentie Gratis
        // Hergebruik, "Bron: Luchtopnamen Digitaal Vlaanderen". Its WMS draws at most 2048 pixels; its WMTS
        // (PNG only) is named in capitals.
        id: 'vlaanderen', name: 'Digitaal Vlaanderen', coverage: COVERAGE.BE_VLG,
        wms: 'https://geo.api.vlaanderen.be/omwrgbmrvl/wms', layer: 'Ortho', maxSide: 2048,
        tile: wmtsTile('https://geo.api.vlaanderen.be/OMWRGBMRVL/wmts', 'omwrgbmrvl', 'GoogleMapsVL', '',
                       { format: 'image/png' }),
        credit: 'Bron: Luchtopnamen Digitaal Vlaanderen', imageCredit: 'Bron: Luchtopnamen Digitaal Vlaanderen',
        href: 'https://www.vlaanderen.be/digitaal-vlaanderen/onze-diensten-en-platformen/open-data/voorwaarden-voor-het-hergebruik-van-overheidsinformatie/modellicentie-gratis-hergebruik',
    },
    {
        // MF-74: Wallonia, the SPW's latest orthophotos; CC BY 4.0. Its WMTS is in Belgian Lambert only.
        id: 'spw', name: 'SPW Wallonie', coverage: COVERAGE.BE_WAL,
        wms: 'https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_LAST/MapServer/WMSServer', layer: '0',
        maxSide: 4096,
        credit: 'Source : Service public de Wallonie (SPW) – Orthophotos (CC BY 4.0)',
        imageCredit: 'Source : Service public de Wallonie (SPW) – Orthophotos (CC BY 4.0)',
        href: 'https://geodata.wallonie.be/id/dfc9f3a2-adff-4b7f-ab77-8a890c4cabbb',
    },
    {
        // MF-75: Luxembourg, the ACT's latest orthophoto (2025), geoportail.lu; CC0 (no credit asked; given).
        id: 'act', name: 'geoportail.lu', coverage: COVERAGE.LUX,
        wms: 'https://wms.geoportail.lu/opendata/service', layer: 'ortho_latest', maxSide: 4096,
        tile: (z, x, y) => `https://wmts1.geoportail.lu/opendata/wmts/ortho_latest/GLOBAL_WEBMERCATOR_4_V3/${z}/${x}/${y}.jpeg`,
        credit: 'Orthophoto © ACT Luxembourg (CC0)', imageCredit: 'Orthophoto © ACT Luxembourg (CC0)',
        href: 'https://data.public.lu/fr/datasets/bd-l-ortho-webservices-wms-et-wmts/',
    },
    {
        // MF-75: SWISSIMAGE (10 cm), Switzerland and Liechtenstein; swisstopo's free geodata, "© swisstopo".
        // Its WMS's fair use is 20 requests a minute of 360 000 pixels: the picture asks at most 2048.
        id: 'swisstopo', name: 'swisstopo', coverage: COVERAGE.CHE,
        wms: 'https://wms.geo.admin.ch/', layer: 'ch.swisstopo.swissimage', maxSide: 2048,
        tile: (z, x, y) => `https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/${z}/${x}/${y}.jpeg`,
        credit: '© swisstopo', imageCredit: '© swisstopo',
        href: 'https://www.swisstopo.admin.ch/en/terms-of-use-free-geodata-and-geoservices',
    },
    {
        // MF-76: Germany, one source per Land, the Land of the point. Berlin: TrueDOP 20 cm, summer 2025;
        // dl-de/zero-2-0 (no credit asked; given). No WMTS in Web Mercator.
        id: 'de-be', name: 'Geoportal Berlin', coverage: COVERAGE.DE_BE,
        wms: 'https://gdi.berlin.de/services/wms/truedop_2025_sommer', layer: 'truedop_2025_sommer_rgb', maxSide: 4096,
        credit: 'Geoportal Berlin / TrueDOP 2025 (dl-de/zero-2-0)',
        imageCredit: 'Geoportal Berlin / TrueDOP 2025 (dl-de/zero-2-0)', href: DL_ZERO,
    },
    {
        // MF-76: Brandenburg (the Berlin-Brandenburg TrueDOP 20 cm); dl-de/by-2-0, its capabilities' credit.
        id: 'de-bb', name: 'LGB Brandenburg', coverage: COVERAGE.DE_BB,
        wms: 'https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms', layer: 'bebb_dop20c', maxSide: 4096,
        credit: '© GeoBasis-DE/LGB, dl-de/by-2-0', imageCredit: '© GeoBasis-DE/LGB, dl-de/by-2-0 (Daten geändert)',
        href: DL_BY,
    },
    {
        // MF-76: Bayern, DOP20; CC BY 4.0, "Bayerische Vermessungsverwaltung – www.geodaten.bayern.de". Its WMTS
        // is on other hosts (bayernwolke.de) with a longer credit (Sentinel-2 at small scales): WMS tiles.
        id: 'de-by', name: 'LDBV Bayern', coverage: COVERAGE.DE_BY,
        wms: 'https://geoservices.bayern.de/od/wms/dop/v1/dop20', layer: 'by_dop20c', maxSide: 4096,
        credit: 'Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC BY 4.0)',
        imageCredit: 'Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC BY 4.0, Daten geändert)',
        href: 'https://www.geodaten.bayern.de/odd/m/3/html/nutzungsbedingungen.html',
    },
    {
        // MF-76: Bremen and Bremerhaven, DOP10 2025; CC BY 4.0, "Landesamt GeoInformation Bremen".
        id: 'de-hb', name: 'GeoInformation Bremen', coverage: COVERAGE.DE_HB,
        wms: 'https://geodienste.bremen.de/wms_dop_lb', layer: 'dop10_2025_HB,dop10_2025_BHV', maxSide: 4096,
        credit: '© Landesamt GeoInformation Bremen (CC BY 4.0)',
        imageCredit: '© Landesamt GeoInformation Bremen (CC BY 4.0)', href: 'https://creativecommons.org/licenses/by/4.0/',
    },
    {
        // MF-76: Hessen, DOP20 (with its overview levels); free of any condition (HVGG § 18, dl-de/zero-2-0).
        // Its WMS draws at most 3000 pixels.
        id: 'de-he', name: 'HVBG Hessen', coverage: COVERAGE.DE_HE,
        wms: 'https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows', layer: 'he_dop_rgb',
        maxSide: 3000,
        credit: 'Geobasisdaten © Hessische Verwaltung für Bodenmanagement und Geoinformation',
        imageCredit: 'Geobasisdaten © Hessische Verwaltung für Bodenmanagement und Geoinformation (Daten geändert)',
        href: DL_ZERO,
    },
    {
        // MF-76: Mecklenburg-Vorpommern, TrueDOP 20 cm; CC BY 4.0, "© GeoBasis-DE/M-V <year>". Its WMTS's
        // capabilities carry older, stricter terms: WMS tiles.
        id: 'de-mv', name: 'LAiV M-V', coverage: COVERAGE.DE_MV,
        wms: 'https://www.geodaten-mv.de/dienste/adv_dop', layer: 'mv_dop', maxSide: 4096,
        credit: `© GeoBasis-DE/M-V ${YEAR} (CC BY 4.0)`, imageCredit: `© GeoBasis-DE/M-V ${YEAR} (CC BY 4.0)`,
        href: 'https://creativecommons.org/licenses/by/4.0/',
    },
    {
        // MF-76: Nordrhein-Westfalen, DOP; dl-de/zero-2-0 (no credit asked; given). Its WMTS's levels are
        // "00" (zoom 5) to "16" (zoom 21); below zoom 5, WMS tiles.
        id: 'de-nw', name: 'Geobasis NRW', coverage: COVERAGE.DE_NW,
        wms: NRW_WMS, layer: 'nw_dop_rgb', maxSide: 4096,
        tile: zooms(5, 21, (z, x, y) => `https://www.wmts.nrw.de/geobasis/wmts_nw_dop/tiles/nw_dop/EPSG_3857_16/${
            String(z - 5).padStart(2, '0')}/${x}/${y}`, wmsTile(NRW_WMS, 'nw_dop_rgb')),
        credit: 'Luftbild: Geobasis NRW (dl-de/zero-2-0)', imageCredit: 'Luftbild: Geobasis NRW (dl-de/zero-2-0)',
        href: DL_ZERO,
    },
    {
        // MF-76: Rheinland-Pfalz, DOP20; dl-de/by-2-0, its capabilities' credit with the year obtained.
        id: 'de-rp', name: 'LVermGeo RLP', coverage: COVERAGE.DE_RP,
        wms: 'https://geo4.service24.rlp.de/wms/rp_dop20.fcgi', layer: 'rp_dop20', maxSide: 4096,
        credit: `©GeoBasis-DE / LVermGeoRP (${YEAR}), dl-de/by-2-0, www.lvermgeo.rlp.de`,
        imageCredit: `©GeoBasis-DE / LVermGeoRP (${YEAR}), dl-de/by-2-0, www.lvermgeo.rlp.de [Daten bearbeitet]`,
        href: DL_BY,
    },
    {
        // MF-76: Saarland, DOP20 2025; dl-de/by-2-0, "© GeoBasis DE/LVGL-SL <year>".
        id: 'de-sl', name: 'LVGL Saarland', coverage: COVERAGE.DE_SL,
        wms: 'https://geoportal.saarland.de/freewms/dop2025', layer: 'sl_dop20_rgb', maxSide: 4096,
        credit: '© GeoBasis DE/LVGL-SL 2025, dl-de/by-2-0',
        imageCredit: '© GeoBasis DE/LVGL-SL 2025, dl-de/by-2-0 (Daten geändert)', href: DL_BY,
    },
    {
        // MF-76: Sachsen, DOP20; dl-de/by-2-0, "Quelle: GeoSN, dl-de/by-2-0". Its WMTS is not on the Web
        // Mercator grid: WMS tiles.
        id: 'de-sn', name: 'GeoSN Sachsen', coverage: COVERAGE.DE_SN,
        wms: 'https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest', layer: 'sn_dop_020', maxSide: 4096,
        credit: 'Quelle: GeoSN, dl-de/by-2-0', imageCredit: 'Quelle: GeoSN, dl-de/by-2-0 (Daten geändert)',
        href: DL_BY,
    },
    {
        // MF-76: Thüringen, DOP20; CC BY 4.0, "© GDI-Th".
        id: 'de-th', name: 'GDI-Th', coverage: COVERAGE.DE_TH,
        wms: 'https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP', layer: 'th_dop', maxSide: 4096,
        credit: '© GDI-Th (CC BY 4.0)', imageCredit: '© GDI-Th (CC BY 4.0)',
        href: 'https://creativecommons.org/licenses/by/4.0/',
    },
    {
        // MF-77: Poland, GUGiK's orthophotomap, free for any use with its source given (Prawo geodezyjne
        // art. 40a; geoportal.gov.pl's terms § 3). The image from its high-resolution WMS (EPSG:4326 only),
        // the tiles from its standard-resolution WMTS (levels "EPSG:3857:<zoom>").
        id: 'gugik', name: 'GUGiK', coverage: COVERAGE.POL,
        wms: 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution', layer: 'Raster', maxSide: 4096,
        tile: wmtsTile('https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution', 'ORTOFOTOMAPA',
                       'EPSG:3857', 'default', { matrix: (z) => `EPSG:3857:${z}` }),
        credit: 'Ortofotomapa: GUGiK (geoportal.gov.pl)', imageCredit: 'Ortofotomapa: GUGiK (geoportal.gov.pl)',
        href: 'https://www.geoportal.gov.pl/en/data/orthophotomap-orto/',
    },
    {
        // MF-77: Czechia, ČÚZK's orthophoto; CC BY 4.0, "ČÚZK, <year>". Its WMTS has the zooms 6 to 18: WMS
        // tiles at the others.
        id: 'cuzk', name: 'ČÚZK', coverage: COVERAGE.CZE,
        wms: CUZK_WMS, layer: '0', maxSide: 4096,
        tile: zooms(6, 18, (z, x, y) => `https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer/tile/${
            z}/${y}/${x}`, wmsTile(CUZK_WMS, '0')),
        credit: `Ortofoto: ČÚZK, ${YEAR} (CC BY 4.0)`, imageCredit: `Ortofoto: ČÚZK, ${YEAR} (CC BY 4.0)`,
        href: 'https://www.cuzk.gov.cz/Predpisy/Podminky-poskytovani-prostor-dat-a-sitovych-sluzeb/Podminky-poskytovani-prostorovych-dat-CUZK.aspx',
    },
];

/** The origins the page fetches a source's image from (connect-src: api.py FIELD_MAP_ORTHOPHOTOS). */
export function imageOrigins() {
    return [...new Set(ORTHO_SOURCES.map((s) => new URL(s.wms).origin))];
}

/** The origins the page reaches for a source's tiles and its image (img-src: api.py FIELD_MAP_ORTHOPHOTOS
 * and FIELD_MAP_ORTHO_TILES). */
export function sourceOrigins() {
    return [...new Set(ORTHO_SOURCES.flatMap((s) => [s.wms, ...(s.tile ? [s.tile(17, 0, 0), s.tile(2, 0, 0)] : [])])
        .map((u) => new URL(u).origin))];
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
