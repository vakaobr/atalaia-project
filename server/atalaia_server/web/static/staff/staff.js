// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Shared by the field staff's pages (server/atalaia_server/web/staff_pages.py): the texts the
// server put in the page, the session, the API client, and small DOM helpers.
//
// The session (decisions FU2-3, FU2-4): the API wants the access token in
// "Authorization: Bearer"; it is kept in this tab's sessionStorage until it expires. A new one
// comes from POST /api/v1/auth/refresh, which reads the HttpOnly refresh cookie (the browser sends
// it to that path only) and wants the header X-Atalaia-Refresh: 1. The refresh token rotates and a
// reused one ends the session, so refreshes are serialised: one at a time in this page, and one at
// a time across this site's tabs (Web Locks). No request is ever authorised by a cookie alone.
//
// Every value from the server is written with textContent or as an attribute value through
// el(); nothing is ever parsed as HTML (FU2-5).

const STRINGS = JSON.parse(document.getElementById('staff-strings').textContent);
export const page = document.body.dataset;
const SESSION_KEY = 'atalaia.staff.session';
const LOCK = 'atalaia-staff-refresh';
const PRIVILEGED = ['admin', 'gm', 'marshal'];

// ---- texts --------------------------------------------------------------------------------

/** The page's text for key, with {name} replaced by vars.name. */
export function t(key, vars) {
    let text = Object.prototype.hasOwnProperty.call(STRINGS, key) ? STRINGS[key] : key;
    if (vars) {
        text = text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
    }
    return text;
}

export function has(key) {
    return Object.prototype.hasOwnProperty.call(STRINGS, key);
}

const LOCALE = page.lang === 'pt' ? 'pt-PT' : 'en-GB';

/** A date and time, in the field's time zone when it is known. */
export function when(iso, zone) {
    if (!iso) return t('none');
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso);
    const options = { dateStyle: 'medium', timeStyle: 'short' };
    try {
        return new Intl.DateTimeFormat(LOCALE, zone ? { ...options, timeZone: zone } : options).format(date);
    } catch (e) {
        return new Intl.DateTimeFormat(LOCALE, options).format(date);
    }
}

/** A game time in milliseconds as m:ss or h:mm:ss. */
export function gameTime(ms) {
    if (ms === null || ms === undefined) return t('none');
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

export function stateName(state) {
    return has(`state_${state}`) ? t(`state_${state}`) : String(state);
}

export function roleName(role) {
    return has(`role_${role}`) ? t(`role_${role}`) : String(role);
}

// ---- DOM ------------------------------------------------------------------------------------

/** A path on this site, keeping an explicitly chosen language. */
export function link(path) {
    if (!page.explicit) return path;
    return `${path}${path.includes('?') ? '&' : '?'}lang=${encodeURIComponent(page.lang)}`;
}

/** An element: attrs are set as attributes (on* as listeners, text as textContent), children appended as nodes
 * or text. An href must be a path on this site. */
export function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (name === 'text') node.textContent = String(value);
        else if (name.startsWith('on') && typeof value === 'function') node.addEventListener(name.slice(2), value);
        else if (name === 'href' && !(String(value).startsWith('/') && !String(value).startsWith('//'))) continue;
        else node.setAttribute(name, value === true ? '' : String(value));
    }
    append(node, children);
    return node;
}

function append(node, children) {
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
}

export function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
}

export function $(id) {
    return document.getElementById(id);
}

/** Shows a message in the page's status line (kind: '', 'error' or 'ok'). */
export function status(message, kind = '') {
    const box = $('status');
    clear(box);
    box.className = `status ${kind}`.trim();
    if (message) box.append(el('p', { text: message }));
}

/** Turns a form's fieldsets on (they are disabled until the script runs, so nothing submits without it). */
export function enable(form) {
    for (const set of form.querySelectorAll('fieldset')) set.disabled = false;
}

