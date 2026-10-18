// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Node health: every box the controller knows in the live game, with what
// its HELLO and STATE reports say, and (for the GM) a zone owner override.

import { html, Component, t, age, teamColour, OFFLINE_MS } from '../ui.js';

const TIERS = { 0: 'full', 1: 'reduced', 2: 'proxy' };

/** Link quality 0-4 from RSSI (dBm), for a bar display. */
export function linkBars(rssi) {
    if (rssi === null || rssi === undefined) return 0;
    if (rssi >= -70) return 4;
    if (rssi >= -85) return 3;
    if (rssi >= -100) return 2;
    if (rssi >= -115) return 1;
    return 0;
}

export class NodeList extends Component {
    setOwner(node, team) {
        const params = team ? { team } : {};
        this.props.app.call('POST', `/nodes/${node.node_id}/cmd`, { cmd: 'set_owner', params });
    }

    render(props) {
        const app = props.app;
        const { nodes, seen, game, role, now, status } = app.state;
        const list = Object.values(nodes).sort((a, b) => a.node_id - b.node_id);
        const teams = (game && game.teams) || [];
        const gm = role === 'gm' && status && status.role === 'leader' && game && game.live;
        return html`<section class="card" aria-labelledby="nodes-h">
            <h2 id="nodes-h">${t('nodes.title')}</h2>
            ${list.length === 0 ? html`<p class="muted">${t('nodes.none')}</p>` : html`
            <div class="table-wrap"><table class="table" data-testid="node-list">
                <thead><tr>
                    <th>${t('nodes.id')}</th><th>${t('nodes.name')}</th><th>${t('nodes.role')}</th>
                    <th>${t('nodes.owner')}</th><th>${t('nodes.tier')}</th><th>${t('nodes.battery')}</th>
                    <th>${t('nodes.signal')}</th><th>${t('nodes.last_seen')}</th><th>${t('nodes.firmware')}</th>
                    <th>${t('nodes.epoch')}</th>
                </tr></thead>
                <tbody>${list.map((n) => {
                    const ago = seen[n.node_id] !== undefined ? now - seen[n.node_id] : null;
                    const offline = ago !== null && ago > OFFLINE_MS;
                    return html`<tr class=${offline ? 'offline' : ''} data-node=${n.node_id}>
                        <td>${n.node_id}</td>
                        <td>${n.name}</td>
                        <td>${n.role}</td>
                        <td>${gm ? html`<select aria-label=${t('nodes.set_owner', { node: n.node_id })} value=${n.owner || ''}
                                onChange=${(e) => this.setOwner(n, e.target.value)}>
                                <option value="">${t('nodes.no_owner')}</option>
                                ${teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}
                            </select>`
                            : html`<span class="owner" ref=${(el) => { if (el) el.style.color = teamColour(n.owner, teams); }}>${n.owner || t('nodes.no_owner')}</span>`}</td>
                        <td>${n.tier === null || n.tier === undefined ? '–' : t(`nodes.tiers.${TIERS[n.tier] || 'full'}`)}</td>
                        <td>${n.battery_pct === null || n.battery_pct === undefined ? '–' : `${n.battery_pct}%`}</td>
                        <td><span class=${`bars bars-${linkBars(n.rssi)}`} aria-hidden="true"></span>
                            ${n.rssi === null || n.rssi === undefined ? '–' : `${n.rssi} dBm`}${n.snr !== null && n.snr !== undefined ? ` / ${n.snr} dB` : ''}</td>
                        <td>${offline ? html`<strong class="warn">${t('nodes.offline')} </strong>` : ''}${age(ago)}</td>
                        <td>${n.fw_version || '–'}</td>
                        <td>${n.epoch === null || n.epoch === undefined ? '–' : n.epoch}</td>
                    </tr>`;
                })}</tbody>
            </table></div>`}
        </section>`;
    }
}
