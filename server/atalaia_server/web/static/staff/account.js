// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The account page (staff_pages.py, decisions ACC-*): the logged-in account's own login methods, on the endpoints
// that already exist. The page holds no rule: it shows what the server says (GET /api/v1/me/login-methods,
// GET /api/v1/auth/methods) and every refusal in words.
//   - Google, Microsoft, Apple: POST /api/v1/auth/oidc/<provider>/start with purpose "link" (or "reauth" to confirm)
//     sends the browser to the provider; it comes back here with ?oidc=linked|reauth or ?oidc_error=<code>;
//     DELETE /api/v1/me/identities/<provider> unlinks;
//   - passkeys: POST /api/v1/me/passkeys/options, the browser's prompt, POST /api/v1/me/passkeys;
//     PATCH and DELETE /api/v1/me/passkeys/<id> rename and remove;
//   - the password: POST /api/v1/me/password sets or changes it, DELETE /api/v1/me/password removes it;
//   - TOTP: POST /api/v1/auth/totp/enrol, /confirm and /disable;
//   - the confirmation a sensitive change asks for: the current password (sent with the change), or for an account with
//     none a proof from the last ten minutes: a TOTP code (POST /api/v1/auth/stepup/totp), a passkey
//     (POST /api/v1/auth/stepup/passkey/options and /passkey) or the provider again (purpose "reauth").

import { $, ApiError, api, boot, clear, el, enable, errorText, has, link, markMfa, session, status, t, when } from './staff.js';
import { attestationJson, assertionJson, creationOptions, passkeysSupported, requestOptions } from './webauthn.js';

const HOME = '/staff/account';
let methods = null;
let offered = [];
let working = false;

// ---- words for a refusal --------------------------------------------------------------------

function refusal(err) {
    if (err instanceof ApiError && has(`acct_e_${err.code}`)) return t(`acct_e_${err.code}`);
    return errorText(err);
}

function fail(err) {
    if (err instanceof ApiError && err.code === 'not_authenticated') return;
    status(refusal(err), 'error');
    if (err instanceof ApiError && err.status === 403 && ['confirmation_required', 'invalid_password'].includes(err.code)) {
        const box = $('confirm-password-box').hidden ? $('confirm-recent-box') : $('confirm-password-box');
        const target = box.querySelector('input, button');
        if (target) target.focus();
    }
}

/** Runs one action: one at a time, its refusal shown in words. */
async function guarded(work) {
    if (working) return false;
    working = true;
    try {
        await work();
        return true;
    } catch (err) {
        fail(err);
        return false;
    } finally {
        working = false;
    }
}

const currentPassword = () => $('confirm-password').value;

/** An account with a password sends it with each sensitive change: asks for it when the box is empty. */
function needsPassword() {
    if (!methods.password.set || currentPassword()) return false;
    status(t('acct_confirm_password_hint'), 'error');
    $('confirm-password').focus();
    return true;
}

// ---- the page ---------------------------------------------------------------------------------

async function reload() {
    methods = await api('GET', '/api/v1/me/login-methods');
    const server = await api('GET', '/api/v1/auth/methods');
    offered = Array.isArray(server.oidc) ? server.oidc : [];
    render(server);
}

function render(server) {
    $('confirm').hidden = false;
    $('confirm-password-box').hidden = !methods.password.set;
    $('confirm-recent-box').hidden = methods.password.set;
    renderConfirm();
    renderProviders();
    renderPasskeys();
    renderPassword(Boolean(server.password_login));
    renderTotp();
}

function renderConfirm() {
    const form = $('confirm-totp-form');
    form.hidden = !methods.totp_enabled;
    enable(form);
    $('confirm-passkey').hidden = !(passkeysSupported() && methods.passkeys.length > 0);
    const box = clear($('confirm-providers'));
    for (const item of methods.identities) {
        if (!offered.some((o) => o.provider === item.provider)) continue;
        box.append(el('button', {
            type: 'button', class: 'provider', 'data-provider': item.provider, 'data-purpose': 'reauth',
            text: t('acct_confirm_with', { provider: item.label }), onclick: () => guarded(() => startProvider(item.provider, 'reauth')),
        }));
    }
}

function renderProviders() {
    const list = clear($('providers'));
    for (const item of methods.identities) {
        const facts = [t('acct_provider_linked_at', { when: when(item.linked_at) })];
        if (item.last_login_at) facts.push(t('acct_provider_last_login', { when: when(item.last_login_at) }));
        list.append(el('li', { 'data-provider': item.provider },
            el('span', { class: 'title', text: item.label }), ' ', el('span', { class: 'when', text: facts.join(' · ') }),
            el('span', { class: 'actions' }, el('button', {
                type: 'button', class: 'danger', 'data-act': 'unlink', text: t('acct_unlink'),
                onclick: () => guarded(() => unlink(item)),
            }))));
    }
    $('providers-none').hidden = methods.identities.length > 0 || offered.length === 0;
    $('providers-off').hidden = offered.length > 0;
    const buttons = clear($('link-buttons'));
    for (const item of offered) {
        if (methods.identities.some((i) => i.provider === item.provider)) continue;
        buttons.append(el('button', {
            type: 'button', class: 'provider', 'data-provider': item.provider, 'data-purpose': 'link',
            text: t('acct_link', { provider: item.label }), onclick: () => guarded(() => startProvider(item.provider, 'link')),
        }));
    }
}

