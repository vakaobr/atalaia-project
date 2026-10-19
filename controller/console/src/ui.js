// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Shared by the GM console and the scoreboard: Preact + HTM, the language
// files, the REST client, the live stream and small formatting helpers.

import { h, render, Component, createRef } from './lib/preact.module.js';
import htm from './lib/htm.module.js';

export const html = htm.bind(h);
export { h, render, Component, createRef };

// ---- languages ---------------------------------------------------------------

export const LANGS = ['pt', 'en'];
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

/** Loads the remembered language (European Portuguese by default). */
export async function loadLanguage(lang) {
    lang = LANGS.includes(lang) ? lang : storageGet(LANG_KEY) || 'pt';
    if (!LANGS.includes(lang)) lang = 'pt';
    if (!fallback.app) fallback = await fetchDict('pt');
    dict = lang === 'pt' ? fallback : await fetchDict(lang);
    current = lang;
    storageSet(LANG_KEY, lang);
    document.documentElement.lang = lang === 'pt' ? 'pt-PT' : 'en';
    return lang;
}

export function lang() {
    return current;
}

/** A mode's name or description in the current language (mode.yaml "i18n"), else the manifest's. */
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
    const key = `feed.events.${String(e.type || '').replace(/\./g, '_')}`;
    const d = e.data || {};
    const s = t(key, { team: e.team || '', player: d.player || '', remaining: d.remaining,
                       used: d.player_heals_used });
    return s === key ? '' : s;
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

export class ApiError extends Error {
    constructor(status, detail) {
        super(detail || `HTTP ${status}`);
        this.status = status;
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
        try {
            const j = await r.json();
            detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
        } catch (e) {
            detail = r.statusText;
        }
        throw new ApiError(r.status, detail);
    }
    const type = r.headers.get('content-type') || '';
    return type.includes('application/json') ? r.json() : r.blob();
}

// ---- the live stream ---------------------------------------------------------

/**
 * WS /api/v1/stream with automatic reconnection (1 s, doubling to 15 s).
 * onMessage gets every JSON message (the first one of each connection is
 * the "hello" snapshot); onState gets 'open', 'closed' or 'denied'.
 */
export class Stream {
    constructor(token, onMessage, onState) {
        this.token = token;
        this.onMessage = onMessage;
        this.onState = onState;
        this.delay = 1000;
        this.stopped = false;
        this.ws = null;
        this.timer = null;
        this.connect();
    }

    connect() {
        if (this.stopped) return;
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/api/v1/stream?token=${encodeURIComponent(this.token)}`;
        const ws = new WebSocket(url);
        this.ws = ws;
        ws.onopen = () => {
            this.delay = 1000;
            this.onState('open');
        };
        ws.onmessage = (e) => {
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
