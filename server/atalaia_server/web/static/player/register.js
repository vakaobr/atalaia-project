// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Registering for a game in the browser (player_pages.py, decisions WREG-*): the same API, checks and records as the
// Atalaia app's registration screen (app/lib/site/site_screens.dart).
//
//   1. The session: a social login coming back (a one-minute ticket in the address fragment, or ?oidc_error=<code>)
//      becomes one at POST /api/v1/auth/oidc/complete; else the tab's kept access token, else the refresh cookie
//      (staff.js). With none, the login: the password and its TOTP code when the server takes passwords, a passkey,
//      or Google, Microsoft or Apple. An unknown social login makes an account only with the notice opened and ticked
//      and the 16-or-older box ticked (LEG-*), and the version of the notice the page offered (CONS-4); the server
//      checks all three and records the notice shown.
//   2. The game and what registering needs: GET /api/v1/fields-by-slug/<slug> (teams, federation number, the field's
//      membership rule and list, the replicas' classes and types); the account's registration: GET
//      /api/v1/me/registrations.
//   3. Registering (POST .../registrations), changing (PATCH /api/v1/me/registrations/<id>), cancelling (DELETE), a new
//      ticket (POST .../ticket). The ticket's text is in the answer only: it is drawn here as a QR code (the vendored
//      generator, nothing sent anywhere) and as text, to print or save; it is never stored by this page.
//   4. After it: the way into the app (atalaia://register, S17-10), and a passkey for next time (POST
//      /api/v1/me/passkeys/options and /me/passkeys) for an account that has no password and no passkey yet.
//
// Every request is authorised by "Authorization: Bearer", never by a cookie (FU2-3); every value is written with
// textContent or as an attribute through el(), never parsed as HTML (FU2-5).

import { $, ApiError, clear, el, enable, forget, has, keep, session, status, t } from '../staff/staff.js';
import { assertionJson, attestationJson, creationOptions, passkeysSupported, requestOptions } from '../staff/webauthn.js';
import qrcode from './qrcode.module.js';

const page = document.body.dataset;
const params = new URLSearchParams(location.search);
const LIVE = ['registered', 'checked_in'];
const GENERATED = /^user-[0-9a-f]{12}$/;  // the username a social login gives a new account (LG-10)

let field = null;    // the field as GET /api/v1/fields-by-slug says it
let game = null;     // this game in that answer (null: it ended, or is not one that can be registered for)
let reg = null;      // the account's registration for this game, if any
let newAccount = false;
let noticeVersion = null;
let defaultName = '';  // the form's name at first: the username, unless it is one a social login made up
const MAKE_MODEL_MAX = 64;  // services/registration.MAKE_MODEL_MAX

// ---- texts --------------------------------------------------------------------------------

/** The association twin of a membership text (<key>_m) for a field outside Portugal or without a country. */
function mt(key, vars) {
    return field && field.country !== 'PT' && has(`${key}_m`) ? t(`${key}_m`, vars) : t(key, vars);
}

/** A refused call in words, next to what it was about. */
function refusal(err) {
    if (!(err instanceof ApiError)) return t('err_generic', { code: String(err && err.message) });
    if (err.status === 0) return t('err_network');
    if (err.status === 429) return t('err_rate', { s: err.retryAfter || 60 });
    if (err.status === 401) return t('err_session');
    if (has(`e_${err.code}`)) return mt(`e_${err.code}`);
    if (err.status === 404) return t('err_not_found');
    return t('err_generic', { code: err.code });
}

// ---- the API --------------------------------------------------------------------------------

/** A call with no session (the login's own steps). */
async function call(method, path, body) {
    let r;
    try {
        r = await fetch(path, {
            method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', cache: 'no-store',
        });
    } catch (e) {
        return { status: 0, body: {} };
    }
    let data = {};
    try {
        data = await r.json();
    } catch (e) {
        data = {};
    }
    return { status: r.status, body: data || {}, retry: r.headers.get('Retry-After') };
}

