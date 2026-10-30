// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings: whether the console may fetch maps from the internet (decision LEG-50). On (the default), the page
// "Load the field from a map" asks OpenStreetMap, Overpass, Nominatim and the open aerial imagery services for the
// map and the field's area. Off, the controller serves that page without those origins (api.py, console_files.dart)
// and the page says so; the field can still be loaded by uploading an image. Both controllers (the Pi and the
// phone) keep the setting.

import { html, Component, t } from '../ui.js';

export class MapFetchingSettings extends Component {
    constructor() {
        super();
        this.state = { settings: null, saved: false };
    }

    async componentDidMount() {
        const settings = await this.props.app.call('GET', '/settings/map-fetching');
        if (settings) this.setState({ settings });
    }

    async choose(on) {
        const out = await this.props.app.call('PUT', '/settings/map-fetching', { map_fetching: on });
        if (out) this.setState({ settings: out, saved: true });
    }

    render(props, state) {
        const s = state.settings;
        if (!s) return html`<section class="card"><p class="muted">…</p></section>`;
        const gm = props.app.state.role === 'gm';
        return html`<section class="card" aria-labelledby="map-fetch-h" data-testid="map-fetching-settings">
            <h2 id="map-fetch-h">${t('map_fetching.title')}</h2>
            <p class="muted small">${t('map_fetching.intro')}</p>
            <div class="field"><label><input type="checkbox" data-testid="map-fetching" checked=${s.map_fetching}
                disabled=${!gm} onChange=${(e) => this.choose(e.target.checked)} /> ${t('map_fetching.label')}</label></div>
            ${state.saved && html`<p class="ok" role="status">${t('map_fetching.saved')}</p>`}
            ${!gm && html`<p class="muted">${t('map_fetching.read_only')}</p>`}
        </section>`;
    }
}