/** Fills a table body with rows of cells (text, nodes, or [content, {attrs}]). */
export function fillRows(table, rows) {
    const tbody = table.tBodies[0];
    clear(tbody);
    for (const row of rows) {
        const tr = el('tr');
        row.forEach((cell, i) => {
            const [content, attrs] = Array.isArray(cell) && cell.length === 2 && cell[1] && !(cell[1] instanceof Node)
                && typeof cell[1] === 'object' ? cell : [cell, {}];
            tr.append(el(i === 0 ? 'th' : 'td', { scope: i === 0 ? 'row' : null, ...attrs }, content));
        });
        tbody.append(tr);
    }
    table.hidden = false;
}

// ---- the session --------------------------------------------------------------------------

function storageGet() {
    try {
        const value = JSON.parse(window.sessionStorage.getItem(SESSION_KEY));
        return value && typeof value.token === 'string' ? value : null;
    } catch (e) {
        return null;
    }
}

function storageSet(value) {
    try {
        if (value === null) window.sessionStorage.removeItem(SESSION_KEY);
        else window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(value));
    } catch (e) {
        /* storage refused: the token lives in this page only */
    }
    memory = value;
}

let memory = null;

/** Keeps a login's or a refresh's answer: the access token until a little before it expires, and who it is. */
export function keep(body) {
    const user = body.user || {};
    storageSet({
        token: body.access_token,
        expires: Date.now() + (body.expires_in || 0) * 1000 - 30000,
        mfa: Boolean(body.mfa),
        user: { username: user.username, server_admin: Boolean(user.server_admin) },
    });
}

export function forget() {
    storageSet(null);
}

function current() {
    const s = storageGet() || memory;
    return s && s.expires > Date.now() ? s : null;
}

async function refreshNow() {
    let r;
    try {
        r = await fetch('/api/v1/auth/refresh', {
            method: 'POST', headers: { 'X-Atalaia-Refresh': '1' }, credentials: 'same-origin', cache: 'no-store',
        });
    } catch (e) {
        throw new ApiError(0, { detail: 'network' });
    }
    if (!r.ok) {
        forget();
        return null;
    }
    keep(await r.json());
    return current();
}

let refreshing = null;

/** The session: the kept one, or a new access token from the refresh cookie; null when there is none. */
export function session(force = false) {
    const s = force ? null : current();
    if (s) return Promise.resolve(s);
    if (!refreshing) {
        const run = () => refreshNow();
        const locked = navigator.locks ? navigator.locks.request(LOCK, run) : run();
        refreshing = locked.finally(() => {
            refreshing = null;
        });
    }
    return refreshing;
}

export class ApiError extends Error {
    constructor(status, body, retryAfter) {
        super(body && typeof body.detail === 'string' ? body.detail : `http_${status}`);
        this.status = status;
        this.body = body || {};
        this.retryAfter = retryAfter;
    }

    get code() {
        return typeof this.body.detail === 'string' ? this.body.detail : `http_${this.status}`;
    }
}

/** Where a page goes without a session: the login page, then back here. */
export function toLogin() {
    const next = `${location.pathname}${location.search}`;
    location.assign(link(`/staff/login?next=${encodeURIComponent(next)}`));
}

/** Calls the API with the session's access token; a 401 gets one refresh and one retry, then the login page. */
export async function api(method, path, body) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
        const s = await session(attempt > 0);
        if (!s) {
            toLogin();
            throw new ApiError(401, { detail: 'not_authenticated' });
        }
        const headers = { Authorization: `Bearer ${s.token}` };
        if (body !== undefined) headers['Content-Type'] = 'application/json';
        let r;
        try {
            r = await fetch(path, {
                method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                credentials: 'same-origin', cache: 'no-store',
            });
        } catch (e) {
            throw new ApiError(0, { detail: 'network' });
        }
        if (r.status === 401) {
            if (attempt === 0) continue;
            forget();
            toLogin();
            throw new ApiError(401, { detail: 'not_authenticated' });
        }
        let data = null;
        if (r.status !== 204) {
            try {
                data = await r.json();
            } catch (e) {
                data = null;
            }
        }
        if (!r.ok) throw new ApiError(r.status, data, r.headers.get('Retry-After'));
        return data;
    }
    throw new ApiError(401, { detail: 'not_authenticated' });
}

