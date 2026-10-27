// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Service worker of the GM console: keeps the static files (the "shell")
// so the console opens without a connection to the controller. Static
// files are fetched from the network first, so a controller update reaches
// the console at once, and come from the cache when the network fails.
// API calls and the live stream are never cached.

const CACHE = 'atalaia-console-v10';
const SHELL = [
    './',
    'index.html',
    'manifest.json',
    'style.css',
    'app.js',
    'ui.js',
    'scoreboard.html',
    'scoreboard.js',
    'scoreboard.css',
    'poster.html',
    'poster.js',
    'poster.css',
    'field-map.html',
    'field-map.js',
    'i18n/pt.json',
    'i18n/en.json',
    'i18n/de.json',
    'i18n/zh-tw.json',
    'components/adopt-panel.js',
    'components/box-invites.js',
    'components/box-language-settings.js',
    'components/branding-settings.js',
    'components/checkin-panel.js',
    'components/field-grid.js',
    'components/field-levels.js',
    'components/fetched-modes.js',
    'components/field-render.js',
    'components/field-view.js',
    'components/firmware-panel.js',
    'components/game-control.js',
    'components/georef-panel.js',
    'components/join-panel.js',
    'components/live-feed.js',
    'components/map-features.js',
    'components/mode-packages.js',
    'components/node-list.js',
    'components/ortho-coverage.js',
    'components/ortho-sources.js',
    'components/place-search.js',
    'components/poster-prompt.js',
    'components/preset-builder.js',
    'components/radio-settings.js',
    'components/remote-gm-log.js',
    'components/scenario-builder.js',
    'components/scenario-block-view.js',
    'components/scenario-blocks.js',
    'components/score-panel.js',
    'components/scoreboard-share.js',
    'components/tag-writer.js',
    'components/tile-map.js',
    'lib/preact.module.js',
    'lib/htm.module.js',
    'lib/qrcode.module.js',
    // Blockly for the scenario blocks (plan phase 7): kept too, so the block view opens offline.
    'lib/blockly/blockly_compressed.js',
    'lib/blockly/msg/en.js',
    'lib/blockly/msg/pt.js',
    'lib/blockly/media/sprites.svg',
    'lib/blockly/media/handclosed.cur',
    'lib/blockly/media/handdelete.cur',
    'lib/blockly/media/handopen.cur',
    'lib/blockly/media/delete-icon.svg',
    'lib/blockly/media/foldout-icon.svg',
    'lib/blockly/media/resize-handle.svg',
    'icons/icon-192.png',
    'icons/icon-512.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
    event.waitUntil(caches.keys()
        .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
        .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET' || url.origin !== self.location.origin
        || !url.pathname.startsWith('/console/')) {
        return; /* the API, the stream and everything else go straight to the network */
    }
    event.respondWith(fetch(event.request)
        .then((response) => {
            if (response.ok) {
                const copy = response.clone();
                caches.open(CACHE).then((cache) => cache.put(event.request, copy));
            }
            return response;
        })
        .catch(() => caches.match(event.request, { ignoreSearch: true })));
});
