// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings: the language of the boxes' screens (join payload key 15, RFC 0001
// Amendment 10). "auto", the default, gives each game the language of the
// console it was created in; Portuguese or English fixes it for the field. A
// game keeps the language it was created with; every join payload of the game
// (card, QR code, text, radio invite) carries it.

import { html, Component, t } from '../ui.js';

export class BoxLanguageSettings extends Component {
    constructor() {
        super();
        this.state = { settings: null, saved: false };
    }

    async componentDidMount() {
        const settings = await this.props.app.call('GET', '/settings/box-language');
        if (settings) this.setState({ settings });
    }

    async choose(value) {
        const out = await this.props.app.call('PUT', '/settings/box-language', { box_language: value });
        if (out) this.setState({ settings: out, saved: true });
    }

    render(props, state) {
        const s = state.settings;
        if (!s) return html`<section class="card"><p class="muted">…</p></section>`;
        const gm = props.app.state.role === 'gm';
        return html`<section class="card" aria-labelledby="box-lang-h" data-testid="box-language-settings">
            <h2 id="box-lang-h">${t('box_language.title')}</h2>
            <p class="muted small">${t('box_language.intro')}</p>
            <div class="field"><label for="box-lang">${t('box_language.label')}</label>
                <select id="box-lang" data-testid="box-language" disabled=${!gm}
                    onChange=${(e) => this.choose(e.target.value)}>
                    ${s.choices.map((c) => html`<option value=${c} selected=${c === s.box_language}>${t(`box_language.choices.${c}`)}</option>`)}
                </select></div>
            ${s.game_box_language && html`<p class="muted small" data-testid="box-language-game">${t('box_language.live', { lang: t(`box_language.choices.${s.game_box_language}`) })}</p>`}
            ${state.saved && html`<p class="ok" role="status">${t('box_language.saved')}</p>`}
            ${!gm && html`<p class="muted">${t('box_language.read_only')}</p>`}
        </section>`;
    }
}
