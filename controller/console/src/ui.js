// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Shared by the GM console and the scoreboard: Preact + HTM, the language
// files, the REST client, the live stream and small formatting helpers.

import { h, render, Component, createRef } from './lib/preact.module.js';
import htm from './lib/htm.module.js';

export const html = htm.bind(h);
export { h, render, Component, createRef };

// ---- languages ---------------------------------------------------------------

export const LANGS = ['pt', 'en', 'de', 'zh-tw'];
// <html lang> for each; a language other than pt and en shows English for a text it lacks
// (decision P5H-2: German and Traditional Chinese may trail the other agents' new keys).
// zh-Hant-TW also picks the CJK font stack (console.css, :lang(zh)).
const HTML_LANG = { pt: 'pt-PT', en: 'en', de: 'de', 'zh-tw': 'zh-Hant-TW' };
// The languages that write a decimal comma (869,525 MHz); English and Chinese use a point.
const DECIMAL_COMMA = new Set(['pt', 'de']);
const LANG_KEY = 'atalaia.lang';
const TOKEN_KEY = 'atalaia.token';
let dict = {};
let fallback = {};
let current = 'pt';

function storageGet(key) {
    try {
        return window.localStorage.getItem(key);
    } catch (e) {
        return null;
    }
}

function storageSet(key, value) {
    try {
        if (value === null) window.localStorage.removeItem(key);
        else window.localStorage.setItem(key, value);
    } catch (e) {
        /* private mode: the setting just is not remembered */
    }
}

async function fetchDict(lang) {
    const r = await fetch(new URL(`i18n/${lang}.json`, import.meta.url));
    if (!r.ok) throw new Error(`i18n/${lang}.json: ${r.status}`);
    return r.json();
}

/** Loads the remembered language (European Portuguese by default). A text the language lacks
 * comes from English (Portuguese for English itself: both are complete). */
export async function loadLanguage(lang) {
    lang = LANGS.includes(lang) ? lang : storageGet(LANG_KEY) || 'pt';
    if (!LANGS.includes(lang)) lang = 'pt';
    const base = lang === 'en' ? 'pt' : 'en';
    const [d, f] = await Promise.all([fetchDict(lang), fetchDict(base)]);
    dict = d;
    fallback = f;
    current = lang;
    storageSet(LANG_KEY, lang);
    document.documentElement.lang = HTML_LANG[lang];
    return lang;
}

/** s ("869.525", "0.1") with the current language's decimal separator. */
export function decimal(s) {
    return DECIMAL_COMMA.has(current) ? String(s).replace('.', ',') : String(s);
}

export function lang() {
    return current;
}

/** A mode's name or description in the current language (mode.yaml "i18n"), else the manifest's
 * (English for a language the manifest lacks; the built-in modes have pt, de and zh-tw, P5H-12). */
export function modeText(mode, key) {
    const tr = mode && mode.i18n && mode.i18n[current];
    return (tr && typeof tr[key] === 'string' && tr[key]) || (mode && mode[key]) || '';
}

/** A mode parameter's label in the current language, else the manifest's, else its name. */
export function paramLabel(mode, name) {
    const tr = mode && mode.i18n && mode.i18n[current];
    const spec = (mode && mode.params && mode.params[name]) || {};
    return (tr && tr.params && tr.params[name]) || spec.label || name;
}

/** A mode command's label (mode.yaml "commands", such as the Medic Kit's refill). */
export function commandLabel(mode, name) {
    const tr = mode && mode.i18n && mode.i18n[current];
    const spec = (mode && mode.commands && mode.commands[name]) || {};
    return (tr && tr.commands && tr.commands[name]) || spec.label || name;
}

/** An event in words for the feed, when the language has words for its type (feed.events,
 * keyed by type with the dots as underscores), else ''. */