function renderPasskeys() {
    const list = clear($('passkeys'));
    for (const key of methods.passkeys) list.append(passkeyRow(key));
    $('passkeys-none').hidden = methods.passkeys.length > 0;
    const supported = passkeysSupported();
    $('passkey-form').hidden = !supported;
    $('passkey-unsupported').hidden = supported;
    enable($('passkey-form'));
}

function passkeyRow(key) {
    const facts = [key.backed_up ? t('acct_passkey_synced') : t('acct_passkey_device'),
        t('acct_passkey_created', { when: when(key.created_at) }),
        key.last_used_at ? t('acct_passkey_used', { when: when(key.last_used_at) }) : t('acct_passkey_unused')];
    const row = el('li', { 'data-passkey': key.id },
        el('span', { class: 'title', text: key.name }), ' ', el('span', { class: 'when', text: facts.join(' · ') }),
        el('span', { class: 'actions' },
            el('button', { type: 'button', 'data-act': 'rename', text: t('acct_rename'), onclick: () => renameForm(row, key) }),
            el('button', {
                type: 'button', class: 'danger', 'data-act': 'remove', text: t('acct_passkey_remove'),
                onclick: () => guarded(() => removePasskey(key)),
            })));
    return row;
}

function renameForm(row, key) {
    const input = el('input', { id: `rename-${key.id}`, value: key.name, maxlength: '64', autocomplete: 'off' });
    const form = el('form', { class: 'staff-form rename', novalidate: true },
        el('label', { for: input.id, text: t('acct_passkey_rename_label') }), input,
        el('button', { type: 'submit', text: t('save') }),
        el('button', { type: 'button', class: 'danger', text: t('cancel'), onclick: () => row.replaceWith(passkeyRow(key)) }));
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        guarded(async () => {
            await api('PATCH', `/api/v1/me/passkeys/${encodeURIComponent(key.id)}`, { name: input.value });
            await reload();
            status(t('acct_passkey_renamed'), 'ok');
        });
    });
    clear(row).append(form);
    input.focus();
}

function renderPassword(passwordLogin) {
    const isSet = methods.password.set;
    $('password-state').textContent = isSet ? t('acct_pw_state_set') : t('acct_pw_state_none');
    $('password-off').hidden = passwordLogin;
    $('password-form').hidden = !passwordLogin;
    enable($('password-form'));
    $('password-save').textContent = isSet ? t('acct_pw_change_button') : t('acct_pw_set_button');
    $('password-remove').hidden = !isSet;
}

function renderTotp() {
    const on = methods.totp_enabled;
    $('totp-state').textContent = on ? t('acct_totp_on') : t('acct_totp_off');
    $('totp-enable').hidden = on;
    $('totp-confirm-form').hidden = true;
    $('totp-disable-form').hidden = !on;
    enable($('totp-disable-form'));
}

// ---- Google, Microsoft, Apple -------------------------------------------------------------------

async function startProvider(provider, purpose) {
    if (purpose === 'link' && needsPassword()) return;
    status(t('login_social_working'));
    const body = { purpose, return_to: link(HOME) };
    if (purpose === 'link') body.password = currentPassword();
    const answer = await api('POST', `/api/v1/auth/oidc/${encodeURIComponent(provider)}/start`, body);
    let target = null;
    try {
        target = new URL(answer.authorization_url);
    } catch (e) {
        target = null;
    }
    if (!target || target.protocol !== 'https:') {
        status(t('oidc_err_other'), 'error');
        return;
    }
    location.assign(target.href);
}

async function unlink(item) {
    if (needsPassword()) return;
    if (!window.confirm(t('acct_unlink_confirm', { provider: item.label }))) return;
    await api('DELETE', `/api/v1/me/identities/${encodeURIComponent(item.provider)}`, { password: currentPassword() });
    $('confirm-password').value = '';
    await reload();
    status(t('acct_unlinked'), 'ok');
}

/** Back from a provider: ?oidc=linked|reauth, or ?oidc_error=<code>; the address is cleaned at once. */
function finishProvider() {
    const params = new URLSearchParams(location.search);
    const ok = params.get('oidc');
    const failure = params.get('oidc_error');
    if (!ok && !failure) return;
    params.delete('oidc');
    params.delete('oidc_error');
    const rest = params.toString();
    history.replaceState(null, '', `${location.pathname}${rest ? `?${rest}` : ''}`);
    if (failure) {
        status(has(`oidc_err_${failure}`) ? t(`oidc_err_${failure}`) : t('oidc_err_other'), 'error');
    } else if (ok === 'linked') {
        status(t('acct_linked'), 'ok');
    } else if (ok === 'reauth') {
        status(t('acct_reauthed'), 'ok');
    }
}