/** A call with the session's access token: a refused token gets one refresh and one retry, then the login. */
async function api(method, path, body) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
        const s = await session(attempt > 0);
        if (!s) break;
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
        if (r.status === 401 && attempt === 0) continue;
        let data = null;
        if (r.status !== 204) {
            try {
                data = await r.json();
            } catch (e) {
                data = null;
            }
        }
        if (r.status === 401) break;
        if (!r.ok) throw new ApiError(r.status, data, r.headers.get('Retry-After'));
        return data;
    }
    forget();
    showLogin();
    throw new ApiError(401, { detail: 'not_authenticated' });
}

// ---- the login --------------------------------------------------------------------------------

const loginForm = $('login-form');
const totpForm = $('totp-form');
let step = null;

function loginRefused(answer, wrong) {
    if (answer.status === 0) return t('err_network');
    if (answer.status === 429) return t('login_locked', { s: answer.retry || 60 });
    if (answer.body.detail === 'invalid_totp_session') return t('login_step_expired');
    if (answer.status === 401) return wrong;
    return t('err_generic', { code: answer.body.detail || `http_${answer.status}` });
}

/** This page's own address, with only the chosen language: where a social login comes back to. */
function here() {
    return page.explicit ? `${location.pathname}?lang=${encodeURIComponent(page.lang)}` : location.pathname;
}

async function loggedIn(body) {
    keep(body);
    newAccount = Boolean(body.new_account);
    $('password').value = '';
    status('');
    await start();
}

loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const username = $('username').value.trim();
    const password = $('password').value;
    if (!username || !password) {
        status(t('login_bad'), 'error');
        return;
    }
    status(t('loading'));
    const answer = await call('POST', '/api/v1/auth/login', { username, password });
    if (answer.status !== 200) {
        status(loginRefused(answer, t('login_bad')), 'error');
        return;
    }
    if (answer.body.totp_required) {
        step = answer.body.totp_session;
        status('');
        loginForm.hidden = true;
        totpForm.hidden = false;
        enable(totpForm);
        $('code').focus();
        return;
    }
    await loggedIn(answer.body);
});

totpForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    status(t('loading'));
    const answer = await call('POST', '/api/v1/auth/login/totp', { totp_session: step,
        code: $('code').value.replace(/\s+/g, '') });
    $('code').value = '';
    if (answer.status === 200) {
        totpForm.hidden = true;
        await loggedIn(answer.body);
        return;
    }
    status(loginRefused(answer, t('login_bad_code')), 'error');
    if (answer.body.detail === 'invalid_totp_session') {
        totpForm.hidden = true;
        loginForm.hidden = false;
    }
});

$('passkey-login').addEventListener('click', async () => {
    status(t('loading'));
    const first = await call('POST', '/api/v1/auth/passkey/login/options', {});
    if (first.status !== 200) {
        status(loginRefused(first, t('passkey_failed')), 'error');
        return;
    }
    let credential = null;
    try {
        credential = await navigator.credentials.get({ publicKey: requestOptions(first.body.options) });
    } catch (e) {
        credential = null;
    }
    if (!credential) {
        status(t('passkey_cancelled'), 'error');
        return;
    }
    const answer = await call('POST', '/api/v1/auth/passkey/login', {
        challenge_token: first.body.challenge_token, credential: assertionJson(credential),
    });
    if (answer.status !== 200) {
        status(loginRefused(answer, t('passkey_failed')), 'error');
        return;
    }
    await loggedIn(answer.body);
});

const SIGNUP_BOX = {
    notice_required: 'notice-seen', notice_version_changed: 'notice-seen', age_confirmation_required: 'age-confirmed',
};

function oidcError(code) {
    return has(`oidc_err_${code}`) ? t(`oidc_err_${code}`) : t('oidc_err_other');
}

/** A refusal to make the account, at the boxes, with the box it is about marked and focused. */
function signupMissing(text, boxId) {
    const note = $('signup-error');
    note.textContent = text;
    note.hidden = false;
    $('signup-row').classList.add('invalid');
    const box = $(boxId);
    if (boxId === 'notice-seen') box.checked = false;
    box.setAttribute('aria-invalid', 'true');
    status('');
    box.focus();
}

