// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// "Notice shown again" (decisions CONS-*, LEG-*): when the privacy notice changed since the version this account was
// last shown, the pages say so at the top and ask the person to read it and confirm they saw it (staff.js loads this
// after the session starts, as it does the step-up). The account rests on the contract, so this is information, not
// consent. GET /api/v1/me says where it stands (notice.status: current, outdated or missing); the notice itself is
// /privacy; POST /api/v1/me/notice names the version the person was shown, so a notice that changed in between is
// refused (409 notice_version_changed) and read again. Nothing is blocked: the panel is asked once per login in a
// tab (sessionStorage, forgotten with the session), and leaves when the notice is acknowledged.

import { $, api, el, errorText, link, status, t } from './staff.js';

const KEY = 'atalaia.staff.notice';

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

async function acknowledge(panel, version) {
    if (!$('notice-tick').checked) {
        status(t('notice_tick'), 'error');
        return;
    }
    status(t('loading'));
    try {
        await api('POST', '/api/v1/me/notice', { notice_version: version });
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    settle();
    panel.remove();
    status(t('notice_done'), 'ok');
}

function offer(notice) {
    const intro = notice.status === 'outdated'
        ? t('notice_intro_outdated', { old: notice.version, version: notice.current_version })
        : t('notice_intro_missing', { version: notice.current_version });
    const panel = el('section', { id: 'notice-again', class: 'notice' }, el('h2', { text: t('notice_title') }),
        el('p', { text: intro }));
    panel.append(notice.notice_published
        ? el('p', {}, el('a', { href: link('/privacy'), target: '_blank', rel: 'noopener', text: t('notice_read') }))
        : el('p', { text: t('notice_no_notice') }));
    const form = el('form', { class: 'staff-form', novalidate: true },
        el('label', {}, el('input', { type: 'checkbox', id: 'notice-tick' }), ' ', t('notice_accept')),
        el('button', { type: 'submit', id: 'notice-button', text: t('notice_button') }));
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        acknowledge(panel, notice.current_version);
    });
    panel.append(form);
    $('status').before(panel);
}

/** Called once the session has started: shows the notice again when the account was last shown another version. */
export async function maybeShowNotice() {
    if (asked()) return;
    let me;
    try {
        me = await api('GET', '/api/v1/me');
    } catch (err) {
        return;
    }
    const notice = me && me.notice;
    if (!notice) return;
    if (notice.status === 'current') settle();
    else offer(notice);
}
