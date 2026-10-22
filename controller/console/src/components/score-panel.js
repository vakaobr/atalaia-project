// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Live score: each team's total (box counters merged by maximum plus the
// GM's adjustments, as the controller computes them) and a timeline of the
// totals since the console opened.

import { html, Component, t, teamColour } from '../ui.js';
import { TeamLabel } from './branding-settings.js';

export function Timeline({ history, teams }) {
    if (!history || history.length < 2) return null;
    const w = 300;
    const hgt = 80;
    const t0 = history[0].at;
    const span = Math.max(1, history[history.length - 1].at - t0);
    let max = 1;
    for (const p of history) for (const tm of teams) max = Math.max(max, p.teams[tm] || 0);
    const line = (tm) => history.map((p) => `${((p.at - t0) / span * w).toFixed(1)},${(hgt - (p.teams[tm] || 0) / max * hgt).toFixed(1)}`).join(' ');
    return html`<svg class="timeline" viewBox=${`0 0 ${w} ${hgt}`} preserveAspectRatio="none" role="img"
        aria-label=${t('score.timeline')}>
        ${teams.map((tm) => html`<polyline points=${line(tm)} fill="none" stroke=${teamColour(tm, teams)}
            stroke-width="2" vector-effect="non-scaling-stroke" />`)}
    </svg>`;
}

export class ScorePanel extends Component {
    render(props) {
        const { game, score, scoreHistory } = props.app.state;
        if (!game) return null;
        const teams = game.teams || [];
        const totals = (score && score.game === game.id && score.teams) || {};
        const max = Math.max(1, ...teams.map((tm) => Math.abs(totals[tm] || 0)));
        return html`<section class="card" aria-labelledby="score-h">
            <h2 id="score-h">${t('score.title')}</h2>
            <ul class="scores" data-testid="scores">
                ${teams.map((tm) => html`<li class="score" data-team=${tm}>
                    <${TeamLabel} game=${game} team=${tm} teams=${teams} />
                    <strong class="team-score" data-testid=${`score-${tm}`}>${totals[tm] || 0}</strong>
                    <span class="bar" aria-hidden="true"><span ref=${(el) => {
                        if (el) {
                            el.style.width = `${Math.round(Math.abs(totals[tm] || 0) / max * 100)}%`;
                            el.style.background = teamColour(tm, teams);
                        }
                    }}></span></span>
                </li>`)}
            </ul>
            <${Timeline} history=${scoreHistory} teams=${teams} />
            <p class="muted small">${t('score.explain')}</p>
        </section>`;
    }
}