// ---- passkeys -------------------------------------------------------------------------------------

async function addPasskey() {
    if (needsPassword()) return;
    status(t('loading'));
    const first = await api('POST', '/api/v1/me/passkeys/options', { password: currentPassword() });
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
    const name = $('passkey-name').value.trim();
    await api('POST', '/api/v1/me/passkeys', {
        challenge_token: first.challenge_token, credential: attestationJson(credential), ...(name ? { name } : {}),
    });
    $('passkey-name').value = '';
    $('confirm-password').value = '';
    await reload();
    status(t('acct_passkey_added'), 'ok');
}

async function removePasskey(key) {
    if (needsPassword()) return;
    if (!window.confirm(t('acct_passkey_remove_confirm', { name: key.name }))) return;
    await api('DELETE', `/api/v1/me/passkeys/${encodeURIComponent(key.id)}`, { password: currentPassword() });
    $('confirm-password').value = '';
    await reload();
    status(t('acct_passkey_removed'), 'ok');
}

// ---- the password -----------------------------------------------------------------------------------

async function savePassword() {
    if (needsPassword()) return;
    const next = $('new-password').value;
    if (!next) return;
    await api('POST', '/api/v1/me/password', { password: currentPassword(), new_password: next });
    $('new-password').value = '';
    $('confirm-password').value = '';
    await reload();
    status(t('acct_pw_changed'), 'ok');
}

async function removePassword() {
    if (needsPassword()) return;
    if (!window.confirm(t('acct_pw_remove_confirm'))) return;
    await api('DELETE', '/api/v1/me/password', { password: currentPassword() });
    $('confirm-password').value = '';
    await reload();
    status(t('acct_pw_removed'), 'ok');
}

// ---- TOTP ----------------------------------------------------------------------------------------------

async function enrolTotp() {
    if (needsPassword()) return;
    const answer = await api('POST', '/api/v1/auth/totp/enrol', { password: currentPassword() });
    $('totp-secret').textContent = answer.secret;
    $('totp-uri').textContent = answer.otpauth_uri;
    $('totp-enrol-intro').textContent = t('acct_totp_enrol_intro', { digits: answer.digits, s: answer.period_s });
    $('totp-enable').hidden = true;
    const form = $('totp-confirm-form');
    form.hidden = false;
    enable(form);
    status('');
    $('totp-enrol-code').focus();
}

async function confirmTotp() {
    const code = $('totp-enrol-code').value.replace(/\s+/g, '');
    if (!code) return;
    try {
        await api('POST', '/api/v1/auth/totp/confirm', { code });
    } catch (err) {
        $('totp-enrol-code').value = '';
        throw err;
    }
    markMfa();
    $('totp-enrol-code').value = '';
    $('confirm-password').value = '';
    await reload();
    status(t('acct_totp_enabled'), 'ok');
}

async function disableTotp() {
    if (needsPassword()) return;
    const code = $('totp-disable-code').value.replace(/\s+/g, '');
    if (!code) return;
    try {
        await api('POST', '/api/v1/auth/totp/disable', { password: currentPassword(), code });
    } catch (err) {
        $('totp-disable-code').value = '';
        throw err;
    }
    $('totp-disable-code').value = '';
    $('confirm-password').value = '';
    try {
        await session(true);  // the sessions lost their second-factor mark: take the new one
    } catch (e) {
        /* the next page asks again */
    }
    await reload();
    status(t('acct_totp_disabled'), 'ok');
}

// ---- the confirmation for an account with no password ---------------------------------------------------

async function confirmWithTotp() {
    const code = $('confirm-code').value.replace(/\s+/g, '');
    if (!code) return;
    try {
        await api('POST', '/api/v1/auth/stepup/totp', { code });
    } catch (err) {
        $('confirm-code').value = '';
        throw err;
    }
    $('confirm-code').value = '';
    markMfa();
    status(t('acct_confirmed'), 'ok');
}

async function confirmWithPasskey() {
    status(t('loading'));
    const first = await api('POST', '/api/v1/auth/stepup/passkey/options');
    let credential = null;
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
    markMfa();
    status(t('acct_confirmed'), 'ok');
}

// ---- start ------------------------------------------------------------------------------------------------

function submit(id, work) {
    $(id).addEventListener('submit', (event) => {
        event.preventDefault();
        guarded(work);
    });
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    $('account-link').setAttribute('aria-current', 'page');
    try {
        await reload();
    } catch (err) {
        fail(err);
        return;
    }
    finishProvider();
    submit('passkey-form', addPasskey);
    submit('password-form', savePassword);
    submit('confirm-totp-form', confirmWithTotp);
    submit('totp-confirm-form', confirmTotp);
    submit('totp-disable-form', disableTotp);
    $('password-remove').addEventListener('click', () => guarded(removePassword));
    $('totp-enable').addEventListener('click', () => guarded(enrolTotp));
    $('confirm-passkey').addEventListener('click', () => guarded(confirmWithPasskey));
}

main();
