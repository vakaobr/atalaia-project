// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The staff login (staff_pages.py): POST /api/v1/auth/login, then /api/v1/auth/login/totp when the
// account has TOTP. The answer's access token is kept for this tab (staff.js); the refresh token
// is the HttpOnly cookie the server sets. Then back to the page that sent the browser here, if it
// is one of the staff pages, else the field list.

import { $, enable, forget, keep, link, status, t } from './staff.js';

const params = new URLSearchParams(location.search);

function next() {
    const wanted = params.get('next') || '';
    const safe = wanted.startsWith('/staff/') && !wanted.includes('//') && !wanted.includes('\\')
        && !wanted.startsWith('/staff/login');
    return safe ? wanted : link('/staff/');
}

async function post(path, body) {
    let r;
    try {
        r = await fetch(path, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            credentials: 'same-origin', cache: 'no-store',
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

function refused(answer, wrong) {
    if (answer.status === 0) return t('err_network');
    if (answer.status === 429) return t('login_locked', { s: answer.retry || 60 });
    if (answer.body.detail === 'invalid_totp_session') return t('login_step_expired');
    if (answer.status === 401) return wrong;
    return t('err_generic', { code: answer.body.detail || `http_${answer.status}` });
}

const loginForm = $('login-form');
const totpForm = $('totp-form');
let step = null;

function done(body) {
    keep(body);
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
        $('username').focus();
    }
});

forget();
if (params.get('out')) status(t('logged_out'), 'ok');
enable(loginForm);
$('username').focus();
