// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The hub link code page (staff_pages.py, decisions HLC-*): in hosted mode, a person's accounts at different fields
// are tied with a one-time link code (SVX-2), on the endpoints that already exist (api/hub_share.py):
//   - GET /api/v1/me/hub-share says whether this account is linked, whether sharing is on, this field (id, name,
//     its own switch and terms), whether the account's consent for it is live, and the other fields the person is
//     linked at; a single-field server answers 404 not_hosted and the page says there is nothing to link;
//   - POST /api/v1/me/hub-share/code makes a code (shown once, 15 minutes, used once);
//   - POST /api/v1/me/hub-share/link {code} links this account to the person the code names;
//   - DELETE /api/v1/me/hub-share unlinks (this field's records leave the hub's view);
//   - the consent sharing needs at this field: PUT and DELETE /api/v1/me/consents/chrono-sharing/<field id>.
// The page holds no rule: the server decides, and every refusal is shown in words (the API answers one
// invalid_code for a wrong, expired or used code, on purpose, so the text names the three). At most 10 codes or
// links an hour per account: a 429 shows how long to wait.

import { $, ApiError, api, boot, clear, el, enable, errorText, has, status, t, when } from './staff.js';

let current = null;
let working = false;
let hideTimer = null;

function refusal(err) {
    if (err instanceof ApiError && has(`hub_e_${err.code}`)) return t(`hub_e_${err.code}`);
    return errorText(err);
}

function fail(err) {
    if (err instanceof ApiError && err.code === 'not_authenticated') return;
    status(refusal(err), 'error');
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

function submit(id, handler) {
    const form = $(id);
    enable(form);
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        guarded(handler);
    });
}

function hideCode() {
    if (hideTimer) window.clearTimeout(hideTimer);
    hideTimer = null;
    $('code-box').hidden = true;
    $('code-value').textContent = '';
}

function show(state) {
    current = state;
    const field = state.field || {};
    $('hub-field').textContent = t('hub_state_field', { field: field.name || '' });
    $('hub-state').textContent = state.linked
        ? t('hub_state_linked', { when: state.linked_at ? when(state.linked_at) : '' })
        : t('hub_state_unlinked');
    $('hub-sharing').textContent = state.sharing ? t('hub_sharing_on') : t('hub_sharing_off');
    $('hub-field-off').hidden = Boolean(field.live);
    $('consent-state').textContent = state.consent ? t('hub_consent_given') : t('hub_consent_none');
    $('consent-form').hidden = Boolean(state.consent);
    $('consent-withdraw').hidden = !state.consent;
    $('hub-unlink-section').hidden = !state.linked;
    const list = clear($('hub-others'));
    if (state.linked) {
        list.append(el('li', {}, el('span', { class: 'title', text: t('hub_others_this', { field: field.name || '' }) }),
            el('span', { class: 'when', text: state.sharing ? t('hub_other_on') : t('hub_other_off') })));
    }
    for (const other of state.others || []) {
        list.append(el('li', {}, el('span', { class: 'title', text: other.field_name }),
            el('span', { class: 'when', text: `${other.sharing ? t('hub_other_on') : t('hub_other_off')}, ${t('hub_other_since', { when: when(other.since) })}` })));
    }
    $('hub-others-none').hidden = (state.others || []).length > 0;
}

async function reload() {
    show(await api('GET', '/api/v1/me/hub-share'));
}

async function makeCode() {
    status('');
    const made = await api('POST', '/api/v1/me/hub-share/code');
    await reload();
    hideCode();
    $('code-value').textContent = made.code;
    $('code-note').textContent = t('hub_code_note', { minutes: Math.ceil((made.expires_in || 900) / 60) });
    $('code-box').hidden = false;
    $('code-copy').hidden = !(navigator.clipboard && navigator.clipboard.writeText);
    hideTimer = window.setTimeout(() => {
        hideCode();
        status(t('hub_code_gone'));
    }, (made.expires_in || 900) * 1000);
}

async function copyCode() {
    try {
        await navigator.clipboard.writeText($('code-value').textContent);
        status(t('hub_copied'), 'ok');
    } catch (err) {
        /* the code is on the page to select: nothing to say */
    }
}

async function linkCode() {
    const code = $('link-code').value.trim();
    if (!code) {
        status(t('hub_code_needed'), 'error');
        $('link-code').focus();
        return;
    }
    status('');
    await api('POST', '/api/v1/me/hub-share/link', { code });
    $('link-code').value = '';
    hideCode();
    await reload();
    status(t('hub_linked_ok'), 'ok');
}

async function unlink() {
    if (!window.confirm(t('hub_unlink_confirm'))) return;
    status('');
    await api('DELETE', '/api/v1/me/hub-share');
    hideCode();
    await reload();
    status(t('hub_unlinked_ok'), 'ok');
}

async function giveConsent() {
    if (!$('consent-tick').checked) {
        status(t('hub_consent_tick_needed'), 'error');
        $('consent-tick').focus();
        return;
    }
    status('');
    await api('PUT', `/api/v1/me/consents/chrono-sharing/${encodeURIComponent(current.field.id)}`);
    $('consent-tick').checked = false;
    await reload();
    status(t('hub_consent_saved'), 'ok');
}

async function withdrawConsent() {
    if (!window.confirm(t('hub_consent_withdraw_confirm'))) return;
    status('');
    await api('DELETE', `/api/v1/me/consents/chrono-sharing/${encodeURIComponent(current.field.id)}`);
    await reload();
    status(t('hub_consent_withdrawn'), 'ok');
}

async function main() {
    const ctx = await boot();
    if (!ctx) return;
    $('account-link').setAttribute('aria-current', 'page');
    try {
        await reload();
    } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'not_hosted') {
            $('hub-none').hidden = false;  // a single-field server: nothing to link
            return;
        }
        fail(err);
        return;
    }
    $('hub-main').hidden = false;
    submit('consent-form', giveConsent);
    submit('link-form', linkCode);
    $('code-make').disabled = false;
    $('code-make').addEventListener('click', () => guarded(makeCode));
    $('code-copy').addEventListener('click', copyCode);
    $('unlink').addEventListener('click', () => guarded(unlink));
    $('consent-withdraw').addEventListener('click', () => guarded(withdrawConsent));
}

main();
