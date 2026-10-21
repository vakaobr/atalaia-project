// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One box's health as a table row (GET /api/v1/fields/{field}/devices and /api/v1/games/{game}/devices):
// battery, radio link, firmware against the catalogue, and its flags, each in words, not only colour.

import { el, t, when } from './staff.js';

const FLAGS = [['battery_low', 'flag_battery_low'], ['offline', 'flag_offline'], ['silent', 'flag_silent'],
    ['tampered', 'flag_tampered']];

export function flags(device) {
    const out = FLAGS.filter(([key]) => device[key]).map(([, label]) => t(label));
    if (device.firmware && device.firmware.outdated) out.push(t('flag_outdated'));
    return out;
}

function flagCell(device) {
    const list = flags(device);
    if (!list.length) return el('span', { class: 'ok', text: t('flag_ok') });
    return el('ul', { class: 'flags' }, list.map((text) => el('li', { class: 'badge', text })));
}

function radio(device) {
    const parts = [];
    if (device.rssi !== null && device.rssi !== undefined) parts.push(`${device.rssi} dBm`);
    if (device.snr !== null && device.snr !== undefined) parts.push(`SNR ${device.snr} dB`);
    if (device.tier !== null && device.tier !== undefined) parts.push(`tier ${device.tier}`);
    return parts.join(', ') || t('none');
}

function firmware(device) {
    const fw = device.firmware || {};
    const parts = [[fw.platform, fw.version].filter(Boolean).join(' ') || t('none')];
    if (fw.latest && fw.latest !== fw.version) parts.push(` (${t('fw_latest', { v: fw.latest })})`);
    return parts.join('');
}

/** The cells of one row; extra cells (the field list's game and count) go at the end. */
export function deviceCells(device, zone, extra = []) {
    const name = `${device.name} (#${device.node_id}${device.role ? `, ${device.role}` : ''})`;
    const battery = device.battery_pct === null || device.battery_pct === undefined ? t('none') : `${device.battery_pct} %`;
    return [name, battery, radio(device), firmware(device), flagCell(device), when(device.last_seen_at, zone), ...extra];
}
