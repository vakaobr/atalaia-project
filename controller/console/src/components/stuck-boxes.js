// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Boxes stuck in an ended game (decisions STUCK-40 to STUCK-47; the controller's side is STUCK-1 to
// STUCK-19, RFC 0001 Amendment 27): a box that was switched off when its game ended never heard the
// GAME_OVERs and comes back still in that game. The USB modem reports the packets of other games;
// for a game this controller ran and ended, the controller says its GAME_OVER again, at most once a
// minute. This list shows those games from GET /api/v1/boxes (`stuck`, kept live by the stream's
// `boxes` message): the game, the node ids heard, how long ago, the signal and how many times its
// GAME_OVER was sent again, with a Release button that sends it now
// (POST /api/v1/boxes/stuck/{game}/release). A radio that cannot report them (`stuck_watch` false)
// gets a hint that fits it (`radio_kind`, STUCK-64 as changed by the maintainer): an older USB radio
// modem, update its firmware; an I/O pod (a phone controller's), use a USB radio modem; both, take
// such a box out at the box (the admin menu's "Leave the game", or @leave). A controller that does
// not report them at all (no `stuck_watch`: an older Pi or phone controller) shows nothing; a phone
// controller reports them since STUCK-60 (with an I/O pod as its radio, `stuck_watch` is false).

import { html, Component, t } from '../ui.js';

export class StuckBoxes extends Component {
    constructor(props) {
        super(props);
        this.state = { busy: null };
    }

    componentDidMount() {
        const { app, compact } = this.props;
        if (!app.state.boxes) app.loadBoxes(false);
        // In the Boxes tab "how long ago" stays current (the invite dialog asks every 15 s itself).
        if (!compact) this.timer = setInterval(() => app.loadBoxes(false), 15000);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
    }

    async release(entry) {
        const { app } = this.props;
        this.setState({ busy: entry.game });
        const out = await app.call('POST', `/boxes/stuck/${entry.game}/release`);
        this.setState({ busy: null });
        if (!out) return; // refused (too soon, another channel...): the toast says why
        const name = entry.name || `#${entry.game}`;
        app.showToast(out.game_over_frame === 'sent' ? t('stuck.released', { game: name })
            : t('stuck.not_released', { game: name, why: t(`stuck.why.${out.game_over_frame}`) }));
        app.loadBoxes(false);
    }

    // The node ids heard: a capped list (the most recent 32) and how many in all (SRB-4); an older
    // controller sends only the list.
    nodes(entry) {
        const nodes = entry.nodes || [];
        const more = (entry.nodes_count ?? nodes.length) - nodes.length;
        const list = nodes.join(', ') || '–';
        return more > 0 ? `${list} ${t('stuck.nodes_more', { n: more })}` : list;
    }

    renderRow(entry) {
        const id = entry.game;
        return html`<tr data-testid=${`stuck-row-${id}`}>
            <td><strong>${entry.name || '–'}</strong> <span class="muted small">#${id}</span></td>
            <td class="small" data-testid=${`stuck-nodes-${id}`}>${this.nodes(entry)}</td>
            <td class="muted small">${t('invites.seen', { s: entry.last_heard_s })}</td>
            <td class="muted small">${entry.rssi != null ? `${entry.rssi} dBm` : '–'}</td>
            <td class="small" data-testid=${`stuck-resent-${id}`}>${entry.game_over_resent}</td>
            <td><button type="button" class="small" data-testid=${`stuck-release-${id}`}
                title=${t('stuck.release_hint')} disabled=${this.state.busy === id}
                onClick=${() => this.release(entry)}>${t('stuck.release')}</button></td>
        </tr>`;
    }

    render(props) {
        const { app, compact } = props;
        const info = app.state.boxes;
        if (app.state.role !== 'gm' || !app.serves('boxes') || !info || info.stuck_watch === undefined) return null;
        const stuck = info.stuck || [];
        // In the invite dialog only when there is something to say; in the Boxes tab always.
        if (compact && !stuck.length && info.stuck_watch) return null;
        return html`<section class=${compact ? 'stuck' : 'card stuck'} data-testid="stuck-boxes" aria-labelledby="stuck-h">
            <h3 id="stuck-h">${t('stuck.title')}</h3>
            ${!info.stuck_watch && html`<p class="warning small" data-testid="stuck-no-watch">${t(info.radio_kind === 'pod' ? 'stuck.no_watch_pod' : 'stuck.no_watch')}</p>`}
            ${stuck.length === 0
                ? info.stuck_watch && html`<p class="muted small" data-testid="stuck-empty">${t('stuck.empty')}</p>`
                : html`<p class="muted small">${t('stuck.intro')}</p>
                    <div class="table-wrap"><table class="stuck-list">
                    <thead><tr><th>${t('stuck.game')}</th><th>${t('stuck.nodes')}</th><th>${t('invites.heard')}</th>
                        <th>${t('stuck.signal')}</th><th>${t('stuck.resent')}</th><th></th></tr></thead>
                    <tbody>${stuck.map((s) => this.renderRow(s))}</tbody></table></div>`}
        </section>`;
    }
}