export function eventWords(e) {
    let key = `feed.events.${String(e.type || '').replace(/\./g, '_')}`;
    const d = e.data || {};
    let team = e.team || '';
    let puzzle = d.puzzle || '';
    if (e.type === 'hacking.solved') {
        // The code a Hacking Terminal reveals is the GM's to see; who solved it may be unknown.
        if (d.code) key += '_code';
        team = team || t('feed.events.nobody');
        const p = t(`feed.puzzles.${puzzle}`);
        if (!p.startsWith('feed.')) puzzle = p;
    }
    // VIP / Payload: the VIP (a player id) from the controller, or the payload prop.
    if (e.type === 'vip.extracted' && d.player) key += '_vip';
    // A box's failed firmware update said over the radio: why, in words (firmware.reasons).
    let reason = d.reason || '';
    if (e.type === 'node.update_failed') {
        const r = t(`firmware.reasons.${reason}`);
        if (!r.startsWith('firmware.')) reason = r;
    }
    // A scenario's objectives: which one is the staff's (decision M6-5); a reveal without a
    // team is for every team.
    if (String(e.type || '').startsWith('scenario.objective.')) {
        if (e.type === 'scenario.objective.revealed' && !e.team) key += '_all';
        else team = team || t('feed.events.nobody');
        if (!d.objective) key += '_hidden';
    }
    const s = t(key, { team, player: d.player || '', remaining: d.remaining,
                       used: d.player_heals_used, amount: d.amount, puzzle, code: d.code || '',
                       objective: d.objective || '', scenario: d.scenario || '', reason,
                       zone: d.zone || (e.node === undefined ? '' : `${t('nodes.node')} ${e.node}`), step: d.step,
                       lives: d.lives_left === undefined ? '' : d.lives_left, fuse: d.fuse_s === undefined ? '' : d.fuse_s,
                       text: d.text || '' });
    return s === key ? '' : s;
}

/** Why the check-in poster cannot be made, in the current language: GET /checkin/poster's
 * problem_code (checkin.problems), else its English text. */
export function posterProblem(p) {
    const key = `checkin.problems.${p.problem_code}`;
    const s = p.problem_code ? t(key, { detail: p.problem || '' }) : key;
    return s === key ? (p.problem || '') : s;
}

/** t('game.start') or t('feed.count', {n: 3}): the text in the current language. */
export function t(key, vars) {
    let s = key.split('.').reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), dict);
    if (typeof s !== 'string') {
        s = key.split('.').reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), fallback);
    }
    if (typeof s !== 'string') return key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? String(vars[k]) : m));
    return s;
}

// ---- token and REST ----------------------------------------------------------

export function savedToken() {
    return storageGet(TOKEN_KEY) || '';
}

export function saveToken(token) {
    storageSet(TOKEN_KEY, token || null);
}

/**
 * The token (and language) given in the address's fragment, #token=...&lang=en, as the
 * scoreboard takes it: the app's web view opens the console so (decision PE24-70). Both are
 * taken out of the address at once (history.replaceState), so the token does not stay in the
 * address bar or the history; the rest of the fragment (a tab, #field) is kept. The fragment is
 * never sent to the controller; the token is never put in a query string and never logged.
 */