async function socialLogin(provider) {
    // Checked here as the app checks it (the box opens only once the notice was opened); the server checks the
    // three values again, and only when the login makes a new account.
    const seen = $('notice-seen').checked;
    const body = { purpose: 'login', notice_seen: seen, age_confirmed: $('age-confirmed').checked, return_to: here() };
    if (seen && noticeVersion) body.notice_version = noticeVersion;
    status(t('login_social_working'));
    const answer = await call('POST', `/api/v1/auth/oidc/${encodeURIComponent(provider)}/start`, body);
    if (answer.status === 409 && answer.body.detail === 'notice_version_changed') {
        noticeVersion = answer.body.current_version || null;
        signupMissing(oidcError('notice_version_changed'), 'notice-seen');
        return;
    }
    if (answer.status !== 200 || typeof answer.body.authorization_url !== 'string') {
        status(loginRefused(answer, t('oidc_err_other')), 'error');
        return;
    }
    let target = null;
    try {
        target = new URL(answer.body.authorization_url);
    } catch (e) {
        target = null;
    }
    if (!target || target.protocol !== 'https:') {
        status(t('oidc_err_other'), 'error');
        return;
    }
    location.assign(target.href);
}

let signupFailed = '';

/** Back from a provider: a ticket in the fragment becomes the session; the address is cleaned at once. */
async function finishSocial() {
    const fragment = new URLSearchParams(location.hash.replace(/^#/, ''));
    const ticket = fragment.get('oidc');
    const failure = params.get('oidc_error');
    if (ticket || failure || location.hash) history.replaceState(null, '', here());
    if (failure) {
        signupFailed = failure;
        return;
    }
    if (!ticket) return;
    status(t('loading'));
    const answer = await call('POST', '/api/v1/auth/oidc/complete', { ticket });
    if (answer.status !== 200) {
        status(oidcError('state_invalid'), 'error');
        return;
    }
    keep(answer.body);
    newAccount = Boolean(answer.body.new_account);
    status('');
}

let offered = false;

async function showLogin() {
    hideAll();
    $('passkey-add').hidden = true;
    $('login-section').hidden = false;
    if (offered) return;
    offered = true;
    const methods = await call('GET', '/api/v1/auth/methods');
    const passwordLogin = methods.status === 200 && Boolean(methods.body.password_login);
    const providers = methods.status === 200 && Array.isArray(methods.body.oidc) ? methods.body.oidc : [];
    loginForm.hidden = !passwordLogin;
    enable(loginForm);
    $('passkey-row').hidden = !passkeysSupported();
    $('social-row').hidden = providers.length === 0;
    $('no-social').hidden = providers.length > 0;
    const buttons = clear($('oidc-buttons'));
    for (const item of providers) {
        buttons.append(el('button', {
            type: 'button', class: 'provider', 'data-provider': item.provider,
            text: t('login_with', { provider: item.label }), onclick: () => socialLogin(item.provider),
        }));
    }
    const box = $('notice-seen');
    const link = $('notice-link');
    if (link) {
        const notice = await call('GET', '/api/v1/privacy-notice');
        noticeVersion = notice.status === 200 && notice.body.version ? notice.body.version : null;
        link.addEventListener('click', () => {
            box.disabled = false;
            $('notice-first').hidden = true;
        });
    } else {
        // No notice published: the server makes no account (unless its operator allowed it for a trial), and says so.
        $('no-notice').hidden = false;
        box.disabled = false;
        $('notice-first').hidden = true;
    }
    for (const id of ['notice-seen', 'age-confirmed']) {
        $(id).addEventListener('change', () => {
            $('signup-error').hidden = true;
            $('signup-row').classList.remove('invalid');
            $('notice-seen').removeAttribute('aria-invalid');
            $('age-confirmed').removeAttribute('aria-invalid');
        });
    }
    if (signupFailed) {
        if (signupFailed in SIGNUP_BOX && providers.length > 0) {
            signupMissing(oidcError(signupFailed), SIGNUP_BOX[signupFailed]);
        } else {
            status(oidcError(signupFailed), 'error');
        }
        signupFailed = '';
    }
}

// ---- the page's parts --------------------------------------------------------------------------------

// The passkey offer is not one of them: it stays while the account is signed in (offerPasskey, showLogin).
const PARTS = ['login-section', 'closed', 'game-cancelled', 'reg-state', 'ticket', 'ticket-lost', 'reg-form',
    'cancel-row', 'next'];

function hideAll() {
    for (const id of PARTS) $(id).hidden = true;
}

function signedIn(s) {
    $('who').textContent = t('w_signed_in', { user: s.user.username || '' });
    const account = $('account-link');
    account.textContent = t('w_account');
    account.setAttribute('href', page.explicit ? `/staff/account?lang=${encodeURIComponent(page.lang)}` : '/staff/account');
    account.hidden = false;
    const logout = $('logout');
    logout.textContent = t('w_logout');
    logout.hidden = false;
}

$('logout').addEventListener('click', async () => {
    try {
        await api('POST', '/api/v1/auth/logout');
    } catch (e) {
        /* forgotten here either way */
    }
    forget();
    $('who').textContent = '';
    $('account-link').hidden = true;
    $('logout').hidden = true;
    reg = null;
    await showLogin();
    status(t('logged_out'), 'ok');
});

// ---- the ticket --------------------------------------------------------------------------------

/** The ticket's QR code as an SVG element (byte mode, error correction M, a 4-module quiet zone). */
function qrSvg(text) {
    const SVG = 'http://www.w3.org/2000/svg';
    const qr = qrcode(0, 'M');
    qr.addData(text, 'Byte');
    qr.make();
    const n = qr.getModuleCount();
    const q = 4;
    let d = '';
    for (let r = 0; r < n; r += 1) {
        for (let c = 0; c < n; c += 1) {
            if (qr.isDark(r, c)) d += `M${c + q} ${r + q}h1v1h-1z`;
        }
    }
    const size = n + 2 * q;
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', t('w_ticket_qr'));
    svg.setAttribute('shape-rendering', 'crispEdges');
    svg.setAttribute('data-testid', 'ticket-qr');
    const ground = document.createElementNS(SVG, 'rect');
    ground.setAttribute('width', String(size));
    ground.setAttribute('height', String(size));
    ground.setAttribute('fill', '#fff');
    const path = document.createElementNS(SVG, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', '#000');
    svg.append(ground, path);
    return svg;
}

/** Shows a ticket the server just made: it is in this answer only. */
function showTicket(text) {
    clear($('ticket-qr')).append(qrSvg(text));
    $('ticket-text').textContent = text;
    $('ticket').hidden = false;
    $('ticket-lost').hidden = true;
    $('ticket-title').focus();
}

$('ticket-title').setAttribute('tabindex', '-1');
$('print-ticket').addEventListener('click', () => window.print());

$('new-ticket').addEventListener('click', async () => {
    if (!reg || !window.confirm(t('w_new_ticket_confirm'))) return;
    status(t('loading'));
    try {
        const answer = await api('POST', `/api/v1/me/registrations/${encodeURIComponent(reg.id)}/ticket`);
        reg = answer;
        status('');
        showTicket(answer.ticket_text);
    } catch (err) {
        status(refusal(err), 'error');
    }
});

// ---- the form --------------------------------------------------------------------------------

function apdAsked(rule) {
    return Boolean(rule && (rule.checkin || rule.register || rule.expiry || rule.accepted));
}

function apdChoices() {
    const seen = new Set();
    const out = [];
    for (const e of [...(field.apds || []), ...((field.apd && field.apd.custom) || [])]) {
        if (e && typeof e.id === 'string' && !seen.has(e.id)) {
            seen.add(e.id);
            out.push(e);
        }
    }
    return out;
}

function typeName(type) {
    return has(`w_type_${type}`) ? t(`w_type_${type}`) : String(type);
}

function replicaRow(item) {
    const index = $('replicas').children.length + 1;
    const known = item && item.replica_id;  // a replica of the field's registry: its type and class are the registry's
    const types = el('select', { 'aria-label': t('w_replica_type'), class: 'replica-type', disabled: known || null },
        (field.replica_types || []).map((v) => el('option', { value: v, text: typeName(v) })));
    const classes = el('select', { 'aria-label': t('w_replica_class'), class: 'replica-class', disabled: known || null },
        el('option', { value: '', text: '—' }),
        (field.classes || []).map((v) => el('option', { value: v, text: v })));
    if (known && !(field.classes || []).includes(item.class)) classes.append(el('option', { value: item.class, text: item.class }));
    const make = el('input', { 'aria-label': t('w_replica_make'), class: 'replica-make', maxlength: MAKE_MODEL_MAX,
        placeholder: t('w_replica_make'), disabled: known || null });
    if (item) {
        types.value = item.type || '';
        classes.value = item.class || '';
        make.value = item.make_model || '';
    }
    const row = el('li', { class: 'replica-row', 'data-replica-id': known ? item.replica_id : null },
        el('span', { class: 'replica-name', text: t('w_replica_n', { n: index }) }), types, classes, make,
        el('button', { type: 'button', class: 'link replica-remove', text: t('w_replica_remove'),
            onclick: () => { row.remove(); renumber(); } }));
    $('replicas').append(row);
    renumber();
    return row;
}

function renumber() {
    [...$('replicas').children].forEach((row, i) => {
        row.querySelector('.replica-name').textContent = t('w_replica_n', { n: i + 1 });
    });
    $('replica-add').hidden = $('replicas').children.length >= field.max_replicas || !(field.classes || []).length;
}

$('replica-add').addEventListener('click', () => {
    const row = replicaRow(null);
    row.querySelector('select').focus();
});

function fillForm() {
    const rule = field.apd || {};
    $('reg-legend').textContent = t(reg && reg.status === 'registered' ? 'w_form_change' : 'w_form');
    $('reg-submit').textContent = t(reg && reg.status === 'registered' ? 'w_save' : 'w_register');
    $('reg-name').value = reg && reg.display_name ? reg.display_name : defaultName;
    // The membership block (protocol/apd.md) or, without a rule, the game's federation number.
    const withApd = apdAsked(rule);
    $('apd-block').hidden = !withApd;
    $('fed-block').hidden = withApd || game.federation === 'off';
    if (withApd) {
        const choices = apdChoices();
        const names = Object.fromEntries(choices.map((e) => [e.id, e.name]));
        $('apd-title').textContent = mt('w_apd_section');
        $('apd-accepts').textContent = rule.accepted
            ? mt('w_apd_accepts', { list: rule.accepted.map((a) => names[a] || a).join(', ') })
            : mt('w_apd_accepts_any');
        $('apd-pick-label').textContent = mt('w_apd_pick');
        const pick = clear($('apd-pick'));
        pick.append(el('option', { value: '', text: t('w_apd_unlisted') }));
        for (const e of choices) pick.append(el('option', { value: e.id, text: e.name }));
        pick.value = reg && reg.apd_id && names[reg.apd_id] ? reg.apd_id : '';
        $('apd-number-label').textContent = t(game.federation === 'required' || rule.register
            ? 'w_apd_number_required' : 'w_apd_number');
        $('apd-number').value = reg && reg.membership_number ? reg.membership_number : '';
        $('apd-expires-label').textContent = t(rule.expiry && rule.register ? 'w_apd_expires_required' : 'w_apd_expires');
        $('apd-expires').value = reg && reg.membership_expires ? reg.membership_expires : '';
    } else if (game.federation !== 'off') {
        const label = field.federation_label || '—';
        $('reg-fed-label').textContent = t(game.federation === 'required' ? 'w_fed_required' : 'w_fed_optional', { label });
        $('reg-fed').value = reg && reg.federation_number ? reg.federation_number : '';
    }
    const teams = Array.isArray(game.teams) ? game.teams : [];
    $('team-block').hidden = teams.length === 0;
    const team = clear($('reg-team'));
    team.append(el('option', { value: '', text: t('w_any_team') }));
    for (const v of teams) team.append(el('option', { value: v, text: v }));
    team.value = reg && reg.team_preference && teams.includes(reg.team_preference) ? reg.team_preference : '';
    $('replicas-block').hidden = !game.predeclare_replicas;
    clear($('replicas'));
    if (game.predeclare_replicas) {
        $('replicas-title').textContent = t('w_replicas', { n: field.max_replicas });
        for (const r of (reg && reg.status === 'registered' ? reg.replicas : []) || []) replicaRow(r);
        renumber();
    }
    $('data-note').hidden = Boolean(reg && reg.status === 'registered');
    $('reg-error').hidden = true;
    $('reg-form').hidden = false;
    enable($('reg-form'));
}

function formError(text, id) {
    const note = $('reg-error');
    note.textContent = text;
    note.hidden = false;
    status('');
    if (id) {
        $(id).setAttribute('aria-invalid', 'true');
        $(id).focus();
    } else {
        note.scrollIntoView({ block: 'center' });
    }
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

function validDate(text) {
    const m = DATE.exec(text);
    if (!m) return false;
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

/** The body the API takes, checked first as the app checks it (the server checks it all again); null when refused. */
function formBody() {
    for (const node of $('reg-form').querySelectorAll('[aria-invalid]')) node.removeAttribute('aria-invalid');
    const rule = field.apd || {};
    const name = $('reg-name').value.trim();
    if (!name) return formError(t('w_need_name'), 'reg-name');
    const body = { display_name: name, team_preference: $('reg-team').value || null };
    if (apdAsked(rule)) {
        const number = $('apd-number').value.trim();
        const expires = $('apd-expires').value.trim();
        if (expires && !validDate(expires)) return formError(t('w_bad_date'), 'apd-expires');
        if ((game.federation === 'required' || rule.register) && !number) return formError(mt('w_need_number'), 'apd-number');
        if (rule.expiry && rule.register && !expires) return formError(t('w_need_expiry'), 'apd-expires');
        Object.assign(body, { apd_id: $('apd-pick').value || null, membership_number: number || null,
            membership_expires: expires || null });
    } else if (game.federation !== 'off') {
        const fed = $('reg-fed').value.trim();
        if (game.federation === 'required' && !fed) {
            return formError(t('w_need_fed', { label: field.federation_label || '—' }), 'reg-fed');
        }
        body.federation_number = fed || null;
    }
    if (game.predeclare_replicas) {
        const rows = [...$('replicas').children];
        if (rows.length > field.max_replicas) return formError(t('w_too_many', { n: field.max_replicas }));
        body.replicas = [];
        for (const row of rows) {
            if (row.dataset.replicaId) {
                body.replicas.push({ replica_id: row.dataset.replicaId });
                continue;
            }
            const cls = row.querySelector('.replica-class');
            if (!cls.value) {
                cls.setAttribute('aria-invalid', 'true');
                return formError(t('w_need_class'));
            }
            const make = row.querySelector('.replica-make').value.trim();
            body.replicas.push({ type: row.querySelector('.replica-type').value, class: cls.value, make_model: make || null });
        }
    }
    return body;
}

$('reg-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = formBody();
    if (!body) return;
    const changing = reg && reg.status === 'registered';
    status(t('loading'));
    $('reg-submit').disabled = true;
    try {
        if (changing) {
            reg = await api('PATCH', `/api/v1/me/registrations/${encodeURIComponent(reg.id)}`, body);
            render();
            status(t('w_changed'), 'ok');
        } else {
            const answer = await api('POST', `/api/v1/fields/${encodeURIComponent(field.id)}/scheduled-games/`
                + `${encodeURIComponent(game.id)}/registrations`, body);
            reg = answer;
            render();
            status(t('w_registered_done'), 'ok');
            showTicket(answer.ticket_text);
            offerPasskey();
        }
    } catch (err) {
        formError(refusal(err));
    } finally {
        $('reg-submit').disabled = false;
    }
});

$('reg-cancel').addEventListener('click', async () => {
    if (!reg || !window.confirm(t('w_cancel_confirm', { game: game ? game.title : '' }))) return;
    status(t('loading'));
    try {
        await api('DELETE', `/api/v1/me/registrations/${encodeURIComponent(reg.id)}`);
        reg = { ...reg, status: 'cancelled' };
        await load();
        status(t('w_cancelled_done'), 'ok');
    } catch (err) {
        status(refusal(err), 'error');
    }
});

// ---- a passkey for next time --------------------------------------------------------------------------------

async function offerPasskey() {
    if (!passkeysSupported()) return;
    let methods;
    try {
        methods = await api('GET', '/api/v1/me/login-methods');
    } catch (err) {
        return;
    }
    if (!methods || (methods.passkeys || []).length > 0) return;
    $('passkey-add').hidden = false;
    // An account with a password confirms with it, and a typo would count against the login lockout: the account page
    // asks for it properly. Same when this session is short of the second factor a staff role needs (SR-1).
    const here = !(methods.password && methods.password.set) && !methods.step_up_needed;
    $('pk-add').hidden = !here;
    $('pk-elsewhere').hidden = here;
}

$('pk-add').addEventListener('click', async () => {
    status(t('loading'));
    try {
        const first = await api('POST', '/api/v1/me/passkeys/options', {});
        let credential = null;
        try {
            credential = await navigator.credentials.create({ publicKey: creationOptions(first.options) });
        } catch (e) {
            credential = null;
        }
        if (!credential) {
            status(t('passkey_cancelled'), 'error');
            return;
        }
        await api('POST', '/api/v1/me/passkeys', { challenge_token: first.challenge_token,
            credential: attestationJson(credential) });
        $('passkey-add').hidden = true;
        status(t('w_pk_added'), 'ok');
    } catch (err) {
        if (err instanceof ApiError && err.status === 403) {
            $('pk-add').hidden = true;
            $('pk-elsewhere').hidden = false;
            status('');
            return;
        }
        status(refusal(err), 'error');
    }
});

// ---- putting it together --------------------------------------------------------------------------------

/** Shows the page for the state of the game and of the account's registration. */
function render() {
    hideAll();
    const live = reg && LIVE.includes(reg.status);
    if (reg && reg.status !== 'cancelled') {
        $('reg-state-text').textContent = t(`w_reg_${reg.status}`);
        $('reg-state').hidden = false;
    }
    if (!game) {
        $('closed').hidden = Boolean(live);
        return;
    }
    if (game.status === 'cancelled') {
        $('game-cancelled').hidden = false;
        return;
    }
    const open = game.status === 'published' && game.registration_state === 'open';
    if (reg && reg.status === 'registered') {
        if (open) fillForm();
        $('cancel-row').hidden = !open;
        // A new ticket until the game starts (the server's rule: services/registration.renew_ticket).
        $('ticket-lost').hidden = !(game.status === 'published' && new Date(game.starts_at) > new Date());
        $('next').hidden = false;
    } else if (!live) {
        if (game.registration_open) fillForm();
        else $('closed').hidden = false;
    }
}

async function load() {
    const [fieldAnswer, mine] = await Promise.all([
        api('GET', `/api/v1/fields-by-slug/${encodeURIComponent(page.slug)}`),
        api('GET', '/api/v1/me/registrations'),
    ]);
    field = fieldAnswer.field;
    game = (fieldAnswer.games || []).find((g) => g.id === page.game) || null;
    const ours = (mine || []).filter((r) => r.scheduled_game_id === page.game);
    reg = ours.find((r) => r.status !== 'cancelled') || ours[0] || null;
    render();
}

async function start() {
    let s = null;
    try {
        s = await session();
    } catch (err) {
        status(refusal(err), 'error');
        return;
    }
    if (!s) {
        await showLogin();
        return;
    }
    signedIn(s);
    defaultName = GENERATED.test(s.user.username || '') ? '' : (s.user.username || '').slice(0, 32);
    try {
        await load();
    } catch (err) {
        if (!(err instanceof ApiError && err.status === 401)) status(refusal(err), 'error');
        return;
    }
    if (newAccount || (reg && reg.status === 'registered')) await offerPasskey();
    import('../staff/consent.js').then((m) => m.maybeShowNotice()).catch(() => {});  // a changed notice (CONS-*)
}

await finishSocial();
await start();
