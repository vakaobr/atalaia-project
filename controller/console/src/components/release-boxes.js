// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The field-wide RELEASE (RFC 0001 Amendment 28; decisions STUCK-50 to STUCK-59): for a
// controller that lost a game entirely (reinstalled, its database lost), no GAME_OVER can name the
// game a box is still in. "Release every box not in this game" asks first, then
// POST /api/v1/boxes/release: every box of the field on this channel that is in a game other than
// the live one (any game, with none live), joined before now, ends it as on a game over. Shown to
// the GM in Settings, on a controller that reports stuck boxes (`stuck_watch` in GET /api/v1/boxes:
// a Pi, or a phone controller since STUCK-60).

import { html, Component, createRef, t } from '../ui.js';

export class ReleaseBoxes extends Component {
    constructor(props) {
        super(props);
        this.state = { asking: false, busy: false };
        this.yesRef = createRef();
        this.openRef = createRef();
    }

    componentDidMount() {
        const { app } = this.props;
        if (!app.state.boxes) app.loadBoxes(false);
    }

    componentDidUpdate(prevProps, prevState) {
        // Focus follows the confirmation: onto Release, and back onto the button after it.
        if (this.state.asking && !prevState.asking && this.yesRef.current) this.yesRef.current.focus();
        if (!this.state.asking && prevState.asking && this.openRef.current) this.openRef.current.focus();
    }

    async release() {
        const { app } = this.props;
        this.setState({ busy: true });
        const out = await app.call('POST', '/boxes/release');
        this.setState({ busy: false, asking: false });
        if (!out) return; // refused (too soon, a clock not set, a standby): the toast says why
        app.showToast(out.release_frame === 'sent' ? t('release_all.sent')
            : t('release_all.not_sent', { why: t(`release_all.why.${out.release_frame}`) }));
    }

    render(props, state) {
        const { app } = props;
        const info = app.state.boxes;
        if (app.state.role !== 'gm' || !app.serves('boxes') || !info || info.stuck_watch === undefined) return null;
        const game = app.state.game;
        const live = game && game.live ? game : null;
        return html`<section class="card" data-testid="release-all" aria-labelledby="release-all-h">
            <h2 id="release-all-h">${t('release_all.title')}</h2>
            <p class="small">${live ? t('release_all.intro', { game: live.name }) : t('release_all.intro_none')}</p>
            ${!state.asking
                ? html`<div class="actions"><button type="button" ref=${this.openRef} data-testid="release-all-open"
                    onClick=${() => this.setState({ asking: true })}>${live
                        ? t('release_all.button') : t('release_all.button_none')}</button></div>`
                : html`<div class="confirm-box" role="group" aria-labelledby="release-all-q" data-testid="release-all-confirm"
                    onKeyDown=${(e) => { if (e.key === 'Escape') this.setState({ asking: false }); }}>
                    <p class="confirm-q" id="release-all-q">${t('release_all.question')}</p>
                    <p class="warning small">${t('release_all.warning')}</p>
                    <div class="actions">
                        <button type="button" class="danger" ref=${this.yesRef} data-testid="release-all-yes"
                            disabled=${state.busy} onClick=${() => this.release()}>${t('release_all.yes')}</button>
                        <button type="button" data-testid="release-all-back"
                            onClick=${() => this.setState({ asking: false })}>${t('release_all.back')}</button>
                    </div>
                </div>`}
        </section>`;
    }
}
