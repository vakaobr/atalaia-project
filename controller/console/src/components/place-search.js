// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Finding the field on the field-map page by a place's name (decisions MF-41 to MF-48):
//
// - a place's name goes to OpenStreetMap's Nominatim search, as its usage policy asks: only when the
//   GM presses *Search* (no search as you type), at most one request a second from this page, the
//   same question answered from this page's memory rather than asked again, the page's origin as the
//   Referer (the console otherwise sends none, as for the tiles), and the attribution shown with the
//   results (the results are OpenStreetMap data, ODbL);
// - "latitude, longitude" never leaves the browser (field-map.js goes straight there);
// - the GM's own position (navigator.geolocation) never leaves the browser either: it only moves
//   the map. Nothing about either is sent to the field controller.

export const NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search';
// The policy asks heavy users to name themselves; a browser cannot set a User-Agent, so the
// project gives its contact address (the maintainer's decision on MF-44, 2026-10-23).
export const CONTACT_EMAIL = 'falecom@andersonleite.me';
export const RESULTS_MAX = 5;
export const MIN_INTERVAL_MS = 1000; // the policy's "an absolute maximum of 1 request per second"
// The console's languages as Nominatim's accept-language (the names in the results).
const ACCEPT_LANGUAGE = { pt: 'pt-PT,pt', en: 'en', de: 'de', 'zh-tw': 'zh-TW,zh' };

/** Raised with a code the page turns into words (fieldmap.place_errors.<code>). */
export class SearchError extends Error {
    constructor(code, detail) {
        super(detail || code);
        this.code = code;
    }
}

function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

/** One Nominatim result as {name, lat, lon, bounds?}, or null if it lacks a usable position. */
export function placeOf(r) {
    if (!r || typeof r !== 'object') return null;
    const lat = num(r.lat);
    const lon = num(r.lon);
    if (lat === null || lon === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    const name = String(r.display_name || r.name || `${lat}, ${lon}`).slice(0, 300);
    let bounds = null;
    // boundingbox: [south, north, west, east], as strings.
    if (Array.isArray(r.boundingbox) && r.boundingbox.length === 4) {
        const [south, north, west, east] = r.boundingbox.map(num);
        if ([south, north, west, east].every((v) => v !== null) && south <= north && west <= east) {
            bounds = { south, north, west, east };
        }
    }
    return { name, lat, lon, bounds };
}

/** Nominatim with the policy's limits: one search at a time, one a second, the same question once. */
export class PlaceSearch {
    constructor(fetcher = (...a) => fetch(...a), now = () => Date.now(), sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
        this.fetcher = fetcher;
        this.now = now;
        this.sleep = sleep;
        this.last = -Infinity;
        this.cache = new Map();
        this.busy = false;
    }

    url(query, lang) {
        const q = new URLSearchParams({ format: 'jsonv2', q: query, limit: String(RESULTS_MAX),
                                        'accept-language': ACCEPT_LANGUAGE[lang] || 'en', email: CONTACT_EMAIL });
        return `${NOMINATIM_URL}?${q}`;
    }

    /** Up to RESULTS_MAX places for the text; throws SearchError. Refuses a second search while one runs. */
    async search(text, lang) {
        const query = text.trim().replace(/\s+/g, ' ');
        if (!query) throw new SearchError('empty');
        const key = `${lang}\n${query.toLowerCase()}`;
        if (this.cache.has(key)) return this.cache.get(key);
        if (this.busy) throw new SearchError('busy_here');
        this.busy = true;
        try {
            const wait = this.last + MIN_INTERVAL_MS - this.now();
            if (wait > 0) await this.sleep(wait);
            this.last = this.now();
            let r;
            try {
                r = await this.fetcher(this.url(query, lang), {
                    credentials: 'omit', cache: 'default',
                    referrerPolicy: 'strict-origin-when-cross-origin', // the Referer the policy asks for
                });
            } catch (e) {
                throw new SearchError('offline');
            }
            if (r.status === 403 || r.status === 429 || r.status === 503) throw new SearchError('refused', `HTTP ${r.status}`);
            if (!r.ok) throw new SearchError('failed', `HTTP ${r.status}`);
            let data;
            try {
                data = await r.json();
            } catch (e) {
                throw new SearchError('failed', 'not JSON');
            }
            if (!Array.isArray(data)) throw new SearchError('failed', 'not a list');
            const places = data.map(placeOf).filter(Boolean).slice(0, RESULTS_MAX);
            this.cache.set(key, places);
            return places;
        } finally {
            this.last = Math.max(this.last, this.now()); // the next one second after this one ended
            this.busy = false;
        }
    }
}

/** Asks the browser for one position. Resolves {lat, lon, accuracy}; rejects with SearchError
 * ('insecure', 'unsupported', 'denied', 'unavailable', 'timeout'). */
export function locate(geo = navigator.geolocation, secure = window.isSecureContext) {
    return new Promise((resolve, reject) => {
        if (!secure) {
            reject(new SearchError('insecure'));
            return;
        }
        if (!geo || typeof geo.getCurrentPosition !== 'function') {
            reject(new SearchError('unsupported'));
            return;
        }
        geo.getCurrentPosition(
            (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }),
            (e) => reject(new SearchError({ 1: 'denied', 2: 'unavailable', 3: 'timeout' }[e && e.code] || 'unavailable',
                                          e && e.message)),
            { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }, // one fresh fix, 20 s at most
        );
    });
}

/** Whether the browser already lets this page read the position (no prompt): Permissions API, where
 * supported; false otherwise. */
export async function locationGranted() {
    try {
        if (!window.isSecureContext || !navigator.permissions || !navigator.geolocation) return false;
        return (await navigator.permissions.query({ name: 'geolocation' })).state === 'granted';
    } catch (e) {
        return false;
    }
}