export function takeHashToken() {
    const raw = window.location.hash.replace(/^#/, '');
    const out = {};
    const rest = [];
    let found = false;
    for (const part of raw.split('&')) {
        const i = part.indexOf('=');
        const k = i < 0 ? part : part.slice(0, i);
        if (k === 'token' || k === 'lang') {
            found = true;
            try {
                const v = decodeURIComponent(i < 0 ? '' : part.slice(i + 1)).trim();
                if (v) out[k] = v;
            } catch (e) {
                /* a malformed value is dropped */
            }
        } else if (part) {
            rest.push(part);
        }
    }
    if (found) {
        const hash = rest.length ? `#${rest.join('&')}` : '';
        try {
            window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}${hash}`);
        } catch (e) {
            /* without the history API the address keeps it; the token still works */
        }
    }
    return out;
}

// ---- what the controller serves (decision PE24-70) -------------------------------

/** The console's areas a controller may serve: GET /api/v1/whoami's "features". The Pi's
 * controller serves them all (api.py FEATURES); the Android controller fewer. */
export const AREAS = ['checkin', 'join', 'box_language', 'positions', 'presets', 'branding', 'radio', 'boxes',
    'adoption', 'firmware', 'atak', 'field', 'scenarios', 'schedule', 'mode_packages', 'failover'];

/** Whether a controller whose whoami gave `features` serves `area`; one that gives no list (an
 * older controller) serves them all. */
export function serves(features, area) {
    return !Array.isArray(features) || features.includes(area);
}

/** Android's web view (the app's own console on a phone controller): it has no downloads and no
 * printing, which need a computer's browser. */
export function inWebView() {
    return /; wv\)/.test(navigator.userAgent || '');
}

export class ApiError extends Error {
    constructor(status, detail, body) {
        super(detail || `HTTP ${status}`);
        this.status = status;
        this.body = body || null; // the JSON answer, such as a refused scenario's problems
    }
}

/** Calls the controller's REST API v1 with the token. Returns the JSON answer. */
export async function api(token, method, path, body, raw) {
    const headers = { Authorization: `Bearer ${token}` };
    let payload;
    if (raw) {
        headers['Content-Type'] = raw.type;
        payload = raw.data;
    } else if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        payload = JSON.stringify(body);
    }
    const r = await fetch(`/api/v1${path}`, { method, headers, body: payload, cache: 'no-store' });
    if (!r.ok) {
        let detail = '';
        let j = null;
        try {
            j = await r.json();
            detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch (e) {
            detail = r.statusText;
        }
        throw new ApiError(r.status, detail, j);
    }
    const type = r.headers.get('content-type') || '';
    return type.includes('application/json') ? r.json() : r.blob();
}

// ---- the live stream ---------------------------------------------------------

/**
 * WS /api/v1/stream with automatic reconnection (1 s, doubling to 15 s).
 * onMessage gets every JSON message (the first one of each connection is
 * the "hello" snapshot); onState gets 'open', 'closed' or 'denied'.
 * A connection that goes silent without closing (a phone that slept, a Wi-Fi
 * that dropped it, a proxy that timed out) is never told by the browser: the
 * stream pings every PING_MS and, when nothing at all has come for DEAD_MS,
 * drops it and connects again, for a fresh "hello" (decision CL-2).
 */
export const PING_MS = 8000;
export const DEAD_MS = 20000;

export class Stream {
    constructor(token, onMessage, onState) {
        this.token = token;
        this.onMessage = onMessage;
        this.onState = onState;
        this.delay = 1000;
        this.stopped = false;
        this.ws = null;
        this.timer = null;
        this.beat = null;
        this.lastRx = Date.now();
        this.wake = () => {
            // A tab brought back to the front or a network that came back: a stale connection is replaced now.
            if (document.visibilityState !== 'hidden' && Date.now() - this.lastRx > PING_MS) this.check();
        };
        document.addEventListener('visibilitychange', this.wake);
        window.addEventListener('online', this.wake);
        this.connect();
    }

    /** Pings the server; a connection silent for DEAD_MS is dropped and opened again. */
    check() {
        const ws = this.ws;
        if (this.stopped || !ws) return;
        if (Date.now() - this.lastRx > DEAD_MS) {
            ws.onclose = null;
            try { ws.close(); } catch (e) { /* already gone */ }
            this.ws = null;
            this.onState('closed');
            this.delay = 1000;
            this.connect();
        } else if (ws.readyState === WebSocket.OPEN) {
            try { ws.send(JSON.stringify({ type: 'ping' })); } catch (e) { /* onclose follows */ }
        }
    }

    connect() {
        if (this.stopped) return;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/api/v1/stream?token=${encodeURIComponent(this.token)}`;
        const ws = new WebSocket(url);
        this.ws = ws;
        this.lastRx = Date.now();
        clearInterval(this.beat);
        this.beat = setInterval(() => this.check(), PING_MS);
        ws.onopen = () => {
            this.delay = 1000;
            this.lastRx = Date.now();
            this.onState('open');
        };
        ws.onmessage = (e) => {
            this.lastRx = Date.now();
            let msg;
            try {
                msg = JSON.parse(e.data);
            } catch (err) {
                return;
            }
            this.onMessage(msg);
        };
        ws.onclose = (e) => {
            if (this.ws !== ws) return;
            this.ws = null;
            clearInterval(this.beat);
            if (this.stopped) return;
            if (e.code === 4401) {
                this.onState('denied');
                return;
            }
            this.onState('closed');
            this.timer = setTimeout(() => this.connect(), this.delay);
            this.delay = Math.min(this.delay * 2, 15000);
        };
        ws.onerror = () => {
            /* onclose follows and reconnects */
        };
    }

    close() {
        this.stopped = true;
        clearTimeout(this.timer);
        clearInterval(this.beat);
        document.removeEventListener('visibilitychange', this.wake);
        window.removeEventListener('online', this.wake);
        if (this.ws) this.ws.close();
        this.ws = null;
    }
}

// A node not heard for this long is flagged offline (several missed STATE reports).
export const OFFLINE_MS = 90000;

// ---- formatting --------------------------------------------------------------

const TEAM_COLOURS = {
    red: '#d7263d', vermelho: '#d7263d', vermelha: '#d7263d',
    blue: '#1b6ee0', azul: '#1b6ee0',
    green: '#2a9d4b', verde: '#2a9d4b',
    yellow: '#e8b400', amarelo: '#e8b400', amarela: '#e8b400',
    orange: '#ef7d1a', laranja: '#ef7d1a',
    purple: '#8e44ad', roxo: '#8e44ad', roxa: '#8e44ad',
    black: '#333', preto: '#333', preta: '#333',
    white: '#bbb', branco: '#bbb', branca: '#bbb',
};
const PALETTE = ['#d7263d', '#1b6ee0', '#2a9d4b', '#e8b400', '#8e44ad', '#ef7d1a', '#16a2b8', '#6c757d'];

/** A colour for a team: its name if it is a colour, otherwise by position. */
export function teamColour(name, teams) {
    if (!name) return 'var(--muted)';
    const known = TEAM_COLOURS[String(name).toLowerCase()];
    if (known) return known;
    const i = teams ? teams.indexOf(name) : -1;
    return PALETTE[(i >= 0 ? i : name.length) % PALETTE.length];
}

// ---- branding (decisions BR1-BR24) ---------------------------------------------

/** A team's name as players see it: the game's display name for it, else its colour name. */
export function teamName(game, team) {
    const info = game && game.team_info && game.team_info[team];
    return (info && info.display_name) || team;
}

/** The address of a team's crest in a game, or null. Crests never change at one address. */
export function crestUrl(game, team) {
    const info = game && game.team_info && game.team_info[team];
    return info && info.crest_id ? `/api/v1/crests/${info.crest_id}` : null;
}

/** The address of the field's logo or wallpaper (GET /api/v1/field/branding's refs), versioned by
 * the image's id so a new upload shows at once. */
export function brandingUrl(ref) {
    return ref ? `${ref.url}?v=${ref.id.slice(0, 16)}` : null;
}

/** Black or white text, whichever reads better on a #rrggbb background. */
export function textOn(hex) {
    const n = parseInt(String(hex).slice(1), 16);
    const lin = (c) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const lum = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
    return lum > 0.4 ? '#101418' : '#ffffff';
}

/** GET /api/v1/field/branding: public, no token (null when the controller cannot be reached). */
export async function fetchBranding() {
    try {
        const r = await fetch('/api/v1/field/branding', { cache: 'no-cache' });
        return r.ok ? r.json() : null;
    } catch (e) {
        return null;
    }
}

/** Game time as m:ss (or h:mm:ss). */
export function clock(ms) {
    if (ms === null || ms === undefined || ms < 0) return '–';
    const s = Math.floor(ms / 1000);
    const hh = Math.floor(s / 3600);
    const mm = Math.floor((s % 3600) / 60);
    const ss = String(s % 60).padStart(2, '0');
    return hh ? `${hh}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
}

/** "12 s", "3 min", "2 h" for an age in milliseconds. */
export function age(ms) {
    if (ms === null || ms === undefined) return '–';
    const s = Math.round(ms / 1000);
    if (s < 90) return t('time.seconds', { n: s });
    if (s < 5400) return t('time.minutes', { n: Math.round(s / 60) });
    return t('time.hours', { n: Math.round(s / 3600) });
}

/** A JSON value as short text for the feed. */
export function brief(data) {
    if (!data || typeof data !== 'object') return '';
    return Object.entries(data)
        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join(', ');
}

/** A button that asks for confirmation in place (no browser dialog). */
export class ConfirmButton extends Component {
    constructor() {
        super();
        this.state = { asking: false };
    }

    render(props, state) {
        if (!state.asking) {
            return html`<button type="button" class=${props.class || ''} disabled=${props.disabled}
                data-testid=${props.testid} onClick=${() => this.setState({ asking: true })}>${props.label}</button>`;
        }
        return html`<span class="confirm" role="group" aria-label=${props.question}>
            <span class="confirm-q">${props.question}</span>
            <button type="button" class="danger" data-testid=${props.testid ? `${props.testid}-yes` : undefined}
                onClick=${() => { this.setState({ asking: false }); props.onConfirm(); }}>${t('common.yes')}</button>
            <button type="button" onClick=${() => this.setState({ asking: false })}>${t('common.no')}</button>
        </span>`;
    }
}
