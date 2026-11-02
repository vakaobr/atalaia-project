// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The staff login (staff_pages.py): the ways this server offers (GET /api/v1/auth/methods).
//   - password: POST /api/v1/auth/login, then /api/v1/auth/login/totp when the account has TOTP;
//   - passkey: POST /api/v1/auth/passkey/login/options, the browser's WebAuthn prompt, POST /api/v1/auth/passkey/login
//     (a passkey is both factors: no code afterwards);
//   - Google, Microsoft or Apple (OpenID Connect): POST /api/v1/auth/oidc/<provider>/start gives the provider's
//     address, the browser goes there and comes back to this page with a one-minute ticket in the address
//     fragment (or ?oidc_error=<code>), which POST /api/v1/auth/oidc/complete turns into a session. A social
//     login alone does not count as the second factor: the pages offer the TOTP or passkey step-up (stepup.js).
// The answer's access token is kept for this tab (staff.js); the refresh token is the HttpOnly cookie the server
// sets. Then back to the page that sent the browser here, if it is one of the staff pages, else the field list.

import { $, el, enable, forget, has, keep, link, status, t } from './staff.js';
import { assertionJson, passkeysSupported, requestOptions } from './webauthn.js';

const params = new URLSearchParams(location.search);

function next() {
    const wanted = params.get('next') || '';
    const safe = wanted.startsWith('/staff/') && !wanted.includes('//') && !wanted.includes('\\')
        && !wanted.startsWith('/staff/login');
    return safe ? wanted : link('/staff/');
}

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

const post = (path, body) => call('POST', path, body || {});

function refused(answer, wrong) {
    if (answer.status === 0) return t('err_network');
    if (answer.status === 429) return t('login_locked', { s: answer.retry || 60 });
    if (answer.body.detail === 'invalid_totp_session') return t('login_step_expired');
    if (answer.status === 401) return wrong;
    return t('err_generic', { code: answer.body.detail || `http_${answer.status}` });
}

const loginForm = $('login-form');
const totpForm = $('totp-form');
const alt = $('alt-logins');
let step = null;

function done(body) {
    keep(body);
    if (body.new_account) {
        // A social login that made the account: the Account page's "choose your username" step first (LG-10),
        // then on to where the browser was going.
        const account = link('/staff/account');
        location.assign(`${account}${account.includes('?') ? '&' : '?'}welcome=1&next=${encodeURIComponent(next())}`);
        return;
    }
    location.assign(next());
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
    const answer = await post('/api/v1/auth/login', { username, password });
    if (answer.status !== 200) {
        status(refused(answer, t('login_bad')), 'error');
        return;
    }
    $('password').value = '';
    if (answer.body.totp_required) {
        step = answer.body.totp_session;
        status('');
        loginForm.hidden = true;
        alt.hidden = true;
        totpForm.hidden = false;
        enable(totpForm);
        $('code').focus();
        return;
    }
    done(answer.body);
});

totpForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const code = $('code').value.replace(/\s+/g, '');
    status(t('loading'));
    const answer = await post('/api/v1/auth/login/totp', { totp_session: step, code });
    if (answer.status === 200) {
        done(answer.body);
        return;
    }
    $('code').value = '';
    status(refused(answer, t('login_bad_code')), 'error');
    if (answer.body.detail === 'invalid_totp_session') {
        step = null;
        totpForm.hidden = true;
        loginForm.hidden = false;
        alt.hidden = false;
        $('username').focus();
    }
});

// ---- passkey ------------------------------------------------------------------------------------

async function passkeyLogin() {
    status(t('loading'));
    const first = await post('/api/v1/auth/passkey/login/options');
    if (first.status !== 200) {
        status(refused(first, t('passkey_failed')), 'error');
        return;
    }
    let credential;
    try {
        credential = await navigator.credentials.get({ publicKey: requestOptions(first.body.options) });
    } catch (e) {
        status(t('passkey_cancelled'), 'error');
        return;
    }
    if (!credential) {
        status(t('passkey_cancelled'), 'error');
        return;
    }
    const answer = await post('/api/v1/auth/passkey/login', {
        challenge_token: first.body.challenge_token, credential: assertionJson(credential),
    });
    if (answer.status !== 200) {
        status(refused(answer, t('passkey_failed')), 'error');
        return;
    }
    done(answer.body);
}

// ---- Google, Microsoft, Apple -------------------------------------------------------------------

