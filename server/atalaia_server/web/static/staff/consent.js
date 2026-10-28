// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// "Consent again" (decisions CONS-*): when the privacy notice changed since the account consented, the pages
// say so at the top and ask for the new consent (staff.js loads this after the session starts, as it does the
// step-up). GET /api/v1/me says where the consent stands (consent.status: current, outdated or missing); the
// notice itself is /privacy; POST /api/v1/me/consents/account names the version the person was shown, so a notice
// that changed in between is refused (409 notice_version_changed) and read again. Nothing is blocked: the panel is
// asked once per login in a tab (sessionStorage, forgotten with the session), and leaves when the consent is given.

import { $, api, el, errorText, link, status, t } from './staff.js';

const KEY = 'atalaia.staff.consent';

function asked() {
    try {
        return window.sessionStorage.getItem(KEY) === 'ok';
    } catch (e) {
        return false;
    }
}

function settle() {
    try {
        window.sessionStorage.setItem(KEY, 'ok');
    } catch (e) {
        /* storage refused: asked again on the next page */
    }
}

async function agree(panel, version) {
    if (!$('consent-tick').checked) {
        status(t('consent_tick'), 'error');
        return;
    }
    status(t('loading'));
    try {
        await api('POST', '/api/v1/me/consents/account', { notice_version: version });
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    settle();
    panel.remove();
    status(t('consent_done'), 'ok');
}

function offer(consent) {
    const intro = consent.status === 'outdated'
        ? t('consent_intro_outdated', { old: consent.version, version: consent.current_version })
        : t('consent_intro_missing', { version: consent.current_version });
    const panel = el('section', { id: 'consent', class: 'notice' }, el('h2', { text: t('consent_title') }),
        el('p', { text: intro }));
    panel.append(consent.notice_published
        ? el('p', {}, el('a', { href: link('/privacy'), target: '_blank', rel: 'noopener', text: t('consent_read') }))
        : el('p', { text: t('consent_no_notice') }));
    const form = el('form', { class: 'staff-form', novalidate: true },
        el('label', {}, el('input', { type: 'checkbox', id: 'consent-tick' }), ' ', t('consent_accept')),
        el('button', { type: 'submit', id: 'consent-button', text: t('consent_button') }));
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        agree(panel, consent.current_version);
    });
    panel.append(form);
    $('status').before(panel);
}

/** Called once the session has started: asks for the consent again when the account's is not for the current notice. */
export async function maybeAskConsent() {
    if (asked()) return;
    let me;
    try {
        me = await api('GET', '/api/v1/me');
    } catch (err) {
        return;
    }
    const consent = me && me.consent;
    if (!consent) return;
    if (consent.status === 'current') settle();
    else offer(consent);
}
