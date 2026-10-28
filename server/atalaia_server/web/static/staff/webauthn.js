// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// WebAuthn in the browser (login.js, stepup.js): the server's options (JSON, binary values in base64url) become
// what navigator.credentials wants, and the browser's answers become the JSON the server reads
// (server/atalaia_server/passkeys.py). Nothing here decides anything: the server checks every byte.

export function passkeysSupported() {
    return Boolean(window.PublicKeyCredential && navigator.credentials && navigator.credentials.get);
}

export function fromB64u(text) {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
    const raw = atob(padded);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return bytes.buffer;
}

export function toB64u(buffer) {
    let raw = '';
    for (const byte of new Uint8Array(buffer)) raw += String.fromCharCode(byte);
    return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function descriptors(list) {
    return (list || []).map((item) => ({ ...item, id: fromB64u(item.id) }));
}

/** The server's options for navigator.credentials.get. */
export function requestOptions(options) {
    const out = { ...options, challenge: fromB64u(options.challenge) };
    if (options.allowCredentials) out.allowCredentials = descriptors(options.allowCredentials);
    return out;
}

/** The server's options for navigator.credentials.create. */
export function creationOptions(options) {
    return {
        ...options,
        challenge: fromB64u(options.challenge),
        user: { ...options.user, id: fromB64u(options.user.id) },
        excludeCredentials: descriptors(options.excludeCredentials),
    };
}

function base(credential) {
    const out = {
        id: credential.id, rawId: toB64u(credential.rawId), type: credential.type,
        clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    };
    if (credential.authenticatorAttachment) out.authenticatorAttachment = credential.authenticatorAttachment;
    return out;
}

/** What the server reads of a finished navigator.credentials.get. */
export function assertionJson(credential) {
    const r = credential.response;
    const response = {
        clientDataJSON: toB64u(r.clientDataJSON), authenticatorData: toB64u(r.authenticatorData),
        signature: toB64u(r.signature),
    };
    if (r.userHandle && r.userHandle.byteLength) response.userHandle = toB64u(r.userHandle);
    return { ...base(credential), response };
}

/** What the server reads of a finished navigator.credentials.create. */
export function attestationJson(credential) {
    const r = credential.response;
    return {
        ...base(credential),
        response: {
            clientDataJSON: toB64u(r.clientDataJSON), attestationObject: toB64u(r.attestationObject),
            transports: r.getTransports ? r.getTransports() : [],
        },
    };
}