async function socialLogin(provider) {
    status(t('login_social_working'));
    const back = `${location.pathname}${location.search}`;
    // A new account (the provider's identifier is unknown here) rests on the contract (LEG-*): the person says they
    // were shown the notice and are 16 or older. Neither is read when the login already has an account.
    const seen = $('notice-seen').checked;
    const body = { purpose: 'login', notice_seen: seen, age_confirmed: $('age-confirmed').checked, return_to: back };
    if (seen && noticeVersion) body.notice_version = noticeVersion;  // the notice this page offered (CONS-7)
    const answer = await post(`/api/v1/auth/oidc/${provider}/start`, body);
    if (answer.status === 409 && answer.body && answer.body.detail === 'notice_version_changed') {
        noticeVersion = answer.body.current_version || null;  // read again; the box is ticked again on purpose
        noticeChanged();
        return;
    }
    if (answer.status !== 200 || typeof answer.body.authorization_url !== 'string') {
        status(refused(answer, t('oidc_err_other')), 'error');
        return;
    }
    let target;
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
let noticeVersion = null;  // the published privacy notice's version, read when the page opened (null: none published)

/** The notice changed after this page read it (or during the round trip): untick, and say so at the box. */
function noticeChanged() {
    $('notice-seen').checked = false;
    signupMissing(t('oidc_err_notice_version_changed'), 'notice-seen');
}

/** A refusal to make an account is shown where the boxes are, with the box it is about marked and focused. */
function signupMissing(text, boxId) {
    const row = $('signup-row');
    const box = $(boxId);
    const note = $('signup-error');
    note.textContent = text;
    note.hidden = false;
    row.classList.add('invalid');
    box.setAttribute('aria-invalid', 'true');
    status('');
    row.scrollIntoView({ block: 'center' });
    box.focus();
}

const SIGNUP_BOX = {
    notice_required: 'notice-seen', notice_version_changed: 'notice-seen', age_confirmation_required: 'age-confirmed',
};

function oidcError(code) {
    const key = `oidc_err_${code}`;
    return has(key) ? t(key) : t('oidc_err_other');
}

/** Back from a provider: a ticket in the fragment makes the session (and leaves the address at once). */
async function finishSocial() {
    const fragment = new URLSearchParams(location.hash.replace(/^#/, ''));
    const ticket = fragment.get('oidc');
    const failure = params.get('oidc_error');
    if (ticket || failure || params.get('oidc')) {
        params.delete('oidc_error');
        params.delete('oidc');
        const rest = params.toString();
        history.replaceState(null, '', `${location.pathname}${rest ? `?${rest}` : ''}`);
    }
    if (failure in SIGNUP_BOX) {
        signupFailed = failure;  // shown at the box once the buttons are on the page (offer)
        return false;
    }
    if (failure) {
        status(oidcError(failure), 'error');
        return false;
    }
    if (!ticket) return false;
    status(t('loading'));
    const answer = await post('/api/v1/auth/oidc/complete', { ticket });
    if (answer.status !== 200) {
        status(oidcError('state_invalid'), 'error');
        return false;
    }
    done(answer.body);
    return true;
}

async function offer() {
    const answer = await call('GET', '/api/v1/auth/methods');
    if (answer.status !== 200) return;
    const { password_login: passwordLogin, oidc } = answer.body;
    if (!passwordLogin) loginForm.hidden = true;
    const providers = Array.isArray(oidc) ? oidc : [];
    const buttons = $('oidc-buttons');
    for (const item of providers) {
        buttons.append(el('button', {
            type: 'button', class: 'provider', 'data-provider': item.provider,
            text: t('login_with', { provider: item.label }),
            onclick: () => socialLogin(item.provider),
        }));
    }
    $('signup-row').hidden = providers.length === 0;
    if (providers.length > 0) {
        const notice = await call('GET', '/api/v1/privacy-notice');  // 404: no notice published, nothing to name
        noticeVersion = notice.status === 200 && notice.body && notice.body.version ? notice.body.version : null;
    }
    for (const id of ['notice-seen', 'age-confirmed']) {
        $(id).addEventListener('change', () => {
            $('signup-error').hidden = true;
            $('signup-row').classList.remove('invalid');
            $('notice-seen').removeAttribute('aria-invalid');
            $('age-confirmed').removeAttribute('aria-invalid');
        });
    }
    const passkey = $('passkey-login');
    passkey.hidden = !passkeysSupported();
    passkey.addEventListener('click', passkeyLogin);
    alt.hidden = providers.length === 0 && passkey.hidden;
    $('login-or').hidden = !passwordLogin;
    if (!passwordLogin) {
        const first = alt.querySelector('button:not([hidden])');
        if (first) first.focus();
    }
    // The box is on the page now (its section was hidden until here): show the refusal there.
    if (signupFailed) {
        if (providers.length > 0) {
            if (signupFailed === 'notice_version_changed') $('notice-seen').checked = false;
            signupMissing(oidcError(signupFailed), SIGNUP_BOX[signupFailed]);
        } else status(oidcError(signupFailed), 'error');
    }
}

forget();
if (params.get('out')) status(t('logged_out'), 'ok');
enable(loginForm);
if (!(await finishSocial())) {
    await offer();
    if (!loginForm.hidden && !signupFailed) $('username').focus();
}
