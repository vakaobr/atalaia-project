// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The second factor for a session that logged in without one (staff.js loads this when a session has no
// "mfa" and the account holds a role that needs it). A social login (Google, Microsoft, Apple) alone never counts:
// the admin, GM and marshal roles count only after a TOTP code (POST /api/v1/auth/stepup/totp) or a passkey
// (POST /api/v1/auth/stepup/passkey/options, the browser's prompt, POST /api/v1/auth/stepup/passkey). The page
// reloads afterwards, so every section shows what the roles now allow.

import { $, ApiError, api, el, errorText, markMfa, status, t } from './staff.js';
import { assertionJson, passkeysSupported, requestOptions } from './webauthn.js';

const PRIVILEGED = ['admin', 'gm', 'marshal'];

function finished() {
    markMfa();
    status(t('stepup_done'), 'ok');
    setTimeout(() => location.reload(), 600);
}

function failure(err, wrong) {
    if (err instanceof ApiError && err.status === 403 && err.code === 'invalid_code') return wrong;
    if (err instanceof ApiError && err.status === 401 && err.code === 'invalid_passkey') return t('passkey_failed');
    return errorText(err);
}

async function withTotp(form) {
    const code = $('stepup-code').value.replace(/\s+/g, '');
    if (!code) return;
    status(t('loading'));
    try {
        await api('POST', '/api/v1/auth/stepup/totp', { code });
    } catch (err) {
        $('stepup-code').value = '';
        status(failure(err, t('login_bad_code')), 'error');
        return;
    }
    finished();
    form.hidden = true;
}

async function withPasskey() {
    status(t('loading'));
    try {
        const first = await api('POST', '/api/v1/auth/stepup/passkey/options');
        let credential;
        try {
            credential = await navigator.credentials.get({ publicKey: requestOptions(first.options) });
        } catch (e) {
            credential = null;
        }
        if (!credential) {
            status(t('passkey_cancelled'), 'error');
            return;
        }
        await api('POST', '/api/v1/auth/stepup/passkey', {
            challenge_token: first.challenge_token, credential: assertionJson(credential),
        });
    } catch (err) {
        status(failure(err, t('passkey_failed')), 'error');
        return;
    }
    finished();
}

/** Puts the step-up panel at the top of the page for an account that has a second factor to offer. */
async function offer() {
    let methods;
    try {
        methods = await api('GET', '/api/v1/me/login-methods');
    } catch (err) {
        return;
    }
    const passkey = passkeysSupported() && methods.passkeys.length > 0;
    const panel = el('section', { id: 'stepup', class: 'notice' },
        el('h2', { text: t('stepup_title') }), el('p', { text: t('stepup_intro') }));
    if (!methods.totp_enabled && !passkey) {
        panel.append(el('p', { text: t('stepup_none') }));
    }
    if (methods.totp_enabled) {
        const form = el('form', { class: 'staff-form', novalidate: true },
            el('label', { for: 'stepup-code', text: t('totp_code') }),
            el('input', { id: 'stepup-code', name: 'code', inputmode: 'numeric', autocomplete: 'one-time-code',
                maxlength: '8', pattern: '[0-9]{6,8}', required: true }),
            el('button', { type: 'submit', text: t('stepup_totp_button') }));
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            withTotp(form);
        });
        panel.append(form);
    }
    if (passkey) {
        panel.append(el('p', {}, el('button', { type: 'button', id: 'stepup-passkey', text: t('stepup_passkey_button'),
            onclick: withPasskey })));
    }
    $('status').before(panel);
}

/** Called for a session without "mfa": offers the step-up when the account holds a role that needs it. */
export async function maybeStepUp() {
    let me;
    try {
        me = await api('GET', '/api/v1/me');
    } catch (err) {
        return;
    }
    const roles = Object.values(me.roles || {}).flat();
    if (me.server_admin || roles.some((r) => PRIVILEGED.includes(r))) await offer();
}
