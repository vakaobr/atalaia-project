// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One image slot (a field's logo or wallpaper, a team's or a club's crest), shared by the branding and the
// club pages: what is set (its type, size and the start of its SHA-256: the server shows no picture), a file to
// upload (the raw body with its type, PUT ...?rights_confirmed=<the box>) and removing it (DELETE). The checks
// (type, size, dimensions, that the uploader confirmed the rights) are the API's: the box is sent as it is
// and its refusal shown in words.

import { api, el, errorText, status, t } from './staff.js';

let counter = 0;

/** The slot as a fieldset. image: the API's image reference or null; paths: {put, del}; changed(): called after
 * a successful change so the page can load again; roles: the roles for a 403's words. */
export function imageBlock({ title, image, put, del, changed, roles, note }) {
    counter += 1;
    const fileId = `img-file-${counter}`;
    const rightsId = `img-rights-${counter}`;
    const file = el('input', { id: fileId, type: 'file' });
    const rights = el('input', { id: rightsId, type: 'checkbox' });
    const current = image
        ? t('image_current', { type: image.content_type, w: image.width, h: image.height, bytes: image.bytes,
            sha: image.sha256.slice(0, 12) })
        : t('image_none');
    const upload = el('button', {
        type: 'button', text: t('image_upload'),
        onclick: async () => {
            const chosen = file.files && file.files[0];
            if (!chosen) {
                file.focus();
                status(t('image_choose'), 'error');
                return;
            }
            try {
                await api('PUT', `${put}?rights_confirmed=${rights.checked ? 'true' : 'false'}`, chosen,
                    { type: chosen.type });
                status(t('image_saved'), 'ok');
                await changed();
            } catch (err) {
                status(errorText(err, roles), 'error');
            }
        },
    });
    const remove = image ? el('button', {
        type: 'button', class: 'danger', text: t('image_remove'),
        onclick: async () => {
            try {
                await api('DELETE', del);
                status(t('image_removed'), 'ok');
                await changed();
            } catch (err) {
                status(errorText(err, roles), 'error');
            }
        },
    }) : null;
    return el('fieldset', { class: 'image-slot' }, el('legend', { text: title }),
        el('p', { text: current }), note ? el('p', { class: 'hint', text: note }) : null,
        el('label', { for: fileId, text: t('image_file') }), file,
        el('p', { class: 'check' }, rights, ' ', el('label', { for: rightsId, text: t('image_rights') })),
        el('p', {}, upload, ' ', remove));
}