/** A failed call in words. roles: the roles its API wants, for a 403. */
export function errorText(err, roles) {
    if (!(err instanceof ApiError)) return t('err_generic', { code: String(err && err.message) });
    if (err.status === 0) return t('err_network');
    if (err.status === 429) return t('err_rate', { s: err.retryAfter || 60 });
    if (err.status === 403 && err.code === 'role_required') {
        const text = t('err_role', { roles: (roles || ['admin', 'gm']).map(roleName).join(` ${t('or')} `) });
        const s = current();
        return s && !s.mfa ? `${text} ${t('err_no_mfa')}` : text;
    }
    if (err.status === 401) return t('err_session');
    const key = `e_${err.code}`;
    if (has(key)) return t(key, { error: err.body.error || '', path: err.body.path || '' });
    if (err.status === 404) return t('err_not_found');
    return t('err_generic', { code: err.code });
}

// ---- the page's frame ---------------------------------------------------------------------

/** The roles that count in this session (privileged ones only after TOTP; a server admin counts as admin). */
export function effectiveRoles(field, s) {
    const roles = new Set(field && Array.isArray(field.my_roles) ? field.my_roles : []);
    if (!s.mfa) for (const r of PRIVILEGED) roles.delete(r);
    if (s.mfa && s.user.server_admin) roles.add('admin');
    return roles;
}

const SECTIONS = {
    history: (r) => r.size > 0,
    scenarios: (r) => r.has('admin') || r.has('gm'),
    presets: (r) => r.has('admin') || r.has('gm'),
    devices: (r) => r.has('admin') || r.has('gm'),
    remote: (r) => r.has('admin') || r.has('gm'),
};

export function sectionAllowed(name, roles) {
    return !SECTIONS[name] || SECTIONS[name](roles);
}

/**
 * Starts a page that needs a session: the account's name and the logout button, and on a field's pages that
 * field (from GET /api/v1/fields: its name, time zone and the account's roles) with the sections its roles
 * reach. Returns {session, field, roles}; null after sending the browser to the login page.
 */
export async function boot() {
    let s;
    try {
        s = await session();
    } catch (err) {
        status(errorText(err), 'error');
        return null;
    }
    if (!s) {
        toLogin();
        return null;
    }
    $('who').textContent = t('signed_in_as', { user: s.user.username || '' });
    const logout = $('logout');
    logout.hidden = false;
    logout.addEventListener('click', async () => {
        try {
            await api('POST', '/api/v1/auth/logout');
        } catch (e) {
            /* the session is forgotten here either way */
        }
        forget();
        location.assign(link('/staff/login?out=1'));
    });
    let field = null;
    let roles = new Set();
    if (page.field) {
        try {
            const fields = await api('GET', '/api/v1/fields');
            field = (fields || []).find((f) => f.id === page.field) || null;
        } catch (err) {
            status(errorText(err), 'error');
        }
        roles = effectiveRoles(field, s);
        if (field) $('field-name').textContent = t('field_heading', { field: field.name });
        for (const item of document.querySelectorAll('#sections li[data-section]')) {
            item.hidden = !sectionAllowed(item.dataset.section, roles);
        }
    }
    return { session: s, field, roles, zone: field ? field.timezone : undefined };
}

/** A path under this field's API. */
export function fieldApi(rest) {
    return `/api/v1/fields/${encodeURIComponent(page.field)}${rest}`;
}

/** A path under this field's staff pages. */
export function fieldPage(rest) {
    return link(`/staff/fields/${encodeURIComponent(page.field)}${rest}`);
}

/** Plain JSON for a cell: compact, and cut at max characters. */
export function brief(value, max = 160) {
    if (value === null || value === undefined) return t('none');
    const text = typeof value === 'string' ? value : JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
